"""fetch_taishin.py 的行為測試：以子行程執行腳本，對本機假 HTTP server 與假 Chrome 下載。

為什麼存在：fetch_taishin.py 是獨立腳本，沒有 CLI 以外的縫。測試只從子行程進入，觀察結束碼、
stdout／stderr、輸出資料夾的檔案、下載清單的內容、假 server 收到的請求，以及假 Chrome 收到的 HTML；
不 import 腳本的函式。

關鍵設計決策：
- 網址前綴（TAISHIN_WWW_BASE）、Chrome 路徑（TAISHIN_CHROME）與請求間隔
  （TAISHIN_REQUEST_INTERVAL_SEC）都用環境變數指到假的版本。
- 假 Chrome 是 tests/fake_chrome.py；測試在暫存資料夾寫一個 shell wrapper 呼叫它，
  腳本拿到的 Chrome 路徑就是這個 wrapper。
- 假頁面依官網結構筆記的最小結構製作：主內容區含預設收合的區塊與彈窗，主內容區外有導覽選單，
  頁面裡有 script 與 style。
- 假 server 記錄每個請求的路徑、收到的時間與 User-Agent。

執行方式：python3 -m unittest scripts/test_fetch_taishin.py

Dependencies: 僅標準函式庫。
"""

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "fetch_taishin.py"
FAKE_CHROME = REPO_ROOT / "tests" / "fake_chrome.py"

OVERVIEW_PATH = "/TSB/personal/credit/intro/overview/"
CARD_PATH_FORMAT = "/TSB/personal/credit/intro/overview/{cg}/{card}/"
FAST_INTERVAL = "0.02"


# ==============================
# 假頁面
# ==============================


def overview_html(card_paths: list[str]) -> str:
    """產生總覽頁：每張卡 3 個錨點（圖片、卡名、按鈕），外加不是卡片頁的干擾連結。

    Args:
        card_paths: 卡片頁的路徑清單。

    Returns:
        總覽頁的 HTML。
    """
    items = ""
    for path in card_paths:
        items += (
            f'<li class="ul-li-items"><a href="{path}"><img src="x.gif"></a>'
            f'<a itemprop="url" href="{path}" class="oval-style">瞭解更多</a>'
            f'<a href="{path}"><p itemprop="name">卡 {path}</p></a>'
            '<a href="https://example.invalid/eServiceA/apply/index.jsp?pc=634">立即申辦</a></li>'
        )
    return (
        "<html><body>"
        '<a href="/TSB/personal/credit/intro/overview/">信用卡總覽</a>'
        '<a href="/TSB/personal/credit/intro/rights/oversea/right0101/">權益</a>'
        f'<ul class="ul-items">{items}</ul>'
        "</body></html>"
    )


def card_html(label: str) -> str:
    """產生卡片頁：主內容區含收合區塊、彈窗與未關閉的標籤，主內容區外有導覽選單與頁尾。

    Args:
        label: 放進主內容區的卡名文字，讓各頁內容不同。

    Returns:
        卡片頁的 HTML。
    """
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>信用卡總覽</title>
<link rel="stylesheet" href="/site.css">
<style>.site{{color:red}} SITE-STYLE-TEXT</style>
<script>var SITE_SCRIPT_TEXT = "<div id='centercontainer'>";</script></head>
<body>
<div id="topnav"><ul><li>NAV-MENU-TEXT</li></ul></div>
<div class="content"><div id="centercontainer">
  <div class="title"><p>{label}</p></div>
  <div id="ts-comp-41-collapse-1" class="collapse"><div class="inner"><p>COLLAPSED-TEXT</p></div></div>
  <div class="modal fade" id="fid001361"><div class="modal-body"><p>MODAL-TEXT 每日23:59前轉換</p></div></div>
  <script>var INNER_SCRIPT_TEXT = 1;</script>
  <style>INNER-STYLE-TEXT</style>
  <img src="/img/a.gif">
  <ul><li>未關閉項目一<li>未關閉項目二</ul>
  <p>未關閉的段落
</div></div>
<div id="leftcontainer">LEFT-MENU-TEXT</div>
<footer>FOOTER-TEXT</footer>
</body></html>"""


def card_html_without_main_content() -> str:
    """產生沒有 id="centercontainer" 的卡片頁。"""
    return "<html><body><div id='other'>NO-MAIN-CONTENT-HERE</div></body></html>"


# ==============================
# 工具：假 server、假 Chrome、執行腳本
# ==============================


class FakeServer:
    """本機假 HTTP server：routes 把路徑（含 query）對到 (狀態碼, body)；沒有登記的路徑回 404。"""

    def __init__(self, routes: dict[str, tuple[int, bytes]]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, float, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append((self.path, time.monotonic(), self.headers.get("User-Agent", "")))
                status, body = outer.routes.get(self.path, (404, b"not found"))
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """假 server 的網址前綴（無結尾斜線）。"""
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def paths(self) -> list[str]:
        """依時間順序列出收到的請求路徑。"""
        return [path for path, _time, _ua in self.requests]


def write_chrome_wrapper(directory: Path) -> Path:
    """在 directory 寫一個 shell wrapper，轉呼叫 tests/fake_chrome.py。

    Args:
        directory: 放 wrapper 的資料夾。

    Returns:
        wrapper 的路徑。
    """
    wrapper = directory / "fake-chrome"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CHROME}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return wrapper


class ScriptTestCase(unittest.TestCase):
    """每個案例有假 server（routes 由案例設定）、假 Chrome wrapper 與暫存的輸出資料夾 self.out。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "taishin"
        self.chrome = write_chrome_wrapper(self.tmp)
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.server = FakeServer(self.routes)
        self.server.start()
        self.addCleanup(self.server.stop)

    def serve_cards(self, cards: dict[str, str]) -> None:
        """登記總覽頁與各卡片頁。

        Args:
            cards: 卡片頁路徑對頁面 HTML。
        """
        self.routes[OVERVIEW_PATH] = (200, overview_html(list(cards)).encode())
        for path, html in cards.items():
            self.routes[path] = (200, html.encode())

    def run_script(self, *, chrome: str | None = None, interval: str = FAST_INTERVAL) -> subprocess.CompletedProcess:
        """以假 server、假 Chrome 與 self.out 執行腳本。

        Args:
            chrome: TAISHIN_CHROME 的值；預設為假 Chrome wrapper。
            interval: TAISHIN_REQUEST_INTERVAL_SEC 的值。

        Returns:
            已完成的行程（文字模式）。
        """
        env = {
            **os.environ,
            "TAISHIN_WWW_BASE": self.server.base_url,
            "TAISHIN_CHROME": chrome if chrome is not None else str(self.chrome),
            "TAISHIN_REQUEST_INTERVAL_SEC": interval,
        }
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--out", str(self.out)],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def manifest(self) -> list[dict[str, str]]:
        """讀下載清單，一行一筆。"""
        text = (self.out / "_meta" / "manifest.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def files_under_out(self) -> list[str]:
        """self.out 底下所有檔案的相對路徑（排序）；資料夾不存在時為空。"""
        if not self.out.exists():
            return []
        return sorted(str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file())


RICHART = CARD_PATH_FORMAT.format(cg="cg047", card="card001")
DAQUANLIAN = CARD_PATH_FORMAT.format(cg="cg010", card="card001")
# 同一個 cg 底下的第二張卡：本地檔名不能只用 cgNNN
DAQUANLIAN_2 = CARD_PATH_FORMAT.format(cg="cg010", card="card002")


# ==============================
# 假 Chrome 夾具本身
# ==============================


class FakeChromeFixtureTests(unittest.TestCase):
    def run_fake(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(FAKE_CHROME), *args], capture_output=True, text=True, timeout=30)

    def test_rejects_unexpected_arguments_and_prints_them(self) -> None:
        result = self.run_fake("--headless", "--print-to-pdf=/tmp/x.pdf", "file:///nonexistent.html")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--print-to-pdf=/tmp/x.pdf", result.stderr)

    def test_rejects_input_that_is_not_an_existing_html_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_fake(
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--user-data-dir={tmp}/profile",
                f"--print-to-pdf={tmp}/out.pdf",
                f"file://{tmp}/missing.html",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(tmp) / "out.pdf").exists())

    def test_writes_pdf_that_contains_the_received_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>收到的內容</p>", encoding="utf-8")
            result = self.run_fake(
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--user-data-dir={tmp}/profile",
                f"--print-to-pdf={tmp}/out.pdf",
                page.as_uri(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = (Path(tmp) / "out.pdf").read_bytes()
            self.assertTrue(data.startswith(b"%PDF-"))
            self.assertIn("<p>收到的內容</p>".encode(), data)


# ==============================
# 卡片頁
# ==============================


class CardPageTests(ScriptTestCase):
    def test_prints_each_card_page_to_pdf_with_unique_names_and_keeps_raw_html(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN"), DAQUANLIAN_2: card_html("DQL2")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(),
            [
                "_meta/html/card_cg010_card001.html",
                "_meta/html/card_cg010_card002.html",
                "_meta/html/card_cg047_card001.html",
                "_meta/manifest.jsonl",
                "_meta/print/card_cg010_card001.html",
                "_meta/print/card_cg010_card002.html",
                "_meta/print/card_cg047_card001.html",
                "cards/card_cg010_card001.pdf",
                "cards/card_cg010_card002.pdf",
                "cards/card_cg047_card001.pdf",
            ],
        )
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertEqual(
            (self.out / "_meta" / "html" / "card_cg047_card001.html").read_bytes(), self.routes[RICHART][1]
        )

    def test_duplicate_links_and_non_card_links_are_fetched_once_or_not_at_all(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.run_script()
        # 總覽頁 1 次；卡片頁 1 次（3 個錨點指向同一頁）；權益連結、申辦連結、總覽頁自己的連結都不下載
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RICHART])


class ChromeInputTests(ScriptTestCase):
    """交給 Chrome 的 HTML：含主內容區的全部文字，不含官網的 script、樣式與主內容區以外的文字。"""

    def setUp(self) -> None:
        super().setUp()
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 假 Chrome 的輸出檔 = 假 PDF 檔頭 + 收到的 HTML
        self.received = (self.out / "cards" / "card_cg047_card001.pdf").read_text(encoding="utf-8", errors="replace")

    def test_contains_main_content_including_collapsed_blocks_and_modals(self) -> None:
        for text in ("RICHART", "COLLAPSED-TEXT", "MODAL-TEXT 每日23:59前轉換", "未關閉項目二", "未關閉的段落"):
            self.assertIn(text, self.received)

    def test_excludes_site_scripts_styles_and_content_outside_the_main_area(self) -> None:
        for text in (
            "SITE_SCRIPT_TEXT",
            "SITE-STYLE-TEXT",
            "INNER_SCRIPT_TEXT",
            "INNER-STYLE-TEXT",
            "NAV-MENU-TEXT",
            "LEFT-MENU-TEXT",
            "FOOTER-TEXT",
            "/site.css",
        ):
            self.assertNotIn(text, self.received)

    def test_has_base_href_pointing_to_the_original_url_and_fixed_print_css(self) -> None:
        self.assertIn(f'<base href="{self.server.base_url}{RICHART}">', self.received)
        self.assertIn("border-collapse:collapse", self.received)
        self.assertIn('<img src="/img/a.gif">', self.received)


class ManifestTests(ScriptTestCase):
    def test_one_line_per_document_with_all_fields(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        self.assertEqual(self.run_script().returncode, 0)
        records = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(sorted(records), ["card_cg010_card001.pdf", "card_cg047_card001.pdf"])
        richart = records["card_cg047_card001.pdf"]
        pdf = (self.out / "cards" / "card_cg047_card001.pdf").read_bytes()
        raw = self.routes[RICHART][1]
        self.assertEqual(richart["url"], self.server.base_url + RICHART)
        self.assertEqual(richart["category"], "卡片")
        self.assertEqual(richart["format"], "PDF")
        self.assertEqual(richart["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(richart["sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertEqual(richart["html_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(richart["result"], "已下載")


class OverviewTests(ScriptTestCase):
    def test_prints_actual_card_count_and_continues_when_it_is_not_16(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("找到 2 張卡片頁（預期 16）", result.stdout)
        self.assertEqual(len(self.manifest()), 2)

    def test_prints_count_16_when_there_are_16_cards(self) -> None:
        cards = {CARD_PATH_FORMAT.format(cg=f"cg{n:03d}", card="card001"): card_html(f"CARD{n}") for n in range(16)}
        self.serve_cards(cards)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("找到 16 張卡片頁（預期 16）", result.stdout)
        self.assertEqual(len(self.manifest()), 16)

    def test_overview_failure_exits_nonzero_and_names_the_list(self) -> None:
        # 沒有登記總覽頁：假 server 回 404
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("信用卡總覽", result.stderr)
        self.assertIn("404", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH])


class FailureTests(ScriptTestCase):
    def assert_failed_page_is_reported(self, result: subprocess.CompletedProcess, filename: str, reason: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(filename, result.stderr)
        self.assertIn(reason, result.stderr)
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual([r["filename"] for r in failed], [filename])
        self.assertIn(reason, failed[0]["detail"])
        self.assertEqual(failed[0]["sha256"], "")

    def test_http_error_on_one_page_does_not_stop_the_others(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        self.routes[RICHART] = (500, b"boom")
        result = self.run_script()
        self.assert_failed_page_is_reported(result, "card_cg047_card001.pdf", "500")
        self.assertTrue((self.out / "cards" / "card_cg010_card001.pdf").is_file())
        self.assertFalse((self.out / "cards" / "card_cg047_card001.pdf").exists())

    def test_page_without_main_content_is_a_failure(self) -> None:
        self.serve_cards({RICHART: card_html_without_main_content(), DAQUANLIAN: card_html("DAQUANLIAN")})
        result = self.run_script()
        self.assert_failed_page_is_reported(result, "card_cg047_card001.pdf", "找不到主內容區")
        self.assertTrue((self.out / "cards" / "card_cg010_card001.pdf").is_file())
        # 原始 HTML 仍保存，清單記錄它的雜湊
        self.assertTrue((self.out / "_meta" / "html" / "card_cg047_card001.html").is_file())
        failed = [r for r in self.manifest() if r["result"] == "失敗"][0]
        self.assertNotEqual(failed["html_sha256"], "")

    def test_chrome_print_failure_is_a_failure_for_that_page_only(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART FAKE-CHROME-FAIL"), DAQUANLIAN: card_html("DAQUANLIAN")})
        result = self.run_script()
        self.assert_failed_page_is_reported(result, "card_cg047_card001.pdf", "Chrome")
        self.assertTrue((self.out / "cards" / "card_cg010_card001.pdf").is_file())
        self.assertFalse((self.out / "cards" / "card_cg047_card001.pdf").exists())

    def test_missing_chrome_names_the_environment_variable(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_script(chrome=str(self.tmp / "no-such-chrome"))
        self.assert_failed_page_is_reported(result, "card_cg047_card001.pdf", "TAISHIN_CHROME")

    def test_all_failures_are_listed_at_the_end(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        self.routes[RICHART] = (404, b"")
        self.routes[DAQUANLIAN] = (500, b"")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("card_cg047_card001.pdf", result.stderr)
        self.assertIn("card_cg010_card001.pdf", result.stderr)


class RerunTests(ScriptTestCase):
    def test_existing_files_are_skipped_without_requesting_the_pages(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        self.assertEqual(self.run_script().returncode, 0)
        first = {r["filename"]: r for r in self.manifest()}
        pdf = self.out / "cards" / "card_cg047_card001.pdf"
        before = pdf.read_bytes()
        self.server.requests.clear()

        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH], "第二次只該請求總覽頁")
        self.assertEqual(pdf.read_bytes(), before)
        second = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(sorted(second), sorted(first))
        for name, record in second.items():
            self.assertEqual(record["result"], "已存在略過")
            self.assertEqual(record["sha256"], first[name]["sha256"])
            self.assertEqual(record["html_sha256"], first[name]["html_sha256"])

    def test_failed_page_is_fetched_again_on_the_next_run(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.routes[RICHART] = (500, b"")
        self.assertEqual(self.run_script().returncode, 1)
        self.routes[RICHART] = (200, card_html("RICHART").encode())
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([r["result"] for r in self.manifest()], ["已下載"])


class RequestPolicyTests(ScriptTestCase):
    def test_every_request_carries_an_identifiable_user_agent(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.run_script()
        self.assertEqual(len(self.server.requests), 2)
        for _path, _time, user_agent in self.server.requests:
            self.assertTrue(user_agent.startswith("llm-lab-fetch-taishin/"), user_agent)

    def test_requests_are_spaced_by_at_least_the_configured_interval(self) -> None:
        self.serve_cards(
            {RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN"), DAQUANLIAN_2: card_html("DQL2")}
        )
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        times = [t for _path, t, _ua in self.server.requests]
        self.assertEqual(len(times), 4)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, interval - 0.02)

    def test_invalid_interval_is_rejected_before_any_request(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_script(interval="abc")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TAISHIN_REQUEST_INTERVAL_SEC", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.paths(), [])

    def test_out_that_is_a_regular_file_is_rejected_before_any_request(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.out.write_text("not a directory")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--out", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.paths(), [])


if __name__ == "__main__":
    unittest.main()
