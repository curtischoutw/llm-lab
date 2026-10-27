"""examples/ 的執行測試：對假 OpenAI server 與假 mineru 實際跑一次範例。

為什麼存在：範例示範從 Python 呼叫 rag_lab.pipeline 的公開函式；rag_lab 改了介面而範例沒跟著改時，
要由測試發現，而不是由第一個照著 README 執行的人發現。

關鍵設計決策：
- 與其他測試一樣只從子行程進入（`python -m examples.<name>`），只看結束碼與 stdout，不 import 範例。
- 先 ingest 一份假 PDF 建出索引，再跑範例；假 server 的 chat 回應固定，所以只驗證流程跑完、
  每題都有問答輸出，不驗證答案內容。

Dependencies: 僅標準函式庫。
"""

import os
import subprocess
import sys
import unittest

from tests.fake_openai_server import CHAT_REPLY
from tests.test_cli import OPTIONAL_FIELDS, REPO_ROOT, REQUIRED_FIELDS
from tests.test_pipeline import INGEST_TIMEOUT, PipelineCase


class QueryFromPythonExampleTest(PipelineCase):
    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)

    def run_example(self) -> subprocess.CompletedProcess:
        """在 repo 根目錄以 `python -m` 執行範例，環境指向假 server 與暫存索引。

        Returns:
            CompletedProcess（text 模式，已擷取 stdout／stderr）。
        """
        env = {k: v for k, v in os.environ.items() if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS}
        env.update(self.env())
        return subprocess.run(
            [sys.executable, "-m", "examples.query_from_python"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=INGEST_TIMEOUT,
        )

    def test_asks_every_question_and_prints_each_answer(self):
        result = self.run_example()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        questions = [line for line in lines if line.startswith("Q: ")]
        answers = [line for line in lines if line.startswith("A: ")]
        self.assertEqual(len(questions), 2, result.stdout)
        self.assertEqual(answers, [f"A: {CHAT_REPLY}"] * 2)


if __name__ == "__main__":
    unittest.main()
