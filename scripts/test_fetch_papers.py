"""fetch_papers.py 的離線行為測試：ID 驗證階段，以及對本機假 arXiv server 的下載失敗行為。

為什麼存在：fetch_papers.py 是獨立腳本、沒有 CLI 縫可接，所以以 subprocess 呼叫腳本，
在公開介面（命令列參數、環境變數、結束碼、stderr）觀察行為。對真實 arXiv 的標題比對、
下載、重複執行不重複下載無法離線驗證，以真實執行的輸出為證據；下載途中斷線這類網路失敗
則用環境變數 FETCH_PAPERS_ARXIV_BASE 把腳本指向本機假 server 來重現。

關鍵設計決策：
- 每個案例都把 --out 指向暫存資料夾，並斷言它沒被建立：ID 驗證必須發生在任何
  網路請求與檔案寫入之前，這同時證明「不合法 ID 不會觸發下載」。
- 假 server 只實作 arXiv API 的標題查詢與 PDF 下載兩個路徑，PDF 路徑可設定成宣告的
  Content-Length 大於實際送出的內容就斷線。

執行方式：python3 -m unittest scripts/test_fetch_papers.py

Dependencies: 僅標準函式庫。
"""

import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "fetch_papers.py"


# ==============================
# 工具函式
# ==============================


def run_script(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """以 subprocess 執行 fetch_papers.py。

    Args:
        *args: 傳給腳本的命令列參數。
        env: 額外的環境變數（疊加在目前環境上）。

    Returns:
        已完成的行程（含 returncode、stdout、stderr，文字模式）。
    """
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


class FakeArxiv:
    """本機假 arXiv：/api/query 回單一論文的標題，/pdf/<id> 宣告 1000 位元組但只送 100 位元組就斷線。"""

    ARXIV_ID = "2005.11401"
    TITLE = "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"

    def __init__(self) -> None:
        feed = (
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            f"<id>http://arxiv.org/abs/{self.ARXIV_ID}v1</id><title>{self.TITLE}</title></entry></feed>"
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                """關閉預設的 stderr 請求記錄。"""

            def do_GET(self) -> None:
                if self.path.startswith("/api/query"):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(feed)))
                    self.end_headers()
                    self.wfile.write(feed)
                    return
                self.send_response(200)
                self.send_header("Content-Length", "1000")
                self.end_headers()
                self.wfile.write(b"%PDF-" + b"x" * 95)
                self.wfile.flush()
                self.close_connection = True

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


# ==============================
# 測試案例
# ==============================


class InvalidIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "papers"

    def assert_rejected(self, bad_id: str, *other_ids: str) -> None:
        result = run_script("--out", str(self.out), "--ids", *other_ids, bad_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(bad_id, result.stderr)
        self.assertFalse(self.out.exists(), "ID 驗證失敗時不應建立輸出資料夾")

    def test_malformed_id_exits_nonzero_and_names_it(self) -> None:
        self.assert_rejected("not-an-id")

    def test_truncated_id_is_rejected(self) -> None:
        self.assert_rejected("2005.1140")

    def test_version_suffix_is_rejected(self) -> None:
        self.assert_rejected("2005.11401v4")

    def test_bad_id_after_valid_ids_is_named_and_nothing_runs(self) -> None:
        self.assert_rejected("20x4.16130", "2005.11401", "2404.16130")

    def test_well_formed_id_outside_the_list_is_rejected(self) -> None:
        # 格式合法但不在清單內：沒有預期標題可比對，不能下載。
        self.assert_rejected("1706.03762")


class DownloadFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "papers"
        self.arxiv = FakeArxiv()
        self.arxiv.start()
        self.addCleanup(self.arxiv.stop)

    def test_connection_dropped_mid_download_exits_nonzero_names_the_id_and_leaves_no_file(self) -> None:
        result = run_script(
            "--out", str(self.out), "--ids", FakeArxiv.ARXIV_ID, env={"FETCH_PAPERS_ARXIV_BASE": self.arxiv.base_url}
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(FakeArxiv.ARXIV_ID, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [], "斷線後不該留下 PDF 或 .part")


if __name__ == "__main__":
    unittest.main()
