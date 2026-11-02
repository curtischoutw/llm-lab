"""匯入對照表（路徑 → 文件 ID）的行為測試：ingest 的「新增」「沒變」分類與 `rag_lab_documents.json`。

為什麼存在：增量更新（spec：.scratch/incremental-update/spec.md「匯入端：對照表」）要靠 rag_lab 自己記的對照表判斷
某個路徑上的文件是新的、變了還是沒變。這裡驗證 ticket 01 的範圍：對照表的建立與補登、分類「新增」「沒變」、
對照表壞掉或寫不進去時 ingest 失敗。替換、移除、清答案快取是後面 ticket 的範圍。

關鍵設計決策：
- 縫與其他 ingest 測試相同：CLI 子行程（`python -m rag_lab`）與 Python API（子行程內呼叫 rag_lab.pipeline 的模組函式與
  Session，driver 見 tests/test_python_api.py），配假 OpenAI server 與假 mineru。測試直接讀寫對照表檔，
  不直接讀 LightRAG 的儲存檔；「沒有呼叫模型」以假 server 收到的請求觀察。
- 對照表的檔名與格式是 spec 定下的公開契約，所以這裡寫死字面值，不從 rag_lab 取值。
- 暫存檔名 `rag_lab_documents.json.tmp` 只用在「寫入失敗」測試：在那個路徑預先建一個資料夾，讓寫暫存檔失敗，
  而讀取對照表仍然成功（ASSUMPTION：暫存檔名是實作細節，spec 只規定先寫暫存檔再改名）。
- 路徑一律以 `resolve()` 比較：macOS 的暫存資料夾在 /var，實體路徑在 /private/var。

Dependencies: 標準函式庫。
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from tests.test_pipeline import PipelineCase
from tests.test_python_api import PythonApiCase

REGISTRY_NAME = "rag_lab_documents.json"
REGISTRY_TMP_NAME = "rag_lab_documents.json.tmp"

# ==============================
# 工具函式
# ==============================


def model_calls(requests: list[dict]) -> list[str]:
    """取出需要模型運算的請求路徑（LLM 與 embedding）。

    Args:
        requests: FakeOpenAIServer.requests。

    Returns:
        路徑為 /v1/chat/completions 或 /v1/embeddings 的請求路徑，依收到順序排列。
    """
    return [r["path"] for r in requests if r["path"] in ("/v1/chat/completions", "/v1/embeddings")]


class RegistryHelpers:
    """提供讀寫對照表的輔助；與 PipelineCase 或 PythonApiCase 組合使用（需要 self.working_dir、self.tmp）。"""

    @property
    def registry_path(self) -> Path:
        """對照表檔案路徑。

        Returns:
            WORKING_DIR 底下的 rag_lab_documents.json。
        """
        return self.working_dir / REGISTRY_NAME

    def read_registry(self) -> dict:
        """讀出對照表。

        Returns:
            對照表檔的 JSON 內容。
        """
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def write_registry(self, content: object) -> None:
        """寫入對照表（必要時建立 WORKING_DIR）。

        Args:
            content: 寫成 JSON 的內容。
        """
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(content), encoding="utf-8")

    def make_document(self, folder: Path, name: str) -> Path:
        """在 folder 建立一份 PDF 文件的替身。

        Args:
            folder: 資料夾（不存在會建立）。
            name: 檔名。

        Returns:
            文件路徑。
        """
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(b"%PDF-1.4 fake")
        return path


class RegistryCase(RegistryHelpers, PipelineCase):
    """CLI 子行程版的對照表測試基底。"""


class RegistryApiCase(RegistryHelpers, PythonApiCase):
    """Python API 子行程版的對照表測試基底。"""


# ==============================
# CLI
# ==============================


class RegistryNewDocumentCliTest(RegistryCase):
    def test_first_ingest_of_a_file_records_it_as_new_with_its_folder(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        registry = self.read_registry()
        self.assertEqual(registry["version"], 1)
        key = str(self.document.resolve())
        self.assertEqual(list(registry["documents"]), [key])
        entry = registry["documents"][key]
        self.assertRegex(entry["doc_id"], r"^doc-[0-9a-f]{32}$")
        self.assertEqual(entry["source_folder"], str(self.document.resolve().parent))
        datetime.fromisoformat(entry["ingested_at"])
        self.assertIn("新增 1 份", result.stdout)
        self.assertIn(f"  {key}", result.stdout)
        self.assertIn("沒變 0 份", result.stdout)

    def test_ingesting_a_folder_records_each_document_with_that_folder_as_source(self):
        folder = self.tmp / "cards"
        self.make_document(folder, "a.pdf")
        self.make_document(folder, "b.pdf")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        documents = self.read_registry()["documents"]
        self.assertEqual(sorted(documents), sorted(str((folder / name).resolve()) for name in ("a.pdf", "b.pdf")))
        for entry in documents.values():
            self.assertEqual(entry["source_folder"], str(folder.resolve()))
        self.assertIn("新增 2 份", result.stdout)

    def test_a_path_through_a_symlink_is_recorded_as_its_real_path(self):
        link = self.tmp / "link.pdf"
        link.symlink_to(self.document)
        self.assertEqual(self.ingest(link).returncode, 0)
        self.assertEqual(list(self.read_registry()["documents"]), [str(self.document.resolve())])


class RegistryUnchangedCliTest(RegistryCase):
    def test_ingesting_the_same_unchanged_document_again_is_unchanged_and_calls_no_model(self):
        self.assertEqual(self.ingest().returncode, 0)
        before_registry = self.registry_path.read_text(encoding="utf-8")
        calls_before = len(model_calls(self.server.requests))
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("沒變 1 份", result.stdout)
        self.assertIn("新增 0 份", result.stdout)
        self.assertEqual(len(model_calls(self.server.requests)), calls_before)
        self.assertEqual(self.registry_path.read_text(encoding="utf-8"), before_registry)

    def test_a_document_registered_with_the_same_id_but_not_fully_imported_is_imported_as_new(self):
        # 對照表有這個路徑、ID 相同，但知識庫裡沒有這份文件（例如先前失敗）：照一般匯入，成功記「新增」
        self.assertEqual(self.ingest().returncode, 0)
        registry = self.read_registry()
        key = str(self.document.resolve())
        registry["documents"][key]["ingested_at"] = "2000-01-01T00:00:00+00:00"
        shutil.rmtree(self.working_dir)
        self.write_registry(registry)
        calls_before = len(model_calls(self.server.requests))
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertIn("沒變 0 份", result.stdout)
        self.assertGreater(len(model_calls(self.server.requests)), calls_before, "知識庫是空的，應該重新匯入")
        entry = self.read_registry()["documents"][key]
        self.assertEqual(entry["doc_id"], registry["documents"][key]["doc_id"])
        self.assertNotEqual(entry["ingested_at"], "2000-01-01T00:00:00+00:00")


class RegistryMigrationCliTest(RegistryCase):
    def test_an_already_imported_document_without_a_registry_is_filled_in_and_reported_unchanged(self):
        self.assertEqual(self.ingest().returncode, 0)
        doc_id = self.read_registry()["documents"][str(self.document.resolve())]["doc_id"]
        self.registry_path.unlink()
        calls_before = len(model_calls(self.server.requests))
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("沒變 1 份", result.stdout)
        self.assertIn("新增 0 份", result.stdout)
        self.assertEqual(len(model_calls(self.server.requests)), calls_before)
        entry = self.read_registry()["documents"][str(self.document.resolve())]
        self.assertEqual(entry["doc_id"], doc_id)
        self.assertEqual(entry["source_folder"], str(self.document.resolve().parent))


class RegistrySharedContentCliTest(RegistryCase):
    def test_a_new_path_with_the_content_of_a_registered_path_is_new_and_writes_nothing_to_the_knowledge_base(self):
        first = self.make_document(self.tmp / "one", "textonly.pdf")
        second = self.make_document(self.tmp / "two", "textonly.pdf")
        self.assertEqual(self.ingest(first).returncode, 0)
        calls_before = len(model_calls(self.server.requests))
        result = self.ingest(second)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("新增 1 份", result.stdout)
        self.assertIn("沒變 0 份", result.stdout)
        self.assertEqual(len(model_calls(self.server.requests)), calls_before, "知識庫已有這份內容，不該再寫入")
        self.assertIn("processed=1", result.stdout, "知識庫仍然只有一份文件")
        documents = self.read_registry()["documents"]
        self.assertEqual(sorted(documents), sorted([str(first.resolve()), str(second.resolve())]))
        self.assertEqual(documents[str(first.resolve())]["doc_id"], documents[str(second.resolve())]["doc_id"])
        self.assertEqual(documents[str(second.resolve())]["source_folder"], str(second.resolve().parent))


class RegistryFailureCliTest(RegistryCase):
    def test_a_broken_registry_fails_before_any_document_is_processed_and_names_the_file(self):
        broken_registries = {
            "not json": "{not json",
            "not an object": "[]",
            "wrong version": json.dumps({"version": 2, "documents": {}}),
            "documents not an object": json.dumps({"version": 1, "documents": []}),
            "entry without doc_id": json.dumps(
                {"version": 1, "documents": {"/x.pdf": {"ingested_at": "2000-01-01", "source_folder": "/"}}}
            ),
            "entry not an object": json.dumps({"version": 1, "documents": {"/x.pdf": "doc-1"}}),
        }
        for label, text in broken_registries.items():
            with self.subTest(label):
                self.working_dir.mkdir(parents=True, exist_ok=True)
                self.registry_path.write_text(text, encoding="utf-8")
                calls_before = len(model_calls(self.server.requests))
                result = self.ingest()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(str(self.registry_path), result.stderr)
                self.assertEqual(len(model_calls(self.server.requests)), calls_before)
                self.assertEqual(self.registry_path.read_text(encoding="utf-8"), text, "壞掉的對照表不可被改寫")

    def test_a_registry_that_cannot_be_written_fails_the_ingest_and_creates_no_registry(self):
        self.working_dir.mkdir(parents=True)
        (self.working_dir / REGISTRY_TMP_NAME).mkdir()
        result = self.ingest()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(str(self.registry_path), result.stderr)
        self.assertFalse(self.registry_path.exists())


# ==============================
# Python API
# ==============================


class RegistryPythonApiTest(RegistryApiCase):
    """模組函式與 Session 的 ingest 回傳結果有同樣的分類，對照表的規則與 CLI 相同。"""

    MODES = ("functions", "session")

    def parse_classify(self, line: str) -> tuple[list[str], list[str]]:
        """解析 driver 的 classify 行。

        Args:
            line: `classify added=<路徑|路徑> replaced=<路徑> unchanged=<路徑>`。

        Returns:
            (新增的路徑, 沒變的路徑)；替換的路徑不回傳（ticket 02 的測試在 tests/test_replace.py）。
        """
        added, rest = line.removeprefix("classify added=").split(" replaced=")
        _, unchanged = rest.split(" unchanged=")
        return [p for p in added.split("|") if p], [p for p in unchanged.split("|") if p]

    def test_summary_lists_new_then_unchanged_documents_across_calls_in_one_process(self):
        second = self.make_document(self.tmp, "second.pdf")
        for mode in self.MODES:
            with self.subTest(mode=mode):
                shutil.rmtree(self.working_dir, ignore_errors=True)
                result = self.run_api("classify:paper.pdf", "classify:paper.pdf,second.pdf", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                first_call, second_call = (self.parse_classify(line) for line in result.stdout.splitlines())
                paper, other = str(self.document.resolve()), str(second.resolve())
                self.assertEqual(first_call, ([paper], []))
                self.assertEqual(second_call, ([other], [paper]))
                documents = self.read_registry()["documents"]
                self.assertEqual(sorted(documents), sorted([paper, other]))
                self.assertEqual(documents[other]["source_folder"], str(second.resolve().parent))

    def test_documents_without_a_registry_entry_are_filled_in_as_unchanged(self):
        self.assertEqual(self.ingest().returncode, 0)
        self.registry_path.unlink()
        calls_before = len(model_calls(self.server.requests))
        for mode in self.MODES:
            with self.subTest(mode=mode):
                self.registry_path.unlink(missing_ok=True)
                result = self.run_api("classify:paper.pdf", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.parse_classify(result.stdout.strip()), ([], [str(self.document.resolve())]))
                self.assertEqual(list(self.read_registry()["documents"]), [str(self.document.resolve())])
        self.assertEqual(len(model_calls(self.server.requests)), calls_before)

    def test_a_new_path_with_the_content_of_a_registered_path_is_listed_as_new(self):
        first = self.make_document(self.tmp / "one", "textonly.pdf")
        second = self.make_document(self.tmp / "two", "textonly.pdf")
        self.document = first
        self.assertEqual(self.ingest(first).returncode, 0)
        calls_before = len(model_calls(self.server.requests))
        # driver 的檔名相對於 document 所在的資料夾
        result = self.run_api("classify:../two/textonly.pdf")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        added, unchanged = self.parse_classify(result.stdout.strip())
        self.assertEqual([Path(p).resolve() for p in added], [second.resolve()])
        self.assertEqual(unchanged, [])
        self.assertEqual(len(model_calls(self.server.requests)), calls_before)

    def test_a_broken_registry_raises_pipeline_error_naming_the_file_before_any_document_is_processed(self):
        self.working_dir.mkdir(parents=True)
        self.registry_path.write_text("{not json", encoding="utf-8")
        for mode in self.MODES:
            with self.subTest(mode=mode):
                result = self.run_api("classify:paper.pdf", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.startswith("classify raised PipelineError "), result.stdout)
                self.assertIn(str(self.registry_path), result.stdout)
        self.assertEqual(model_calls(self.server.requests), [])

    def test_a_registry_that_cannot_be_written_raises_pipeline_error(self):
        self.working_dir.mkdir(parents=True)
        (self.working_dir / REGISTRY_TMP_NAME).mkdir()
        for mode in self.MODES:
            with self.subTest(mode=mode):
                result = self.run_api("classify:paper.pdf", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.startswith("classify raised PipelineError "), result.stdout)
                self.assertIn(str(self.registry_path), result.stdout)
