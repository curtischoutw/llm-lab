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
- 假 server 記錄每個請求的路徑、收到的時間與 User-Agent。沒有登記的路徑交給 fallback（預設 404）；
  文件下載頁用 fallback 模擬官網「超過最後一頁時回 200 並重複最後一頁」。

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
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "fetch_taishin.py"
FAKE_CHROME = REPO_ROOT / "tests" / "fake_chrome.py"
FAKE_LIBREOFFICE = REPO_ROOT / "tests" / "fake_libreoffice.py"

OVERVIEW_PATH = "/TSB/personal/credit/intro/overview/"
CARD_PATH_FORMAT = "/TSB/personal/credit/intro/overview/{cg}/{card}/"
RIGHTS_LIST_PATH = "/TSB/personal/credit/intro/rights/"
RIGHTS_PATH_FORMAT = "/TSB/personal/credit/intro/rights/{group}/{page}/"
DOWNLOAD_LIST_PATH = "/TSB/personal/common/download/index.html"
DOWNLOAD_QUERY = "?nav1=credit&nav2=file-download"
FILES_DIR = "/TSB/export/sites/TSB/files/creditcard/"
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


def rights_list_html(sub_paths: list[str]) -> str:
    """產生權益頁：子頁連結在單引號屬性的 ul 裡，外加選單連結、PDF 連結與重複的錨點等干擾。

    Args:
        sub_paths: 權益子頁的路徑清單。

    Returns:
        權益頁的 HTML。
    """
    items = "".join(
        f"<li class='ts-comp-19-items-ul-li '><a href=\"{path}\" alt=\"x\"  target='_self'>子頁 {path}</a></li>"
        for path in sub_paths
    )
    return (
        "<html><body>"
        '<div id="topnav"><a href="/TSB/personal/credit/intro/rights/">信用卡權益</a>'
        '<a href="/TSB/personal/credit/intro/overview/">信用卡總覽</a>'
        '<a href="/TSB/personal/credit/intro/payment/">繳費</a></div>'
        f"<ul class='ts-comp-19-items-ul'>{items}{items[:items.find('</li>') + 5]}</ul>"
        '<a href="/TSB/export/sites/TSB/files/creditcard/x.pdf">PDF</a>'
        '<a href="/TSB/personal/credit/intro/overview/cg047/card001/">卡片</a>'
        "</body></html>"
    )


def download_page_html(pdf_paths: list[str], total_pages: int) -> str:
    """產生文件下載頁：每個 PDF 一個 <li>，外加頁碼選單與不該下載的干擾連結。

    Args:
        pdf_paths: 這一頁的 PDF 路徑（只有路徑的相對網址，和官網一樣）。
        total_pages: 頁碼選單列出的頁數。

    Returns:
        下載頁的 HTML。
    """
    items = "".join(
        f'<li><div class="text-block"><p>文件 {path}</p></div>'
        f'<div class="ts-comp-30 btn-block"><div class="editor-btnnn"><div class="btnnn">'
        f'<a href="{path}" title="x" class="oval-style" target="_blank">立即下載</a></div></div></div></li>'
        for path in pdf_paths
    )
    options = "".join(f'<option value="{n}">{n}</option>' for n in range(1, total_pages + 1))
    return (
        "<html><body>"
        '<a href="/TSB/personal/credit/intro/overview/">信用卡總覽</a>'
        '<a href="/TSB/personal/credit/intro/rights/">信用卡權益</a>'
        '<a href="https://example.invalid/outside.pdf">外部網站的 PDF</a>'
        f'<ul class="list-and-btn-block">{items}</ul>'
        f'<a href="?page={total_pages}&nav2=file-download&nav1=credit" title="到最末頁">到最末頁</a>'
        f'<select name="page" id="_page">{options}</select>'
        "</body></html>"
    )


def pdf_bytes(path: str) -> bytes:
    """產生內容隨路徑而異、以 %PDF- 開頭的假 PDF。"""
    return b"%PDF-1.4\n" + path.encode() + b"\n%%EOF\n"


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
        self.fallback: Callable[[str], tuple[int, bytes]] | None = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append((self.path, time.monotonic(), self.headers.get("User-Agent", "")))
                if self.path in outer.routes:
                    status, body = outer.routes[self.path]
                elif outer.fallback is not None:
                    status, body = outer.fallback(self.path)
                else:
                    status, body = 404, b"not found"
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


def write_office_wrappers(directory: Path, names: tuple[str, ...] = ("libreoffice", "soffice")) -> Path:
    """在 directory 寫 shell wrapper（每個名稱一個），轉呼叫 tests/fake_libreoffice.py。

    Args:
        directory: 放 wrapper 的資料夾（會建立）。
        names: wrapper 的檔名。

    Returns:
        directory。
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        wrapper = directory / name
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_LIBREOFFICE}" "$@"\n')
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return directory


class ScriptTestCase(unittest.TestCase):
    """每個案例有假 server（routes 由案例設定）、假 Chrome wrapper 與暫存的輸出資料夾 self.out。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "taishin"
        self.chrome = write_chrome_wrapper(self.tmp)
        self.office_bin = write_office_wrappers(self.tmp / "office_bin")
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.server = FakeServer(self.routes)
        self.server.start()
        self.addCleanup(self.server.stop)
        # 沒有任何子頁的總覽頁與權益頁；案例需要子頁時用 serve_cards、serve_rights 覆蓋
        self.serve_cards({})
        self.serve_rights({})
        self.serve_downloads([[]])

    def serve_cards(self, cards: dict[str, str]) -> None:
        """登記總覽頁與各卡片頁。

        Args:
            cards: 卡片頁路徑對頁面 HTML。
        """
        self.routes[OVERVIEW_PATH] = (200, overview_html(list(cards)).encode())
        for path, html in cards.items():
            self.routes[path] = (200, html.encode())

    def serve_rights(self, pages: dict[str, str]) -> None:
        """登記權益頁與各權益子頁。

        Args:
            pages: 權益子頁路徑對頁面 HTML。
        """
        self.routes[RIGHTS_LIST_PATH] = (200, rights_list_html(list(pages)).encode())
        for path, html in pages.items():
            self.routes[path] = (200, html.encode())

    def serve_downloads(self, pages: list[list[str]]) -> None:
        """登記文件下載頁的每一頁與其中的 PDF；page 超過最後一頁時回 200 並重複最後一頁，和官網一樣。

        Args:
            pages: 每一頁的 PDF 路徑清單。同一個路徑只登記一次內容（pdf_bytes）。
        """
        for paths in pages:
            for path in paths:
                self.routes[path] = (200, pdf_bytes(path))

        def page_response(request_path: str) -> tuple[int, bytes]:
            parsed = urlparse(request_path)
            number = parse_qs(parsed.query).get("page", [""])[0]
            if parsed.path != DOWNLOAD_LIST_PATH or not number.isdigit() or int(number) < 1:
                return 404, b"not found"
            shown = min(int(number), len(pages))
            return 200, download_page_html(pages[shown - 1], len(pages)).encode()

        self.server.fallback = page_response

    def run_script(
        self, *, chrome: str | None = None, interval: str = FAST_INTERVAL, path: str | None = None
    ) -> subprocess.CompletedProcess:
        """以假 server、假 Chrome、假 LibreOffice 與 self.out 執行腳本。

        Args:
            chrome: TAISHIN_CHROME 的值；預設為假 Chrome wrapper。
            interval: TAISHIN_REQUEST_INTERVAL_SEC 的值。
            path: PATH 的完整值；預設是把放了假 LibreOffice 的 self.office_bin 放在原本的 PATH 前面。

        Returns:
            已完成的行程（文字模式）。
        """
        env = {
            **os.environ,
            "TAISHIN_WWW_BASE": self.server.base_url,
            "TAISHIN_CHROME": chrome if chrome is not None else str(self.chrome),
            "TAISHIN_REQUEST_INTERVAL_SEC": interval,
            "PATH": path if path is not None else f"{self.office_bin}{os.pathsep}{os.environ['PATH']}",
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

INSURANCE = RIGHTS_PATH_FORMAT.format(group="insurance", page="right0201")
PARKING = RIGHTS_PATH_FORMAT.format(group="parking", page="right0301")
# 真實的權益子頁有 notice/-00001/，路徑最後一段以連字號開頭
NOTICE_DASH = RIGHTS_PATH_FORMAT.format(group="notice", page="-00001")

APPLICATION = FILES_DIR + "word_CR04131_1150B.pdf"
TERMS = FILES_DIR + "terms_1150.pdf"
FEES = FILES_DIR + "fees.pdf"
# 真實的檔名有以 - 或 _ 開頭的，以 - 開頭的名字當命令列參數會被當成選項
DASH_NAMED = FILES_DIR + "-_11407.pdf"
UNDERSCORE_NAMED = FILES_DIR + "__11507.pdf"


def download_page_path(number: int) -> str:
    """文件下載頁第 number 頁的請求路徑（含 query）。"""
    return f"{DOWNLOAD_LIST_PATH}{DOWNLOAD_QUERY}&page={number}"


# 預設的下載頁只有第 1 頁而且沒有 PDF：沒有新連結，所以每次執行都剛好請求這一頁
DOWNLOAD_PAGE_1 = download_page_path(1)


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


class FakeLibreOfficeFixtureTests(unittest.TestCase):
    """假 LibreOffice 新增轉 docx 的介面；轉 PDF 的既有介面（tests/test_pipeline.py 在用）維持嚴格檢查。"""

    DOCX_FILTER = "docx:MS Word 2007 XML"

    def run_fake(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(FAKE_LIBREOFFICE), *args], capture_output=True, text=True, timeout=30)

    def test_converts_html_to_docx_that_contains_the_received_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>收到的內容</p>", encoding="utf-8")
            result = self.run_fake("--headless", "--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = (Path(tmp) / "page.docx").read_bytes()
            self.assertTrue(data.startswith(b"PK"))
            self.assertIn("<p>收到的內容</p>".encode(), data)

    def test_rejects_plain_docx_target_because_real_libreoffice_has_no_export_filter_for_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake("--headless", "--convert-to", "docx", "--outdir", tmp, str(page))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--convert-to", result.stderr)
            self.assertFalse((Path(tmp) / "page.docx").exists())

    def test_docx_conversion_still_checks_the_other_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake("--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--outdir", result.stderr)

    def test_docx_conversion_fails_for_names_starting_with_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "broken_page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake("--headless", "--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(tmp) / "broken_page.docx").exists())

    def test_pdf_conversion_keeps_its_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "report.docx"
            page.write_bytes(b"not a real docx")
            result = self.run_fake("--headless", "--convert-to", "pdf", "--outdir", tmp, str(page))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(tmp) / "report.pdf").read_bytes().startswith(b"%PDF-"))
            broken = Path(tmp) / "broken1.docx"
            broken.write_bytes(b"x")
            failed = self.run_fake("--headless", "--convert-to", "pdf", "--outdir", tmp, str(broken))
            self.assertNotEqual(failed.returncode, 0)


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
        # 總覽頁 1 次；卡片頁 1 次（3 個錨點指向同一頁）；權益連結、申辦連結、總覽頁自己的連結都不下載；權益頁 1 次；下載頁 1 次
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RICHART, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1])


class RightsPageTests(ScriptTestCase):
    def test_converts_each_rights_subpage_to_docx_with_unique_names_and_keeps_raw_html(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING"), NOTICE_DASH: card_html("NOTICE")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(),
            [
                "_meta/html/rights_insurance_right0201.html",
                "_meta/html/rights_notice_-00001.html",
                "_meta/html/rights_parking_right0301.html",
                "_meta/manifest.jsonl",
                "_meta/print/rights_insurance_right0201.html",
                "_meta/print/rights_notice_-00001.html",
                "_meta/print/rights_parking_right0301.html",
                "rights/rights_insurance_right0201.docx",
                "rights/rights_notice_-00001.docx",
                "rights/rights_parking_right0301.docx",
            ],
        )
        self.assertTrue((self.out / "rights" / "rights_insurance_right0201.docx").read_bytes().startswith(b"PK"))
        self.assertEqual(
            (self.out / "_meta" / "html" / "rights_insurance_right0201.html").read_bytes(), self.routes[INSURANCE][1]
        )

    def test_menu_links_pdf_links_and_duplicate_anchors_are_not_fetched_again(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.run_script()
        # 權益頁的選單連結（權益頁自己、總覽、繳費）、PDF 連結、卡片頁連結都不下載；重複的錨點只抓一次
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, INSURANCE, DOWNLOAD_PAGE_1])

    def test_cards_and_rights_are_downloaded_in_one_run_into_separate_folders(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.assertEqual(self.run_script().returncode, 0)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())
        self.assertTrue((self.out / "rights" / "rights_insurance_right0201.docx").is_file())
        self.assertEqual(len(self.manifest()), 2)

    def test_prints_actual_subpage_count_and_continues_when_it_is_not_46(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("找到 2 個權益子頁（預期 46）", result.stdout)

    def test_prints_count_46_when_there_are_46_subpages(self) -> None:
        pages = {RIGHTS_PATH_FORMAT.format(group="g", page=f"right{n:04d}"): card_html(f"P{n}") for n in range(46)}
        self.serve_rights(pages)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("找到 46 個權益子頁（預期 46）", result.stdout)
        self.assertEqual(len(self.manifest()), 46)


class DownloadAreaTests(ScriptTestCase):
    def test_walks_pages_until_a_page_has_no_new_pdf_and_saves_each_pdf_unchanged(self) -> None:
        self.serve_downloads([[APPLICATION, DASH_NAMED], [TERMS, UNDERSCORE_NAMED]])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 第 3 頁重複第 2 頁的清單（和官網一樣）：沒有新連結，所以停在第 3 頁，不發第 4 頁的請求
        list_requests = [p for p in self.server.paths() if p.startswith(DOWNLOAD_LIST_PATH)]
        self.assertEqual(list_requests, [download_page_path(1), download_page_path(2), download_page_path(3)])
        self.assertEqual(
            [f for f in self.files_under_out() if f.startswith("downloads/")],
            [
                "downloads/download_-_11407.pdf",
                "downloads/download___11507.pdf",
                "downloads/download_terms_1150.pdf",
                "downloads/download_word_CR04131_1150B.pdf",
            ],
        )
        for path in (APPLICATION, TERMS, DASH_NAMED, UNDERSCORE_NAMED):
            saved = self.out / "downloads" / f"download_{path.rsplit('/', 1)[1]}"
            self.assertEqual(saved.read_bytes(), pdf_bytes(path))
        self.assertEqual(sorted(p for p in self.server.paths() if p.endswith(".pdf")), sorted([APPLICATION, TERMS, DASH_NAMED, UNDERSCORE_NAMED]))


    def test_pdf_listed_on_several_pages_and_non_pdf_links_are_handled_once_or_not_at_all(self) -> None:
        # 第 2 頁重複第 1 頁的 B，另有新的 C：有新連結所以繼續翻；頁面上的選單連結與外部網站的 PDF 不下載
        self.serve_downloads([[APPLICATION, TERMS], [TERMS, FEES]])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pdf_requests = [p for p in self.server.paths() if p.endswith(".pdf")]
        self.assertEqual(sorted(pdf_requests), sorted([APPLICATION, TERMS, FEES]))
        self.assertEqual(len([r for r in self.manifest() if r["category"] == "下載"]), 3)
        self.assertNotIn("outside", result.stdout + result.stderr)

    def test_prints_actual_pdf_count_and_continues_when_it_is_not_19(self) -> None:
        self.serve_downloads([[APPLICATION, TERMS]])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("找到 2 個 PDF（預期 19）", result.stdout)

    def test_names_are_unique_when_different_urls_share_a_file_name(self) -> None:
        other_dir = "/TSB/export/sites/TSB/personal/credit/intro/payment/"
        same_name = [FEES, other_dir + "fees.pdf", other_dir + "Fees.pdf", APPLICATION]
        self.serve_downloads([same_name])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = {r["url"]: r["filename"] for r in self.manifest()}
        names = [records[self.server.base_url + path] for path in same_name]
        self.assertEqual(len({n.lower() for n in names}), 4, names)
        self.assertEqual(names[3], "download_word_CR04131_1150B.pdf")
        for name in names[:3]:
            self.assertRegex(name, r"^download_[Ff]ees_[0-9a-f]{8}\.pdf$")
        for path, name in zip(same_name, names):
            self.assertEqual((self.out / "downloads" / name).read_bytes(), pdf_bytes(path))

    def test_file_names_with_spaces_and_chinese_are_requested_percent_encoded_and_saved_with_safe_names(self) -> None:
        href = FILES_DIR + "費用 表.pdf"
        self.serve_downloads([[href]])
        self.routes[quote(href)] = (200, pdf_bytes(href))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(quote(href), self.server.paths())
        self.assertEqual((self.out / "downloads" / "download_費用_表.pdf").read_bytes(), pdf_bytes(href))

    def test_list_pages_and_pdfs_are_spaced_by_the_configured_interval(self) -> None:
        self.serve_downloads([[APPLICATION], [TERMS]])
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        times = [t for _path, t, _ua in self.server.requests]
        # 總覽頁、權益頁、下載頁 3 頁、PDF 2 份
        self.assertEqual(len(times), 7)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, interval - 0.02)


class DownloadAreaManifestTests(ScriptTestCase):
    def test_record_has_the_same_fields_and_no_html_sha256(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_downloads([[TERMS]])
        self.assertEqual(self.run_script().returncode, 0)
        records = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(sorted(records), ["card_cg047_card001.pdf", "download_terms_1150.pdf"])
        record = records["download_terms_1150.pdf"]
        pdf = (self.out / "downloads" / "download_terms_1150.pdf").read_bytes()
        self.assertEqual(record["url"], self.server.base_url + TERMS)
        self.assertEqual(record["category"], "下載")
        self.assertEqual(record["format"], "PDF")
        self.assertEqual(record["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(record["sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertEqual(record["html_sha256"], "")
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(set(record), set(records["card_cg047_card001.pdf"]))
        self.assertFalse((self.out / "_meta" / "html" / "download_terms_1150.html").exists())


class DownloadAreaFailureTests(ScriptTestCase):
    def test_pdf_http_error_fails_that_pdf_only(self) -> None:
        self.serve_downloads([[APPLICATION, TERMS, FEES]])
        self.routes[TERMS] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("download_terms_1150.pdf", result.stderr)
        self.assertIn("500", result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "downloads").iterdir()),
            ["download_fees.pdf", "download_word_CR04131_1150B.pdf"],
        )
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual([r["filename"] for r in failed], ["download_terms_1150.pdf"])
        self.assertEqual(failed[0]["sha256"], "")

    def test_content_that_does_not_start_with_pdf_magic_is_a_failure_and_is_not_saved(self) -> None:
        self.serve_downloads([[APPLICATION, TERMS, FEES]])
        self.routes[TERMS] = (200, b"<html><body>Service Unavailable</body></html>")
        self.routes[FEES] = (200, b"")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("download_terms_1150.pdf", result.stderr)
        self.assertIn("download_fees.pdf", result.stderr)
        self.assertIn("不是 PDF", result.stderr)
        self.assertEqual(
            [f for f in self.files_under_out() if f != "_meta/manifest.jsonl"],
            ["downloads/download_word_CR04131_1150B.pdf"],
        )

    def test_first_page_failure_exits_nonzero_names_the_list_and_keeps_the_other_categories(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.routes[DOWNLOAD_PAGE_1] = (404, b"gone")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("文件下載", result.stderr)
        self.assertIn("第 1 頁", result.stderr)
        self.assertIn("404", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())

    def test_later_page_failure_exits_nonzero_and_names_the_page(self) -> None:
        self.serve_downloads([[APPLICATION], [TERMS]])
        self.routes[download_page_path(2)] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("文件下載", result.stderr)
        self.assertIn("第 2 頁", result.stderr)
        self.assertIn("500", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_stops_at_the_page_limit_when_every_page_keeps_having_new_pdfs(self) -> None:
        def endless(request_path: str) -> tuple[int, bytes]:
            number = int(parse_qs(urlparse(request_path).query)["page"][0])
            return 200, download_page_html([f"{FILES_DIR}page{number}.pdf"], number).encode()

        self.server.fallback = endless
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("文件下載", result.stderr)
        self.assertIn("上限 20 頁", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        list_requests = [p for p in self.server.paths() if p.startswith(DOWNLOAD_LIST_PATH)]
        self.assertEqual(list_requests, [download_page_path(n) for n in range(1, 21)])


class DownloadAreaRerunTests(ScriptTestCase):
    def test_existing_pdfs_are_skipped_without_requesting_them_but_the_list_is_walked_again(self) -> None:
        self.serve_downloads([[APPLICATION], [TERMS]])
        self.assertEqual(self.run_script().returncode, 0)
        first = {r["filename"]: r for r in self.manifest()}
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [p for p in self.server.paths() if p.endswith(".pdf")], [], "已存在的 PDF 不該再請求"
        )
        second = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(sorted(second), sorted(first))
        for name, record in second.items():
            self.assertEqual(record["result"], "已存在略過")
            self.assertEqual(record["sha256"], first[name]["sha256"])
            self.assertEqual(record["html_sha256"], "")

    def test_failed_pdf_is_fetched_again_on_the_next_run(self) -> None:
        self.serve_downloads([[APPLICATION]])
        self.routes[APPLICATION] = (200, b"<html>error</html>")
        self.assertEqual(self.run_script().returncode, 1)
        self.routes[APPLICATION] = (200, pdf_bytes(APPLICATION))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([r["result"] for r in self.manifest() if r["category"] == "下載"], ["已下載"])


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


class LibreOfficeInputTests(ScriptTestCase):
    """交給 LibreOffice 的 HTML：含主內容區的全部文字，不含官網的 script、樣式與主內容區以外的文字。"""

    def setUp(self) -> None:
        super().setUp()
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 假 LibreOffice 的輸出檔 = 假 docx 檔頭 + 收到的 HTML
        self.received = (self.out / "rights" / "rights_insurance_right0201.docx").read_text(
            encoding="utf-8", errors="replace"
        )

    def test_contains_main_content(self) -> None:
        for text in ("INSURANCE", "COLLAPSED-TEXT", "MODAL-TEXT 每日23:59前轉換", "未關閉項目二"):
            self.assertIn(text, self.received)

    def test_excludes_site_scripts_styles_and_content_outside_the_main_area(self) -> None:
        for text in ("SITE_SCRIPT_TEXT", "SITE-STYLE-TEXT", "INNER_SCRIPT_TEXT", "NAV-MENU-TEXT", "LEFT-MENU-TEXT", "FOOTER-TEXT"):
            self.assertNotIn(text, self.received)

    def test_has_base_href_pointing_to_the_original_url(self) -> None:
        self.assertIn(f'<base href="{self.server.base_url}{INSURANCE}">', self.received)


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


class RightsManifestTests(ScriptTestCase):
    def test_record_has_the_same_fields_as_cards(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.assertEqual(self.run_script().returncode, 0)
        records = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(sorted(records), ["card_cg047_card001.pdf", "rights_insurance_right0201.docx"])
        rights = records["rights_insurance_right0201.docx"]
        docx = (self.out / "rights" / "rights_insurance_right0201.docx").read_bytes()
        self.assertEqual(rights["url"], self.server.base_url + INSURANCE)
        self.assertEqual(rights["category"], "權益")
        self.assertEqual(rights["format"], "DOCX")
        self.assertEqual(rights["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(rights["sha256"], hashlib.sha256(docx).hexdigest())
        self.assertEqual(rights["html_sha256"], hashlib.sha256(self.routes[INSURANCE][1]).hexdigest())
        self.assertEqual(rights["result"], "已下載")
        self.assertEqual(set(rights), set(records["card_cg047_card001.pdf"]))


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
        del self.routes[OVERVIEW_PATH]  # 假 server 對沒有登記的路徑回 404
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("信用卡總覽", result.stderr)
        self.assertIn("404", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_overview_failure_does_not_stop_the_rights_category(self) -> None:
        del self.routes[OVERVIEW_PATH]
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, INSURANCE, DOWNLOAD_PAGE_1])
        self.assertTrue((self.out / "rights" / "rights_insurance_right0201.docx").is_file())

    def test_rights_list_failure_exits_nonzero_names_the_list_and_keeps_the_cards(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        del self.routes[RIGHTS_LIST_PATH]
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("信用卡權益", result.stderr)
        self.assertIn("404", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())


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


class RightsFailureTests(ScriptTestCase):
    def assert_failed_subpage(self, result: subprocess.CompletedProcess, filename: str, reason: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(filename, result.stderr)
        self.assertIn(reason, result.stderr)
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual([r["filename"] for r in failed], [filename])
        self.assertIn(reason, failed[0]["detail"])
        self.assertEqual(failed[0]["sha256"], "")

    def write_office_script(self, body: str) -> Path:
        """寫一個只有 libreoffice／soffice 兩個名稱的假命令資料夾，內容是 sh 腳本 body。"""
        directory = self.tmp / "custom_office"
        directory.mkdir()
        for name in ("libreoffice", "soffice"):
            wrapper = directory / name
            wrapper.write_text(f"#!/bin/sh\n{body}\n")
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        return directory

    def test_missing_libreoffice_fails_each_subpage_but_not_the_cards(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING")})
        empty = self.tmp / "empty_path"
        empty.mkdir()
        result = self.run_script(path=str(empty))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual(
            sorted(r["filename"] for r in failed),
            ["rights_insurance_right0201.docx", "rights_parking_right0301.docx"],
        )
        for record in failed:
            self.assertIn("LibreOffice", record["detail"])
            self.assertIn("libreoffice", record["detail"])
            self.assertIn("soffice", record["detail"])
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())

    def test_soffice_alone_is_found(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        only_soffice = write_office_wrappers(self.tmp / "soffice_only", names=("soffice",))
        result = self.run_script(path=str(only_soffice))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.out / "rights" / "rights_insurance_right0201.docx").is_file())

    def test_libreoffice_is_preferred_over_soffice(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        directory = self.write_office_script('echo "called $0" >&2; exit 7')
        (directory / "soffice").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_LIBREOFFICE}" "$@"\n')
        result = self.run_script(path=str(directory))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("結束碼 7", result.stderr)

    def test_conversion_failure_fails_that_subpage_only(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING")})
        # 不是假 LibreOffice 的 broken 規則：腳本的本地檔名都以 rights_ 開頭，改用依輸入檔名決定的 wrapper
        directory = self.write_office_script(
            f'case "$6" in *insurance*) echo "cannot convert" >&2; exit 3;; esac\n'
            f'exec "{sys.executable}" "{FAKE_LIBREOFFICE}" "$@"'
        )
        result = self.run_script(path=str(directory))
        self.assert_failed_subpage(result, "rights_insurance_right0201.docx", "結束碼 3")
        self.assertIn("cannot convert", result.stderr)
        self.assertTrue((self.out / "rights" / "rights_parking_right0301.docx").is_file())
        self.assertFalse((self.out / "rights" / "rights_insurance_right0201.docx").exists())

    def test_exit_code_zero_without_output_is_a_failure(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        result = self.run_script(path=str(self.write_office_script("exit 0")))
        self.assert_failed_subpage(result, "rights_insurance_right0201.docx", "沒有產出")

    def test_http_error_on_one_subpage_does_not_stop_the_others(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING")})
        self.routes[INSURANCE] = (500, b"boom")
        result = self.run_script()
        self.assert_failed_subpage(result, "rights_insurance_right0201.docx", "500")
        self.assertTrue((self.out / "rights" / "rights_parking_right0301.docx").is_file())

    def test_subpage_without_main_content_is_a_failure(self) -> None:
        self.serve_rights({INSURANCE: card_html_without_main_content(), PARKING: card_html("PARKING")})
        result = self.run_script()
        self.assert_failed_subpage(result, "rights_insurance_right0201.docx", "找不到主內容區")
        self.assertTrue((self.out / "_meta" / "html" / "rights_insurance_right0201.html").is_file())
        self.assertTrue((self.out / "rights" / "rights_parking_right0301.docx").is_file())


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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1], "第二次只該請求列表頁")
        self.assertEqual(pdf.read_bytes(), before)
        second = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(sorted(second), sorted(first))
        for name, record in second.items():
            self.assertEqual(record["result"], "已存在略過")
            self.assertEqual(record["sha256"], first[name]["sha256"])
            self.assertEqual(record["html_sha256"], first[name]["html_sha256"])

    def test_existing_rights_documents_are_skipped_without_converting_them_again(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.assertEqual(self.run_script().returncode, 0)
        first = self.manifest()[0]
        docx = self.out / "rights" / "rights_insurance_right0201.docx"
        before = docx.read_bytes()
        self.server.requests.clear()
        # 第二次執行 PATH 上沒有 LibreOffice：略過的文件不需要它
        empty = self.tmp / "empty_path"
        empty.mkdir()
        result = self.run_script(path=str(empty))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1])
        self.assertEqual(docx.read_bytes(), before)
        second = self.manifest()[0]
        self.assertEqual(second["result"], "已存在略過")
        self.assertEqual(second["sha256"], first["sha256"])
        self.assertEqual(second["html_sha256"], first["html_sha256"])

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
        self.assertEqual(len(self.server.requests), 4)
        for _path, _time, user_agent in self.server.requests:
            self.assertTrue(user_agent.startswith("llm-lab-fetch-taishin/"), user_agent)

    def test_requests_are_spaced_by_at_least_the_configured_interval(self) -> None:
        self.serve_cards(
            {RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN"), DAQUANLIAN_2: card_html("DQL2")}
        )
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        times = [t for _path, t, _ua in self.server.requests]
        self.assertEqual(len(times), 6)
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
