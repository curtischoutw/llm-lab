"""既有文件遷移的行為測試：對照表沒有這個路徑時，ingest 用檔名到文件狀態找舊版本並替換。

為什麼存在：現有知識庫的 311 份文件是對照表建立之前匯入的，內容改了之後要能被替換，不能當成新文件而留下兩個版本
（spec：.scratch/incremental-update/spec.md「匯入端：對照表」規則 3、故事 29、30）。這裡驗證 ticket 03 的範圍：
檔名剛好對到一份就替換、排除已對照到別的路徑的 ID、對到 0 份當作新增、對到多份記成失敗並列出候選。

關鍵設計決策：
- 縫與其他 ingest 測試相同：CLI 子行程與 Python API（子行程內呼叫模組函式與 Session），配假 OpenAI server 與假 mineru。
- 「對照表建立之前匯入」靠先正常匯入、再刪掉對照表檔造出來（對照表的檔名與格式是公開契約）；「候選已對照到別的路徑」
  靠只留下一部分對照表紀錄造出來。內容用假 mineru 的版本標記行區分（見 tests/test_replace.py）。
- 同名但在不同資料夾的文件用來造出「檔名對到多份」：文件狀態只記檔名，不記路徑。

Dependencies: 標準函式庫。
"""

import json
import re
import shutil

from tests.test_replace import NEW, OLD, ReplaceApiCase, ReplaceCase

THIRD = "VERSIONTHIRD"
DOC_ID = r"doc-[0-9a-f]{32}"


class MigrateHelpers:
    """造出同名文件與對照表狀態的輔助；與 ReplaceCase 或 ReplaceApiCase 組合使用。"""

    def named_copy(self, folder_name: str, marker: str):
        """在 tmp 的子資料夾建一份 shared.pdf 並寫入版本標記。

        Args:
            folder_name: 子資料夾名稱。
            marker: 版本標記。

        Returns:
            文件路徑。
        """
        folder = self.tmp / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "shared.pdf"
        self.write_version(path, marker)
        return path

    def forget_paths(self, *paths) -> None:
        """從對照表移除這些路徑的紀錄，造出「對照表建立之前就匯入」的狀態。

        Args:
            *paths: 要移除紀錄的文件路徑。
        """
        registry = self.read_registry()
        for path in paths:
            del registry["documents"][str(path.resolve())]
        self.write_registry(registry)

    def registry_keys(self) -> set[str]:
        """對照表裡所有的路徑。

        Returns:
            路徑集合。
        """
        return set(self.read_registry()["documents"])


class MigrateCliTest(MigrateHelpers, ReplaceCase):
    def test_a_changed_document_missing_from_the_registry_replaces_the_version_found_by_file_name(self):
        old_id = self.import_old_then_change()
        self.registry_path.unlink()

        result = self.ingest()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertIn("新增 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 1, "舊版本被刪掉，知識庫只有一個版本")
        self.assertNotEqual(self.registered_id(self.document), old_id)
        context = self.context_of_query("What is Fake Entity Beta?")
        self.assertIn(NEW, context)
        self.assertNotIn(OLD, context)

    def test_a_candidate_registered_to_another_path_is_excluded_so_the_document_is_added(self):
        registered = self.named_copy("one", OLD)
        self.assertEqual(self.ingest(registered).returncode, 0)
        registered_id = self.registered_id(registered)
        newcomer = self.named_copy("two", NEW)

        result = self.ingest(newcomer)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertIn("替換 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2, "同名但已對照到別的路徑的文件不能被當成舊版本刪掉")
        self.assertEqual(self.registered_id(registered), registered_id)

    def test_only_the_candidate_without_a_registry_entry_is_replaced_when_another_one_is_registered(self):
        registered = self.named_copy("one", OLD)
        legacy = self.named_copy("two", NEW)
        self.assertEqual(self.ingest(registered).returncode, 0)
        self.assertEqual(self.ingest(legacy).returncode, 0)
        registered_id = self.registered_id(registered)
        self.forget_paths(legacy)
        self.write_version(legacy, THIRD)

        result = self.ingest(legacy)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("替換 1 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2, "one 的版本留著，two 的舊版本換成新版本")
        self.assertEqual(self.registered_id(registered), registered_id)
        context = self.context_of_query("What is Fake Entity Gamma?")
        self.assertIn(OLD, context)
        self.assertIn(THIRD, context)
        self.assertNotIn(NEW, context)

    def test_a_file_name_that_matches_nothing_is_added(self):
        self.write_version(self.document, OLD)
        self.assertEqual(self.ingest().returncode, 0)
        self.registry_path.unlink()
        other = self.make_document(self.tmp / "other", "different-name.pdf")
        self.write_version(other, NEW)

        result = self.ingest(other)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertIn("替換 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2)

    def test_a_file_name_that_matches_several_documents_fails_and_changes_nothing(self):
        first = self.named_copy("one", OLD)
        second = self.named_copy("two", NEW)
        self.assertEqual(self.ingest(first).returncode, 0)
        self.assertEqual(self.ingest(second).returncode, 0)
        candidates = {self.registered_id(first), self.registered_id(second)}
        self.registry_path.unlink()
        third = self.named_copy("three", THIRD)

        result = self.ingest(third)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        message = next(line for line in result.stderr.splitlines() if line.startswith("匯入失敗：shared.pdf"))
        self.assertEqual(set(re.findall(DOC_ID, message)), candidates, "訊息列出所有候選的文件 ID")
        self.assertIn("新增 0 份", result.stdout)
        self.assertIn("替換 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2, "不替換也不新增")
        self.assertEqual(self.status_count(result, "failed"), 0)
        self.assertNotIn(str(third.resolve()), self.registry_keys() if self.registry_path.exists() else set())

    def test_a_folder_run_reports_the_ambiguous_document_as_failed_and_still_processes_the_others(self):
        first = self.named_copy("one", OLD)
        second = self.named_copy("two", NEW)
        self.assertEqual(self.ingest(first).returncode, 0)
        self.assertEqual(self.ingest(second).returncode, 0)
        self.registry_path.unlink()
        folder = self.named_copy("three", THIRD).parent
        fresh = self.make_document(folder, "fresh.pdf")

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("1/2 篇匯入失敗", result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertEqual(list(json.loads(self.registry_path.read_text(encoding="utf-8"))["documents"]), [str(fresh.resolve())])


class MigratePythonApiTest(MigrateHelpers, ReplaceApiCase):
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

    def test_a_changed_document_missing_from_the_registry_is_listed_as_replaced(self):
        paper = str(self.document.resolve())
        for mode in self.MODES:
            with self.subTest(mode=mode):
                shutil.rmtree(self.working_dir, ignore_errors=True)
                self.write_version(self.document, OLD)
                self.assertEqual(self.ingest().returncode, 0)
                self.registry_path.unlink()
                self.write_version(self.document, NEW)

                result = self.run_api("classify:paper.pdf", "classify:paper.pdf", mode=mode)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                replaced, unchanged = self.classify_lines(result)
                self.assertEqual(replaced, {"added": [], "replaced": [paper], "unchanged": []})
                self.assertEqual(unchanged, {"added": [], "replaced": [], "unchanged": [paper]})

    def test_a_file_name_that_matches_several_documents_is_a_failed_report_listing_the_candidates(self):
        first = self.named_copy("one", OLD)
        second = self.named_copy("two", NEW)
        self.assertEqual(self.ingest(first).returncode, 0)
        self.assertEqual(self.ingest(second).returncode, 0)
        candidates = {self.registered_id(first), self.registered_id(second)}
        self.registry_path.unlink()
        self.document = self.named_copy("three", THIRD)
        for mode in self.MODES:
            with self.subTest(mode=mode):
                result = self.run_api("doc:shared.pdf", "classify:shared.pdf", mode=mode)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report, classified = result.stdout.splitlines()
                self.assertRegex(report, r"^doc shared\.pdf skipped=False error=")
                self.assertEqual(set(re.findall(DOC_ID, report)), candidates)
                self.assertEqual(classified, "classify added= replaced= unchanged=")
                self.assertFalse(self.registry_path.exists())
