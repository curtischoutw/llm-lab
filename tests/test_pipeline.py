"""ingest／query 的 CLI 行為測試：對假 OpenAI server 與假 mineru 跑完整流程。

為什麼存在：ticket 03 的第一條完整路徑（匯入一篇 PDF、再問答）需要快速、不依賴
真實模型的回歸保護。spec 的測試縫只有 CLI，所以這裡全部從 `python -m rag_lab` 進入，
只觀察結束碼、stdout／stderr、產生的檔案，以及假 server 在 HTTP 邊界收到的請求。

關鍵設計決策：
- 每個測試用獨立的暫存資料夾放索引（WORKING_DIR）與解析輸出（PARSER_OUTPUT_DIR），
  彼此不汙染，也不碰 repo 內的 rag_storage／output。
- 假 mineru 以 PATH 上的可執行檔提供（tests/fake_mineru.py），讓 RAG-Anything 走它真實的
  subprocess 路徑；PDF 內容不重要，只要檔案存在。
- 「端點不可達」用一個已關閉的本機埠模擬。

Dependencies: 僅標準函式庫。
"""

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fake_openai_server import CHAT_REPLY, FakeOpenAIServer
from tests.test_cli import REPO_ROOT, SECRET, run_cli, valid_env

INGEST_TIMEOUT = 180
# 端點失敗後應在這個秒數內結束（正常約 10 秒，含 LightRAG 限流器 shutdown 最多等 5 秒）
HANG_TIMEOUT = 60
# .env 內以字面 \n 表示換行；CLI 讀進來後是真正的換行
QUERY_PREFIX_ENV = r"Instruct: Given a question, retrieve relevant passages that answer the question\nQuery:"

# ==============================
# 工具函式
# ==============================


def closed_port_url() -> str:
    """取得一個沒有任何程式在聽的本機 base URL。

    Returns:
        指向已關閉埠的 http URL（含 /v1）。
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


class PipelineCase(unittest.TestCase):
    """提供假 server、假 mineru、暫存資料夾與 CLI 執行輔助的測試基底。"""

    def setUp(self):
        self.server = FakeOpenAIServer(embed_dim=1024)
        self.server.start()
        self.addCleanup(self.server.stop)

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        mineru = bin_dir / "mineru"
        mineru.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{REPO_ROOT}/tests/fake_mineru.py" "$@"\n')
        mineru.chmod(mineru.stat().st_mode | stat.S_IXUSR)
        self.bin_dir = bin_dir

        self.working_dir = self.tmp / "rag_storage"
        self.output_dir = self.tmp / "output"
        self.pdf = self.tmp / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fake")

    def env(self, **overrides: str) -> dict[str, str]:
        """組出指向假 server 與暫存資料夾的環境變數。

        Args:
            **overrides: 覆蓋的環境變數。

        Returns:
            可傳給 run_cli 的 overrides。
        """
        env = valid_env(self.server.base_url)
        env.update(
            WORKING_DIR=str(self.working_dir),
            PARSER_OUTPUT_DIR=str(self.output_dir),
            EMBED_QUERY_PREFIX=QUERY_PREFIX_ENV,
            PATH=f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
        )
        env.update(overrides)
        return env

    def ingest(self, path: Path | None = None, **overrides: str):
        """執行 `ingest`。"""
        return run_cli(["ingest", str(path or self.pdf)], self.env(**overrides), timeout=INGEST_TIMEOUT)

    def query(self, question: str = "What is Fake Entity Alpha?", *extra: str, **overrides: str):
        """執行 `query`。"""
        return run_cli(["query", question, *extra], self.env(**overrides), timeout=INGEST_TIMEOUT)


# ==============================
# ingest
# ==============================


class IngestTest(PipelineCase):
    def test_ingests_one_pdf_and_reports_stage_timings(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("paper.pdf", result.stdout)
        self.assertIn("解析", result.stdout)
        self.assertIn("建圖", result.stdout)
        self.assertTrue((self.working_dir / "graph_chunk_entity_relation.graphml").is_file())

    def test_images_tables_and_equations_are_described_and_vlm_calls_are_counted(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        chats = [r["payload"] for r in self.server.requests if r["path"] == "/v1/chat/completions"]
        image_requests = [c for c in chats if any(isinstance(m["content"], list) for m in c["messages"])]
        self.assertEqual(len(image_requests), 1, "圖片應以 base64 data URI 送給 VLM 恰一次")
        image_part = next(
            part
            for m in image_requests[0]["messages"]
            if isinstance(m["content"], list)
            for part in m["content"]
            if part["type"] == "image_url"
        )
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))
        described = [c for c in chats if "detailed_description" in str(c["messages"])]
        self.assertEqual(len(described), 3, "圖、表、公式各一次描述請求")
        self.assertIn("多模態", result.stdout)
        self.assertIn("VLM 呼叫：成功 1，失敗 0", result.stdout)
        self.assertIn("The image shows a red square", result.stdout)

    def test_graph_counts_are_reported_with_belongs_to_edges_separated(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("圖譜：實體 5，關係 7", result.stdout)
        self.assertIn("belongs_to 邊 6", result.stdout)

    def test_reingesting_the_same_pdf_creates_nothing_and_calls_no_model(self):
        first = self.ingest()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        requests_after_first = len(self.server.requests)

        second = self.ingest()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("略過", second.stdout)
        self.assertEqual(len(self.server.requests), requests_after_first, "重複匯入不該再呼叫任何模型")
        for result in (first, second):
            self.assertIn("processed=1", result.stdout)
            self.assertIn("failed=0", result.stdout)
        self.assertIn("圖譜：實體 5，關係 7", second.stdout)

    def test_retrying_a_failed_pdf_processes_it_without_a_dup_record(self):
        self.server.fail_chat = True
        failed = self.ingest()
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)

        self.server.fail_chat = False
        retried = self.ingest()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("processed=1", retried.stdout)
        self.assertIn("failed=0", retried.stdout)
        self.assertIn("圖譜：實體 5，關係 7", retried.stdout)
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text())
        self.assertEqual([doc_id for doc_id in statuses if doc_id.startswith("dup-")], [])

    def test_ingests_every_pdf_in_a_folder(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        for name in ("a.pdf", "b.pdf"):
            (folder / name).write_bytes(b"%PDF-1.4 " + name.encode())
        (folder / "notes.txt").write_text("not a pdf")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("a.pdf", result.stdout)
        self.assertIn("b.pdf", result.stdout)
        self.assertNotIn("notes.txt", result.stdout)
        self.assertIn("processed=2", result.stdout)

    def test_rejects_missing_or_non_pdf_paths(self):
        text_file = self.tmp / "notes.txt"
        text_file.write_text("hello")
        empty_dir = self.tmp / "empty"
        empty_dir.mkdir()
        for path in (self.tmp / "nope.pdf", text_file, empty_dir):
            with self.subTest(path=path.name):
                result = self.ingest(path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("輸入錯誤", result.stderr)
                self.assertEqual(self.server.requests, [])

    def test_mineru_is_called_with_the_chosen_backend(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        argv_files = list(self.output_dir.rglob("argv.json"))
        self.assertEqual(len(argv_files), 1)
        argv = json.loads(argv_files[0].read_text())
        self.assertEqual(argv[argv.index("-b") + 1], "pipeline")

    def test_llm_concurrency_follows_llm_max_async(self):
        self.server.chat_delay = 0.2
        serial = self.ingest(LLM_MAX_ASYNC="1")
        self.assertEqual(serial.returncode, 0, serial.stdout + serial.stderr)
        self.assertEqual(self.server.max_inflight_chat, 1)

    def test_higher_llm_max_async_allows_parallel_requests(self):
        self.server.chat_delay = 0.2
        parallel = self.ingest(LLM_MAX_ASYNC="3")
        self.assertEqual(parallel.returncode, 0, parallel.stdout + parallel.stderr)
        self.assertGreater(self.server.max_inflight_chat, 1)

    def test_exits_with_llm_error_when_generation_dies_mid_ingest(self):
        # 真實 mlx_lm.server GPU 記憶體不足時：正在生成的請求不回應，其他請求回 404。
        # 曾因 LightRAG 的限流 worker 吞掉取消、asyncio.run 收尾時永遠等不到它結束而卡住。
        self.server.chat_delay = 0.2
        self.server.die_after_chat = 3
        pdf = self.tmp / "multichunk.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        try:
            result = run_cli(["ingest", str(pdf)], self.env(LLM_MAX_ASYNC="2"), timeout=HANG_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.fail(f"LLM 端點失敗後 ingest 超過 {HANG_TIMEOUT} 秒沒有結束")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LLM", result.stderr)
        self.assertIn("generation thread died", result.stderr)

    def test_embedding_concurrency_follows_embed_max_async(self):
        self.server.embed_delay = 0.2
        serial = self.ingest(EMBED_MAX_ASYNC="1")
        self.assertEqual(serial.returncode, 0, serial.stdout + serial.stderr)
        self.assertEqual(self.server.max_inflight_embed, 1)

    def test_higher_embed_max_async_allows_parallel_requests(self):
        self.server.embed_delay = 0.2
        parallel = self.ingest(EMBED_MAX_ASYNC="4")
        self.assertEqual(parallel.returncode, 0, parallel.stdout + parallel.stderr)
        self.assertGreater(self.server.max_inflight_embed, 1)


# ==============================
# query
# ==============================


class QueryTest(PipelineCase):
    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.requests_before_query = len(self.server.requests)

    def query_requests(self) -> list[dict]:
        """匯入完成後才收到的請求。"""
        return self.server.requests[self.requests_before_query :]

    def test_prints_the_answer_in_mix_mode_by_default(self):
        result = self.query()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), CHAT_REPLY)
        keyword_calls = [r for r in self.query_requests() if r["payload"].get("response_format")]
        self.assertEqual(len(keyword_calls), 1, "mix 模式每次查詢會先做關鍵字抽取")

    def test_every_mode_answers_and_naive_skips_keyword_extraction(self):
        for mode in ("naive", "local", "global", "hybrid", "mix"):
            with self.subTest(mode=mode):
                before = len(self.server.requests)
                result = self.query("What is Fake Entity Alpha?", "--mode", mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), CHAT_REPLY)
                keyword_calls = [r for r in self.server.requests[before:] if r["payload"].get("response_format")]
                self.assertEqual(len(keyword_calls), 0 if mode == "naive" else 1)

    def test_answers_without_mineru_on_path(self):
        # RAG-Anything 初始化時（查詢也會）檢查 `mineru --version`；使用者沒 activate venv
        # 時 PATH 上沒有 mineru，CLI 要自己補上專案 venv 的 bin 目錄
        result = self.query(PATH=os.pathsep.join(["/usr/bin", "/bin"]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), CHAT_REPLY)

    def test_rejects_unknown_mode(self):
        result = self.query("q", "--mode", "bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("bogus", result.stderr)

    def test_query_side_embeddings_carry_the_instruction_prefix_and_documents_do_not(self):
        prefix = QUERY_PREFIX_ENV.replace("\\n", "\n")
        document_inputs = [
            text
            for r in self.server.requests[: self.requests_before_query]
            if r["path"] == "/v1/embeddings"
            for text in r["payload"]["input"]
        ]
        self.assertTrue(document_inputs)
        self.assertFalse([t for t in document_inputs if t.startswith("Instruct:")])

        result = self.query("What is Fake Entity Alpha?")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        query_inputs = [
            text for r in self.query_requests() if r["path"] == "/v1/embeddings" for text in r["payload"]["input"]
        ]
        self.assertTrue(query_inputs)
        self.assertTrue(all(t.startswith(prefix) for t in query_inputs), query_inputs)

    def test_failed_llm_call_exits_nonzero_with_the_original_error_and_no_answer(self):
        self.server.fail_chat = True
        result = self.query()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("injected chat failure", result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class QueryBudgetTest(PipelineCase):
    def setUp(self):
        super().setUp()
        # multichunk 會切出約 20 個 chunk，naive 模式全部檢索得到，預設 30k 的上限放得下大部分
        self.pdf = self.tmp / "multichunk.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fake")
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)

    def answer_prompt_chars(self, question: str, budget: str) -> int:
        """以指定的 QUERY_MAX_TOTAL_TOKENS 跑 naive 查詢，回傳答案請求的訊息總字元數。

        Args:
            question: 問題；每次要不同，LightRAG 的 LLM 快取 key 不含 token 上限，同題會命中快取。
            budget: QUERY_MAX_TOTAL_TOKENS 的值。

        Returns:
            答案請求所有訊息的字元數總和。
        """
        before = len(self.server.requests)
        result = self.query(question, "--mode", "naive", QUERY_MAX_TOTAL_TOKENS=budget)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        answers = [
            r
            for r in self.server.requests[before:]
            if r["path"] == "/v1/chat/completions" and not r["payload"].get("response_format")
        ]
        self.assertEqual(len(answers), 1)
        return sum(len(m["content"]) for m in answers[0]["payload"]["messages"])

    def test_query_context_follows_query_max_total_tokens(self):
        large = self.answer_prompt_chars("What relates to Fake Entity 3-17?", "30000")
        small = self.answer_prompt_chars("What relates to Fake Entity 5-40?", "4000")
        # 英文約 4 字元一個 token；4000 token 的上限換算不會超過 4 * 4000 字元
        self.assertLess(small, 4 * 4000)
        self.assertGreater(large, 2 * small)


# ==============================
# 端點不可達
# ==============================


class UnreachableEndpointTest(PipelineCase):
    def assert_names_endpoint(self, result, label: str, url: str) -> None:
        """斷言非零結束，且 stderr 指出端點名稱與位址。"""
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(label, result.stderr)
        self.assertIn(url, result.stderr)

    def test_ingest_names_each_unreachable_endpoint(self):
        for label, field in (("LLM", "LLM_BASE_URL"), ("VLM", "VLM_BASE_URL"), ("Embedding", "EMBED_BASE_URL")):
            with self.subTest(endpoint=label):
                dead = closed_port_url()
                result = self.ingest(**{field: dead})
                self.assert_names_endpoint(result, label, dead)

    def test_query_names_each_unreachable_endpoint_it_depends_on(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        for label, field in (("LLM", "LLM_BASE_URL"), ("Embedding", "EMBED_BASE_URL")):
            with self.subTest(endpoint=label):
                dead = closed_port_url()
                result = self.query(**{field: dead})
                self.assert_names_endpoint(result, label, dead)

    def test_endpoint_failing_midway_is_still_attributed_to_the_endpoint(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.server.fail_chat = True
        result = self.query()
        self.assert_names_endpoint(result, "LLM", self.server.base_url)

    def test_vlm_failing_midway_fails_ingest_even_though_rag_anything_does_not(self):
        self.server.fail_vision = True
        result = self.ingest()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("VLM", result.stderr)
        self.assertIn(self.server.base_url, result.stderr)
        self.assertIn("injected vision failure", result.stderr)

    def test_errors_never_print_api_keys(self):
        result = self.ingest(LLM_BASE_URL=closed_port_url())
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(SECRET, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
