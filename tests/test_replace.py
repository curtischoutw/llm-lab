"""替換變更的文件的行為測試：同一個路徑上的內容改了，ingest 先匯入新版本、成功後才刪舊版本。

為什麼存在：增量更新（spec：.scratch/incremental-update/spec.md「匯入端：對照表」規則 2、「匯入端：替換與移除」）要讓
知識庫跟上來源檔的改版，查詢不能同時檢索到新舊兩個版本。這裡驗證 ticket 02 的範圍：替換的順序、新版本失敗時清掉寫了
一半的內容、刪除前先查共用版本、舊版本刪除失敗與替換中斷後的補刪。用檔名遷移、prune、答案快取是後面 ticket 的範圍。

關鍵設計決策：
- 縫與其他 ingest 測試相同：CLI 子行程（`python -m rag_lab`）與 Python API（子行程內呼叫模組函式與 Session），
  配假 OpenAI server 與假 mineru。「內容改了」靠假 mineru 的版本標記行（`% fake version: <文字>`，見 tests/fake_mineru.py）：
  改寫 PDF 的位元組就得到新的文件 ID，版本標記同時進文字 chunk 與表格 chunk。
- 「查詢只看到新版本」從假 server 收到的查詢 prompt 觀察，不直接讀 LightRAG 的儲存檔；「知識庫裡有幾份文件」從 CLI 輸出的
  文件狀態統計觀察（processed=、failed=）。
- 「對照表記的 ID 不在知識庫」「替換中斷」這類狀態直接寫對照表檔造出來（對照表的檔名與格式是公開契約）。

Dependencies: 標準函式庫。
"""

import re
import shutil
from pathlib import Path

from tests.test_pipeline import PipelineCase, query_prompts
from tests.test_python_api import PythonApiCase
from tests.test_registry import RegistryHelpers

OLD = "VERSIONOLD"
NEW = "VERSIONNEW"
# 讓子行程裡 LightRAG 的第 1 次刪除失敗的夾具（tests/delete_failure/sitecustomize.py）
FAIL_FIRST_DELETE_ENV = {"PYTHONPATH": str(Path(__file__).parent / "delete_failure"), "FAIL_NTH_DELETE": "1"}


class ReplaceHelpers(RegistryHelpers):
    """寫入不同版本內容與觀察查詢 context 的輔助；與 PipelineCase 組合使用。"""

    def write_version(self, path, marker: str) -> None:
        """把 path 改寫成帶有指定版本標記的 PDF 替身。

        Args:
            path: 文件路徑；不存在會建立（父資料夾要已存在）。
            marker: 版本標記文字。
        """
        path.write_bytes(f"%PDF-1.4 fake\n% fake version: {marker}\n".encode())

    def registered_id(self, path) -> str:
        """對照表裡 path 那一筆的文件 ID。

        Args:
            path: 文件路徑。

        Returns:
            文件 ID。
        """
        return self.read_registry()["documents"][str(path.resolve())]["doc_id"]

    def import_old_then_change(self) -> str:
        """匯入舊版本，再把文件改成新版本。

        Returns:
            舊版本的文件 ID。
        """
        self.write_version(self.document, OLD)
        self.assertEqual(self.ingest().returncode, 0)
        old_id = self.registered_id(self.document)
        self.write_version(self.document, NEW)
        return old_id

    def context_of_query(self, question: str) -> str:
        """執行一次 query，回傳送給模型產生答案的 prompt（含檢索到的 context）。

        同一題會命中 LightRAG 的答案快取（快取鍵不含檢索到的內容；清快取是 ticket 05 的範圍），所以每次查詢要用不同的題目。

        Args:
            question: 問題文字。

        Returns:
            這次 query 送出的答案 prompt。
        """
        before = len(self.server.requests)
        result = self.query(question)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return "\n".join(query_prompts(self.server.requests[before:]))

    def status_count(self, result, status: str) -> int:
        """從 ingest 的 stdout 讀出某個文件狀態的份數。

        Args:
            result: ingest 的 CompletedProcess。
            status: 狀態名稱，例如 processed。

        Returns:
            份數。
        """
        match = re.search(rf"(?<![a-z]){status}=(\d+)", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        return int(match.group(1))


class ReplaceCase(ReplaceHelpers, PipelineCase):
    """CLI 子行程版的替換測試基底。"""


class ReplaceChangedDocumentCliTest(ReplaceCase):
    def test_a_changed_document_replaces_its_old_version_and_queries_see_only_the_new_one(self):
        self.write_version(self.document, OLD)
        self.assertEqual(self.ingest().returncode, 0)
        old_id = self.registered_id(self.document)
        self.assertIn(OLD, self.context_of_query("What is Fake Entity Alpha?"))

        self.write_version(self.document, NEW)
        result = self.ingest()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertIn("新增 0 份", result.stdout)
        self.assertIn("沒變 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 1, "知識庫裡同一份文件只有一個版本")
        self.assertNotEqual(self.registered_id(self.document), old_id)
        context = self.context_of_query("What is Fake Entity Beta?")
        self.assertIn(NEW, context)
        self.assertNotIn(OLD, context)


class ReplaceFailureCliTest(ReplaceCase):
    def assert_old_version_still_alone(self, result, old_id: str, new_marker: str) -> None:
        """失敗的替換之後：知識庫只剩舊版本、沒有失敗紀錄、對照表不變、查詢只看到舊內容。

        Args:
            result: 失敗的 ingest 的 CompletedProcess。
            old_id: 替換之前對照表記的文件 ID。
            new_marker: 新版本的版本標記。
        """
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.status_count(result, "processed"), 1)
        self.assertEqual(self.status_count(result, "failed"), 0, "替換失敗的新版本不留失敗紀錄")
        self.assertEqual(self.registered_id(self.document), old_id)
        self.assertIn("替換 0 份", result.stdout)
        self.assertIn(old_id, result.stderr)
        self.assertIn("舊版本", result.stderr)
        context = self.context_of_query("What is Fake Entity Gamma?")
        self.assertIn(OLD, context)
        self.assertNotIn(new_marker, context)

    def test_a_new_version_that_fails_to_import_is_removed_and_the_old_version_stays(self):
        old_id = self.import_old_then_change()
        self.server.fail_chat_containing = NEW
        result = self.ingest()
        self.assert_old_version_still_alone(result, old_id, NEW)

    def test_a_new_version_whose_image_description_fails_is_removed_and_the_old_version_stays(self):
        old_id = self.import_old_then_change()
        self.server.fail_vision = True
        result = self.ingest()
        self.assert_old_version_still_alone(result, old_id, NEW)
        self.assertIn("描述呼叫失敗", result.stderr)

    def test_a_replacement_that_succeeds_after_a_failed_one_is_reported_as_replaced(self):
        self.import_old_then_change()
        self.server.fail_vision = True
        self.assertEqual(self.ingest().returncode, 1)
        self.server.fail_vision = False
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 1)
        self.assertEqual(self.status_count(result, "failed"), 0)


class ReplaceDeletionFailureCliTest(ReplaceCase):
    def test_failing_to_clean_up_a_half_written_new_version_reports_both_document_ids(self):
        old_id = self.import_old_then_change()
        self.server.fail_vision = True

        result = self.ingest(**FAIL_FIRST_DELETE_ENV)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.registered_id(self.document), old_id)
        self.assertIn("替換 0 份", result.stdout)
        message = next(line for line in result.stderr.splitlines() if line.startswith("匯入失敗：paper.pdf"))
        self.assertIn(old_id, message)
        (new_id,) = set(re.findall(r"doc-[0-9a-f]{32}", message)) - {old_id}
        self.assertIn("injected deletion failure", message)
        # 修好之後重試：殘留的新版本先被清掉再重匯，記替換
        self.server.fail_vision = False
        retried = self.ingest()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("替換 1 份", retried.stdout)
        self.assertEqual(self.status_count(retried, "processed"), 1)
        self.assertEqual(self.registered_id(self.document), new_id)

    def test_failing_to_delete_the_old_version_reports_both_ids_and_the_next_ingest_finishes_the_replacement(self):
        old_id = self.import_old_then_change()

        result = self.ingest(**FAIL_FIRST_DELETE_ENV)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.registered_id(self.document), old_id, "對照表不變，下次才知道要補刪")
        self.assertIn("替換 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2, "新舊兩個版本都在")
        message = next(line for line in result.stderr.splitlines() if line.startswith("匯入失敗：paper.pdf"))
        self.assertIn(old_id, message)
        (new_id,) = set(re.findall(r"doc-[0-9a-f]{32}", message)) - {old_id}
        self.assertIn("injected deletion failure", message)

        retried = self.ingest()

        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("替換 1 份", retried.stdout)
        self.assertEqual(self.status_count(retried, "processed"), 1)
        self.assertEqual(self.registered_id(self.document), new_id)


class ReplaceNewDocumentFailureCliTest(ReplaceCase):
    def test_a_new_document_that_fails_to_import_keeps_its_failure_record(self):
        # 不是替換：維持現行行為，失敗紀錄留在知識庫，下次 ingest 先清掉再重匯
        self.write_version(self.document, OLD)
        self.server.fail_vision = True
        failed = self.ingest()
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertEqual(self.status_count(failed, "failed"), 1)
        self.assertEqual(self.status_count(failed, "processed"), 0)
        self.server.fail_vision = False
        retried = self.ingest()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("新增 1 份", retried.stdout)
        self.assertEqual(self.status_count(retried, "failed"), 0)
        self.assertEqual(self.status_count(retried, "processed"), 1)


class ReplaceRegistryStateCliTest(ReplaceCase):
    def textonly(self, folder_name: str, marker: str):
        """在 tmp 的子資料夾建一份 textonly.pdf 並寫入版本標記（不同資料夾、同一個標記的兩份得到相同的文件 ID）。

        Args:
            folder_name: 子資料夾名稱。
            marker: 版本標記。

        Returns:
            文件路徑。
        """
        folder = self.tmp / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "textonly.pdf"
        self.write_version(path, marker)
        return path

    def test_a_registered_id_that_is_gone_from_the_knowledge_base_is_imported_as_new_and_deletes_nothing(self):
        other = self.make_document(self.tmp / "other", "textonly.pdf")
        self.write_version(self.document, OLD)
        self.assertEqual(self.ingest(other).returncode, 0)
        self.assertEqual(self.ingest().returncode, 0)
        registry = self.read_registry()
        key = str(self.document.resolve())
        registry["documents"][key]["doc_id"] = "doc-" + "0" * 32
        self.write_registry(registry)
        self.write_version(self.document, NEW)

        result = self.ingest()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertIn("替換 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 3, "沒有刪任何東西：other、舊版本與新版本都在")
        self.assertRegex(self.registered_id(self.document), r"^doc-[0-9a-f]{32}$")
        self.assertNotEqual(self.registered_id(self.document), "doc-" + "0" * 32)

    def test_a_replacement_interrupted_after_the_new_version_was_imported_deletes_the_old_version_next_time(self):
        # 造出中斷後的狀態：知識庫有兩個版本，對照表仍指向舊版本，路徑上的內容已是新版本
        old_copy = self.textonly("old", OLD)
        new_copy = self.textonly("new", NEW)
        self.assertEqual(self.ingest(old_copy).returncode, 0)
        self.assertEqual(self.ingest(new_copy).returncode, 0)
        registry = self.read_registry()
        old_key, new_key = str(old_copy.resolve()), str(new_copy.resolve())
        new_id = registry["documents"][new_key]["doc_id"]
        del registry["documents"][new_key]
        self.write_registry(registry)
        self.write_version(old_copy, NEW)
        before = len(self.server.requests)

        result = self.ingest(old_copy)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 1)
        self.assertEqual(self.registered_id(old_copy), new_id)
        self.assertNotIn(
            "/v1/chat/completions", [r["path"] for r in self.server.requests[before:]], "新版本已匯入，不該再呼叫 LLM"
        )

    def test_the_old_version_is_kept_when_another_path_still_uses_it(self):
        first = self.textonly("one", OLD)
        second = self.textonly("two", OLD)
        self.assertEqual(self.ingest(first).returncode, 0)
        self.assertEqual(self.ingest(second).returncode, 0)
        old_id = self.registered_id(first)
        self.assertEqual(self.registered_id(second), old_id)
        self.write_version(first, NEW)

        result = self.ingest(first)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2, "舊版本留著給 two 用，加上新版本")
        self.assertNotEqual(self.registered_id(first), old_id)
        self.assertEqual(self.registered_id(second), old_id)
        context = self.context_of_query("What is Fake Entity Delta?")
        self.assertIn(OLD, context)
        self.assertIn(NEW, context)


class ReplaceFolderCliTest(ReplaceCase):
    def test_ingesting_a_folder_replaces_only_the_changed_documents(self):
        folder = self.tmp / "cards"
        changed = self.make_document(folder, "changed.pdf")
        steady = self.make_document(folder, "steady.pdf")
        self.write_version(changed, OLD)
        self.assertEqual(self.ingest(folder).returncode, 0)
        steady_id = self.registered_id(steady)
        self.write_version(changed, NEW)

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertIn("沒變 1 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2)
        self.assertEqual(self.registered_id(steady), steady_id)


# ==============================
# Python API
# ==============================


class ReplaceApiCase(ReplaceHelpers, PythonApiCase):
    """Python API 子行程版的替換測試基底。"""


class ReplacePythonApiTest(ReplaceApiCase):
    """模組函式與 Session 的 ingest 回傳結果有 replaced 分類，替換規則與 CLI 相同。"""

    MODES = ("functions", "session")

    def classify_lines(self, result) -> list[dict[str, list[str]]]:
        """解析 driver 的 classify 行。

        Args:
            result: run_api 的 CompletedProcess。

        Returns:
            每個 classify 步驟一個 {"added", "replaced", "unchanged"} → 路徑清單。
        """
        parsed = []
        for line in result.stdout.splitlines():
            match = re.fullmatch(r"classify added=(.*) replaced=(.*) unchanged=(.*)", line)
            if match:
                names = ("added", "replaced", "unchanged")
                parsed.append({name: [p for p in value.split("|") if p] for name, value in zip(names, match.groups())})
        return parsed

    def test_a_document_rewritten_between_two_ingests_in_one_process_is_listed_as_replaced(self):
        paper = str(self.document.resolve())
        for mode in self.MODES:
            with self.subTest(mode=mode):
                shutil.rmtree(self.working_dir, ignore_errors=True)
                self.write_version(self.document, OLD)
                result = self.run_api(
                    "classify:paper.pdf", "rewrite:paper.pdf:" + NEW, "classify:paper.pdf", "classify:paper.pdf", mode=mode
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                first, second, third = self.classify_lines(result)
                self.assertEqual(first, {"added": [paper], "replaced": [], "unchanged": []})
                self.assertEqual(second, {"added": [], "replaced": [paper], "unchanged": []})
                self.assertEqual(third, {"added": [], "replaced": [], "unchanged": [paper]})

    def test_a_failed_replacement_is_reported_on_the_report_and_replaced_after_the_retry(self):
        paper = str(self.document.resolve())
        self.write_version(self.document, OLD)
        self.assertEqual(self.run_api("doc:paper.pdf").returncode, 0)
        old_id = self.registered_id(self.document)
        self.write_version(self.document, NEW)
        self.server.fail_vision = True

        failed = self.run_api("doc:paper.pdf")

        self.assertEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertRegex(failed.stdout, r"doc paper\.pdf skipped=False error=.*舊版本 " + old_id)
        self.assertEqual(self.registered_id(self.document), old_id)

        self.server.fail_vision = False
        retried = self.run_api("classify:paper.pdf")
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertEqual(self.classify_lines(retried), [{"added": [], "replaced": [paper], "unchanged": []}])
