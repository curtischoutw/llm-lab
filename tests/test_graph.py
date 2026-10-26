"""graph 子命令的 CLI 行為測試：抽樣檢視知識圖譜，供人工判斷抽取品質（ticket 04）。

為什麼存在：使用者要抽樣看實體與關係來判斷 4B LLM 的抽取品質。spec 的測試縫只有 CLI，
所以這裡先用 `ingest` 對假 OpenAI server 建出圖譜，再只觀察 `graph` 的結束碼與輸出。

關鍵設計決策：
- 空圖譜用一份字面的空 graphml 檔模擬，不 import rag_lab 內部模組。
- 可重現性以兩次獨立子行程的輸出完全相同來驗證（子行程各自有不同的雜湊種子，能抓到
  依賴 set／dict 順序的實作）。
- 假圖譜只有 5 個實體，抽樣數測試用小於 5 的值才看得出「恰好 N 個」。

Dependencies: 僅標準函式庫。
"""

import re
import unittest

from tests.test_cli import run_cli
from tests.test_pipeline import PipelineCase, closed_port_url

ENTITY_LINE = re.compile(r"^實體 \d+/\d+：", re.MULTILINE)
EMPTY_GRAPHML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n'
    '  <graph edgedefault="undirected"/>\n'
    "</graphml>\n"
)


class GraphTest(PipelineCase):
    def graph(self, *extra: str, **overrides: str):
        """執行 `graph`。"""
        return run_cli(["graph", *extra], self.env(**overrides))

    def ingest_then_graph(self, *extra: str, **overrides: str):
        """先 ingest 建圖譜，再執行 `graph`。"""
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        return self.graph(*extra, **overrides)

    def test_lists_sampled_entities_with_name_type_and_description_and_their_relations(self):
        result = self.ingest_then_graph()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("實體 5，關係 7", result.stdout)
        # 抽樣數預設 10 > 5 個實體，全部列出
        self.assertEqual(len(ENTITY_LINE.findall(result.stdout)), 5)
        self.assertIn("Fake Entity Alpha（concept）", result.stdout)
        self.assertIn("Fake Entity Beta（method）", result.stdout)
        self.assertIn("Fake Entity Alpha is a made-up concept.", result.stdout)
        self.assertIn("Fake Entity Alpha -- Fake Entity Beta", result.stdout)
        self.assertIn("fake link", result.stdout)
        self.assertIn("Alpha is related to Beta.", result.stdout)

    def test_sample_size_limits_the_number_of_entities(self):
        result = self.ingest_then_graph("--sample", "2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(ENTITY_LINE.findall(result.stdout)), 2)
        # 總數仍是整張圖的數字，不是抽樣的數字
        self.assertIn("實體 5，關係 7", result.stdout)

    def test_same_arguments_give_identical_output_across_runs(self):
        first = self.ingest_then_graph("--sample", "2")
        second = self.graph("--sample", "2")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_seed_changes_which_entities_are_sampled(self):
        outputs = set()
        self.ingest_then_graph("--sample", "2")
        for seed in range(6):
            result = self.graph("--sample", "2", "--seed", str(seed))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            outputs.add(result.stdout)
        self.assertGreater(len(outputs), 1, "不同 seed 應能抽到不同的實體")

    def test_needs_no_model_endpoint(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        dead = closed_port_url()
        result = self.graph(LLM_BASE_URL=dead, VLM_BASE_URL=dead, EMBED_BASE_URL=dead)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Fake Entity Alpha", result.stdout)

    def test_missing_graph_exits_nonzero_and_points_to_ingest(self):
        result = self.graph()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ingest", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_empty_graph_exits_nonzero_with_a_clear_message(self):
        self.working_dir.mkdir()
        (self.working_dir / "graph_chunk_entity_relation.graphml").write_text(EMPTY_GRAPHML, encoding="utf-8")
        result = self.graph()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("空", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_rejects_non_positive_sample_size(self):
        for bad in ("0", "-3", "abc"):
            with self.subTest(sample=bad):
                result = self.graph("--sample", bad)
                self.assertEqual(result.returncode, 2)
                self.assertIn("--sample", result.stderr)


if __name__ == "__main__":
    unittest.main()
