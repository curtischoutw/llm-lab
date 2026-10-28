"""fetch_documents.py 的行為測試：以子行程執行腳本，對本機假 HTTP server 下載。

為什麼存在：fetch_documents.py 是獨立腳本，沒有 CLI 以外的縫。測試只從子行程進入，觀察
結束碼、stdout／stderr、輸出資料夾的內容，以及假 server 收到的請求；不 import 腳本的函式。

關鍵設計決策：
- 腳本裡寫死的清單帶真實的 SHA-256，假 server 送不出符合的內容。所以測試用一個 `python -c`
  driver 進入：driver 載入腳本、把模組層級的清單 DOCUMENTS 換成測試用的小清單，再呼叫 main(argv)。
  這是本檔唯一碰到腳本內部的地方（DOCUMENTS 的欄位名稱）。腳本實際使用的清單另有一個測試，
  對照 spec 的兩張表，不經過假 server。
- 下載位址的前綴用環境變數 FETCH_DOCUMENTS_BASE 指向假 server。
- 假 server 記錄收到的請求（路徑與 User-Agent），讓測試能斷言「沒有發出請求」與「請求了哪些路徑」。
- 每個案例的 --out 都指向暫存資料夾。

執行方式：python3 -m unittest scripts/test_fetch_documents.py

Dependencies: 僅標準函式庫。
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

# driver：把腳本的 DOCUMENTS 換成 argv[1] 的 JSON 清單後執行 main(argv[2:])。
DRIVER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import fetch_documents
fetch_documents.DOCUMENTS = [fetch_documents.Document(**d) for d in json.loads(sys.argv[2])]
sys.exit(fetch_documents.main(sys.argv[3:]))
"""

# driver：印出腳本實際使用的清單（JSON），供對照 spec 的表格。
LIST_DRIVER = """
import dataclasses, json, sys
sys.path.insert(0, sys.argv[1])
import fetch_documents
print(json.dumps([dataclasses.asdict(d) for d in fetch_documents.DOCUMENTS]))
"""

URL_PREFIX = "https://raw.githubusercontent.com/"


# ==============================
# 工具：測試用清單、假 server、執行腳本
# ==============================


def sha256(data: bytes) -> str:
    """回傳 data 的 SHA-256 十六進位字串。"""
    return hashlib.sha256(data).hexdigest()


class Fixture:
    """一份測試文件：檔名、資料夾、假 server 上的內容。"""

    def __init__(self, name: str, fmt: str, folder: str, body: bytes) -> None:
        self.name = name
        self.fmt = fmt
        self.folder = folder
        self.body = body
        self.server_path = f"/test/{name}"

    def entry(self, *, sha: str | None = None) -> dict[str, str]:
        """腳本清單的一筆（欄位名稱同 fetch_documents.Document）。

        Args:
            sha: 預期的 SHA-256；預設為 body 的雜湊。
        """
        return {
            "name": self.name,
            "format": self.fmt,
            "folder": self.folder,
            "url": f"{URL_PREFIX}test/{self.name}",
            "sha256": sha if sha is not None else sha256(self.body),
            "license": "MIT（test/repo）",
        }


SLIDES = Fixture("a.pptx", "PPT", "documents", b"slides-a" * 50)
REPORT = Fixture("b.docx", "Word", "documents", b"report-b" * 50)
SHEET = Fixture("c.xlsx", "Excel", "format_check", b"sheet-c" * 50)
OLD_SHEET = Fixture("d.xls", "Excel", "format_check", b"oldxls-d" * 50)
ALL = [SLIDES, REPORT, SHEET, OLD_SHEET]


class FakeServer:
    """本機假 server：依路徑回傳設定好的回應，並記錄每個請求。

    路徑沒有設定時回 404。`truncated` 內的路徑宣告的 Content-Length 大於實際送出的內容，
    送到一半就斷線。
    """

    def __init__(self, fixtures: list[Fixture]) -> None:
        self.bodies = {f.server_path: f.body for f in fixtures}
        self.truncated: set[str] = set()
        self.requests: list[tuple[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                """關閉預設的 stderr 請求記錄。"""

            def do_GET(self) -> None:
                outer.requests.append((self.path, self.headers.get("User-Agent", "")))
                body = outer.bodies.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                if self.path in outer.truncated:
                    self.send_header("Content-Length", str(len(body) + 1000))
                    self.end_headers()
                    self.wfile.write(body[: len(body) // 2])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """腳本要使用的 base URL（不含結尾斜線）。"""
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        """啟動背景 thread。"""
        self._thread.start()

    def stop(self) -> None:
        """停止 server 並釋放埠。"""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


def run_script(
    entries: list[dict[str, str]], *args: str, base_url: str = "http://127.0.0.1:9"
) -> subprocess.CompletedProcess:
    """以 driver 執行 fetch_documents.main。

    Args:
        entries: 取代 DOCUMENTS 的清單。
        *args: 傳給 main 的命令列參數。
        base_url: FETCH_DOCUMENTS_BASE 的值。預設指向沒有人在聽的埠，下載會失敗。

    Returns:
        已完成的行程（文字模式）。
    """
    return subprocess.run(
        [sys.executable, "-c", DRIVER, str(SCRIPTS_DIR), json.dumps(entries), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "FETCH_DOCUMENTS_BASE": base_url},
    )


class ServerTestCase(unittest.TestCase):
    """每個案例有一個假 server（提供 ALL 的內容）與暫存的輸出資料夾 self.out。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "data"
        self.server = FakeServer(ALL)
        self.server.start()
        self.addCleanup(self.server.stop)

    def run_fetch(self, entries: list[dict[str, str]], *args: str) -> subprocess.CompletedProcess:
        """以假 server 與 self.out 執行腳本。"""
        return run_script(entries, "--out", str(self.out), *args, base_url=self.server.base_url)

    def files_under_out(self) -> list[str]:
        """self.out 底下所有檔案的相對路徑（排序）；資料夾不存在時為空。"""
        if not self.out.exists():
            return []
        return sorted(str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file())


# ==============================
# 測試案例
# ==============================


class DownloadTests(ServerTestCase):
    def test_downloads_every_document_into_its_folder(self) -> None:
        result = self.run_fetch([f.entry() for f in ALL])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(),
            ["documents/a.pptx", "documents/b.docx", "format_check/c.xlsx", "format_check/d.xls"],
        )
        for f in ALL:
            self.assertEqual((self.out / f.folder / f.name).read_bytes(), f.body)

    def test_each_document_is_reported_by_name(self) -> None:
        result = self.run_fetch([f.entry() for f in ALL])
        for f in ALL:
            self.assertIn(f.name, result.stdout)
        self.assertIn("downloaded", result.stdout)

    def test_requests_carry_an_identifiable_user_agent(self) -> None:
        self.run_fetch([f.entry() for f in ALL])
        self.assertEqual(len(self.server.requests), len(ALL))
        for _path, user_agent in self.server.requests:
            self.assertTrue(user_agent.startswith("llm-lab-fetch-documents/"), user_agent)

class HashTests(ServerTestCase):
    WRONG = "0" * 64

    def test_hash_mismatch_exits_nonzero_names_the_document_and_keeps_no_file(self) -> None:
        entries = [SLIDES.entry(), REPORT.entry(sha=self.WRONG), SHEET.entry()]
        result = self.run_fetch(entries)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(REPORT.name, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        # 雜湊不符的那份既不是正式檔案、也不留 .part；失敗後不再下載後面的文件
        self.assertEqual(self.files_under_out(), ["documents/a.pptx"])
        self.assertNotIn(SHEET.server_path, [path for path, _ in self.server.requests])

class NetworkFailureTests(ServerTestCase):
    def test_http_error_exits_nonzero_names_the_document_and_stops(self) -> None:
        del self.server.bodies[REPORT.server_path]  # 假 server 對這個路徑回 404
        result = self.run_fetch([f.entry() for f in ALL])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(REPORT.name, result.stderr)
        self.assertIn("404", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.files_under_out(), ["documents/a.pptx"])
        self.assertNotIn(SHEET.server_path, [path for path, _ in self.server.requests])

    def test_connection_dropped_mid_download_names_the_document_and_leaves_no_file(self) -> None:
        self.server.truncated.add(SLIDES.server_path)
        result = self.run_fetch([f.entry() for f in ALL])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(SLIDES.name, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.files_under_out(), [], "斷線後不該留下正式檔案或 .part")

    def test_unreachable_server_names_the_document(self) -> None:
        result = run_script([SLIDES.entry()], "--out", str(self.out))  # 預設 base_url 沒有人在聽
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(SLIDES.name, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

class ExistingFileTests(ServerTestCase):
    def test_second_run_skips_documents_whose_hash_matches(self) -> None:
        entries = [f.entry() for f in ALL]
        self.assertEqual(self.run_fetch(entries).returncode, 0)
        requests_after_first_run = len(self.server.requests)
        result = self.run_fetch(entries)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.server.requests), requests_after_first_run, "第二次執行不該發出請求")
        self.assertEqual(result.stdout.count("exists"), len(ALL), result.stdout)
        self.assertNotIn("downloaded", result.stdout)

    def test_existing_file_with_wrong_hash_is_reported_and_not_overwritten(self) -> None:
        (self.out / "documents").mkdir(parents=True)
        stale = self.out / "documents" / SLIDES.name
        stale.write_bytes(b"edited by hand")
        result = self.run_fetch([f.entry() for f in ALL])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(SLIDES.name, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(stale.read_bytes(), b"edited by hand", "雜湊不符的既有檔案不該被覆蓋")
        self.assertEqual(self.server.requests, [], "既有檔案雜湊不符時不該再發請求")

    def test_leftover_part_file_from_an_interrupted_run_is_replaced(self) -> None:
        (self.out / "documents").mkdir(parents=True)
        (self.out / "documents" / (SLIDES.name + ".part")).write_bytes(b"half")
        result = self.run_fetch([SLIDES.entry()])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.files_under_out(), ["documents/a.pptx"])
        self.assertEqual((self.out / "documents" / SLIDES.name).read_bytes(), SLIDES.body)

class GroupTests(ServerTestCase):
    def test_group_documents_downloads_only_that_folder(self) -> None:
        result = self.run_fetch([f.entry() for f in ALL], "--group", "documents")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.files_under_out(), ["documents/a.pptx", "documents/b.docx"])
        self.assertEqual(sorted(path for path, _ in self.server.requests), [SLIDES.server_path, REPORT.server_path])

    def test_group_format_check_downloads_only_that_folder(self) -> None:
        result = self.run_fetch([f.entry() for f in ALL], "--group", "format_check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.files_under_out(), ["format_check/c.xlsx", "format_check/d.xls"])
        self.assertEqual(sorted(path for path, _ in self.server.requests), [SHEET.server_path, OLD_SHEET.server_path])


class ArgumentValidationTests(ServerTestCase):
    def test_unknown_group_is_rejected_before_any_request(self) -> None:
        result = self.run_fetch([f.entry() for f in ALL], "--group", "papers")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("papers", result.stderr)
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.out.exists(), "參數不合法時不應建立輸出資料夾")

    def test_out_that_is_a_regular_file_is_rejected_before_any_request(self) -> None:
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.out.write_text("not a folder")
        result = self.run_fetch([f.entry() for f in ALL])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(str(self.out), result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.requests, [])


class DocumentListTests(unittest.TestCase):
    """腳本實際使用的清單，對照 spec「選定的文件」的兩張表（URL、格式、資料夾、授權）。"""

    # (資料夾, 格式, 檔名, URL 去掉前綴後的路徑, 授權所在 repo)
    EXPECTED = [
        ("documents", "PPT", "RAGHack-EvaluatingAChatApp.pptx", "microsoft/RAG_Hack/main/slides/RAGHack-EvaluatingAChatApp.pptx", "MIT"),
        ("documents", "PPT", "docling_arch.pptx", "docling-project/docling/main/docs/assets/docling_arch.pptx", "MIT"),
        ("documents", "Word", "Experimentations_for_Kg_creation.docx", "neo4j-labs/llm-graph-builder/main/experiments/Experimentations%20for%20Kg%20creation.docx", "Apache-2.0"),
        ("documents", "Word", "LLM_Comparisons_with_one_pdf.docx", "neo4j-labs/llm-graph-builder/main/experiments/LLM%20Comparisons%20with%20one%20pdf.docx", "Apache-2.0"),
        ("documents", "圖片", "graphrag-auto-tune-diagram.png", "microsoft/graphrag/main/docs/img/auto-tune-diagram.png", "MIT"),
        ("documents", "圖片", "graphrag-unified-search-app.png", "microsoft/graphrag/main/unified-search-app/images/image-1.png", "MIT"),
        ("format_check", "Excel", "2023-half-year-analyses-by-segment.xlsx", "Unstructured-IO/unstructured/main/example-docs/2023-half-year-analyses-by-segment.xlsx", "Apache-2.0"),
        ("format_check", "Excel", "xlsx_01.xlsx", "docling-project/docling/main/tests/data/xlsx/sources/xlsx_01.xlsx", "MIT"),
        ("format_check", "PPT（舊格式）", "legacy_sample.ppt", "docling-project/docling/main/tests/data/ppt/sources/legacy_sample.ppt", "MIT"),
        ("format_check", "Word（舊格式）", "legacy_sample.doc", "docling-project/docling/main/tests/data/doc/sources/legacy_sample.doc", "MIT"),
        ("format_check", "Excel（舊格式）", "legacy_sample.xls", "docling-project/docling/main/tests/data/xls/sources/legacy_sample.xls", "MIT"),
    ]

    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run(
            [sys.executable, "-c", LIST_DRIVER, str(SCRIPTS_DIR)], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        cls.documents = json.loads(result.stdout)

    def test_list_matches_the_spec_tables(self) -> None:
        actual = [
            (d["folder"], d["format"], d["name"], d["url"].removeprefix(URL_PREFIX), d["license"].split("（")[0])
            for d in self.documents
        ]
        self.assertEqual(actual, self.EXPECTED)

    def test_every_entry_has_a_sha256_and_a_license_with_its_repo(self) -> None:
        for d in self.documents:
            self.assertRegex(d["sha256"], r"^[0-9a-f]{64}$", d["name"])
            self.assertIn("（", d["license"], d["name"])
        self.assertEqual(len({d["sha256"] for d in self.documents}), len(self.documents))

    def test_names_are_unique_within_each_folder(self) -> None:
        keys = [(d["folder"], d["name"]) for d in self.documents]
        self.assertEqual(len(set(keys)), len(keys))


if __name__ == "__main__":
    unittest.main()
