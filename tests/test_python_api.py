"""Python API 的行為測試：在同一個 process 裡呼叫 rag_lab.pipeline 的模組函式與 Session。

為什麼存在：使用者除了 CLI，也會在自己的程式裡呼叫 ingest／query／evaluate，而且常在同一個
process 內呼叫好幾次。CLI 每次只呼叫一次就結束 process，碰不到「第二次呼叫才出錯」的問題
（LightRAG 的共用鎖綁在上一個 event loop 上、統計累加、實例被 atexit 留住），所以另立這個縫。
涵蓋：模組函式連續呼叫、同一個 Session 依序呼叫、每次 ingest 的統計獨立、只初始化一次與釋放實例、
誤用時的例外、開 Session 失敗後不留狀態、忘了 close 時的收尾。

關鍵設計決策：
- 仍從子行程進入：以 `python -c` 執行一段依序呼叫公開函式的程式，每一步的結果印成一行，
  測試只看結束碼與 stdout，不在測試 process 裡 import rag_lab（避免載入 lightrag 與跨測試共用狀態）。
- 子行程在 repo 根目錄執行、環境變數組法與 CLI 測試相同，指向假 OpenAI server 與暫存資料夾。

Dependencies: 僅標準函式庫。
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

from tests.fake_openai_server import CHAT_REPLY
from tests.test_cli import OPTIONAL_FIELDS, REPO_ROOT, REQUIRED_FIELDS
from tests.test_pipeline import INGEST_TIMEOUT, PipelineCase

# 依 argv 的步驟依序呼叫公開函式；每一步印一行結果。
# argv[1] 是 PDF 路徑，argv[2] 是題目檔，argv[3] 是 functions（模組函式）或 session（同一個 Session），其餘是步驟。
# 步驟 stats:<檔名> 匯入 PDF 旁邊的另一個檔案，印出這一次的 VLM 與描述統計；
# 步驟 instances 印出存活的 RAGAnything 實例數，並在最後（Session 已關閉）再印一次；
# 步驟 second／closed／thread／loop／bad_mode 各做一種誤用並印出例外類別；orphan 讓建立 session 的執行緒
# 沒關閉就結束，再由主執行緒關閉；init_fail 讓開 session 失敗一次；
# forget 開一個 session 問一題、不關閉就結束。
DRIVER = """
import asyncio
import contextlib
import gc
import sys
import threading
from pathlib import Path

from rag_lab import pipeline
from rag_lab.config import get_settings
from rag_lab.evaluation import load_questions
from raganything import RAGAnything


def instances():
    '''Returns: gc 後存活的 RAGAnything 實例數。'''
    gc.collect()
    return sum(isinstance(obj, RAGAnything) for obj in gc.get_objects())


def error_name(call):
    '''Args: call 無引數的函式。Returns: (例外類別名稱, 訊息)；沒有例外時為 ("ok", "")。'''
    try:
        call()
    except Exception as exc:
        return type(exc).__name__, str(exc)
    return "ok", ""


def ask(session):
    '''Args: session 或 pipeline 模組。Returns: 固定問題的答案。'''
    return session.query("What is Fake Entity Alpha?", mode="mix")


def in_other_thread(session):
    '''Args: session 開著的 Session。Returns: 在另一個執行緒提問的 error_name 結果。'''
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(error_name(lambda: ask(session))))
    worker.start()
    worker.join()
    return outcome[0]


async def construct_inside_running_loop():
    '''Returns: 在執行中的 event loop 裡建構 Session 的 error_name 結果。'''
    return error_name(pipeline.Session)


forgotten = []

pdf = Path(sys.argv[1])
questions = Path(sys.argv[2])
use_session = sys.argv[3] == "session"
with pipeline.Session() if use_session else contextlib.nullcontext(pipeline) as api:
    for step in sys.argv[4:]:
        if step == "ingest":
            summary = api.ingest([pdf])
            for report in summary.reports:
                print(f"ingest skipped={report.skipped} error={report.error}")
        elif step.startswith("stats:"):
            name = step.removeprefix("stats:")
            summary = api.ingest([pdf.parent / name])
            failed = sum(report.description_failed for report in summary.reports)
            print(
                f"stats {name} vlm_ok={summary.vlm_ok} vlm_failed={summary.vlm_failed} "
                f"description_failed={failed} description_error={summary.description_error is not None}"
            )
        elif step == "query":
            print(f"query {api.query('What is Fake Entity Alpha?', mode='mix')}")
        elif step == "evaluate":
            cells = api.evaluate(load_questions(questions))
            for row in cells:
                print("evaluate " + " ".join(cell.answer if cell.error is None else "ERROR" for cell in row))
        elif step == "instances":
            print(f"instances {instances()}")
        elif step == "second":
            with pipeline.Session():
                print(f"second {error_name(pipeline.Session)[0]}")
        elif step == "closed":
            session = pipeline.Session()
            session.close()
            print(f"closed {error_name(lambda: ask(session))[0]}")
        elif step == "thread":
            with pipeline.Session() as session:
                print(f"thread {in_other_thread(session)[0]}")
        elif step == "loop":
            name, message = asyncio.run(construct_inside_running_loop())
            print(f"loop {name} to_thread={'asyncio.to_thread' in message}")
        elif step == "init_fail":
            # 測試把 WORKING_DIR 建成檔案；開 session 失敗後刪掉它，之後的步驟要能照常開 session
            working_dir = Path(get_settings().working_dir)
            print(f"init_fail {error_name(pipeline.Session)[0] != 'ok'}")
            working_dir.unlink()
        elif step == "bad_mode":
            with pipeline.Session() as session:
                print(f"bad_mode {error_name(lambda: session.query('What is Fake Entity Alpha?', mode='bypass'))[0]}")
        elif step == "orphan":
            opened = []
            worker = threading.Thread(target=lambda: opened.append(pipeline.Session()))
            worker.start()
            worker.join()
            print(f"orphan close {error_name(opened[0].close)[0]}")
        elif step == "forget":
            session = pipeline.Session()
            forgotten.append(session)
            print(f"forget {ask(session)}")
        else:
            raise SystemExit(f"unknown step: {step}")
if "instances" in sys.argv[4:]:
    print(f"instances after close {instances()}")
"""


class PythonApiCase(PipelineCase):
    """提供「在同一個子行程內依序呼叫公開函式」的執行輔助。"""

    def setUp(self):
        super().setUp()
        # 假 mineru 每次 `--version`（RAGAnything 每次初始化一次）在這個檔附加一行；只記 run_api 的子行程
        self.version_log = self.tmp / "mineru_version.log"

    def initializations(self) -> int:
        """run_api 子行程裡 RAGAnything 初始化的次數。

        Returns:
            假 mineru 收到 `--version` 的次數。
        """
        if not self.version_log.exists():
            return 0
        return len(self.version_log.read_text(encoding="utf-8").splitlines())

    def run_api(self, *steps: str, mode: str = "functions") -> subprocess.CompletedProcess:
        """以子行程在同一個 process 內依序執行步驟。

        Args:
            *steps: ingest、stats:<檔名>、query、evaluate、instances、second、closed、thread、loop、
                bad_mode、orphan、init_fail、forget 的任意序列。
            mode: functions 呼叫模組函式；session 在同一個 Session 裡呼叫。

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
        env.update(self.env(FAKE_MINERU_VERSION_LOG=str(self.version_log)))
        return subprocess.run(
            [sys.executable, "-c", DRIVER, str(self.pdf), str(questions), mode, *steps],
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



class SessionTest(PythonApiCase):
    """同一個 Session 裡依序呼叫：結果與各自獨立執行相同，知識庫只初始化一次。"""

    def test_steps_in_one_session_match_separate_calls(self):
        result = self.run_api("ingest", "query", "evaluate", "query", mode="session")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        every_mode = " ".join([CHAT_REPLY] * 5)
        self.assertEqual(
            result.stdout.splitlines(),
            ["ingest skipped=False error=None", f"query {CHAT_REPLY}", f"evaluate {every_mode}", f"query {CHAT_REPLY}"],
        )

    def test_one_session_initializes_once_and_releases_its_instance(self):
        self.assertEqual(self.ingest().returncode, 0)
        result = self.run_api("query", "query", "query", "instances", mode="session")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [f"query {CHAT_REPLY}"] * 3 + ["instances 1", "instances after close 0"],
        )
        self.assertEqual(self.initializations(), 1)


class SessionMisuseTest(PythonApiCase):
    """誤用時拋專案自己的例外，而且不留下狀態：之後再開 session 照常可用。"""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.ingest().returncode, 0)

    def test_each_misuse_raises_a_session_error_and_a_new_session_still_works(self):
        result = self.run_api("second", "closed", "thread", "loop", "query")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "second SessionError",
                "closed SessionClosedError",
                "thread SessionError",
                "loop SessionError to_thread=True",
                f"query {CHAT_REPLY}",
            ],
        )

    def test_an_unknown_mode_is_rejected_before_querying(self):
        before = len(self.server.requests)
        result = self.run_api("bad_mode")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["bad_mode ValueError"])
        # LightRAG 的 bypass 模式不檢索、直接問 LLM；不合法的模式不該送出任何 chat 請求
        chats = [r for r in self.server.requests[before:] if r["path"] == "/v1/chat/completions"]
        self.assertEqual(chats, [])

    def test_a_session_left_open_by_a_finished_thread_can_be_closed_elsewhere(self):
        result = self.run_api("orphan", "query")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["orphan close ok", f"query {CHAT_REPLY}"])

    def test_a_failed_session_start_releases_everything(self):
        shutil.rmtree(self.working_dir)
        self.working_dir.write_text("not a directory")
        result = self.run_api("init_fail", "ingest", "query")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["init_fail True", "ingest skipped=False error=None", f"query {CHAT_REPLY}"],
        )

    def test_a_forgotten_session_is_closed_at_exit_and_its_cache_is_written(self):
        result = self.run_api("forget")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), [f"forget {CHAT_REPLY}"])
        self.assertIn("Session 沒有呼叫 close()", result.stderr)

        before = len(self.server.requests)
        again = self.query()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        chats = [r for r in self.server.requests[before:] if r["path"] == "/v1/chat/completions"]
        self.assertEqual(chats, [], "收尾時沒有寫回 LLM 快取，同一題又呼叫了 LLM")


class IngestStatsTest(PythonApiCase):
    """每次 ingest 的統計只算那一次，不累加前一次呼叫的數字。"""

    def setUp(self):
        super().setUp()
        for name in ("a.pdf", "b.pdf"):
            (self.tmp / name).write_bytes(b"%PDF-1.4 " + name.encode())

    def test_each_ingest_reports_only_its_own_vlm_calls(self):
        result = self.run_api("stats:a.pdf", "stats:b.pdf")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "stats a.pdf vlm_ok=1 vlm_failed=0 description_failed=0 description_error=False",
                "stats b.pdf vlm_ok=1 vlm_failed=0 description_failed=0 description_error=False",
            ],
        )

    def test_each_ingest_in_one_session_counts_its_own_description_failures(self):
        self.server.fail_vision = True
        result = self.run_api("stats:a.pdf", "stats:b.pdf", mode="session")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 假 mineru 每份 PDF 有一張圖：VLM 失敗 1 次，圖片描述失敗 1 次
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "stats a.pdf vlm_ok=0 vlm_failed=1 description_failed=1 description_error=True",
                "stats b.pdf vlm_ok=0 vlm_failed=1 description_failed=1 description_error=True",
            ],
        )


if __name__ == "__main__":
    unittest.main()
