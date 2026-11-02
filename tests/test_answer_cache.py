"""知識庫有改動時清掉查詢答案快取的行為測試：每份有改動的文件處理完就清，沒改動不清。

為什麼存在：LightRAG 的 LLM 快取 key 由模式、問題文字與查詢參數算出，不含檢索到的內容，所以新增、替換、刪除文件之後，
問以前問過的題目會拿到舊答案（spec：.scratch/incremental-update/spec.md「匯入端：答案快取」「詞彙」的「知識庫有改動」）。
這裡驗證 ticket 05 的範圍：新增、替換、prune 刪除與兩種失敗（寫了一半的內容被清掉、新文件寫入後失敗）之後會清；解析階段
失敗、沒變、共用版本的新增與刪除不清；清除發生在每份文件處理完而不是整批結束；查詢關鍵字與匯入用的抽取快取保留；
報告寫出清掉的筆數，CLI 與 Python API 相同。

關鍵設計決策：
- 縫與其他 ingest 測試相同：CLI 子行程（`python -m rag_lab`）與 Python API（子行程內呼叫模組函式與 Session），
  配假 OpenAI server 與假 mineru。答案快取有沒有被清，從假 server 的請求紀錄觀察：同一題再問時有沒有再送出答案請求
  （prompt 含該題文字的聊天請求）與關鍵字請求（帶 response_format）；不直接讀 LightRAG 的儲存檔。
- 「每份文件處理完就清」靠行程中途被結束來驗證：資料夾裡第一份文件被替換、第二份是假 mineru 的 `stall` 檔（解析時睡著），
  等假 mineru 回報已開始解析第二份，就結束整個行程群組，再問先前的題目。
- 文件內容用假 mineru 的版本標記行（`% fake version: <文字>`）區分。

Dependencies: 標準函式庫。
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time

from tests.test_cli import OPTIONAL_FIELDS, REPO_ROOT, REQUIRED_FIELDS, run_cli
from tests.test_pipeline import INGEST_TIMEOUT, query_prompts
from tests.test_prune import PruneApiCase, PruneCase, extraction_calls
from tests.test_replace import FAIL_FIRST_DELETE_ENV, NEW, OLD

QUESTION = "What is Fake Entity Alpha?"
# 等假 mineru 開始解析第二份文件的秒數上限
STALL_WAIT_SECONDS = 120
# 讓子行程裡清答案快取的第 1 次刪除失敗的夾具（tests/delete_failure/sitecustomize.py）
FAIL_FIRST_CACHE_DELETE_ENV = {
    "PYTHONPATH": str(REPO_ROOT / "tests" / "delete_failure"),
    "FAIL_NTH_CACHE_DELETE": "1",
}


class AnswerCacheHelpers:
    """問同一題並從假 server 的請求紀錄判讀答案快取的輔助；與 PruneCase 組合使用。"""

    def ask(self, question: str = QUESTION) -> tuple[int, int]:
        """執行一次 query，回傳它送出的答案請求數與關鍵字請求數。

        Args:
            question: 問題文字。

        Returns:
            (答案請求數, 關鍵字請求數)。命中答案快取時兩者都是 0；答案被清而關鍵字快取還在時是 (1, 0)。
        """
        before = len(self.server.requests)
        result = self.query(question)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return count_answer_requests(self.server.requests[before:], question)

    def prime(self, question: str = QUESTION) -> None:
        """問一次題目讓答案與關鍵字進快取，並確認第二次問命中快取。

        Args:
            question: 問題文字。
        """
        self.assertEqual(self.ask(question), (1, 1), "第一次問：要生成答案也要抽關鍵字")
        self.assertEqual(self.ask(question), (0, 0), "第二次問：答案命中快取")

    def assert_answer_cleared(self, question: str = QUESTION) -> None:
        """同一題再問會重新生成答案，但查詢關鍵字仍命中快取。

        Args:
            question: 問題文字。
        """
        self.assertEqual(self.ask(question), (1, 0))

    def assert_answer_kept(self, question: str = QUESTION) -> None:
        """同一題再問仍命中答案快取。

        Args:
            question: 問題文字。
        """
        self.assertEqual(self.ask(question), (0, 0))

    def cleared_line(self, result) -> str:
        """取出 ingest 報告裡清掉答案快取筆數的那一行。

        Args:
            result: ingest 的 CompletedProcess。

        Returns:
            「清掉答案快取 N 筆」那一行；沒有時測試失敗。
        """
        lines = [line for line in result.stdout.splitlines() if line.startswith("清掉答案快取 ")]
        self.assertEqual(len(lines), 1, f"報告要有一行清掉答案快取的筆數：\n{result.stdout}")
        return lines[0]


def count_answer_requests(requests: list[dict], question: str) -> tuple[int, int]:
    """數出一批請求裡某一題的答案請求與關鍵字請求。

    Args:
        requests: FakeOpenAIServer.requests 的一段。
        question: 問題文字（答案請求的 prompt 含它）。

    Returns:
        (答案請求數, 關鍵字請求數)。
    """
    answers = sum(1 for prompt in query_prompts(requests) if question in prompt)
    keywords = sum(
        1
        for r in requests
        if r["path"] == "/v1/chat/completions"
        and r["payload"].get("response_format")
        and any(question in str(m.get("content")) for m in r["payload"]["messages"])
    )
    return answers, keywords


# ==============================
# CLI：有改動就清
# ==============================


class AnswerCacheCase(AnswerCacheHelpers, PruneCase):
    """CLI 子行程版的答案快取測試基底。"""


class AnswerCacheClearedOnChangeCliTest(AnswerCacheCase):
    def test_a_new_document_clears_the_cached_answer_and_the_report_says_how_many(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "b.pdf", "cards-b.pdf")

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 1 筆")
        self.assert_answer_cleared()

    def test_a_replaced_document_clears_the_cached_answer(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "a.pdf", NEW)

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 1 筆")
        self.assert_answer_cleared()

    def test_prune_deleting_a_document_clears_the_cached_answer(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        (folder / "gone.pdf").unlink()

        result = self.prune(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("已刪除 1 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 1 筆")
        self.assert_answer_cleared()

    def test_the_count_adds_up_every_cached_answer_in_every_mode(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        for mode in ("naive", "mix"):
            result = self.query(QUESTION, "--mode", mode)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.write_version(folder / "a.pdf", NEW)

        result = self.ingest(folder)

        self.assertEqual(self.cleared_line(result), "清掉答案快取 2 筆")


class AnswerCacheClearedOnFailureCliTest(AnswerCacheCase):
    def test_a_failed_replacement_clears_the_cached_answer(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "a.pdf", NEW)
        self.server.fail_vision = True

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("替換 0 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 1 筆")
        self.server.fail_vision = False
        self.assert_answer_cleared()

    def test_a_failed_new_document_that_was_already_written_into_the_knowledge_base_clears_the_cached_answer(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "b.pdf", "cards-b.pdf")
        self.server.fail_vision = True

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 1 筆")
        self.server.fail_vision = False
        self.assert_answer_cleared()

    def test_a_deletion_that_fails_still_counts_as_a_change(self):
        # 刪除可能已經動到儲存（刪除失敗的訊息不保證什麼都沒改），所以呼叫過刪除就清
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        (folder / "gone.pdf").unlink()

        result = run_cli(["ingest", str(folder), "--prune"], self.env(**FAIL_FIRST_DELETE_ENV), timeout=INGEST_TIMEOUT)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 1 筆")
        self.assert_answer_cleared()

    def test_a_document_that_fails_while_being_parsed_does_not_clear_the_cached_answer(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "broken-b.pdf", "cards-broken-b.pdf")

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("broken-b.pdf", result.stderr)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 0 筆")
        self.assert_answer_kept()


class AnswerCacheClearFailureCliTest(AnswerCacheCase):
    """清答案快取本身失敗（儲存寫不進去）時，這份文件與前面文件的收尾仍要做完，例外照樣往上拋。"""

    def doc_status_of(self, filename: str) -> str:
        """文件狀態裡某個檔名的狀態（processed、failed…）。

        Args:
            filename: 檔名（文件狀態只記檔名）。

        Returns:
            狀態字串；知識庫裡沒有這個檔名時測試失敗。
        """
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text(encoding="utf-8"))
        found = [record["status"] for record in statuses.values() if record["file_path"] == filename]
        self.assertEqual(len(found), 1, f"{filename} 在文件狀態裡有 {len(found)} 筆：{statuses}")
        return found[0]

    def ingest_with_failing_cache_clear(self, folder):
        """對資料夾執行 ingest，其中清答案快取的第 1 次刪除會失敗。

        Args:
            folder: 資料夾路徑。

        Returns:
            CompletedProcess。
        """
        return run_cli(["ingest", str(folder)], self.env(**FAIL_FIRST_CACHE_DELETE_ENV), timeout=INGEST_TIMEOUT)

    def test_a_failed_cache_clearing_still_marks_the_document_whose_description_failed_as_failed(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "b.pdf", "cards-b.pdf")
        self.server.fail_vision = True

        result = self.ingest_with_failing_cache_clear(folder)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("injected cache deletion failure", result.stderr, "清快取的例外要往上拋，不能被吞掉")
        self.assertEqual(self.doc_status_of("b.pdf"), "failed", "描述失敗的文件要記成失敗，下次 ingest 才會重試")

    def test_a_failed_cache_clearing_does_not_lose_the_registry_entry_of_the_document_just_imported(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "b.pdf", "cards-b.pdf")

        result = self.ingest_with_failing_cache_clear(folder)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("injected cache deletion failure", result.stderr)
        self.assertIn(str((folder / "b.pdf").resolve()), self.read_registry()["documents"], "已匯入的文件要先記進對照表")


class AnswerCacheKeptWhenNothingChangedCliTest(AnswerCacheCase):
    def test_ingesting_unchanged_documents_again_keeps_the_cached_answer(self):
        folder = self.make_folder("cards", "a.pdf", "b.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("沒變 2 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 0 筆")
        self.assert_answer_kept()

    # 文件 ID 只由解析後的內容算出；textonly 開頭的檔名讓假 mineru 不輸出（含路徑的）圖片，兩個資料夾裡同名的檔案才得到相同的 ID

    def test_a_new_path_that_shares_a_version_writes_nothing_and_keeps_the_cached_answer(self):
        first = self.make_folder("first")
        second = self.make_folder("second")
        self.write_version(first / "textonly-shared.pdf", "SHARED")
        self.write_version(second / "textonly-shared.pdf", "SHARED")
        self.assertEqual(self.ingest(first).returncode, 0)
        self.prime()

        result = self.ingest(second)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 0 筆")
        self.assert_answer_kept()

    def test_pruning_a_path_whose_version_another_path_still_uses_deletes_nothing_and_keeps_the_cached_answer(self):
        first = self.make_folder("first", "keep.pdf")
        second = self.make_folder("second")
        self.write_version(first / "textonly-shared.pdf", "SHARED")
        self.write_version(second / "textonly-shared.pdf", "SHARED")
        self.assertEqual(self.ingest(first).returncode, 0)
        self.assertEqual(self.ingest(second).returncode, 0)
        self.prime()
        (first / "textonly-shared.pdf").unlink()

        result = self.prune(first)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("已刪除 1 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 0 筆")
        self.assert_answer_kept()

    def test_missing_sources_that_are_only_listed_keep_the_cached_answer(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        (folder / "gone.pdf").unlink()

        result = self.ingest(folder)

        self.assertIn("來源已不在（未刪） 1 份", result.stdout)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 0 筆")
        self.assert_answer_kept()


class AnswerCacheKeepsOtherCachesCliTest(AnswerCacheCase):
    def test_the_keyword_cache_survives_the_clearing(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        self.write_version(folder / "a.pdf", NEW)
        self.assertEqual(self.ingest(folder).returncode, 0)

        answers, keywords = self.ask()

        self.assertEqual(answers, 1, "答案重新生成")
        self.assertEqual(keywords, 0, "關鍵字命中快取，不重新抽取")

    def test_the_extraction_cache_survives_the_clearing(self):
        # textonly 開頭的檔名讓假 mineru 不輸出圖片，LLM 呼叫只剩實體抽取與表格、公式描述
        folder = self.make_folder("cards", "textonly-keep.pdf", "textonly-gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        (folder / "textonly-gone.pdf").unlink()
        self.assertEqual(self.prune(folder).returncode, 0)
        self.write_version(folder / "textonly-gone.pdf", "cards-textonly-gone.pdf")
        before = len(self.server.requests)

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.cleared_line(result), "清掉答案快取 0 筆", "上一步 prune 已經清過，這裡沒有答案可清")
        self.assertEqual(extraction_calls(self.server.requests[before:]), 0, "實體抽取命中快取，不再呼叫 LLM")


class AnswerCacheClearedPerDocumentCliTest(AnswerCacheCase):
    def test_the_answer_is_cleared_as_soon_as_a_document_is_done_without_waiting_for_the_rest_of_the_batch(self):
        folder = self.make_folder("cards", "a.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        self.prime()
        old_id = self.registered_id(folder / "a.pdf")
        # 依檔名排序，a.pdf（替換）先處理，stall-b.pdf 在解析時睡著
        self.write_version(folder / "a.pdf", NEW)
        self.write_version(folder / "stall-b.pdf", "cards-stall-b.pdf")
        stalled = self.tmp / "stalled.flag"
        env = {k: v for k, v in os.environ.items() if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS}
        env.update(self.env(FAKE_MINERU_STALLED=str(stalled)))
        process = subprocess.Popen(
            [sys.executable, "-m", "rag_lab", "ingest", str(folder)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + STALL_WAIT_SECONDS
            while not stalled.exists():
                self.assertIsNone(process.poll(), "ingest 在第二份文件開始解析之前就結束了")
                self.assertLess(time.monotonic(), deadline, "等不到第二份文件開始解析")
                time.sleep(0.2)
        finally:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

        self.assertNotEqual(self.registered_id(folder / "a.pdf"), old_id, "第一份文件已經替換完")
        self.assert_answer_cleared()


# ==============================
# Python API
# ==============================


class AnswerCachePythonApiTest(PruneApiCase):
    """模組函式與 Session 的 ingest 回傳 answer_cache_cleared，清除規則與 CLI 相同。"""

    MODES = ("functions", "session")

    def test_the_summary_counts_the_cleared_answers_and_the_cache_follows_the_changes(self):
        for mode in self.MODES:
            with self.subTest(mode=mode):
                shutil.rmtree(self.working_dir, ignore_errors=True)
                self.write_version(self.document, OLD)
                before = len(self.server.requests)

                result = self.run_api(
                    "cache:paper.pdf",  # 新文件，快取還是空的
                    "query",
                    "rewrite:paper.pdf:" + NEW,
                    "cache:paper.pdf",  # 替換：清掉剛才那一題的答案
                    "query",  # 重新生成
                    "query",  # 命中
                    "cache:paper.pdf",  # 沒變：不清
                    "query",  # 仍命中
                    mode=mode,
                )

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                cleared = [line for line in result.stdout.splitlines() if line.startswith("cache ")]
                self.assertEqual(cleared, ["cache cleared=0", "cache cleared=1", "cache cleared=0"])
                answers, keywords = count_answer_requests(self.server.requests[before:], QUESTION)
                self.assertEqual(answers, 2, "只有第一次與替換之後的第一次要生成答案")
                self.assertEqual(keywords, 1, "關鍵字只抽取一次，替換之後命中快取")

    def test_prune_through_the_api_clears_the_answers_and_counts_them(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.run_api("sync:cards").returncode, 0)
        (folder / "gone.pdf").unlink()
        before = len(self.server.requests)

        result = self.run_api("query", "sync:cards:prune", "query")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        answers, _ = count_answer_requests(self.server.requests[before:], QUESTION)
        self.assertEqual(answers, 2, "prune 刪除之後同一題重新生成答案")
