"""fetch_taishin.py 的行為測試：以子行程執行腳本，對本機假 HTTP server 與假 Chrome 下載。

為什麼存在：fetch_taishin.py 是獨立腳本，沒有 CLI 以外的縫。測試只從子行程進入，觀察結束碼、
stdout／stderr、輸出資料夾的檔案、下載清單的內容、假 server 收到的請求，以及假 Chrome 收到的 HTML；
不 import 腳本的函式。

關鍵設計決策：
- 網址前綴（TAISHIN_WWW_BASE、TAISHIN_MKPCARD_BASE、TAISHIN_MKP_BASE）、Chrome 路徑（TAISHIN_CHROME）與請求間隔
  （TAISHIN_REQUEST_INTERVAL_SEC）都用環境變數指到假的版本。www 與 mkpcard 指到同一個假 server（self.server），
  mkp 指到另一個（self.mkp_server），所以測試能看出活動詳情頁與主視覺是向 mkp 的前綴請求，不是向 mkpcard。
- 假 Chrome 是 tests/fake_chrome.py；測試在暫存資料夾寫一個 shell wrapper 呼叫它，
  腳本拿到的 Chrome 路徑就是這個 wrapper。
- 假頁面依官網結構筆記的最小結構製作：主內容區含預設收合的區塊與彈窗，主內容區外有導覽選單，
  頁面裡有 script 與 style。
- 假 server 記錄每個請求的路徑、收到的時間與 User-Agent。沒有登記的路徑交給 fallback（預設 404）；
  文件下載頁用 fallback 模擬官網「超過最後一頁時回 200 並重複最後一頁」，刷卡優惠列表用 fallback 模擬
  「超過最後一頁時回 200、沒有活動、含查無資料」。
- 活動詳情頁的連結有相對路徑與指向不存在網域（.invalid）的絕對網址兩種：腳本若照絕對網址發請求，
  請求會失敗，測試就會變紅，不會對真的官網發請求。

執行方式：python3 -m unittest scripts/test_fetch_taishin.py

Dependencies: 僅標準函式庫。
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

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
OFFER_LIST_PREFIX = "/tscccms/promotion/offerList/"
OFFER_CATEGORIES = "ABCDEFGHI"
DETAIL_PREFIX = "/tscccms/promotion/detail/"
UPLOAD_PREFIX = "/tscccms/campaignPromotions/upload/2026/"
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


def rights_page_with_pdfs(label: str, hrefs: list[str]) -> str:
    """產生權益子頁：主內容區裡有指向 PDF 的連結（真實的聯名卡、雙幣卡、企業卡子頁就是這樣連到條款 PDF）。

    Args:
        label: 放進主內容區的文字，讓各頁內容不同。
        hrefs: PDF 連結的 href（相對路徑，或其他網域的絕對網址）。

    Returns:
        權益子頁的 HTML，主內容區結構和 card_html 相同。
    """
    anchors = "".join(f'<a href="{href}" title="x" class="oval-style" target="_blank">條款</a>' for href in hrefs)
    return card_html(label).replace('<img src="/img/a.gif">', f'<img src="/img/a.gif"><p>{anchors}</p>')


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


def offer_list_html(hrefs: list[str]) -> str:
    """產生刷卡優惠列表的一頁：每筆活動一個 a.card-holder，外加不該收的干擾連結。

    干擾：<script> 內的 JS 字串樣板（含 card-holder 與假連結）、頁頂輪播的絕對網址連結、分類導覽連結。
    沒有活動時和官網一樣顯示「查無資料」。

    Args:
        hrefs: 這一頁各筆活動的詳情頁連結（相對路徑或絕對網址）。

    Returns:
        列表頁的 HTML。
    """
    boxes = "".join(
        f'<div class="offer-box col-xl-4"><a class="card-holder" href="{href}" title="x"><img src="t.jpg">'
        "<li>活動期間：2026-09-22~2026-12-31</li></a></div>"
        for href in hrefs
    )
    body = boxes or '<div class="alert alert-danger"><p class="mb-0">查無資料</p></div>'
    return (
        "<html><body>"
        + "".join(f'<a href="{OFFER_LIST_PREFIX}{letter}" title="x">分類 {letter}</a>' for letter in OFFER_CATEGORIES)
        + f'<ul class="slides"><a target="_blank" href="https://mkpcard.example.invalid{CAROUSEL_ONLY}" class="btn btn-sm btn-slide">輪播</a></ul>'
        + f'<div class="offer-container offer-list-container">{body}</div>'
        + "<script>var tpl = '<a class=\"card-holder\" href=\"" + DETAIL_PREFIX
        + "'+encodeHTML(proObj.promotionId)+'\" title=\"x\">';</script>"
        "</body></html>"
    )


def offer_detail_html(
    label: str, *, period: str | None = "2099-01-01~2099-12-31", banner: str | None = None
) -> str:
    """產生活動詳情頁：主內容區是 class 含 page-content 的 div，導覽與頁尾在主內容區外。

    頁面還有兩個干擾：主內容區裡的分享圖示（不是主視覺），以及正文自由文字裡的另一種活動期間寫法（已過期）。

    Args:
        label: 放進主內容區的活動名稱，讓各頁內容不同。
        period: <h5 class="subtitle">活動期間</h5> 後面 <p> 的文字；None 表示整個區塊不存在。
        banner: div.banner-image 裡的圖片網址；None 表示頁面沒有這個元素。

    Returns:
        活動詳情頁的 HTML。
    """
    banner_block = (
        f'<div class="page-banner page-banner-inner"><div class="page-banner-combo">'
        f'<div class="banner-image"><img src="{banner}" class="img-fluid" alt="x"/></div></div></div>'
        if banner is not None
        else ""
    )
    period_block = f'<h5 class="subtitle">活動期間</h5>\n<p>{period}</p>' if period is not None else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{label} ： 台新銀行</title>
<style>.site{{color:red}} SITE-STYLE-TEXT</style>
<script>var SITE_SCRIPT_TEXT = "<div class='page-content'>";</script></head>
<body>
<div id="topnav"><ul><li>NAV-MENU-TEXT</li></ul></div>
{banner_block}
<div class="page-content extra"><div class="offer-container">
  <div class="sharelist"><a target="_blank" id="lineShare" href=""><img src="/tscccms/img/round-default.png"></a></div>
  <h1 class="content-title">{label}</h1>
  <h5 class="subtitle">優惠內容</h5>
  <p>FREE-TEXT 活動期間：2020/1/1-2020/1/31</p>
  {period_block}
  <div id="offer-accordion"><div class="collapse"><p>COLLAPSED-TEXT</p></div></div>
  <script>var INNER_SCRIPT_TEXT = 1;</script>
  <style>INNER-STYLE-TEXT</style>
  <ul><li>未關閉項目一<li>未關閉項目二</ul>
</div></div>
<footer>FOOTER-TEXT</footer>
</body></html>"""


def detail_path(number: int) -> str:
    """第 number 個假活動的詳情頁路徑（官網的編號是 WM_ 加 17 位數字）。"""
    return f"{DETAIL_PREFIX}WM_2026090314180{number:04d}"


def banner_path(number: int, extension: str = "png") -> str:
    """第 number 個假活動的主視覺路徑（和官網一樣放在 upload/<年>/<WM 編號>/ 底下）。"""
    return f"{UPLOAD_PREFIX}WM_2026090314180{number:04d}/WM_2026090314180{number:04d}_banner_image.{extension}"


def period_from_today(start_offset_days: int, end_offset_days: int) -> str:
    """產生以下載當天為基準的活動期間文字，格式和官網一樣：2026-09-22~2026-12-31。"""
    today = date.today()
    return f"{today + timedelta(days=start_offset_days)}~{today + timedelta(days=end_offset_days)}"


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake png body"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"fake jpeg body"
# 沒有被任何列表的 card-holder 列出、只出現在輪播的活動
CAROUSEL_ONLY = detail_path(999)


# ==============================
# 工具：假 server、假 Chrome、執行腳本
# ==============================


class FakeServer:
    """本機假 HTTP server：routes 把路徑（含 query）對到 (狀態碼, body)；沒有登記的路徑回 404。

    redirects 把路徑對到 Location，登記的路徑回 302（優先於 routes）。
    """

    def __init__(self, routes: dict[str, tuple[int, bytes]]) -> None:
        self.routes = routes
        self.redirects: dict[str, str] = {}
        self.requests: list[tuple[str, float, str]] = []
        self.fallback: Callable[[str], tuple[int, bytes]] | None = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append((self.path, time.monotonic(), self.headers.get("User-Agent", "")))
                if self.path in outer.redirects:
                    self.send_response(302)
                    self.send_header("Location", outer.redirects[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
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
        # mkp（活動詳情頁與主視覺）是另一個假 server，和 www、mkpcard 分開
        self.mkp_routes: dict[str, tuple[int, bytes]] = {}
        self.mkp_server = FakeServer(self.mkp_routes)
        self.mkp_server.start()
        self.addCleanup(self.mkp_server.stop)
        self.list_handlers: dict[str, Callable[[str], tuple[int, bytes] | None]] = {}
        self.server.fallback = self._answer_with_list_handlers
        # 沒有任何子頁的總覽頁與權益頁；案例需要子頁時用 serve_cards、serve_rights 覆蓋
        self.serve_cards({})
        self.serve_rights({})
        self.serve_downloads([[]])
        self.serve_offers({})

    def _answer_with_list_handlers(self, request_path: str) -> tuple[int, bytes]:
        """依序問各個列表的處理函式，第一個認得這個路徑的回答；都不認得時回 404。"""
        for handler in self.list_handlers.values():
            answer = handler(request_path)
            if answer is not None:
                return answer
        return 404, b"not found"

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

        def page_response(request_path: str) -> tuple[int, bytes] | None:
            parsed = urlparse(request_path)
            number = parse_qs(parsed.query).get("page", [""])[0]
            if parsed.path != DOWNLOAD_LIST_PATH or not number.isdigit() or int(number) < 1:
                return None
            shown = min(int(number), len(pages))
            return 200, download_page_html(pages[shown - 1], len(pages)).encode()

        self.list_handlers["downloads"] = page_response

    def serve_offers(self, categories: dict[str, list[list[str]]]) -> None:
        """登記刷卡優惠列表（GET ?page=N）；page 超過最後一頁時回 200、沒有活動、含查無資料，和官網一樣。

        Args:
            categories: 分類字母對各頁的活動詳情頁連結清單；沒有列出的分類沒有任何活動。
        """

        def page_response(request_path: str) -> tuple[int, bytes] | None:
            parsed = urlparse(request_path)
            match = re.fullmatch(re.escape(OFFER_LIST_PREFIX) + r"([A-I])", parsed.path)
            number = parse_qs(parsed.query).get("page", [""])[0]
            if match is None or not number.isdigit() or int(number) < 1:
                return None
            pages = categories.get(match.group(1), [])
            hrefs = pages[int(number) - 1] if int(number) <= len(pages) else []
            return 200, offer_list_html(hrefs).encode()

        self.list_handlers["offers"] = page_response

    def serve_images(self, images: dict[str, bytes]) -> None:
        """在 mkp 登記各主視覺圖片。

        Args:
            images: 圖片路徑對檔案內容。
        """
        for path, data in images.items():
            self.mkp_routes[path] = (200, data)

    def serve_details(self, details: dict[str, str]) -> None:
        """在 mkp 登記各活動詳情頁。

        Args:
            details: 詳情頁路徑對頁面 HTML。
        """
        for path, html in details.items():
            self.mkp_routes[path] = (200, html.encode())

    def run_script(
        self,
        *,
        chrome: str | None = None,
        interval: str = FAST_INTERVAL,
        path: str | None = None,
        extra_env: dict[str, str] | None = None,
        extra_args: list[str] | None = None,
    ) -> subprocess.CompletedProcess:
        """以假 server、假 Chrome、假 LibreOffice 與 self.out 執行腳本。

        Args:
            chrome: TAISHIN_CHROME 的值；預設為假 Chrome wrapper。
            interval: TAISHIN_REQUEST_INTERVAL_SEC 的值。
            path: PATH 的完整值；預設是把放了假 LibreOffice 的 self.office_bin 放在原本的 PATH 前面。
            extra_env: 另外加進行程環境變數的項目。
            extra_args: 接在 --out 後面的命令列參數（例如更新模式的 --update）。

        Returns:
            已完成的行程（文字模式）。
        """
        env = {
            **os.environ,
            "TAISHIN_WWW_BASE": self.server.base_url,
            "TAISHIN_MKPCARD_BASE": self.server.base_url,
            "TAISHIN_MKP_BASE": self.mkp_server.base_url,
            "TAISHIN_CHROME": chrome if chrome is not None else str(self.chrome),
            "TAISHIN_REQUEST_INTERVAL_SEC": interval,
            "PATH": path if path is not None else f"{self.office_bin}{os.pathsep}{os.environ['PATH']}",
            **(extra_env or {}),
        }
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--out", str(self.out), *(extra_args or [])],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def run_update(self, **kwargs) -> subprocess.CompletedProcess:
        """以更新模式（--update）執行腳本；其餘參數同 run_script。"""
        return self.run_script(extra_args=["--update"], **kwargs)

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

# 權益子頁連到的條款 PDF：聯名卡子頁連到 /personal/credit/intro/rights/right/... 底下，雙幣卡連到 files/ 底下
CO_BRAND_PAGE = RIGHTS_PATH_FORMAT.format(group="right", page="right0702")
DUAL_PAGE = RIGHTS_PATH_FORMAT.format(group="right", page="right0704")
CO_BRAND_PDF = "/TSB/export/sites/TSB/personal/credit/intro/rights/right/right0702/TSCC-11312.pdf"
DUAL_PDF = FILES_DIR + "dual-card_01.pdf"
DUAL_PDF_2 = FILES_DIR + "dual-card_02.pdf"


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
        """執行假 Chrome。

        Args:
            args: 命令列引數（不含程式名稱）。

        Returns:
            已完成的行程（文字模式）。
        """
        return subprocess.run([sys.executable, str(FAKE_CHROME), *args], capture_output=True, text=True, timeout=30)

    @staticmethod
    def write_profile(directory: str, javascript_setting: int | None = 2) -> None:
        """在 directory/profile 寫 Chrome 的 Preferences。

        Args:
            directory: 放 profile 的資料夾。
            javascript_setting: default_content_setting_values.javascript 的值（2 是封鎖）；None 表示不寫這個設定。
        """
        default = Path(directory) / "profile" / "Default"
        default.mkdir(parents=True)
        values = {} if javascript_setting is None else {"javascript": javascript_setting}
        (default / "Preferences").write_text(json.dumps({"profile": {"default_content_setting_values": values}}))

    def test_rejects_unexpected_arguments_and_prints_them(self) -> None:
        result = self.run_fake("--headless", "--print-to-pdf=/tmp/x.pdf", "file:///nonexistent.html")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--print-to-pdf=/tmp/x.pdf", result.stderr)

    def test_rejects_input_that_is_not_an_existing_html_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.write_profile(tmp)
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
            self.write_profile(tmp)
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

    def test_rejects_a_profile_that_does_not_block_javascript(self) -> None:
        for setting in (None, 1):
            with self.subTest(javascript_setting=setting), tempfile.TemporaryDirectory() as tmp:
                page = Path(tmp) / "page.html"
                page.write_text("<p>x</p>", encoding="utf-8")
                self.write_profile(tmp, setting)
                result = self.run_fake(
                    "--headless",
                    "--disable-gpu",
                    "--no-pdf-header-footer",
                    f"--user-data-dir={tmp}/profile",
                    f"--print-to-pdf={tmp}/out.pdf",
                    page.as_uri(),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("javascript", result.stderr)
                self.assertFalse((Path(tmp) / "out.pdf").exists())

    def test_rejects_a_profile_folder_without_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake(
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--user-data-dir={tmp}/profile",
                f"--print-to-pdf={tmp}/out.pdf",
                page.as_uri(),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("javascript", result.stderr)


class FakeLibreOfficeFixtureTests(unittest.TestCase):
    """假 LibreOffice 新增轉 docx 的介面；轉 PDF 的既有介面（tests/test_pipeline.py 在用）維持嚴格檢查。"""

    DOCX_FILTER = "docx:MS Word 2007 XML"

    def run_fake(self, *args: str) -> subprocess.CompletedProcess:
        """執行假 LibreOffice。

        Args:
            args: 命令列引數（不含程式名稱）。

        Returns:
            已完成的行程（文字模式）。
        """
        return subprocess.run([sys.executable, str(FAKE_LIBREOFFICE), *args], capture_output=True, text=True, timeout=30)

    @staticmethod
    def profile_arg(directory: str) -> str:
        """directory 底下一個新的 user profile 資料夾對應的 -env:UserInstallation 引數。

        Args:
            directory: 放 profile 資料夾的位置。

        Returns:
            `-env:UserInstallation=file://<directory>/profile`。
        """
        return f"-env:UserInstallation={(Path(directory) / 'profile').as_uri()}"

    def test_converts_html_to_docx_that_contains_the_received_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>收到的內容</p>", encoding="utf-8")
            result = self.run_fake(
                self.profile_arg(tmp), "--headless", "--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = (Path(tmp) / "page.docx").read_bytes()
            self.assertTrue(data.startswith(b"PK"))
            self.assertIn("<p>收到的內容</p>".encode(), data)

    def test_rejects_plain_docx_target_because_real_libreoffice_has_no_export_filter_for_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake(self.profile_arg(tmp), "--headless", "--convert-to", "docx", "--outdir", tmp, str(page))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--convert-to", result.stderr)
            self.assertFalse((Path(tmp) / "page.docx").exists())

    def test_docx_conversion_still_checks_the_other_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake(self.profile_arg(tmp), "--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--outdir", result.stderr)

    def test_docx_conversion_requires_a_user_profile_because_a_running_libreoffice_makes_the_default_one_unusable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake("--headless", "--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("UserInstallation", result.stderr)
            self.assertFalse((Path(tmp) / "page.docx").exists())

    def test_docx_conversion_rejects_a_profile_that_is_not_a_file_url_or_is_already_in_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            convert = ["--headless", "--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page)]
            plain_path = self.run_fake(f"-env:UserInstallation={tmp}/profile", *convert)
            self.assertNotEqual(plain_path.returncode, 0)
            first = self.run_fake(self.profile_arg(tmp), *convert)
            self.assertEqual(first.returncode, 0, first.stderr)
            reused = self.run_fake(self.profile_arg(tmp), *convert)
            self.assertNotEqual(reused.returncode, 0)
            self.assertIn("already in use", reused.stderr)

    def test_docx_conversion_fails_for_names_starting_with_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "broken_page.html"
            page.write_text("<p>x</p>", encoding="utf-8")
            result = self.run_fake(
                self.profile_arg(tmp), "--headless", "--convert-to", self.DOCX_FILTER, "--outdir", tmp, str(page)
            )
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

    def test_pdf_conversion_does_not_accept_a_user_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "report.docx"
            page.write_bytes(b"not a real docx")
            result = self.run_fake(self.profile_arg(tmp), "--headless", "--convert-to", "pdf", "--outdir", tmp, str(page))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(tmp) / "report.pdf").exists())


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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RICHART, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS])


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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, INSURANCE, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS])

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
        # 總覽頁、權益頁、下載頁 3 頁、PDF 2 份、刷卡優惠列表 9 個分類各 1 頁
        self.assertEqual(len(times), 16)
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


# 把原檔的修改時間設成很久以前：更新模式若重寫沒變的檔案，修改時間就會變成現在
OLD_MTIME_NS = 1_000_000_000 * 10**9


class UpdateModeDownloadAreaTests(ScriptTestCase):
    def download_once(self, paths: list[str]) -> dict[str, Path]:
        """第一次下載（不開更新模式）後，把每份 PDF 的修改時間設成很久以前。

        Args:
            paths: 下載區的 PDF 路徑。

        Returns:
            PDF 路徑對本地檔案。
        """
        self.serve_downloads([paths])
        self.assertEqual(self.run_script().returncode, 0)
        saved = {path: self.out / "downloads" / f"download_{path.rsplit('/', 1)[1]}" for path in paths}
        for file in saved.values():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.server.requests.clear()
        return saved

    def download_records(self) -> dict[str, dict[str, str]]:
        """下載清單中下載區的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "下載"}

    def test_pdf_with_the_same_content_keeps_its_bytes_and_modification_time_and_is_recorded_as_unchanged(self) -> None:
        saved = self.download_once([APPLICATION])
        before = saved[APPLICATION].read_bytes()
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(saved[APPLICATION].read_bytes(), before)
        self.assertEqual(saved[APPLICATION].stat().st_mtime_ns, OLD_MTIME_NS)
        self.assertIn(APPLICATION, self.server.paths(), "更新模式要重新下載來比對")
        record = self.download_records()["download_word_CR04131_1150B.pdf"]
        self.assertEqual(record["result"], "未變")
        self.assertEqual(record["sha256"], hashlib.sha256(before).hexdigest())

    def test_pdf_with_new_content_replaces_the_file_and_is_recorded_as_changed(self) -> None:
        saved = self.download_once([APPLICATION, TERMS])
        new_content = pdf_bytes(APPLICATION) + b"revised\n"
        self.routes[APPLICATION] = (200, new_content)
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(saved[APPLICATION].read_bytes(), new_content)
        self.assertEqual(saved[TERMS].read_bytes(), pdf_bytes(TERMS))
        self.assertEqual(saved[TERMS].stat().st_mtime_ns, OLD_MTIME_NS)
        records = self.download_records()
        self.assertEqual(records["download_word_CR04131_1150B.pdf"]["result"], "內容變更")
        self.assertEqual(records["download_word_CR04131_1150B.pdf"]["sha256"], hashlib.sha256(new_content).hexdigest())
        self.assertEqual(records["download_word_CR04131_1150B.pdf"]["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(records["download_terms_1150.pdf"]["result"], "未變")
        self.assertEqual(
            sorted(p.name for p in (self.out / "downloads").iterdir()),
            ["download_terms_1150.pdf", "download_word_CR04131_1150B.pdf"],
            "換內容時不留暫存檔",
        )

    def test_pdf_that_is_new_to_the_folder_is_downloaded_as_usual(self) -> None:
        self.download_once([APPLICATION])
        self.serve_downloads([[APPLICATION, TERMS]])
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = self.download_records()
        self.assertEqual(records["download_terms_1150.pdf"]["result"], "已下載")
        self.assertEqual((self.out / "downloads" / "download_terms_1150.pdf").read_bytes(), pdf_bytes(TERMS))
        self.assertEqual(records["download_word_CR04131_1150B.pdf"]["result"], "未變")

    def test_failed_download_keeps_the_original_file_and_is_recorded_as_failed(self) -> None:
        saved = self.download_once([APPLICATION, TERMS, FEES])
        before = {path: file.read_bytes() for path, file in saved.items()}
        self.routes[APPLICATION] = (500, b"boom")
        self.routes[TERMS] = (200, b"<html>Service Unavailable</html>")
        self.routes[FEES] = (200, b"")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for path, file in saved.items():
            self.assertEqual(file.read_bytes(), before[path])
            self.assertEqual(file.stat().st_mtime_ns, OLD_MTIME_NS)
        records = self.download_records()
        for filename in ("download_word_CR04131_1150B.pdf", "download_terms_1150.pdf", "download_fees.pdf"):
            self.assertEqual(records[filename]["result"], "失敗", filename)
            self.assertIn(filename, result.stderr)
        self.assertIn("500", records["download_word_CR04131_1150B.pdf"]["detail"])
        self.assertIn("不是 PDF", records["download_terms_1150.pdf"]["detail"])
        self.assertEqual(
            sorted(p.name for p in (self.out / "downloads").iterdir()),
            ["download_fees.pdf", "download_terms_1150.pdf", "download_word_CR04131_1150B.pdf"],
        )

    def test_requests_in_update_mode_are_still_spaced_by_the_configured_interval(self) -> None:
        self.download_once([APPLICATION, TERMS])
        interval = 0.3
        result = self.run_update(interval=str(interval))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        times = [t for _path, t, _ua in self.server.requests]
        # 總覽頁、權益頁、下載頁 2 頁（第 2 頁重複第 1 頁而停止）、重新下載 PDF 2 份、刷卡優惠列表 9 個分類各 1 頁
        self.assertEqual(len(times), 15)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, interval - 0.02)

    def test_prints_the_count_of_each_result_per_category(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.download_once([APPLICATION, TERMS, FEES])
        self.serve_downloads([[APPLICATION, TERMS, FEES, DASH_NAMED]])
        self.routes[TERMS] = (200, pdf_bytes(TERMS) + b"revised\n")
        self.routes[FEES] = (500, b"boom")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("下載：已下載 1、內容變更 1、未變 1、失敗 1", result.stdout)
        self.assertIn("卡片：已存在略過 1", result.stdout)
        self.assertIn("活動：沒有文件", result.stdout)


class WithoutUpdateModeTests(ScriptTestCase):
    def test_existing_pdf_with_different_content_is_left_alone_and_no_summary_is_printed(self) -> None:
        self.serve_downloads([[APPLICATION]])
        self.assertEqual(self.run_script().returncode, 0)
        saved = self.out / "downloads" / "download_word_CR04131_1150B.pdf"
        before = saved.read_bytes()
        os.utime(saved, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.routes[APPLICATION] = (200, pdf_bytes(APPLICATION) + b"revised\n")
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(saved.read_bytes(), before)
        self.assertEqual(saved.stat().st_mtime_ns, OLD_MTIME_NS)
        self.assertNotIn(APPLICATION, self.server.paths())
        self.assertEqual([r["result"] for r in self.manifest() if r["category"] == "下載"], ["已存在略過"])
        self.assertNotIn("各類別統計", result.stdout)


def offer_list_path(letter: str, number: int) -> str:
    """刷卡優惠列表某分類第 number 頁的請求路徑（含 query）。"""
    return f"{OFFER_LIST_PREFIX}{letter}?page={number}"


# 預設的刷卡優惠列表沒有任何活動：九個分類各請求第 1 頁就停
EMPTY_OFFER_REQUESTS = [offer_list_path(letter, 1) for letter in OFFER_CATEGORIES]


def wm(number: int) -> str:
    """第 number 個假活動的 WM 編號。"""
    return detail_path(number).removeprefix(DETAIL_PREFIX)


class OfferListTests(ScriptTestCase):
    def test_walks_every_category_and_page_until_no_new_link_and_fetches_each_detail_page_once(self) -> None:
        absolute = f"https://mkp.example.invalid{detail_path(5)}"
        self.serve_offers(
            {
                "A": [[detail_path(1), detail_path(2)], [detail_path(3)]],
                "B": [[detail_path(4), detail_path(1)]],
                "I": [[absolute], [detail_path(6)]],
            }
        )
        self.serve_details({detail_path(n): offer_detail_html(f"OFFER{n}") for n in range(1, 7)})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        offer_requests = [p for p in self.server.paths() if p.startswith(OFFER_LIST_PREFIX)]
        self.assertEqual(
            offer_requests,
            [offer_list_path("A", n) for n in (1, 2, 3)]
            + [offer_list_path("B", n) for n in (1, 2)]
            + [offer_list_path(letter, 1) for letter in "CDEFGH"]
            + [offer_list_path("I", n) for n in (1, 2, 3)],
        )
        # 詳情頁只向 mkp 請求，依發現順序各一次；絕對網址改用 mkp 的前綴；輪播連結與 JS 樣板的假連結不收
        self.assertEqual(self.mkp_server.paths(), [detail_path(n) for n in (1, 2, 3, 4, 5, 6)])
        self.assertFalse([p for p in self.server.paths() if p.startswith(DETAIL_PREFIX)])

    def test_prints_each_activity_page_to_pdf_named_by_wm_number_and_keeps_raw_html(self) -> None:
        self.serve_offers({"A": [[detail_path(1), detail_path(2)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1"), detail_path(2): offer_detail_html("OFFER2")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(),
            [
                f"_meta/html/offer_{wm(1)}.html",
                f"_meta/html/offer_{wm(2)}.html",
                "_meta/manifest.jsonl",
                f"_meta/print/offer_{wm(1)}.html",
                f"_meta/print/offer_{wm(2)}.html",
                f"offers/offer_{wm(1)}.pdf",
                f"offers/offer_{wm(2)}.pdf",
            ],
        )
        self.assertTrue((self.out / "offers" / f"offer_{wm(1)}.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertEqual((self.out / "_meta" / "html" / f"offer_{wm(1)}.html").read_bytes(), self.mkp_routes[detail_path(1)][1])

    def test_prints_the_activity_count_found(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]], "C": [[detail_path(2), detail_path(1)]]})
        self.serve_details({detail_path(n): offer_detail_html(f"OFFER{n}") for n in (1, 2)})
        result = self.run_script()
        self.assertIn("找到 2 個活動頁", result.stdout)


class OfferPeriodTests(ScriptTestCase):
    def serve_one_activity(self, html: str) -> dict[str, str]:
        """登記只有一個活動的列表與詳情頁，執行腳本，回傳該活動的清單紀錄。"""
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): html})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = self.manifest()
        self.assertEqual(len(records), 1)
        return records[0]

    def test_activity_that_ended_before_today_is_skipped_and_recorded_as_expired(self) -> None:
        period = period_from_today(-60, -1)
        record = self.serve_one_activity(offer_detail_html("OFFER1", period=period))
        self.assertEqual(record["result"], "過期略過")
        self.assertEqual(record["period"], period)
        self.assertEqual(record["category"], "活動")
        self.assertEqual(self.files_under_out(), ["_meta/html/offer_%s.html" % wm(1), "_meta/manifest.jsonl"])

    def test_activity_that_ends_today_is_downloaded(self) -> None:
        period = period_from_today(-10, 0)
        record = self.serve_one_activity(offer_detail_html("OFFER1", period=period))
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(record["period"], period)
        self.assertTrue((self.out / "offers" / f"offer_{wm(1)}.pdf").is_file())

    def test_activity_without_a_period_block_is_downloaded_and_marked_unknown_ignoring_free_text(self) -> None:
        # 頁面正文的自由文字寫著已過期的期間，不能拿來當活動期間
        record = self.serve_one_activity(offer_detail_html("OFFER1", period=None))
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(record["period"], "期間不明")
        self.assertTrue((self.out / "offers" / f"offer_{wm(1)}.pdf").is_file())

    def test_period_in_another_format_or_with_a_nonexistent_date_is_unknown(self) -> None:
        for text in ("2020/09/22~2020/12/31", "2020-9-22~2020-12-31", "2020-09-22 ~ 2020-12-31", "2020-13-45~2020-12-31", ""):
            with self.subTest(period=text):
                self.server.requests.clear()
                self.mkp_server.requests.clear()
                shutil.rmtree(self.out, ignore_errors=True)
                record = self.serve_one_activity(offer_detail_html("OFFER1", period=text))
                self.assertEqual(record["result"], "已下載")
                self.assertEqual(record["period"], "期間不明")

    def test_expired_activity_is_not_printed_and_does_not_fail_the_run(self) -> None:
        self.serve_offers({"A": [[detail_path(1), detail_path(2)]]})
        self.serve_details(
            {
                detail_path(1): offer_detail_html("OFFER1", period=period_from_today(-60, -1)),
                detail_path(2): offer_detail_html("OFFER2", period=period_from_today(-1, 60)),
            }
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in (self.out / "offers").iterdir()), [f"offer_{wm(2)}.pdf"])
        self.assertIn(f"過期略過 活動 offer_{wm(1)}.pdf", result.stdout)

    def test_rerun_keeps_the_period_of_existing_activities_in_the_manifest(self) -> None:
        period = period_from_today(-5, 30)
        self.serve_one_activity(offer_detail_html("OFFER1", period=period))
        self.mkp_server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.mkp_server.paths(), [], "已存在的活動頁不該再請求")
        record = self.manifest()[0]
        self.assertEqual(record["result"], "已存在略過")
        self.assertEqual(record["period"], period)


# 每種支援的圖片副檔名對應一段合法的檔頭（RAG-Anything 支援的 8 種，見 rag_lab/formats.py）
VALID_IMAGE_HEADERS = {
    "png": PNG_BYTES,
    "jpg": JPEG_BYTES,
    "jpeg": JPEG_BYTES,
    "gif": b"GIF89a" + b"fake gif body",
    "bmp": b"BM" + b"fake bmp body",
    "tiff": b"II*\x00" + b"fake tiff body",
    "tif": b"MM\x00*" + b"fake tif body",
    "webp": b"RIFF\x10\x00\x00\x00WEBP" + b"fake webp body",
}


class OfferImageTests(ScriptTestCase):
    def serve_activities(self, banners: dict[int, str | None], *, periods: dict[int, str] | None = None) -> None:
        """登記活動 1..N（N 是 banners 的最大編號）都在分類 A 的第 1 頁，各自的主視覺網址是 mkp 前綴加 banners[n]。

        Args:
            banners: 活動編號對主視覺路徑；None 表示該活動頁沒有 div.banner-image。
            periods: 活動編號對活動期間；沒有列出的活動期間是 2099 年。
        """
        periods = periods or {}
        self.serve_offers({"A": [[detail_path(n) for n in sorted(banners)]]})
        self.serve_details(
            {
                detail_path(n): offer_detail_html(
                    f"OFFER{n}",
                    period=periods.get(n, "2099-01-01~2099-12-31"),
                    banner=None if path is None else self.mkp_server.base_url + path,
                )
                for n, path in banners.items()
            }
        )

    def image_requests(self) -> list[str]:
        """mkp 收到的圖片請求路徑（依時間順序）。"""
        return [p for p in self.mkp_server.paths() if p.startswith(UPLOAD_PREFIX)]

    def test_saves_the_banner_of_the_first_8_activities_that_have_one_in_discovery_order(self) -> None:
        # 活動 1 沒有主視覺（頁面只有分享圖示），2–10 有 9 個：只收前 8 個，也就是 2–9
        banners = {1: None, **{n: banner_path(n) for n in range(2, 11)}}
        self.serve_activities(banners)
        self.serve_images({banner_path(n): PNG_BYTES + str(n).encode() for n in range(2, 11)})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [banner_path(n) for n in range(2, 10)])
        self.assertNotIn("round-default.png", " ".join(self.mkp_server.paths()))
        saved = sorted(p.name for p in (self.out / "offer_images").iterdir())
        self.assertEqual(saved, [f"offer_image_{wm(n)}_banner_image.png" for n in range(2, 10)])
        self.assertEqual(
            (self.out / "offer_images" / f"offer_image_{wm(2)}_banner_image.png").read_bytes(), PNG_BYTES + b"2"
        )
        self.assertEqual(len(list((self.out / "offers").iterdir())), 10, "10 個活動頁都要列印成 PDF")
        self.assertIn("找到 8 張主視覺", result.stdout)

    def test_expired_activities_do_not_take_a_banner_slot(self) -> None:
        banners = {n: banner_path(n) for n in range(1, 11)}
        self.serve_activities(banners, periods={1: period_from_today(-60, -1)})
        self.serve_images({banner_path(n): PNG_BYTES for n in range(1, 11)})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [banner_path(n) for n in range(2, 10)])

    def test_record_for_a_saved_banner(self) -> None:
        self.serve_activities({1: banner_path(1)})
        self.serve_images({banner_path(1): PNG_BYTES})
        self.assertEqual(self.run_script().returncode, 0)
        record = next(r for r in self.manifest() if r["category"] == "活動圖片")
        self.assertEqual(record["url"], self.mkp_server.base_url + banner_path(1))
        self.assertEqual(record["filename"], f"offer_image_{wm(1)}_banner_image.png")
        self.assertEqual(record["format"], "圖片")
        self.assertEqual(record["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(record["sha256"], hashlib.sha256(PNG_BYTES).hexdigest())
        self.assertEqual(record["html_sha256"], "")
        self.assertEqual(record["period"], "")
        self.assertEqual(record["result"], "已下載")

    def test_unsupported_image_format_is_skipped_recorded_and_still_takes_a_slot(self) -> None:
        banners = {1: banner_path(1, "svg"), **{n: banner_path(n) for n in range(2, 11)}}
        self.serve_activities(banners)
        self.serve_images({banner_path(1, "svg"): b"<svg/>", **{banner_path(n): PNG_BYTES for n in range(2, 11)}})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [banner_path(n) for n in range(2, 9)], "svg 不請求，前 8 個有主視覺的是 1–8")
        record = next(r for r in self.manifest() if r["filename"] == f"offer_image_{wm(1)}_banner_image.svg")
        self.assertEqual(record["result"], "格式不支援略過")
        self.assertIn(".svg", record["detail"])
        self.assertEqual(len(list((self.out / "offer_images").iterdir())), 7)

    def test_every_supported_extension_is_saved_when_the_header_matches_and_the_extension_is_lowercased(self) -> None:
        # 8 種副檔名各一個活動，剛好用滿 8 個名額；jpg 在網址裡寫成大寫
        extensions = list(VALID_IMAGE_HEADERS)
        banners = {n: banner_path(n, "JPG" if ext == "jpg" else ext) for n, ext in enumerate(extensions, start=1)}
        self.serve_activities(banners)
        self.serve_images({banners[n]: VALID_IMAGE_HEADERS[ext] for n, ext in enumerate(extensions, start=1)})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        saved = sorted(p.suffix for p in (self.out / "offer_images").iterdir())
        self.assertEqual(saved, sorted(f".{ext}" for ext in extensions))

    def test_content_that_does_not_match_the_extension_is_a_failure_and_is_not_saved(self) -> None:
        self.serve_activities({1: banner_path(1, "png"), 2: banner_path(2, "jpg"), 3: banner_path(3, "gif")})
        self.serve_images(
            {
                banner_path(1, "png"): JPEG_BYTES,
                banner_path(2, "jpg"): b"<html>error page</html>",
                banner_path(3, "gif"): b"GIF89a ok",
            }
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in (self.out / "offer_images").iterdir()), [f"offer_image_{wm(3)}_banner_image.gif"])
        self.assertIn(f"offer_image_{wm(1)}_banner_image.png", result.stderr)
        self.assertIn(f"offer_image_{wm(2)}_banner_image.jpg", result.stderr)
        self.assertIn("檔頭", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_banner_outside_the_mkp_domain_is_a_failure_and_is_not_requested(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", banner="https://img.example.invalid/b.png")})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("mkp", result.stderr)
        self.assertEqual(self.image_requests(), [])
        self.assertFalse((self.out / "offer_images").exists() and list((self.out / "offer_images").iterdir()))

    def test_http_error_on_one_banner_does_not_stop_the_others(self) -> None:
        self.serve_activities({1: banner_path(1), 2: banner_path(2)})
        self.serve_images({banner_path(2): PNG_BYTES})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"offer_image_{wm(1)}_banner_image.png", result.stderr)
        self.assertEqual(sorted(p.name for p in (self.out / "offer_images").iterdir()), [f"offer_image_{wm(2)}_banner_image.png"])

    def test_activity_that_failed_to_download_has_no_banner_and_the_next_one_takes_its_slot(self) -> None:
        banners = {n: banner_path(n) for n in range(1, 11)}
        self.serve_activities(banners)
        self.serve_images({banner_path(n): PNG_BYTES for n in range(1, 11)})
        del self.mkp_routes[detail_path(1)]
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [banner_path(n) for n in range(2, 10)])

    def test_activity_whose_pdf_failed_has_no_banner_and_the_next_one_takes_its_slot(self) -> None:
        # 活動 1 的原始 HTML 存下來了，但列印失敗，沒有 PDF
        banners = {n: banner_path(n) for n in range(1, 11)}
        self.serve_activities(banners)
        self.mkp_routes[detail_path(1)] = (200, offer_detail_html("FAKE-CHROME-FAIL", banner=self.mkp_server.base_url + banner_path(1)).encode())
        self.serve_images({banner_path(n): PNG_BYTES for n in range(1, 11)})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.out / "_meta" / "html" / f"offer_{wm(1)}.html").is_file())
        self.assertFalse((self.out / "offers" / f"offer_{wm(1)}.pdf").exists())
        self.assertEqual(self.image_requests(), [banner_path(n) for n in range(2, 10)])

    def test_banner_given_as_an_absolute_url_on_the_real_mkp_domain_is_replaced_with_the_mkp_prefix(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details(
            {detail_path(1): offer_detail_html("OFFER1", banner="https://mkp.taishinbank.com.tw" + banner_path(1))}
        )
        self.serve_images({banner_path(1): PNG_BYTES})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [banner_path(1)])
        record = next(r for r in self.manifest() if r["category"] == "活動圖片")
        self.assertEqual(record["url"], self.mkp_server.base_url + banner_path(1))
        self.assertEqual(record["result"], "已下載")

    def test_banner_on_another_domain_names_that_domain_in_the_failure(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", banner="https://img.example.invalid/b.png")})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("img.example.invalid", result.stderr)
        self.assertNotIn("mkp.taishinbank.com.tw", result.stderr)

    def test_rerun_skips_existing_banners_without_requesting_them(self) -> None:
        self.serve_activities({1: banner_path(1), 2: None})
        self.serve_images({banner_path(1): PNG_BYTES})
        self.assertEqual(self.run_script().returncode, 0)
        self.mkp_server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.mkp_server.paths(), [])
        record = next(r for r in self.manifest() if r["category"] == "活動圖片")
        self.assertEqual(record["result"], "已存在略過")

    def test_no_banners_when_the_offer_list_failed(self) -> None:
        self.routes[offer_list_path("A", 1)] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stderr.count("ERROR 列表"), 1)
        self.assertEqual(self.image_requests(), [])


class OfferFailureTests(ScriptTestCase):
    def test_list_page_failure_exits_nonzero_names_the_list_category_and_page_and_keeps_the_other_categories(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_offers({"A": [[detail_path(1)], [detail_path(2)]]})
        self.routes[offer_list_path("A", 2)] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for text in ("刷卡優惠", "分類 A", "第 2 頁", "500"):
            self.assertIn(text, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())
        self.assertEqual(self.mkp_server.paths(), [], "列表失敗時，這一類不下載任何活動頁")

    def test_later_category_failure_also_fails_the_whole_offer_list(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.routes[offer_list_path("D", 1)] = (404, b"gone")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("分類 D", result.stderr)

    def test_stops_at_the_page_limit_when_a_category_keeps_having_new_activities(self) -> None:
        def endless(request_path: str) -> tuple[int, bytes] | None:
            parsed = urlparse(request_path)
            if not parsed.path.startswith(OFFER_LIST_PREFIX):
                return None
            number = int(parse_qs(parsed.query)["page"][0])
            return 200, offer_list_html([detail_path(number)]).encode()

        self.list_handlers["offers"] = endless
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("分類 A", result.stderr)
        self.assertIn("上限 20 頁", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        offer_requests = [p for p in self.server.paths() if p.startswith(OFFER_LIST_PREFIX)]
        self.assertEqual(offer_requests, [offer_list_path("A", n) for n in range(1, 21)])

    def test_http_error_on_one_activity_page_does_not_stop_the_others(self) -> None:
        self.serve_offers({"A": [[detail_path(1), detail_path(2)]]})
        self.serve_details({detail_path(2): offer_detail_html("OFFER2")})
        self.mkp_routes[detail_path(1)] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"offer_{wm(1)}.pdf", result.stderr)
        self.assertIn("500", result.stderr)
        self.assertTrue((self.out / "offers" / f"offer_{wm(2)}.pdf").is_file())

    def test_activity_page_without_a_main_content_area_is_a_failure(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): card_html_without_main_content()})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("找不到主內容區", result.stderr)
        self.assertFalse((self.out / "offers" / f"offer_{wm(1)}.pdf").exists())

    def test_chrome_print_failure_fails_that_activity_only(self) -> None:
        self.serve_offers({"A": [[detail_path(1), detail_path(2)]]})
        self.serve_details({detail_path(1): offer_detail_html("FAKE-CHROME-FAIL"), detail_path(2): offer_detail_html("OFFER2")})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"offer_{wm(1)}.pdf", result.stderr)
        self.assertTrue((self.out / "offers" / f"offer_{wm(2)}.pdf").is_file())

    def test_missing_chrome_fails_each_activity_and_names_the_environment_variable(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1")})
        result = self.run_script(chrome=str(self.tmp / "no-such-chrome"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("TAISHIN_CHROME", result.stderr)


class OfferRequestPolicyTests(ScriptTestCase):
    def test_requests_to_all_three_domains_carry_the_user_agent_and_are_spaced_by_the_interval(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", banner=self.mkp_server.base_url + banner_path(1))})
        self.serve_images({banner_path(1): PNG_BYTES})
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        requests = sorted(self.server.requests + self.mkp_server.requests, key=lambda r: r[1])
        self.assertEqual(len(self.mkp_server.requests), 2, "詳情頁與主視覺各 1 個")
        for _path, _time, user_agent in requests:
            self.assertTrue(user_agent.startswith("llm-lab-fetch-taishin/"), user_agent)
        for earlier, later in zip(requests, requests[1:]):
            self.assertGreaterEqual(later[1] - earlier[1], interval - 0.02)


class OfferChromeInputTests(ScriptTestCase):
    """交給 Chrome 的活動頁 HTML：只含 class 含 page-content 的主內容區。"""

    def setUp(self) -> None:
        super().setUp()
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", banner=self.mkp_server.base_url + banner_path(1))})
        self.serve_images({banner_path(1): PNG_BYTES})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.received = (self.out / "offers" / f"offer_{wm(1)}.pdf").read_text(encoding="utf-8", errors="replace")

    def test_contains_main_content_including_collapsed_blocks(self) -> None:
        for text in ("OFFER1", "COLLAPSED-TEXT", "未關閉項目二"):
            self.assertIn(text, self.received)

    def test_excludes_site_scripts_styles_and_content_outside_the_main_area(self) -> None:
        for text in ("SITE_SCRIPT_TEXT", "SITE-STYLE-TEXT", "INNER_SCRIPT_TEXT", "INNER-STYLE-TEXT", "NAV-MENU-TEXT", "FOOTER-TEXT", "banner-image"):
            self.assertNotIn(text, self.received)

    def test_has_base_href_pointing_to_the_original_url(self) -> None:
        self.assertIn(f'<base href="{self.mkp_server.base_url}{detail_path(1)}">', self.received)


class OfferManifestTests(ScriptTestCase):
    def test_record_has_the_same_fields_as_other_categories_and_the_period(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_offers({"A": [[detail_path(1)]]})
        period = period_from_today(-5, 30)
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", period=period)})
        self.assertEqual(self.run_script().returncode, 0)
        records = {r["filename"]: r for r in self.manifest()}
        record = records[f"offer_{wm(1)}.pdf"]
        pdf = (self.out / "offers" / f"offer_{wm(1)}.pdf").read_bytes()
        self.assertEqual(record["url"], self.mkp_server.base_url + detail_path(1))
        self.assertEqual(record["category"], "活動")
        self.assertEqual(record["format"], "PDF")
        self.assertEqual(record["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(record["sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertEqual(record["html_sha256"], hashlib.sha256(self.mkp_routes[detail_path(1)][1]).hexdigest())
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(record["period"], period)
        self.assertEqual(set(record), set(records["card_cg047_card001.pdf"]))
        self.assertEqual(records["card_cg047_card001.pdf"]["period"], "")


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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, INSURANCE, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS])
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
            'for last; do :; done\n'
            'case "$last" in *insurance*) echo "cannot convert" >&2; exit 3;; esac\n'
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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS], "第二次只該請求列表頁")
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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS])
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
        # 總覽頁、卡片頁、權益頁、下載頁各 1 個，加刷卡優惠列表 9 個分類各 1 頁
        self.assertEqual(len(self.server.requests), 13)
        for _path, _time, user_agent in self.server.requests:
            self.assertTrue(user_agent.startswith("llm-lab-fetch-taishin/"), user_agent)

    def test_requests_are_spaced_by_at_least_the_configured_interval(self) -> None:
        self.serve_cards(
            {RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN"), DAQUANLIAN_2: card_html("DQL2")}
        )
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        times = [t for _path, t, _ua in self.server.requests]
        self.assertEqual(len(times), 15)
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


# ==============================
# code-review 修正：請求前的網址處理、轉址、清單範圍
# ==============================

BAD_HREF = "http://[bad"


class UrlHandlingTests(ScriptTestCase):
    def test_pdf_link_with_a_non_ascii_query_is_requested_with_the_query_percent_encoded(self) -> None:
        href = APPLICATION + "?name=費用"
        self.serve_downloads([[href]])
        self.routes[APPLICATION + "?name=" + quote("費用")] = (200, pdf_bytes(APPLICATION))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(APPLICATION + "?name=" + quote("費用"), self.server.paths())
        self.assertEqual((self.out / "downloads" / "download_word_CR04131_1150B.pdf").read_bytes(), pdf_bytes(APPLICATION))

    def test_a_page_whose_url_cannot_be_encoded_fails_that_page_only_and_the_manifest_is_still_written(self) -> None:
        non_ascii = RIGHTS_PATH_FORMAT.format(group="保險", page="頁")
        self.serve_rights({non_ascii: card_html("NON-ASCII"), PARKING: card_html("PARKING")})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        records = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(records["rights_保險_頁.docx"]["result"], "失敗")
        self.assertEqual(records["rights_parking_right0301.docx"]["result"], "已下載")

    def test_a_malformed_href_in_the_overview_is_skipped_and_the_other_cards_are_downloaded(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.routes[OVERVIEW_PATH] = (
            200,
            overview_html([RICHART]).replace("</body>", f'<a href="{BAD_HREF}">壞連結</a></body>').encode(),
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual([r["filename"] for r in self.manifest()], ["card_cg047_card001.pdf"])

    def test_a_malformed_href_in_the_download_list_is_skipped_and_the_other_pdfs_are_downloaded(self) -> None:
        self.serve_downloads([[APPLICATION]])
        original = self.list_handlers["downloads"]

        def with_bad_link(request_path: str) -> tuple[int, bytes] | None:
            """下載頁的回應加上一個格式錯誤的連結；不是下載頁的路徑回 None。"""
            answer = original(request_path)
            if answer is None:
                return None
            return answer[0], answer[1].replace(b"</body>", f'<a href="{BAD_HREF}">壞連結</a></body>'.encode())

        self.list_handlers["downloads"] = with_bad_link
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual([r["filename"] for r in self.manifest()], ["download_word_CR04131_1150B.pdf"])

    def test_a_malformed_href_in_the_offer_list_is_skipped_and_the_other_activities_are_downloaded(self) -> None:
        self.serve_offers({"A": [[BAD_HREF, detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual([r["result"] for r in self.manifest() if r["category"] == "活動"], ["已下載"])

    def test_links_that_differ_only_by_fragment_are_one_page(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.routes[OVERVIEW_PATH] = (200, overview_html([RICHART, RICHART + "#tab2", RICHART + "#"]).encode())
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths().count(RICHART), 1)
        self.assertEqual([r["filename"] for r in self.manifest()], ["card_cg047_card001.pdf"])
        self.assertIn("找到 1 張卡片頁", result.stdout)


class RedirectTests(ScriptTestCase):
    def test_redirect_to_another_domain_is_not_followed_and_fails_that_page_with_the_domain_in_the_reason(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING")})
        outside = urlparse(self.mkp_server.base_url).netloc
        self.server.redirects[INSURANCE] = self.mkp_server.base_url + "/outside/page/"
        self.mkp_routes["/outside/page/"] = (200, card_html("OUTSIDE").encode())
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.mkp_server.paths(), [], "外部網域不該收到請求")
        records = {r["filename"]: r for r in self.manifest()}
        failed = records["rights_insurance_right0201.docx"]
        self.assertEqual(failed["result"], "失敗")
        self.assertIn(f"轉址到外部網域 {outside}", failed["detail"])
        self.assertEqual(records["rights_parking_right0301.docx"]["result"], "已下載")
        self.assertFalse((self.out / "rights" / "rights_insurance_right0201.docx").exists())

    def test_redirect_within_the_same_domain_is_followed(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.server.redirects[INSURANCE] = "/TSB/moved/insurance/"
        self.routes["/TSB/moved/insurance/"] = (200, card_html("MOVED-INSURANCE").encode())
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"MOVED-INSURANCE", (self.out / "rights" / "rights_insurance_right0201.docx").read_bytes())

    def test_redirect_of_a_banner_to_another_domain_is_not_followed(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", banner=self.mkp_server.base_url + banner_path(1))})
        self.mkp_server.redirects[banner_path(1)] = self.server.base_url + "/outside.png"
        self.routes["/outside.png"] = (200, PNG_BYTES)
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("/outside.png", self.server.paths())
        record = next(r for r in self.manifest() if r["category"] == "活動圖片")
        self.assertEqual(record["result"], "失敗")
        self.assertIn("轉址到外部網域", record["detail"])


class ExpiredActivityRerunTests(ScriptTestCase):
    def test_rerun_does_not_request_the_page_of_an_activity_whose_saved_html_is_expired(self) -> None:
        period = period_from_today(-60, -1)
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", period=period)})
        self.assertEqual(self.run_script().returncode, 0)
        self.mkp_server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.mkp_server.paths(), [], "已知過期的活動頁不該再請求")
        record = self.manifest()[0]
        self.assertEqual(record["result"], "過期略過")
        self.assertEqual(record["period"], period)
        self.assertEqual(record["html_sha256"], hashlib.sha256(self.mkp_routes[detail_path(1)][1]).hexdigest())

    def test_rerun_requests_the_page_again_when_the_saved_html_is_not_expired_but_the_pdf_is_missing(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("FAKE-CHROME-FAIL")})
        self.assertEqual(self.run_script().returncode, 1)
        self.mkp_server.requests.clear()
        self.serve_details({detail_path(1): offer_detail_html("OFFER1")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.mkp_server.paths(), [detail_path(1)])
        self.assertTrue((self.out / "offers" / f"offer_{wm(1)}.pdf").is_file())


SITECUSTOMIZE_CLOCK = """
import datetime as _dt
_real = _dt.date


class _Date(_real):
    calls = 0

    @classmethod
    def today(cls):
        _Date.calls += 1
        today = _real.today()
        return today if _Date.calls == 1 else today + _dt.timedelta(days=1)


_dt.date = _Date
"""


class RunDateTests(ScriptTestCase):
    def test_today_is_read_once_per_run_so_crossing_midnight_does_not_change_the_result(self) -> None:
        # 子行程的 date.today() 第一次回真正的今天，之後每次都回明天（模擬執行到一半跨過午夜）
        clock = self.tmp / "clock"
        clock.mkdir()
        (clock / "sitecustomize.py").write_text(SITECUSTOMIZE_CLOCK, encoding="utf-8")
        ends_today = period_from_today(-10, 0)
        self.serve_offers({"A": [[detail_path(n) for n in (1, 2, 3)]]})
        self.serve_details(
            {detail_path(n): offer_detail_html(f"OFFER{n}", period=ends_today, banner=self.mkp_server.base_url + banner_path(n)) for n in (1, 2, 3)}
        )
        self.serve_images({banner_path(n): PNG_BYTES for n in (1, 2, 3)})
        result = self.run_script(extra_env={"PYTHONPATH": str(clock)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = [r for r in self.manifest() if r["category"] in ("活動", "活動圖片")]
        self.assertEqual([r["result"] for r in records], ["已下載"] * 6)
        self.assertEqual({r["downloaded_at"] for r in records}, {time.strftime("%Y-%m-%d")})


class LibreOfficeProfileTests(ScriptTestCase):
    def test_each_conversion_uses_its_own_temporary_user_profile_that_is_removed_afterwards(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING")})
        log = self.tmp / "office_args.log"
        directory = self.tmp / "logging_office"
        directory.mkdir()
        for name in ("libreoffice", "soffice"):
            wrapper = directory / name
            wrapper.write_text(
                f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{log}"\nexec "{sys.executable}" "{FAKE_LIBREOFFICE}" "$@"\n'
            )
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        result = self.run_script(path=str(directory))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first_args = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(first_args), 2)
        profiles = [Path(unquote(arg.removeprefix("-env:UserInstallation=file://"))) for arg in first_args]
        self.assertEqual(len({str(p) for p in profiles}), 2, "兩次轉檔要各用自己的資料夾")
        for profile in profiles:
            self.assertTrue(profile.is_relative_to(self.out.resolve()), f"暫時資料夾要在輸出資料夾內：{profile}")
            self.assertFalse(profile.parent.exists(), "轉檔完要移除暫時資料夾")
        self.assertEqual(
            [f for f in self.files_under_out() if not f.startswith("_meta/")],
            ["rights/rights_insurance_right0201.docx", "rights/rights_parking_right0301.docx"],
        )
        self.assertEqual([f for f in self.files_under_out() if "profile" in f or "user" in f], [])


def unsafe_card_html() -> str:
    """產生卡片頁：主內容區含 inline 事件屬性、javascript: 網址、iframe 與 <link rel=stylesheet>。

    Returns:
        卡片頁的 HTML；另有會被保留的標記（未關閉的 <p>、字元參照、有引號的屬性值、boolean 屬性、rel=icon 的 link）。
    """
    return """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="centercontainer">
  <p onclick="evil1()">UNSAFE-KEEP-TEXT</p>
  <img src="/img/a.gif" onerror="evil2()" ONLOAD="evil3()">
  <a href="javascript:evil4()">JS-LINK-TEXT</a>
  <a href=" Java&#9;Script:evil5()">JS-LINK-TEXT-2</a>
  <iframe src="https://example.invalid/frame"><p>IFRAME-INNER</p></iframe>
  <link rel="stylesheet" href="/inner.css">
  <link rel="icon" href="/favicon.ico">
  <div class="kept" data-x='a"b' hidden>QUOTE-AND-FLAG</div>
  <a href="/ok/">OK-LINK</a>
  <p>AFTER &amp; ENTITY &copy; 2026
</div></body></html>"""


class ActiveContentTests(ScriptTestCase):
    """交給 Chrome 與 LibreOffice 的 HTML 不含會執行或載入外部內容的元素；Chrome 的 profile 封鎖 JavaScript。"""

    def setUp(self) -> None:
        """卡片、權益與活動頁都用含主動內容的頁面執行一次，收下各自交給 Chrome 或 LibreOffice 的 HTML。"""
        super().setUp()
        self.serve_cards({RICHART: unsafe_card_html()})
        self.serve_rights({INSURANCE: unsafe_card_html()})
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): unsafe_card_html().replace("centercontainer", "page-content").replace("id=", "class=")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.received = {
            "card": (self.out / "cards" / "card_cg047_card001.pdf").read_text(encoding="utf-8", errors="replace"),
            "rights": (self.out / "rights" / "rights_insurance_right0201.docx").read_text(encoding="utf-8", errors="replace"),
            "offer": (self.out / "offers" / f"offer_{wm(1)}.pdf").read_text(encoding="utf-8", errors="replace"),
        }

    def test_removes_inline_event_attributes_javascript_urls_iframes_and_stylesheet_links(self) -> None:
        for kind, received in self.received.items():
            with self.subTest(kind=kind):
                for text in ("evil1", "evil2", "evil3", "evil4", "evil5", "onclick", "onerror", "onload", "javascript", "<iframe", "IFRAME-INNER", "inner.css"):
                    self.assertNotIn(text.lower(), received.lower())

    def test_keeps_the_text_and_the_other_markup(self) -> None:
        for kind, received in self.received.items():
            with self.subTest(kind=kind):
                for text in (
                    "UNSAFE-KEEP-TEXT",
                    "JS-LINK-TEXT",
                    "JS-LINK-TEXT-2",
                    '<img src="/img/a.gif">',
                    '<a href="/ok/">OK-LINK</a>',
                    '<link rel="icon" href="/favicon.ico">',
                    "data-x=\"a&quot;b\" hidden",
                    "QUOTE-AND-FLAG",
                    "AFTER &amp; ENTITY &copy; 2026",
                ):
                    self.assertIn(text, received)


class RightsAttachmentTests(ScriptTestCase):
    def test_pdfs_linked_from_rights_subpages_are_saved_unchanged_into_their_own_folder(self) -> None:
        self.serve_rights(
            {
                CO_BRAND_PAGE: rights_page_with_pdfs("CO_BRAND", [CO_BRAND_PDF]),
                DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF_2]),
            }
        )
        for path in (CO_BRAND_PDF, DUAL_PDF, DUAL_PDF_2):
            self.routes[path] = (200, pdf_bytes(path))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [f for f in self.files_under_out() if f.startswith("rights_attachments/")],
            [
                "rights_attachments/attachment_TSCC-11312.pdf",
                "rights_attachments/attachment_dual-card_01.pdf",
                "rights_attachments/attachment_dual-card_02.pdf",
            ],
        )
        for path in (CO_BRAND_PDF, DUAL_PDF, DUAL_PDF_2):
            saved = self.out / "rights_attachments" / f"attachment_{path.rsplit('/', 1)[1]}"
            self.assertEqual(saved.read_bytes(), pdf_bytes(path))

    def test_pdf_on_another_domain_is_not_requested_and_is_recorded_as_skipped(self) -> None:
        external = "https://www.icash.invalid/pdf/icash2_contract.pdf"
        self.serve_rights({CO_BRAND_PAGE: rights_page_with_pdfs("CO_BRAND", [CO_BRAND_PDF, external])})
        self.routes[CO_BRAND_PDF] = (200, pdf_bytes(CO_BRAND_PDF))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [f for f in self.files_under_out() if f.startswith("rights_attachments/")],
            ["rights_attachments/attachment_TSCC-11312.pdf"],
        )
        skipped = [r for r in self.manifest() if r["result"] == "外部網域略過"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["url"], external)
        self.assertEqual(skipped[0]["category"], "權益附件")
        self.assertEqual(skipped[0]["sha256"], "")
        self.assertIn("www.icash.invalid", skipped[0]["detail"])

    def test_pdf_already_in_the_download_area_is_not_downloaded_again_and_the_record_names_the_download_file(self) -> None:
        self.serve_downloads([[DUAL_PDF]])
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF_2])})
        self.routes[DUAL_PDF_2] = (200, pdf_bytes(DUAL_PDF_2))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths().count(DUAL_PDF), 1)
        self.assertEqual(
            [f for f in self.files_under_out() if f.endswith(".pdf")],
            ["downloads/download_dual-card_01.pdf", "rights_attachments/attachment_dual-card_02.pdf"],
        )
        duplicates = [r for r in self.manifest() if r["result"] == "重複略過"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["url"], self.server.base_url + DUAL_PDF)
        self.assertEqual(duplicates[0]["category"], "權益附件")
        self.assertEqual(duplicates[0]["sha256"], "")
        self.assertIn("download_dual-card_01.pdf", duplicates[0]["detail"])

    def test_existing_attachments_are_skipped_without_requesting_them_or_the_subpage(self) -> None:
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF_2])})
        for path in (DUAL_PDF, DUAL_PDF_2):
            self.routes[path] = (200, pdf_bytes(path))
        self.assertEqual(self.run_script().returncode, 0)
        first = {r["filename"]: r for r in self.manifest() if r["category"] == "權益附件"}
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS])
        second = {r["filename"]: r for r in self.manifest() if r["category"] == "權益附件"}
        self.assertEqual(sorted(second), sorted(first))
        for name, record in second.items():
            self.assertEqual(record["result"], "已存在略過")
            self.assertEqual(record["sha256"], first[name]["sha256"])

    def test_existing_subpage_is_read_from_the_saved_html_and_not_requested_again(self) -> None:
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF])})
        self.routes[DUAL_PDF] = (200, pdf_bytes(DUAL_PDF))
        self.assertEqual(self.run_script().returncode, 0)
        shutil.rmtree(self.out / "rights_attachments")
        # 子頁已存在而略過；官網上的子頁現在已經沒有這個連結，但存下來的原始 HTML 還有
        self.routes[DUAL_PAGE] = (200, rights_page_with_pdfs("DUAL", []).encode())
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, DUAL_PDF, *EMPTY_OFFER_REQUESTS])
        self.assertEqual(
            (self.out / "rights_attachments" / "attachment_dual-card_01.pdf").read_bytes(), pdf_bytes(DUAL_PDF)
        )
        self.assertEqual([r["result"] for r in self.manifest() if r["category"] == "權益"], ["已存在略過"])

    def test_subpage_whose_conversion_failed_still_contributes_its_pdf_links(self) -> None:
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF])})
        self.routes[DUAL_PDF] = (200, pdf_bytes(DUAL_PDF))
        empty = self.tmp / "empty_path"
        empty.mkdir()
        result = self.run_script(path=str(empty))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("LibreOffice", result.stderr)
        self.assertTrue((self.out / "rights_attachments" / "attachment_dual-card_01.pdf").is_file())

    def test_failed_attachment_is_downloaded_again_on_the_next_run(self) -> None:
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF])})
        self.routes[DUAL_PDF] = (500, b"boom")
        self.assertEqual(self.run_script().returncode, 1)
        self.routes[DUAL_PDF] = (200, pdf_bytes(DUAL_PDF))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([r["result"] for r in self.manifest() if r["category"] == "權益附件"], ["已下載"])

    def test_a_pdf_linked_from_several_subpages_is_downloaded_once(self) -> None:
        self.serve_rights(
            {
                CO_BRAND_PAGE: rights_page_with_pdfs("CO_BRAND", [DUAL_PDF, CO_BRAND_PDF]),
                DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF]),
            }
        )
        for path in (CO_BRAND_PDF, DUAL_PDF):
            self.routes[path] = (200, pdf_bytes(path))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths().count(DUAL_PDF), 1)
        self.assertEqual(len([r for r in self.manifest() if r["category"] == "權益附件"]), 2)

    def test_names_are_unique_when_different_urls_share_a_file_name(self) -> None:
        other_dir = "/TSB/export/sites/TSB/personal/credit/intro/payment/"
        same_name = [FILES_DIR + "terms.pdf", other_dir + "terms.pdf", other_dir + "Terms.pdf"]
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", same_name)})
        for path in same_name:
            self.routes[path] = (200, pdf_bytes(path))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = {r["url"]: r["filename"] for r in self.manifest() if r["category"] == "權益附件"}
        names = [records[self.server.base_url + path] for path in same_name]
        self.assertEqual(len({n.lower() for n in names}), 3, names)
        for name in names:
            self.assertRegex(name, r"^attachment_[Tt]erms_[0-9a-f]{8}\.pdf$")
        for path, name in zip(same_name, names):
            self.assertEqual((self.out / "rights_attachments" / name).read_bytes(), pdf_bytes(path))

    def test_relative_links_are_resolved_against_the_subpage_and_the_extension_is_case_insensitive(self) -> None:
        self.serve_rights({CO_BRAND_PAGE: rights_page_with_pdfs("CO_BRAND", ["terms.PDF", "../notes.pdf#page=2"])})
        self.routes[CO_BRAND_PAGE + "terms.PDF"] = (200, pdf_bytes("terms"))
        self.routes[CO_BRAND_PAGE.rsplit("right0702/", 1)[0] + "notes.pdf"] = (200, pdf_bytes("notes"))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [f for f in self.files_under_out() if f.startswith("rights_attachments/")],
            ["rights_attachments/attachment_notes.pdf", "rights_attachments/attachment_terms.pdf"],
        )

    def test_links_that_are_not_pdfs_are_ignored(self) -> None:
        hrefs = ["/TSB/personal/credit/intro/overview/", FILES_DIR + "form.docx", FILES_DIR + "pdf-guide.html"]
        self.serve_rights({CO_BRAND_PAGE: rights_page_with_pdfs("CO_BRAND", hrefs)})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([r for r in self.manifest() if r["category"] == "權益附件"], [])
        self.assertIn("權益子頁找到 0 個 PDF 連結", result.stdout)

    def test_prints_the_number_of_pdf_links_found_including_the_skipped_ones(self) -> None:
        external = "https://www.icash.invalid/pdf/icash2_contract.pdf"
        self.serve_downloads([[DUAL_PDF]])
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF_2, external])})
        self.routes[DUAL_PDF_2] = (200, pdf_bytes(DUAL_PDF_2))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("權益子頁找到 3 個 PDF 連結", result.stdout)
        self.assertEqual(
            sorted(r["result"] for r in self.manifest() if r["category"] == "權益附件"),
            sorted(["已下載", "外部網域略過", "重複略過"]),
        )


class RightsAttachmentManifestTests(ScriptTestCase):
    def test_record_has_the_same_fields_as_the_other_categories_and_no_html_sha256(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF])})
        self.routes[DUAL_PDF] = (200, pdf_bytes(DUAL_PDF))
        self.assertEqual(self.run_script().returncode, 0)
        records = {r["filename"]: r for r in self.manifest()}
        record = records["attachment_dual-card_01.pdf"]
        self.assertEqual(record["url"], self.server.base_url + DUAL_PDF)
        self.assertEqual(record["category"], "權益附件")
        self.assertEqual(record["format"], "PDF")
        self.assertEqual(record["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(record["sha256"], hashlib.sha256(pdf_bytes(DUAL_PDF)).hexdigest())
        self.assertEqual(record["html_sha256"], "")
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(record["period"], "")
        self.assertEqual(set(record), set(records["card_cg047_card001.pdf"]))
        self.assertFalse((self.out / "_meta" / "html" / "attachment_dual-card_01.html").exists())


class RightsAttachmentFailureTests(ScriptTestCase):
    def test_pdf_http_error_fails_that_pdf_only(self) -> None:
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF_2])})
        self.routes[DUAL_PDF_2] = (200, pdf_bytes(DUAL_PDF_2))
        self.routes[DUAL_PDF] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("attachment_dual-card_01.pdf", result.stderr)
        self.assertIn("500", result.stderr)
        self.assertEqual(
            [f for f in self.files_under_out() if f.startswith("rights_attachments/")],
            ["rights_attachments/attachment_dual-card_02.pdf"],
        )
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual([r["filename"] for r in failed], ["attachment_dual-card_01.pdf"])
        self.assertEqual(failed[0]["sha256"], "")

    def test_content_that_does_not_start_with_pdf_magic_is_a_failure_and_is_not_saved(self) -> None:
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF_2])})
        self.routes[DUAL_PDF] = (200, b"<html><body>Service Unavailable</body></html>")
        self.routes[DUAL_PDF_2] = (200, pdf_bytes(DUAL_PDF_2))
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("attachment_dual-card_01.pdf", result.stderr)
        self.assertIn("不是 PDF", result.stderr)
        self.assertEqual(
            [f for f in self.files_under_out() if f.startswith("rights_attachments/")],
            ["rights_attachments/attachment_dual-card_02.pdf"],
        )

    def test_a_subpage_that_could_not_be_fetched_does_not_stop_the_attachments_of_the_others(self) -> None:
        self.serve_rights(
            {
                CO_BRAND_PAGE: rights_page_with_pdfs("CO_BRAND", [CO_BRAND_PDF]),
                DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF]),
            }
        )
        self.routes[DUAL_PDF] = (200, pdf_bytes(DUAL_PDF))
        self.routes[CO_BRAND_PAGE] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            [f for f in self.files_under_out() if f.startswith("rights_attachments/")],
            ["rights_attachments/attachment_dual-card_01.pdf"],
        )

    def test_rights_list_failure_leaves_no_attachments_and_the_failure_is_reported_once(self) -> None:
        self.routes[RIGHTS_LIST_PATH] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stderr.count("列表「信用卡權益」"), 1)
        self.assertNotIn("權益附件", result.stderr)
        self.assertEqual([r for r in self.manifest() if r["category"] == "權益附件"], [])


class RightsAttachmentRequestPolicyTests(ScriptTestCase):
    def test_attachment_requests_carry_the_user_agent_and_are_spaced_by_the_interval(self) -> None:
        self.serve_rights({DUAL_PAGE: rights_page_with_pdfs("DUAL", [DUAL_PDF, DUAL_PDF_2])})
        for path in (DUAL_PDF, DUAL_PDF_2):
            self.routes[path] = (200, pdf_bytes(path))
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        requests = self.server.requests
        # 總覽頁 1、權益頁 1、子頁 1、下載頁 1、PDF 2 份、刷卡優惠列表 9 個分類各 1 頁，共 15 個請求
        self.assertEqual(len(requests), 15)
        for earlier, later in zip(requests, requests[1:]):
            self.assertGreaterEqual(later[1] - earlier[1], interval - 0.02)
        self.assertTrue(all(user_agent.startswith("llm-lab-fetch-taishin/") for _p, _t, user_agent in requests))


if __name__ == "__main__":
    unittest.main()
