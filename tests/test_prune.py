"""來源已不在的文件與 `--prune` 的行為測試：ingest 資料夾時列出之前匯入、現在檔案不在的文件，加 `--prune` 才刪。

為什麼存在：官網撤下的文件要離開知識庫（spec：.scratch/incremental-update/spec.md「匯入端：替換與移除」「匯入端：介面」），
但路徑打錯或指到別的資料夾時不能刪光。這裡驗證 ticket 04 的範圍：只列出不刪、`--prune` 只刪來源資料夾等於這次資料夾的紀錄、
刪除前先查共用版本、資料夾不存在或沒有文件時不做移除、單一檔案不檢查移除、刪除失敗的回報，以及對照表的來源資料夾
記的是 `ingest <資料夾>` 的那個資料夾。答案快取見 tests/test_answer_cache.py。

關鍵設計決策：
- 縫與其他 ingest 測試相同：CLI 子行程（`python -m rag_lab`）與 Python API（子行程內呼叫模組函式與 Session），
  配假 OpenAI server 與假 mineru。測試直接讀對照表檔，「知識庫裡有幾份文件」從 CLI 輸出的文件狀態統計觀察，
  不直接讀 LightRAG 的儲存檔。
- 文件內容用假 mineru 的版本標記行（`% fake version: <文字>`）區分：不同標記得到不同的文件 ID，同一個標記的兩個路徑共用同一個版本。
- 「來源已不在」靠刪掉檔案造出來；路徑一律以 `resolve()` 比較（macOS 的暫存資料夾在 /var，實體路徑在 /private/var）。

Dependencies: 標準函式庫。
"""

import shutil

from tests.test_cli import run_cli
from tests.test_pipeline import INGEST_TIMEOUT
from tests.test_python_api import PythonApiCase
from tests.test_replace import FAIL_FIRST_DELETE_ENV, ReplaceCase, ReplaceHelpers

# ==============================
# CLI
# ==============================


def extraction_calls(requests: list[dict]) -> int:
    """LightRAG 實體抽取送出的 LLM 請求數（抽取的 prompt 以 Knowledge Graph Specialist 開頭）。

    Args:
        requests: FakeOpenAIServer.requests。

    Returns:
        路徑為 /v1/chat/completions、而且訊息含實體抽取角色說明的請求數。
    """
    return sum(
        1
        for r in requests
        if r["path"] == "/v1/chat/completions"
        and any("Knowledge Graph Specialist" in str(m.get("content")) for m in r["payload"]["messages"])
    )


class PruneHelpers(ReplaceHelpers):
    """建立資料夾與判讀報告的輔助；與 PipelineCase 組合使用。"""

    def make_folder(self, name: str, *documents: str):
        """建立資料夾，裡面每份文件的內容各不相同（以檔名當版本標記）。

        Args:
            name: tmp 底下的資料夾名稱。
            *documents: 檔名。

        Returns:
            資料夾路徑。
        """
        folder = self.tmp / name
        folder.mkdir(parents=True, exist_ok=True)
        for document in documents:
            self.write_version(folder / document, f"{name}-{document}")
        return folder

    def prune(self, folder):
        """對資料夾執行 `ingest --prune`。

        Args:
            folder: 資料夾路徑。

        Returns:
            CompletedProcess。
        """
        return run_cli(["ingest", str(folder), "--prune"], self.env(), timeout=INGEST_TIMEOUT)

    def section(self, result, label: str) -> list[str]:
        """取出 ingest 報告裡某個分類的路徑清單（標題行「<label> N 份」之後縮排兩格的行）。

        Args:
            result: ingest 的 CompletedProcess。
            label: 分類名稱，例如「已刪除」。

        Returns:
            該分類列出的路徑；沒有這個分類的標題行時測試失敗。
        """
        lines = result.stdout.splitlines()
        heading = next((i for i, line in enumerate(lines) if line.startswith(f"{label} ") and line.endswith(" 份")), None)
        self.assertIsNotNone(heading, f"報告沒有「{label}」：\n{result.stdout}")
        paths = []
        for line in lines[heading + 1 :]:
            if not line.startswith("  "):
                break
            paths.append(line.strip())
        return paths


class PruneCase(PruneHelpers, ReplaceCase):
    """CLI 子行程版的 prune 測試基底。"""


class MissingSourcesCliTest(PruneCase):
    def test_without_prune_a_document_whose_file_is_gone_is_only_listed(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        gone_key = str((folder / "gone.pdf").resolve())
        registry_before = self.read_registry()
        (folder / "gone.pdf").unlink()

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("來源已不在（未刪） 1 份", result.stdout)
        self.assertEqual(self.section(result, "來源已不在（未刪）"), [gone_key])
        self.assertIn("已刪除 0 份", result.stdout)
        self.assertEqual(self.status_count(result, "processed"), 2, "知識庫沒有改動")
        self.assertEqual(self.read_registry(), registry_before, "對照表沒有改動")


class PruneCliTest(PruneCase):
    def test_prune_deletes_the_document_from_the_knowledge_base_and_the_registry(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        keep_key, gone_key = str((folder / "keep.pdf").resolve()), str((folder / "gone.pdf").resolve())
        (folder / "gone.pdf").unlink()

        result = self.prune(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("已刪除 1 份", result.stdout)
        self.assertEqual(self.section(result, "已刪除"), [gone_key])
        self.assertIn("來源已不在（未刪） 0 份", result.stdout, "每份文件只歸一類")
        self.assertEqual(self.status_count(result, "processed"), 1)
        self.assertEqual(list(self.read_registry()["documents"]), [keep_key])
        self.assertNotIn("gone.pdf", self.context_of_query("What is Fake Entity Alpha?"))

    def test_prune_keeps_the_llm_extraction_cache_so_a_document_that_comes_back_is_cheap_to_import(self):
        # textonly 開頭的檔名讓假 mineru 不輸出圖片，LLM 呼叫只剩實體抽取與表格、公式描述
        folder = self.make_folder("cards", "textonly-keep.pdf", "textonly-gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        (folder / "textonly-gone.pdf").unlink()
        self.assertEqual(self.prune(folder).returncode, 0)
        self.write_version(folder / "textonly-gone.pdf", "cards-textonly-gone.pdf")
        before = len(self.server.requests)

        result = self.ingest(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertEqual(extraction_calls(self.server.requests[before:]), 0, "實體抽取命中快取，不再呼叫 LLM")

    def test_prune_only_touches_documents_imported_from_this_folder(self):
        first = self.make_folder("first", "keep.pdf", "gone.pdf")
        second = self.make_folder("second", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(first).returncode, 0)
        self.assertEqual(self.ingest(second).returncode, 0)
        (first / "gone.pdf").unlink()
        (second / "gone.pdf").unlink()

        result = self.prune(first)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.section(result, "已刪除"), [str((first / "gone.pdf").resolve())])
        self.assertEqual(self.status_count(result, "processed"), 3, "second 的文件不受影響")
        self.assertIn(str((second / "gone.pdf").resolve()), self.read_registry()["documents"])
        listed = self.ingest(second)
        self.assertEqual(self.section(listed, "來源已不在（未刪）"), [str((second / "gone.pdf").resolve())])

    def test_a_document_imported_as_a_single_file_is_checked_when_its_folder_is_pruned(self):
        # ASSUMPTION（spec「匯入端：對照表」）：單一檔案記它所在的資料夾，之後對那個資料夾 --prune 時也在檢查範圍內
        folder = self.make_folder("cards", "keep.pdf", "solo.pdf")
        self.assertEqual(self.ingest(folder / "keep.pdf").returncode, 0)
        self.assertEqual(self.ingest(folder / "solo.pdf").returncode, 0)
        (folder / "solo.pdf").unlink()

        result = self.prune(folder)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.section(result, "已刪除"), [str((folder / "solo.pdf").resolve())])

    def test_prune_removes_only_the_path_when_another_path_still_uses_the_same_version(self):
        first = self.make_folder("first", "keep.pdf")
        second = self.make_folder("second")
        self.write_version(first / "shared.pdf", "SHARED")
        self.write_version(second / "shared.pdf", "SHARED")
        self.assertEqual(self.ingest(first).returncode, 0)
        self.assertEqual(self.ingest(second).returncode, 0)
        (first / "shared.pdf").unlink()

        result = self.prune(first)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.section(result, "已刪除"), [str((first / "shared.pdf").resolve())], "仍記為已刪除")
        self.assertEqual(self.status_count(result, "processed"), 2, "共用的版本還在：keep 與 shared 各一份")
        self.assertEqual(list(self.read_registry()["documents"]), [str((first / "keep.pdf").resolve()), str((second / "shared.pdf").resolve())])
        self.assertIn("SHARED", self.context_of_query("What is Fake Entity Alpha?"))

    def test_a_deletion_failure_is_reported_as_a_failure_and_leaves_the_registry_alone(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        gone_key = str((folder / "gone.pdf").resolve())
        registry_before = self.read_registry()
        (folder / "gone.pdf").unlink()

        result = run_cli(["ingest", str(folder), "--prune"], self.env(**FAIL_FIRST_DELETE_ENV), timeout=INGEST_TIMEOUT)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("已刪除 0 份", result.stdout)
        self.assertIn("來源已不在（未刪） 0 份", result.stdout, "刪除失敗的文件只歸「失敗」")
        self.assertIn(gone_key, result.stderr)
        self.assertIn("injected deletion failure", result.stderr)
        self.assertEqual(self.read_registry(), registry_before)
        self.assertEqual(self.status_count(result, "processed"), 2)

        retried = self.prune(folder)

        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertEqual(self.section(retried, "已刪除"), [gone_key])
        self.assertEqual(self.status_count(retried, "processed"), 1)


    def test_a_registry_that_cannot_be_written_after_the_deletion_fails_with_a_message_that_says_so(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        (folder / "gone.pdf").unlink()
        # 讓寫暫存檔失敗（暫存檔名是實作細節，見 tests/test_registry.py）；讀取對照表仍然成功
        (self.working_dir / "rag_lab_documents.json.tmp").mkdir()

        result = self.prune(folder)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(str(self.registry_path), result.stderr)
        self.assertIn("已從知識庫刪除但對照表沒有更新", result.stderr)

        (self.working_dir / "rag_lab_documents.json.tmp").rmdir()
        retried = self.prune(folder)

        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertEqual(self.section(retried, "已刪除"), [str((folder / "gone.pdf").resolve())])
        self.assertEqual(list(self.read_registry()["documents"]), [str((folder / "keep.pdf").resolve())])


class PruneRefusalCliTest(PruneCase):
    def test_a_folder_that_does_not_exist_is_a_usage_error_and_removes_nothing(self):
        folder = self.make_folder("cards", "keep.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        registry_before = self.read_registry()

        for extra in ((), ("--prune",)):
            with self.subTest(extra=extra):
                result = run_cli(["ingest", str(self.tmp / "typo"), *extra], self.env(), timeout=INGEST_TIMEOUT)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("路徑不存在", result.stderr)
                self.assertEqual(self.read_registry(), registry_before)

    def test_a_folder_with_no_supported_documents_is_a_usage_error_and_removes_nothing(self):
        folder = self.make_folder("cards", "keep.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        registry_before = self.read_registry()
        (folder / "keep.pdf").unlink()
        (folder / "notes.txt").write_text("not a document", encoding="utf-8")

        for extra in ((), ("--prune",)):
            with self.subTest(extra=extra):
                result = run_cli(["ingest", str(folder), *extra], self.env(), timeout=INGEST_TIMEOUT)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("資料夾內沒有支援的文件", result.stderr)
                self.assertEqual(self.read_registry(), registry_before)

    def test_prune_with_a_single_file_is_a_usage_error_that_says_why(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        registry_before = self.read_registry()
        (folder / "gone.pdf").unlink()

        result = run_cli(["ingest", str(folder / "keep.pdf"), "--prune"], self.env(), timeout=INGEST_TIMEOUT)

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--prune", result.stderr)
        self.assertIn("資料夾", result.stderr)
        self.assertEqual(self.read_registry(), registry_before)

    def test_ingesting_a_single_file_does_not_check_for_missing_sources(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        (folder / "gone.pdf").unlink()

        result = self.ingest(folder / "keep.pdf")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("來源已不在", result.stdout)
        self.assertIn(str((folder / "gone.pdf").resolve()), self.read_registry()["documents"])


class SourceFolderCliTest(PruneCase):
    def test_the_registry_records_the_folder_that_was_ingested(self):
        folder = self.make_folder("cards", "keep.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        entry = self.read_registry()["documents"][str((folder / "keep.pdf").resolve())]
        self.assertEqual(entry["source_folder"], str(folder.resolve()))

    def test_a_symlinked_file_whose_target_is_outside_the_folder_is_still_found_missing_and_pruned(self):
        outside = self.make_folder("outside", "real.pdf")
        folder = self.make_folder("cards", "keep.pdf")
        (folder / "link.pdf").symlink_to(outside / "real.pdf")
        self.assertEqual(self.ingest(folder).returncode, 0)
        target_key = str((outside / "real.pdf").resolve())
        entry = self.read_registry()["documents"][target_key]
        self.assertEqual(entry["source_folder"], str(folder.resolve()), "記的是 ingest 的資料夾，不是實體檔案所在的資料夾")
        (outside / "real.pdf").unlink()

        listed = self.ingest(folder)
        self.assertEqual(self.section(listed, "來源已不在（未刪）"), [target_key])

        pruned = self.prune(folder)
        self.assertEqual(pruned.returncode, 0, pruned.stdout + pruned.stderr)
        self.assertEqual(self.section(pruned, "已刪除"), [target_key])
        self.assertEqual(list(self.read_registry()["documents"]), [str((folder / "keep.pdf").resolve())])


# ==============================
# Python API
# ==============================


class PruneApiCase(PruneHelpers, PythonApiCase):
    """Python API 子行程版的 prune 測試基底。"""


class PrunePythonApiTest(PruneApiCase):
    """模組函式與 Session 的 ingest 指定來源資料夾與 prune 時，規則與 CLI 相同。"""

    MODES = ("functions", "session")

    def sync_line(self, result) -> str:
        """取出 driver 的 sync 結果行（正常結果或例外）。

        Args:
            result: run_api 的 CompletedProcess。

        Returns:
            以 sync 開頭的那一行（只有一個 sync 步驟時）。
        """
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (line,) = [line for line in result.stdout.splitlines() if line.startswith("sync ")]
        return line

    def test_missing_sources_are_listed_without_prune_and_deleted_with_it(self):
        for mode in self.MODES:
            with self.subTest(mode=mode):
                shutil.rmtree(self.working_dir, ignore_errors=True)
                folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
                self.assertEqual(self.sync_line(self.run_api("sync:cards", mode=mode)), "sync missing= removed= failed=")
                registry_before = self.read_registry()
                (folder / "gone.pdf").unlink()

                listed = self.run_api("sync:cards", mode=mode)

                self.assertEqual(self.sync_line(listed), "sync missing=gone.pdf removed= failed=")
                self.assertEqual(self.read_registry(), registry_before)

                pruned = self.run_api("sync:cards:prune", mode=mode)

                self.assertEqual(self.sync_line(pruned), "sync missing= removed=gone.pdf failed=")
                self.assertEqual(list(self.read_registry()["documents"]), [str((folder / "keep.pdf").resolve())])
                self.write_version(folder / "gone.pdf", "restored")

    def test_a_deletion_failure_is_reported_on_the_summary_and_leaves_the_registry_alone(self):
        folder = self.make_folder("cards", "keep.pdf", "gone.pdf")
        self.assertEqual(self.sync_line(self.run_api("sync:cards")), "sync missing= removed= failed=")
        registry_before = self.read_registry()
        (folder / "gone.pdf").unlink()

        result = self.run_api("sync:cards:prune", **FAIL_FIRST_DELETE_ENV)

        self.assertEqual(self.sync_line(result), "sync missing= removed= failed=gone.pdf")
        self.assertEqual(self.read_registry(), registry_before)

    def test_a_source_folder_that_does_not_exist_or_has_no_documents_is_a_usage_error_with_or_without_prune(self):
        folder = self.make_folder("cards", "keep.pdf")
        self.assertEqual(self.run_api("sync:cards").returncode, 0)
        registry_before = self.read_registry()
        empty = self.tmp / "empty"
        empty.mkdir()
        (empty / "notes.txt").write_text("not a document", encoding="utf-8")
        (folder / "keep.pdf").unlink()
        for mode in self.MODES:
            for name in ("typo", "empty", "cards"):
                for option in ("", ":prune"):
                    with self.subTest(mode=mode, folder=name, option=option):
                        line = self.sync_line(self.run_api(f"sync:{name}{option}", mode=mode))
                        self.assertTrue(line.startswith("sync raised PipelineError "), line)
                        self.assertEqual(self.read_registry(), registry_before)

    def test_prune_without_a_source_folder_is_a_usage_error(self):
        for mode in self.MODES:
            with self.subTest(mode=mode):
                result = self.run_api("bare_prune:paper.pdf", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, r"bare_prune PipelineError .*source_folder")
                self.assertFalse(self.registry_path.exists())

    def test_the_registry_records_the_source_folder_that_was_given_and_the_files_folder_when_none_was(self):
        other = self.make_folder("elsewhere", "stray.pdf", "plain.pdf")
        folder = self.make_folder("cards", "keep.pdf")
        self.assertEqual(self.run_api("into:elsewhere/stray.pdf:cards", "doc:elsewhere/plain.pdf").returncode, 0)
        documents = self.read_registry()["documents"]
        self.assertEqual(documents[str((other / "stray.pdf").resolve())]["source_folder"], str(folder.resolve()))
        self.assertEqual(documents[str((other / "plain.pdf").resolve())]["source_folder"], str(other.resolve()))

    def test_importing_an_unchanged_document_again_with_another_source_folder_moves_it_to_that_folder(self):
        other = self.make_folder("elsewhere", "stray.pdf")
        folder = self.make_folder("cards", "keep.pdf")
        key = str((other / "stray.pdf").resolve())
        self.assertEqual(self.run_api("doc:elsewhere/stray.pdf").returncode, 0)
        before = self.read_registry()["documents"][key]
        self.assertEqual(before["source_folder"], str(other.resolve()))

        self.assertEqual(self.run_api("into:elsewhere/stray.pdf:cards").returncode, 0)

        after = self.read_registry()["documents"][key]
        self.assertEqual(after["source_folder"], str(folder.resolve()))
        self.assertEqual(after["doc_id"], before["doc_id"])
        self.assertEqual(after["ingested_at"], before["ingested_at"], "內容沒變，匯入時間不動")
