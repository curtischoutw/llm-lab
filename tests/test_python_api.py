"""Python API 的行為測試：在同一個 process 裡呼叫 rag_lab.pipeline 的公開函式。

為什麼存在：使用者除了 CLI，也會在自己的程式裡呼叫 ingest／query／evaluate，而且常在同一個
process 內呼叫好幾次。CLI 每次只呼叫一次就結束 process，碰不到「第二次呼叫才出錯」的問題
（LightRAG 的共用鎖綁在上一個 event loop 上），所以另立這個縫。

關鍵設計決策：
- 仍從子行程進入：以 `python -c` 執行一段依序呼叫公開函式的程式，每一步的結果印成一行，
  測試只看結束碼與 stdout，不在測試 process 裡 import rag_lab（避免載入 lightrag 與跨測試共用狀態）。
- 子行程在 repo 根目錄執行、環境變數組法與 CLI 測試相同，指向假 OpenAI server 與暫存資料夾。

Dependencies: 僅標準函式庫。
"""

import json
import os
import subprocess
import sys
import unittest

from tests.fake_openai_server import CHAT_REPLY
from tests.test_cli import OPTIONAL_FIELDS, REPO_ROOT, REQUIRED_FIELDS
from tests.test_pipeline import INGEST_TIMEOUT, PipelineCase

# 依 argv 的步驟依序呼叫公開函式；每一步印一行結果。argv[1] 是 PDF 路徑，argv[2] 是題目檔，其餘是步驟名稱。
DRIVER = """
import sys
from pathlib import Path

from rag_lab import pipeline
from rag_lab.evaluation import load_questions

pdf = Path(sys.argv[1])
questions = Path(sys.argv[2])
for step in sys.argv[3:]:
    if step == "ingest":
        summary = pipeline.ingest([pdf])
        for report in summary.reports:
            print(f"ingest skipped={report.skipped} error={report.error}")
    elif step == "query":
        print(f"query {pipeline.query('What is Fake Entity Alpha?', mode='mix')}")
    elif step == "evaluate":
        cells = pipeline.evaluate(load_questions(questions))
        for row in cells:
            print("evaluate " + " ".join(cell.answer if cell.error is None else "ERROR" for cell in row))
    else:
        raise SystemExit(f"unknown step: {step}")
"""


class PythonApiCase(PipelineCase):
    """提供「在同一個子行程內依序呼叫公開函式」的執行輔助。"""

    def run_api(self, *steps: str) -> subprocess.CompletedProcess:
        """以子行程在同一個 process 內依序執行步驟。

        Args:
            *steps: ingest、query、evaluate 的任意序列。

        Returns:
            CompletedProcess（text 模式，已擷取 stdout／stderr）。
        """
        # 假索引只有 Fake Entity 的內容；題目要問得到它，naive 模式才檢索得到 chunk
        questions = self.tmp / "questions.jsonl"
        record = {
            "id": "q1",
            "question": "What is Fake Entity Alpha?",
            "reference": "A made-up concept.",
            "type": "text",
            "source": "paper.pdf",
        }
        questions.write_text(json.dumps(record) + "\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS}
        env.update(self.env())
        return subprocess.run(
            [sys.executable, "-c", DRIVER, str(self.pdf), str(questions), *steps],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=INGEST_TIMEOUT,
        )


class ExistingIndexTest(PythonApiCase):
    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)

    def test_query_can_be_called_twice_in_one_process(self):
        result = self.run_api("query", "query")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), [f"query {CHAT_REPLY}"] * 2)

    def test_query_after_evaluate_in_the_same_process(self):
        result = self.run_api("evaluate", "query")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 題目檔 1 題，五種模式各一格
        every_mode = " ".join([CHAT_REPLY] * 5)
        self.assertEqual(result.stdout.splitlines(), [f"evaluate {every_mode}", f"query {CHAT_REPLY}"])


class EmptyIndexTest(PythonApiCase):
    def test_query_after_ingest_in_the_same_process(self):
        result = self.run_api("ingest", "query")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["ingest skipped=False error=None", f"query {CHAT_REPLY}"],
        )

    def test_ingesting_the_same_pdf_twice_skips_the_second_time(self):
        result = self.run_api("ingest", "ingest")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["ingest skipped=False error=None", "ingest skipped=True error=None"],
        )


if __name__ == "__main__":
    unittest.main()
