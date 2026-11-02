"""fetch_taishin.py 的行為測試：以子行程執行腳本，對本機假 HTTP server 與假 Chrome 下載。

為什麼存在：fetch_taishin.py 是獨立腳本，沒有 CLI 以外的縫。測試只從子行程進入，觀察結束碼、
stdout／stderr、輸出資料夾的檔案、下載清單的內容、假 server 收到的請求，以及假 Chrome 收到的 HTML；
不 import 腳本的函式。

關鍵設計決策：
- 網址前綴（TAISHIN_WWW_BASE、TAISHIN_MKPCARD_BASE、TAISHIN_MKP_BASE、TAISHIN_RICHART_BASE）、Chrome 路徑（TAISHIN_CHROME）
  與請求間隔（TAISHIN_REQUEST_INTERVAL_SEC）都用環境變數指到假的版本。www 與 mkpcard 指到同一個假 server（self.server），
  mkp 指到另一個（self.mkp_server），所以測試能看出活動詳情頁與主視覺是向 mkp 的前綴請求，不是向 mkpcard。
  richart.tw 也是獨立的假 server（self.richart_server），預設登記兩個沒有任何優惠細則連結的卡片頁。
- 假 Chrome 是 tests/fake_chrome.py；測試在暫存資料夾寫一個 shell wrapper 呼叫它，
  腳本拿到的 Chrome 路徑就是這個 wrapper。
- 金融卡卡片頁：專區列表頁（payment/）連到群組落地頁（payment/cgXXX/），落地頁只有一段 location.replace 轉址，
  轉址目標是卡片頁（card01/ 或 card001/）；測試用 serve_debit_cards 登記這三層。預設（setUp）專區列表頁沒有任何卡。
- 金融卡約定條款 PDF 與說明頁：約定條款頁（notice/TSBankGridPage-000003/）列出 PDF 連結，用 serve_debit_terms 登記；
  說明頁是寫死的 7 個網址，用 serve_debit_info 登記。預設（setUp）約定條款頁沒有任何 PDF，7 個說明頁各有一個最小的主內容區，
  所以每個案例都多出 1 個約定條款頁請求、7 個說明頁請求，以及 7 份說明頁文件（debit_info/）。
- richart.tw：簽帳金融卡頁、信用卡頁是寫死的兩個網址，兩頁連到 /discount/discount-details?discount=<id> 的優惠細則；
  測試用 serve_richart 登記這兩頁與各細則頁。
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
DEBIT_LIST_PATH = "/TSB/personal/credit/intro/payment/"
DEBIT_GROUP_FORMAT = "/TSB/personal/credit/intro/payment/{cg}/"
DEBIT_CARD_FORMAT = "/TSB/personal/credit/intro/payment/{cg}/{card}/"
DEBIT_NOTICE_FORMAT = "/TSB/personal/credit/intro/payment/notice/TSBankGridPage-{number}/"
DEBIT_TERMS_PATH = DEBIT_NOTICE_FORMAT.format(number="000003")
DEBIT_DEPOSIT_PREFIX = "/TSB/personal/deposit/debit-card/"
# 金融卡說明頁：寫死的 7 個網址（費用、常見問題 2 頁、Richart 摘要、存款專區晶片金融卡 3 頁），照請求順序
DEBIT_INFO_PATHS = (
    DEBIT_NOTICE_FORMAT.format(number="000004"),
    DEBIT_NOTICE_FORMAT.format(number="000001"),
    DEBIT_NOTICE_FORMAT.format(number="000340"),
    DEBIT_NOTICE_FORMAT.format(number="000344"),
    DEBIT_DEPOSIT_PREFIX,
    DEBIT_DEPOSIT_PREFIX + "card-list/",
    DEBIT_DEPOSIT_PREFIX + "overseas-withdraw-cash-and-payment/",
)
DEBIT_INFO_NAMES = (
    "debit_info_TSBankGridPage-000004",
    "debit_info_TSBankGridPage-000001",
    "debit_info_TSBankGridPage-000340",
    "debit_info_TSBankGridPage-000344",
    "debit_info_debit-card",
    "debit_info_card-list",
    "debit_info_overseas-withdraw-cash-and-payment",
)
# setUp 預設登記的約定條款頁與 7 個說明頁，每次下載都多出這 8 個請求（接在專區列表頁之後）
DEBIT_DEFAULT_REQUESTS = [DEBIT_TERMS_PATH, *DEBIT_INFO_PATHS]
# 7 份說明頁文件在輸出資料夾裡的檔案（文件、原始 HTML、列印用 HTML），預設每次下載都會有
DEBIT_INFO_FILES = sorted(
    [f"debit_info/{name}.pdf" for name in DEBIT_INFO_NAMES]
    + [f"_meta/{folder}/{name}.html" for folder in ("html", "print") for name in DEBIT_INFO_NAMES]
)
DEBIT_INFO_DOCUMENTS = sorted(f"{name}.pdf" for name in DEBIT_INFO_NAMES)
RICHART_DEBIT_PATH = "/TSDIB_RichartWeb/card/debit-card"
RICHART_CREDIT_PATH = "/TSDIB_RichartWeb/card/credit-card"
RICHART_DISCOUNT_FORMAT = "/TSDIB_RichartWeb/discount/discount-details?discount={id}"
# 預設（setUp）登記的兩個 richart.tw 卡片頁每次執行都會下載，所以下載資料夾裡一定有這些檔案，清單裡一定有這兩份文件
RICHART_DEFAULT_FILES = [
    "_meta/html/richart_credit-card.html",
    "_meta/html/richart_debit-card.html",
    "_meta/print/richart_credit-card.html",
    "_meta/print/richart_debit-card.html",
    "richart/richart_credit-card.pdf",
    "richart/richart_debit-card.pdf",
]
RICHART_DEFAULT_DOCUMENTS = ["richart_debit-card.pdf", "richart_credit-card.pdf"]
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


def debit_list_html(group_paths: list[str]) -> str:
    """產生簽帳金融卡專區列表頁：每張卡一個「瞭解更多」連結到群組落地頁，外加不是落地頁的干擾連結。

    Args:
        group_paths: 群組落地頁（payment/cgXXX/）的路徑清單。

    Returns:
        專區列表頁的 HTML。
    """
    items = "".join(
        f'<div class="card"><a itemprop="url" href="{path}" class="oval-style">瞭解更多</a></div>'
        for path in group_paths
    )
    return (
        "<html><body>"
        '<a href="/TSB/personal/credit/intro/payment/">簽帳金融卡</a>'
        '<a href="/TSB/personal/credit/intro/overview/cg047/card001/">信用卡</a>'
        '<a href="/TSB/personal/credit/intro/payment/notice/TSBankGridPage-000003/">約定條款</a>'
        f'<div id="centercontainer">{items}</div>'
        "</body></html>"
    )


def debit_landing_html(redirect_target: str | None) -> str:
    """產生群組落地頁：主內容區只有卡片群組名稱和一段 location.replace 轉址（真實官網的落地頁就是這樣）。

    Args:
        redirect_target: location.replace 的參數；None 表示沒有轉址那段 JS。

    Returns:
        落地頁的 HTML。
    """
    script = (
        ""
        if redirect_target is None
        else f'<script>$(document).ready(function(){{location.replace("{redirect_target}");}})</script>'
    )
    return (
        "<html><body>"
        '<script>if (old) { window.location.href = "/TSB/ie_no_support/index.html"; }</script>'
        f'<div id="centercontainer"><div>卡片群組名稱:某金融卡<br>卡片群組:{script}</div></div>'
        "</body></html>"
    )


def debit_terms_html(hrefs: list[str]) -> str:
    """產生約定條款頁：主內容區有一串條款連結（官網的 PDF 連結是相對路徑），主內容區外的導覽也有連結。

    Args:
        hrefs: 條款連結的 href（相對路徑，或其他網域的絕對網址）。

    Returns:
        約定條款頁的 HTML。
    """
    anchors = "".join(f'<li><a href="{href}" title="" class="oval-style">條款</a></li>' for href in hrefs)
    return (
        "<html><body>"
        '<div id="topnav"><a href="https://tsbk.tw/5grsa9/">短網址</a></div>'
        f'<div id="centercontainer"><ul>{anchors}</ul></div>'
        "</body></html>"
    )


def debit_info_html(path: str) -> str:
    """產生金融卡說明頁：主內容區的文字帶著網址，讓各頁內容不同。

    Args:
        path: 說明頁的網址路徑。

    Returns:
        說明頁的 HTML（結構同 card_html）。
    """
    return card_html(f"INFO{path}")


def discount_href(discount_id: str) -> str:
    """richart.tw 優惠細則頁的連結（相對路徑，和真實頁面一樣）。"""
    return RICHART_DISCOUNT_FORMAT.format(id=discount_id)


def richart_page_html(label: str, hrefs: list[str]) -> str:
    """產生 richart.tw 的卡片頁：主內容區是 id="main-container"，含優惠細則連結，導覽與頁尾在主內容區外。

    Args:
        label: 放進主內容區的文字，讓各頁內容不同。
        hrefs: 主內容區裡的連結（優惠細則、優惠列表、外部網域的連結等，原樣放進 href）。

    Returns:
        卡片頁的 HTML。
    """
    links = "".join(f'<a class="btn" href="{href}">看優惠詳情</a>' for href in hrefs)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Richart</title>
<script>var RICHART_SCRIPT_TEXT = 1;</script></head>
<body>
<div class="main-header"><ul><li>RICHART-NAV-TEXT</li></ul></div>
<div class="smooth-scroll product" id="main-container">
  <div class="section"><h1>{label}</h1><img src="data:image/png;base64,AAAA">{links}</div>
  <script>var RICHART_INNER_SCRIPT_TEXT = 1;</script>
</div>
<div class="modal fade" id="modalOutside">RICHART-OUTSIDE-MODAL-TEXT</div>
<div class="main-footer">RICHART-FOOTER-TEXT</div>
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
        # richart.tw 也是另一個假 server；預設的兩個卡片頁沒有任何優惠細則連結，案例用 serve_richart 覆蓋
        self.richart_routes: dict[str, tuple[int, bytes]] = {}
        self.richart_server = FakeServer(self.richart_routes)
        self.richart_server.start()
        self.addCleanup(self.richart_server.stop)
        self.list_handlers: dict[str, Callable[[str], tuple[int, bytes] | None]] = {}
        self.server.fallback = self._answer_with_list_handlers
        # 沒有任何子頁的總覽頁與權益頁；案例需要子頁時用 serve_cards、serve_rights 覆蓋
        self.serve_cards({})
        self.serve_rights({})
        self.serve_debit_cards({})
        self.serve_debit_terms([])
        self.serve_debit_info()
        self.serve_richart([], [])
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

    def serve_debit_cards(self, groups: dict[str, str | None], cards: dict[str, str] | None = None) -> None:
        """登記簽帳金融卡專區列表頁、各群組落地頁與各卡片頁。

        Args:
            groups: 群組落地頁路徑對轉址目標（location.replace 的參數）；None 表示落地頁沒有轉址那段 JS。
            cards: 卡片頁路徑對頁面 HTML。
        """
        self.routes[DEBIT_LIST_PATH] = (200, debit_list_html(list(groups)).encode())
        for path, target in groups.items():
            self.routes[path] = (200, debit_landing_html(target).encode())
        for path, html in (cards or {}).items():
            self.routes[path] = (200, html.encode())

    def serve_debit_terms(self, pdf_paths: list[str], extra_hrefs: list[str] | None = None) -> None:
        """登記金融卡約定條款頁與其中的 PDF。

        Args:
            pdf_paths: 條款頁上連到的 PDF 路徑（以相對路徑連結）；每個 PDF 登記一次內容（pdf_bytes）。
            extra_hrefs: 接在 PDF 連結後面的其他連結（例如外部網域的網址）。
        """
        hrefs = [*pdf_paths, *(extra_hrefs or [])]
        self.routes[DEBIT_TERMS_PATH] = (200, debit_terms_html(hrefs).encode())
        for path in pdf_paths:
            self.routes[path] = (200, pdf_bytes(path))

    def serve_debit_info(self, pages: dict[str, str] | None = None) -> None:
        """登記金融卡說明頁的 7 個網址。

        Args:
            pages: 說明頁路徑對頁面 HTML；沒有列出的說明頁用 debit_info_html 的預設內容。
        """
        for path in DEBIT_INFO_PATHS:
            html = (pages or {}).get(path, debit_info_html(path))
            self.routes[path] = (200, html.encode())

    def serve_richart(
        self, debit_hrefs: list[str], credit_hrefs: list[str], discounts: dict[str, str] | None = None
    ) -> None:
        """登記 richart.tw 的簽帳金融卡頁、信用卡頁與各優惠細則頁。

        Args:
            debit_hrefs: 簽帳金融卡頁主內容區裡的連結（原樣放進 href）。
            credit_hrefs: 信用卡頁主內容區裡的連結。
            discounts: 優惠細則的 id 對放進該頁的文字；沒有列出的 id 不登記（請求會得到 404）。
        """
        self.richart_routes[RICHART_DEBIT_PATH] = (200, richart_page_html("RICHART-DEBIT", debit_hrefs).encode())
        self.richart_routes[RICHART_CREDIT_PATH] = (200, richart_page_html("RICHART-CREDIT", credit_hrefs).encode())
        for discount_id, label in (discounts or {}).items():
            self.richart_routes[RICHART_DISCOUNT_FORMAT.format(id=discount_id)] = (
                200,
                richart_page_html(label, []).encode(),
            )

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
            "TAISHIN_RICHART_BASE": self.richart_server.base_url,
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

# 金融卡的群組編號和信用卡卡片頁重複（官網的信用卡也有 cg003、cg008），本地名稱靠 debit_ 前綴區分
DEBIT_VISA_GROUP = DEBIT_GROUP_FORMAT.format(cg="cg001")
DEBIT_VISA = DEBIT_CARD_FORMAT.format(cg="cg001", card="card01")
DEBIT_LABOR_GROUP = DEBIT_GROUP_FORMAT.format(cg="cg006")
DEBIT_LABOR = DEBIT_CARD_FORMAT.format(cg="cg006", card="card001")

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
            sorted(
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
                    *DEBIT_INFO_FILES,
                    *RICHART_DEFAULT_FILES,
                ]
            ),
        )
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertEqual(
            (self.out / "_meta" / "html" / "card_cg047_card001.html").read_bytes(), self.routes[RICHART][1]
        )

    def test_duplicate_links_and_non_card_links_are_fetched_once_or_not_at_all(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.run_script()
        # 總覽頁 1 次；卡片頁 1 次（3 個錨點指向同一頁）；權益連結、申辦連結、總覽頁自己的連結都不下載；權益頁 1 次；下載頁 1 次
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RICHART, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS, DEBIT_LIST_PATH, *DEBIT_DEFAULT_REQUESTS])


class DebitCardPageTests(ScriptTestCase):
    def test_follows_the_landing_page_redirect_to_card01_and_card001_and_prints_each_card(self) -> None:
        self.serve_debit_cards(
            {DEBIT_VISA_GROUP: DEBIT_VISA, DEBIT_LABOR_GROUP: DEBIT_LABOR},
            {DEBIT_VISA: card_html("VISA金融卡"), DEBIT_LABOR: card_html("勞動保障卡")},
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(),
            sorted(
                [
                    "_meta/html/debit_card_cg001_card01.html",
                    "_meta/html/debit_card_cg006_card001.html",
                    "_meta/manifest.jsonl",
                    "_meta/print/debit_card_cg001_card01.html",
                    "_meta/print/debit_card_cg006_card001.html",
                    "debit_cards/debit_card_cg001_card01.pdf",
                    "debit_cards/debit_card_cg006_card001.pdf",
                    *DEBIT_INFO_FILES,
                    *RICHART_DEFAULT_FILES,
                ]
            ),
        )
        self.assertTrue((self.out / "debit_cards" / "debit_card_cg001_card01.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertEqual(
            (self.out / "_meta" / "html" / "debit_card_cg001_card01.html").read_bytes(), self.routes[DEBIT_VISA][1]
        )


class DebitCardRedirectTests(ScriptTestCase):
    def test_relative_and_absolute_redirect_targets_are_resolved_against_the_landing_page(self) -> None:
        group_2 = DEBIT_GROUP_FORMAT.format(cg="cg002")
        group_3 = DEBIT_GROUP_FORMAT.format(cg="cg003")
        card_2 = DEBIT_CARD_FORMAT.format(cg="cg002", card="card01")
        card_3 = DEBIT_CARD_FORMAT.format(cg="cg003", card="card01")
        self.serve_debit_cards(
            {
                DEBIT_VISA_GROUP: "card01/",
                DEBIT_LABOR_GROUP: self.server.base_url + DEBIT_LABOR,
                group_2: card_2,
                group_3: f"{self.server.base_url}{card_3}#tab2",
            },
            {
                DEBIT_VISA: card_html("VISA"),
                DEBIT_LABOR: card_html("LABOR"),
                card_2: card_html("GENKI"),
                card_3: card_html("WEALTH"),
            },
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "debit_cards").iterdir()),
            [
                "debit_card_cg001_card01.pdf",
                "debit_card_cg002_card01.pdf",
                "debit_card_cg003_card01.pdf",
                "debit_card_cg006_card001.pdf",
            ],
        )
        self.assertEqual(self.server.paths().count(card_3), 1, "fragment 不送出，而且只請求一次")

    def test_redirect_target_outside_the_official_domain_is_a_failed_card_and_is_not_requested(self) -> None:
        self.serve_debit_cards(
            {DEBIT_VISA_GROUP: DEBIT_VISA, DEBIT_LABOR_GROUP: "http://example.invalid" + DEBIT_LABOR},
            {DEBIT_VISA: card_html("VISA"), DEBIT_LABOR: card_html("LABOR")},
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "debit_cards").iterdir()], ["debit_card_cg001_card01.pdf"])
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual([r["url"] for r in failed], [self.server.base_url + DEBIT_LABOR_GROUP])
        self.assertIn("找不到轉址目標", failed[0]["detail"])
        self.assertIn("example.invalid", failed[0]["detail"])
        self.assertIn(self.server.base_url + DEBIT_LABOR_GROUP, result.stderr)
        self.assertNotIn(DEBIT_LABOR, self.server.paths())

    def test_redirect_target_outside_the_same_group_is_a_failed_card_and_is_not_requested(self) -> None:
        other_group_card = DEBIT_CARD_FORMAT.format(cg="cg002", card="card01")
        not_a_card = "/TSB/personal/credit/intro/payment/notice/TSBankGridPage-000999/"
        too_deep = DEBIT_VISA + "tab/"
        group_2 = DEBIT_GROUP_FORMAT.format(cg="cg002")
        group_3 = DEBIT_GROUP_FORMAT.format(cg="cg003")
        group_4 = DEBIT_GROUP_FORMAT.format(cg="cg004")
        group_5 = DEBIT_GROUP_FORMAT.format(cg="cg005")
        self.serve_debit_cards(
            {
                DEBIT_VISA_GROUP: other_group_card,
                group_2: not_a_card,
                group_3: "../../overview/cg003/card01/",
                group_4: "javascript:void(0)",
                group_5: too_deep,
            },
            {
                other_group_card: card_html("OTHER"),
                not_a_card: card_html("NOTICE"),
                "/TSB/personal/credit/intro/overview/cg003/card01/": card_html("CREDIT"),
                too_deep: card_html("DEEP"),
            },
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((self.out / "debit_cards").exists() and list((self.out / "debit_cards").iterdir()))
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual(len(failed), 5)
        for record in failed:
            self.assertIn("找不到轉址目標", record["detail"])
        for path in (other_group_card, not_a_card, "/TSB/personal/credit/intro/overview/cg003/card01/", too_deep):
            self.assertNotIn(path, self.server.paths())

    def test_landing_page_without_a_redirect_is_a_failed_card_and_the_other_cards_continue(self) -> None:
        self.serve_debit_cards(
            {DEBIT_VISA_GROUP: None, DEBIT_LABOR_GROUP: DEBIT_LABOR},
            {DEBIT_LABOR: card_html("LABOR")},
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "debit_cards").iterdir()], ["debit_card_cg006_card001.pdf"])
        records = {r["filename"]: r for r in self.manifest() if r["category"] == "金融卡卡片頁"}
        failed = records["debit_card_cg001"]
        self.assertEqual(failed["result"], "失敗")
        self.assertEqual(failed["url"], self.server.base_url + DEBIT_VISA_GROUP)
        self.assertIn("找不到轉址目標", failed["detail"])
        self.assertEqual(records["debit_card_cg006_card001.pdf"]["result"], "已下載")
        self.assertIn(f"FAILED {self.server.base_url + DEBIT_VISA_GROUP}", result.stderr)

    def test_landing_page_request_failure_is_a_failed_card_and_the_other_cards_continue(self) -> None:
        self.serve_debit_cards(
            {DEBIT_VISA_GROUP: DEBIT_VISA, DEBIT_LABOR_GROUP: DEBIT_LABOR},
            {DEBIT_VISA: card_html("VISA"), DEBIT_LABOR: card_html("LABOR")},
        )
        del self.routes[DEBIT_LABOR_GROUP]
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "debit_cards").iterdir()], ["debit_card_cg001_card01.pdf"])
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual([r["filename"] for r in failed], ["debit_card_cg006"])
        self.assertIn("404", failed[0]["detail"])

    def test_list_page_failure_exits_nonzero_names_the_list_and_keeps_the_other_categories(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        del self.routes[DEBIT_LIST_PATH]
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("簽帳金融卡專區", result.stderr)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())

    def test_chrome_receives_the_card_page_main_content_only(self) -> None:
        self.serve_debit_cards({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA金融卡")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        printed = (self.out / "_meta" / "print" / "debit_card_cg001_card01.html").read_text(encoding="utf-8")
        self.assertIn("VISA金融卡", printed)
        self.assertIn("COLLAPSED-TEXT", printed)
        self.assertNotIn("NAV-MENU-TEXT", printed)
        self.assertNotIn("INNER_SCRIPT_TEXT", printed)


class DebitCardNamingTests(ScriptTestCase):
    def test_debit_and_credit_card_pages_with_the_same_group_and_card_number_do_not_overwrite_each_other(self) -> None:
        credit = CARD_PATH_FORMAT.format(cg="cg001", card="card01")
        self.serve_cards({credit: card_html("CREDIT-CG001")})
        self.serve_debit_cards({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("DEBIT-CG001")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(),
            sorted(
                [
                    "_meta/html/card_cg001_card01.html",
                    "_meta/html/debit_card_cg001_card01.html",
                    "_meta/manifest.jsonl",
                    "_meta/print/card_cg001_card01.html",
                    "_meta/print/debit_card_cg001_card01.html",
                    "cards/card_cg001_card01.pdf",
                    "debit_cards/debit_card_cg001_card01.pdf",
                    *DEBIT_INFO_FILES,
                    *RICHART_DEFAULT_FILES,
                ]
            ),
        )
        credit_raw = (self.out / "_meta" / "html" / "card_cg001_card01.html").read_text(encoding="utf-8")
        debit_raw = (self.out / "_meta" / "html" / "debit_card_cg001_card01.html").read_text(encoding="utf-8")
        self.assertIn("CREDIT-CG001", credit_raw)
        self.assertIn("DEBIT-CG001", debit_raw)

    def test_manifest_records_url_category_format_hashes_and_date_like_the_credit_card_pages(self) -> None:
        self.serve_debit_cards({DEBIT_LABOR_GROUP: DEBIT_LABOR}, {DEBIT_LABOR: card_html("LABOR")})
        self.assertEqual(self.run_script().returncode, 0)
        [record] = [r for r in self.manifest() if r["category"] == "金融卡卡片頁"]
        pdf = (self.out / "debit_cards" / "debit_card_cg006_card001.pdf").read_bytes()
        self.assertEqual(record["url"], self.server.base_url + DEBIT_LABOR)
        self.assertEqual(record["filename"], "debit_card_cg006_card001.pdf")
        self.assertEqual(record["format"], "PDF")
        self.assertEqual(record["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(record["sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertEqual(record["html_sha256"], hashlib.sha256(self.routes[DEBIT_LABOR][1]).hexdigest())
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(record["period"], "")

    def test_rerun_without_update_skips_existing_cards_and_does_not_request_the_card_pages(self) -> None:
        self.serve_debit_cards({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA")})
        self.assertEqual(self.run_script().returncode, 0)
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.server.paths().count(DEBIT_VISA), 0)
        [record] = [r for r in self.manifest() if r["category"] == "金融卡卡片頁"]
        self.assertEqual(record["result"], "已存在略過")

    def test_requests_keep_the_minimum_interval(self) -> None:
        self.serve_debit_cards(
            {DEBIT_VISA_GROUP: DEBIT_VISA, DEBIT_LABOR_GROUP: DEBIT_LABOR},
            {DEBIT_VISA: card_html("VISA"), DEBIT_LABOR: card_html("LABOR")},
        )
        result = self.run_script(interval="0.3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        times = [t for path, t, _ua in self.server.requests if path.startswith(DEBIT_LIST_PATH)]
        self.assertEqual(len(times), 10, "專區列表頁 1 次、落地頁 2 次、卡片頁 2 次、約定條款頁 1 次、payment/notice/ 的說明頁 4 次")
        self.assertTrue(all(b - a >= 0.28 for a, b in zip(times, times[1:])), times)


class DebitCardUpdateModeTests(ScriptTestCase):
    def first_download(self, cards: dict[str, str | None], pages: dict[str, str]) -> None:
        """第一次下載（不開更新模式），把每份金融卡文件的修改時間設成很久以前，清掉請求紀錄。"""
        self.serve_debit_cards(cards, pages)
        self.assertEqual(self.run_script().returncode, 0)
        for file in (self.out / "debit_cards").iterdir():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.server.requests.clear()

    def removed_dir(self) -> Path:
        """今天的下架資料夾 DIR/_meta/removed/<日期>/。"""
        return self.out / "_meta" / "removed" / date.today().isoformat()

    def records(self) -> dict[str, dict[str, str]]:
        """下載清單中金融卡卡片頁的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "金融卡卡片頁"}

    def test_card_page_whose_main_content_is_the_same_is_not_converted_and_nothing_is_touched(self) -> None:
        self.first_download({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: with_csrf(card_html("VISA"), "token-1")})
        document = self.out / "debit_cards" / "debit_card_cg001_card01.pdf"
        raw_path = self.out / "_meta" / "html" / "debit_card_cg001_card01.html"
        print_path = self.out / "_meta" / "print" / "debit_card_cg001_card01.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path, print_path)}
        self.serve_debit_cards({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: with_csrf(card_html("VISA"), "token-2")})
        empty_path = self.tmp / "empty_path"
        empty_path.mkdir()
        result = self.run_update(chrome=str(self.tmp / "no-such-chrome"), path=str(empty_path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(DEBIT_VISA, self.server.paths(), "更新模式要重新取得原始 HTML 來比對")
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        self.assertEqual(self.records()["debit_card_cg001_card01.pdf"]["result"], "未變")
        self.assertIn("金融卡卡片頁：未變 1", result.stdout)

    def test_card_page_whose_main_content_changed_is_converted_again(self) -> None:
        self.first_download({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA-OLD")})
        before = (self.out / "debit_cards" / "debit_card_cg001_card01.pdf").read_bytes()
        self.serve_debit_cards({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA-NEW")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual((self.out / "debit_cards" / "debit_card_cg001_card01.pdf").read_bytes(), before)
        raw = (self.out / "_meta" / "html" / "debit_card_cg001_card01.html").read_text(encoding="utf-8")
        self.assertIn("VISA-NEW", raw)
        self.assertEqual(self.records()["debit_card_cg001_card01.pdf"]["result"], "內容變更")

    def test_card_missing_from_the_list_is_moved_with_its_html_and_recorded_as_removed(self) -> None:
        self.first_download(
            {DEBIT_VISA_GROUP: DEBIT_VISA, DEBIT_LABOR_GROUP: DEBIT_LABOR},
            {DEBIT_VISA: card_html("VISA"), DEBIT_LABOR: card_html("LABOR")},
        )
        pdf_before = (self.out / "debit_cards" / "debit_card_cg006_card001.pdf").read_bytes()
        self.serve_debit_cards({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        removed = self.removed_dir()
        self.assertFalse((self.out / "debit_cards" / "debit_card_cg006_card001.pdf").exists())
        self.assertFalse((self.out / "_meta" / "html" / "debit_card_cg006_card001.html").exists())
        self.assertEqual((removed / "debit_cards" / "debit_card_cg006_card001.pdf").read_bytes(), pdf_before)
        self.assertTrue((removed / "html" / "debit_card_cg006_card001.html").is_file())
        self.assertTrue((removed / "print" / "debit_card_cg006_card001.html").is_file())
        self.assertTrue((self.out / "debit_cards" / "debit_card_cg001_card01.pdf").is_file())
        self.assertEqual(self.records()["debit_card_cg006_card001.pdf"]["result"], "下架")
        self.assertIn("金融卡卡片頁：未變 1、下架 1", result.stdout)

    def test_credit_card_pages_are_not_judged_against_the_debit_list(self) -> None:
        credit = CARD_PATH_FORMAT.format(cg="cg001", card="card01")
        self.serve_cards({credit: card_html("CREDIT")})
        self.first_download({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.out / "cards" / "card_cg001_card01.pdf").is_file())
        self.assertTrue((self.out / "debit_cards" / "debit_card_cg001_card01.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_list_that_parses_to_zero_cards_while_local_has_documents_does_not_judge_removal(self) -> None:
        self.first_download({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA")})
        self.serve_debit_cards({})
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for text in ("簽帳金融卡專區", "0 筆", "不搬任何檔案"):
            self.assertIn(text, result.stderr)
        self.assertTrue((self.out / "debit_cards" / "debit_card_cg001_card01.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_card_without_a_redirect_target_blocks_removal_for_the_whole_category(self) -> None:
        group_2 = DEBIT_GROUP_FORMAT.format(cg="cg002")
        card_2 = DEBIT_CARD_FORMAT.format(cg="cg002", card="card01")
        pages = {DEBIT_VISA: card_html("VISA"), card_2: card_html("GENKI"), DEBIT_LABOR: card_html("LABOR")}
        self.first_download({DEBIT_VISA_GROUP: DEBIT_VISA, group_2: card_2, DEBIT_LABOR_GROUP: DEBIT_LABOR}, pages)
        # cg001 的落地頁這次沒有轉址；cg006 從列表消失（本來會被當成下架）；cg002 正常，所以列表不是 0 筆
        self.serve_debit_cards({DEBIT_VISA_GROUP: None, group_2: card_2}, pages)
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "debit_cards").iterdir()),
            ["debit_card_cg001_card01.pdf", "debit_card_cg002_card01.pdf", "debit_card_cg006_card001.pdf"],
        )
        self.assertFalse((self.out / "_meta" / "removed").exists())
        self.assertIn("不搬任何檔案", result.stderr)
        self.assertIn(self.server.base_url + DEBIT_VISA_GROUP, result.stderr)
        self.assertNotIn("下架", [r["result"] for r in self.manifest()])

    def test_card_whose_landing_page_request_failed_is_not_moved(self) -> None:
        self.first_download(
            {DEBIT_VISA_GROUP: DEBIT_VISA, DEBIT_LABOR_GROUP: DEBIT_LABOR},
            {DEBIT_VISA: card_html("VISA"), DEBIT_LABOR: card_html("LABOR")},
        )
        del self.routes[DEBIT_VISA_GROUP]
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.out / "debit_cards" / "debit_card_cg001_card01.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_redirect_target_changing_from_card01_to_card001_moves_the_old_name_and_adds_the_new_one(self) -> None:
        self.first_download({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA")})
        new_target = DEBIT_CARD_FORMAT.format(cg="cg001", card="card001")
        self.serve_debit_cards({DEBIT_VISA_GROUP: new_target}, {new_target: card_html("VISA")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "debit_cards").iterdir()], ["debit_card_cg001_card001.pdf"])
        self.assertTrue((self.removed_dir() / "debit_cards" / "debit_card_cg001_card01.pdf").is_file())
        results = {name: r["result"] for name, r in self.records().items()}
        self.assertEqual(results, {"debit_card_cg001_card001.pdf": "已下載", "debit_card_cg001_card01.pdf": "下架"})


DEBIT_TERM_PDF = "/TSB/export/sites/TSB/personal/credit/intro/payment/notice/_11504.pdf"
DEBIT_TERM_PDF_2 = "/TSB/export/sites/TSB/files/creditcard/Debit-11312.pdf"
EASYCARD_TERM = "https://www.easycard.invalid/term"


class DebitTermsTests(ScriptTestCase):
    def test_saves_the_pdfs_the_terms_page_links_to_as_is_and_skips_the_external_link(self) -> None:
        self.serve_debit_terms([DEBIT_TERM_PDF, DEBIT_TERM_PDF_2], [EASYCARD_TERM])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "debit_terms").iterdir()),
            ["debit_term_Debit-11312.pdf", "debit_term__11504.pdf"],
        )
        for path, name in ((DEBIT_TERM_PDF, "debit_term__11504.pdf"), (DEBIT_TERM_PDF_2, "debit_term_Debit-11312.pdf")):
            self.assertEqual((self.out / "debit_terms" / name).read_bytes(), pdf_bytes(path))
        self.assertIn(DEBIT_TERM_PDF, self.server.paths())
        self.assertFalse([p for p in self.server.paths() if "easycard" in p])


    def test_terms_page_itself_is_not_saved_as_a_document(self) -> None:
        self.serve_debit_terms([DEBIT_TERM_PDF])
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual([f for f in self.files_under_out() if "000003" in f], [])
        self.assertEqual([r["filename"] for r in self.manifest() if r["category"] == "金融卡約定條款 PDF"], ["debit_term__11504.pdf"])

    def test_manifest_records_url_category_format_hash_and_date_like_the_download_area(self) -> None:
        self.serve_debit_terms([DEBIT_TERM_PDF])
        self.assertEqual(self.run_script().returncode, 0)
        [record] = [r for r in self.manifest() if r["category"] == "金融卡約定條款 PDF"]
        self.assertEqual(record["url"], self.server.base_url + DEBIT_TERM_PDF)
        self.assertEqual(record["filename"], "debit_term__11504.pdf")
        self.assertEqual(record["format"], "PDF")
        self.assertEqual(record["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(record["sha256"], hashlib.sha256(pdf_bytes(DEBIT_TERM_PDF)).hexdigest())
        self.assertEqual(record["html_sha256"], "")
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(record["period"], "")

    def test_pdf_with_the_same_stem_as_a_download_area_pdf_does_not_overwrite_it(self) -> None:
        same_stem = FILES_DIR + "_11504.pdf"
        self.serve_downloads([[same_stem]])
        self.serve_debit_terms([DEBIT_TERM_PDF])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.out / "downloads" / "download__11504.pdf").read_bytes(), pdf_bytes(same_stem))
        self.assertEqual((self.out / "debit_terms" / "debit_term__11504.pdf").read_bytes(), pdf_bytes(DEBIT_TERM_PDF))

    def test_two_pdfs_with_the_same_stem_in_different_folders_both_survive_with_a_hash_suffix(self) -> None:
        other = FILES_DIR + "_11504.pdf"
        self.serve_debit_terms([DEBIT_TERM_PDF, other])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        files = sorted((self.out / "debit_terms").iterdir())
        self.assertEqual(len(files), 2)
        self.assertEqual(sorted(f.read_bytes() for f in files), sorted([pdf_bytes(DEBIT_TERM_PDF), pdf_bytes(other)]))
        self.assertTrue(all(re.fullmatch(r"debit_term__11504_[0-9a-f]{8}\.pdf", f.name) for f in files), files)

    def test_terms_page_request_failure_is_reported_and_the_other_categories_continue(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.routes[DEBIT_TERMS_PATH] = (500, b"boom")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("金融卡約定條款", result.stderr)
        self.assertIn(self.server.base_url + DEBIT_TERMS_PATH, result.stderr)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())
        self.assertFalse((self.out / "debit_terms").exists())

    def test_a_link_that_does_not_return_a_pdf_fails_only_that_file(self) -> None:
        self.serve_debit_terms([DEBIT_TERM_PDF, DEBIT_TERM_PDF_2])
        self.routes[DEBIT_TERM_PDF] = (200, b"<html>error</html>")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("debit_term__11504.pdf", result.stderr)
        self.assertEqual([p.name for p in (self.out / "debit_terms").iterdir()], ["debit_term_Debit-11312.pdf"])
        results = {r["filename"]: r["result"] for r in self.manifest() if r["category"] == "金融卡約定條款 PDF"}
        self.assertEqual(results, {"debit_term__11504.pdf": "失敗", "debit_term_Debit-11312.pdf": "已下載"})

    def test_rerun_without_update_skips_existing_pdfs_and_does_not_download_them_again(self) -> None:
        self.serve_debit_terms([DEBIT_TERM_PDF])
        self.assertEqual(self.run_script().returncode, 0)
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(DEBIT_TERM_PDF, self.server.paths())
        [record] = [r for r in self.manifest() if r["category"] == "金融卡約定條款 PDF"]
        self.assertEqual(record["result"], "已存在略過")


class DebitTermsUpdateModeTests(ScriptTestCase):
    def first_download(self, pdf_paths: list[str]) -> dict[str, Path]:
        """第一次下載（不開更新模式），把每份約定條款 PDF 的修改時間設成很久以前，清掉請求紀錄。

        Args:
            pdf_paths: 約定條款頁上連到的 PDF 路徑。

        Returns:
            PDF 路徑對本地檔案。
        """
        self.serve_debit_terms(pdf_paths)
        self.assertEqual(self.run_script().returncode, 0)
        saved = {path: self.out / "debit_terms" / f"debit_term_{path.rsplit('/', 1)[1][:-4]}.pdf" for path in pdf_paths}
        for file in saved.values():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.server.requests.clear()
        return saved

    def records(self) -> dict[str, dict[str, str]]:
        """下載清單中金融卡約定條款 PDF 的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "金融卡約定條款 PDF"}

    def removed_dir(self) -> Path:
        """今天的下架資料夾 DIR/_meta/removed/<日期>/。"""
        return self.out / "_meta" / "removed" / date.today().isoformat()

    def test_pdf_with_the_same_content_keeps_its_bytes_and_modification_time(self) -> None:
        saved = self.first_download([DEBIT_TERM_PDF])
        before = saved[DEBIT_TERM_PDF].read_bytes()
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(saved[DEBIT_TERM_PDF].read_bytes(), before)
        self.assertEqual(saved[DEBIT_TERM_PDF].stat().st_mtime_ns, OLD_MTIME_NS)
        self.assertIn(DEBIT_TERM_PDF, self.server.paths(), "更新模式要重新下載來比對")
        self.assertEqual(self.records()["debit_term__11504.pdf"]["result"], "未變")
        self.assertIn("金融卡約定條款 PDF：未變 1", result.stdout)

    def test_pdf_with_new_content_replaces_the_file_and_is_recorded_as_changed(self) -> None:
        saved = self.first_download([DEBIT_TERM_PDF, DEBIT_TERM_PDF_2])
        new_content = pdf_bytes(DEBIT_TERM_PDF) + b"revised\n"
        self.routes[DEBIT_TERM_PDF] = (200, new_content)
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(saved[DEBIT_TERM_PDF].read_bytes(), new_content)
        self.assertEqual(saved[DEBIT_TERM_PDF_2].stat().st_mtime_ns, OLD_MTIME_NS)
        records = self.records()
        self.assertEqual(records["debit_term__11504.pdf"]["result"], "內容變更")
        self.assertEqual(records["debit_term__11504.pdf"]["sha256"], hashlib.sha256(new_content).hexdigest())
        self.assertEqual(records["debit_term_Debit-11312.pdf"]["result"], "未變")

    def test_pdf_the_terms_page_no_longer_links_to_is_moved_to_removed_and_recorded(self) -> None:
        saved = self.first_download([DEBIT_TERM_PDF, DEBIT_TERM_PDF_2])
        before = saved[DEBIT_TERM_PDF_2].read_bytes()
        self.serve_debit_terms([DEBIT_TERM_PDF])
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(saved[DEBIT_TERM_PDF_2].exists())
        self.assertEqual((self.removed_dir() / "debit_terms" / "debit_term_Debit-11312.pdf").read_bytes(), before)
        self.assertTrue(saved[DEBIT_TERM_PDF].is_file())
        self.assertEqual(self.records()["debit_term_Debit-11312.pdf"]["result"], "下架")
        self.assertIn("金融卡約定條款 PDF：未變 1、下架 1", result.stdout)

    def test_failed_terms_page_does_not_judge_removal(self) -> None:
        saved = self.first_download([DEBIT_TERM_PDF])
        self.routes[DEBIT_TERMS_PATH] = (500, b"boom")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("金融卡約定條款", result.stderr)
        self.assertIn("不搬任何檔案", result.stderr)
        self.assertTrue(saved[DEBIT_TERM_PDF].is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_terms_page_that_parses_to_zero_pdfs_while_local_has_files_does_not_judge_removal(self) -> None:
        saved = self.first_download([DEBIT_TERM_PDF])
        self.serve_debit_terms([])
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for text in ("金融卡約定條款", "0 筆", "不搬任何檔案"):
            self.assertIn(text, result.stderr)
        self.assertTrue(saved[DEBIT_TERM_PDF].is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_download_area_pdfs_are_not_judged_against_the_terms_page(self) -> None:
        self.serve_downloads([[APPLICATION]])
        self.first_download([DEBIT_TERM_PDF])
        self.serve_debit_terms([DEBIT_TERM_PDF])
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.out / "downloads" / "download_word_CR04131_1150B.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())


class DebitInfoTests(ScriptTestCase):
    def info_files(self, folder: str) -> list[str]:
        """self.out 底下某個資料夾的檔名（排序）。"""
        return sorted(p.name for p in (self.out / folder).iterdir())

    def test_prints_the_main_content_of_each_of_the_seven_pages_to_debit_info(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.info_files("debit_info"), sorted(f"{name}.pdf" for name in DEBIT_INFO_NAMES))
        richart_pages = ["richart_credit-card.html", "richart_debit-card.html"]
        self.assertEqual(
            self.info_files("_meta/html"), sorted([f"{name}.html" for name in DEBIT_INFO_NAMES] + richart_pages)
        )
        self.assertEqual(
            self.info_files("_meta/print"), sorted([f"{name}.html" for name in DEBIT_INFO_NAMES] + richart_pages)
        )
        for path in DEBIT_INFO_PATHS:
            self.assertIn(path, self.server.paths())
        for path, name in zip(DEBIT_INFO_PATHS, DEBIT_INFO_NAMES):
            received = (self.out / "debit_info" / f"{name}.pdf").read_text(encoding="utf-8", errors="replace")
            self.assertIn(f"INFO{path}", received)
            self.assertIn("COLLAPSED-TEXT", received)
            for text in ("NAV-MENU-TEXT", "FOOTER-TEXT", "SITE_SCRIPT_TEXT"):
                self.assertNotIn(text, received)
            self.assertEqual((self.out / "_meta" / "html" / f"{name}.html").read_bytes(), self.routes[path][1])

    def test_manifest_records_url_category_format_hashes_and_date_like_the_card_pages(self) -> None:
        self.assertEqual(self.run_script().returncode, 0)
        records = {r["filename"]: r for r in self.manifest() if r["category"] == "金融卡說明頁"}
        self.assertEqual(sorted(records), sorted(f"{name}.pdf" for name in DEBIT_INFO_NAMES))
        record = records["debit_info_card-list.pdf"]
        pdf = (self.out / "debit_info" / "debit_info_card-list.pdf").read_bytes()
        card_list = DEBIT_DEPOSIT_PREFIX + "card-list/"
        self.assertEqual(record["url"], self.server.base_url + card_list)
        self.assertEqual(record["format"], "PDF")
        self.assertEqual(record["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(record["sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertEqual(record["html_sha256"], hashlib.sha256(self.routes[card_list][1]).hexdigest())
        self.assertEqual(record["result"], "已下載")
        self.assertEqual(record["period"], "")

    def test_page_without_a_main_content_area_fails_and_the_others_are_converted(self) -> None:
        self.serve_debit_info({DEBIT_INFO_PATHS[2]: card_html_without_main_content()})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("debit_info_TSBankGridPage-000340.pdf", result.stderr)
        self.assertIn("找不到主內容區", result.stderr)
        self.assertEqual(
            self.info_files("debit_info"),
            sorted(f"{name}.pdf" for name in DEBIT_INFO_NAMES if name != "debit_info_TSBankGridPage-000340"),
        )
        results = {r["filename"]: r["result"] for r in self.manifest() if r["category"] == "金融卡說明頁"}
        self.assertEqual(results["debit_info_TSBankGridPage-000340.pdf"], "失敗")
        self.assertEqual(list(results.values()).count("已下載"), 6)

    def test_page_whose_request_failed_is_recorded_as_failed_and_the_others_are_converted(self) -> None:
        del self.routes[DEBIT_INFO_PATHS[4]]
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(self.server.base_url + DEBIT_INFO_PATHS[4], result.stderr)
        self.assertEqual(
            self.info_files("debit_info"),
            sorted(f"{name}.pdf" for name in DEBIT_INFO_NAMES if name != "debit_info_debit-card"),
        )

    def test_rerun_without_update_skips_existing_pages_and_does_not_request_them_again(self) -> None:
        self.assertEqual(self.run_script().returncode, 0)
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in DEBIT_INFO_PATHS:
            self.assertNotIn(path, self.server.paths())
        results = {r["result"] for r in self.manifest() if r["category"] == "金融卡說明頁"}
        self.assertEqual(results, {"已存在略過"})

    def test_names_do_not_collide_with_the_documents_of_the_other_categories(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_debit_cards({DEBIT_VISA_GROUP: DEBIT_VISA}, {DEBIT_VISA: card_html("VISA")})
        self.serve_debit_terms([DEBIT_TERM_PDF])
        self.serve_downloads([[APPLICATION]])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        filenames = [r["filename"] for r in self.manifest()]
        self.assertEqual(len(filenames), len(set(filenames)), filenames)
        self.assertEqual(
            self.info_files("_meta/html"),
            sorted(
                [f"{name}.html" for name in DEBIT_INFO_NAMES]
                + ["card_cg047_card001.html", "debit_card_cg001_card01.html"]
                + ["richart_credit-card.html", "richart_debit-card.html"]
            ),
        )


class DebitInfoUpdateModeTests(ScriptTestCase):
    def first_download(self, pages: dict[str, str] | None = None) -> None:
        """第一次下載（不開更新模式），把每份說明頁文件的修改時間設成很久以前，清掉請求紀錄。"""
        self.serve_debit_info(pages)
        self.assertEqual(self.run_script().returncode, 0)
        for file in (self.out / "debit_info").iterdir():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.server.requests.clear()

    def records(self) -> dict[str, dict[str, str]]:
        """下載清單中金融卡說明頁的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "金融卡說明頁"}

    def test_page_whose_main_content_is_the_same_is_not_converted_and_nothing_is_touched(self) -> None:
        page = DEBIT_INFO_PATHS[0]
        self.first_download({page: with_csrf(debit_info_html(page), "token-1")})
        document = self.out / "debit_info" / "debit_info_TSBankGridPage-000004.pdf"
        raw_path = self.out / "_meta" / "html" / "debit_info_TSBankGridPage-000004.html"
        print_path = self.out / "_meta" / "print" / "debit_info_TSBankGridPage-000004.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path, print_path)}
        self.serve_debit_info({page: with_csrf(debit_info_html(page), "token-2")})
        empty_path = self.tmp / "empty_path"
        empty_path.mkdir()
        result = self.run_update(chrome=str(self.tmp / "no-such-chrome"), path=str(empty_path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(page, self.server.paths(), "更新模式要重新取得原始 HTML 來比對")
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        self.assertEqual(self.records()["debit_info_TSBankGridPage-000004.pdf"]["result"], "未變")
        self.assertIn("金融卡說明頁：未變 7", result.stdout)

    def test_page_whose_main_content_changed_is_converted_again(self) -> None:
        self.first_download()
        before = (self.out / "debit_info" / "debit_info_card-list.pdf").read_bytes()
        self.serve_debit_info({DEBIT_INFO_PATHS[5]: card_html("CARD-LIST-NEW")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual((self.out / "debit_info" / "debit_info_card-list.pdf").read_bytes(), before)
        raw = (self.out / "_meta" / "html" / "debit_info_card-list.html").read_text(encoding="utf-8")
        self.assertIn("CARD-LIST-NEW", raw)
        results = {name: r["result"] for name, r in self.records().items()}
        self.assertEqual(results.pop("debit_info_card-list.pdf"), "內容變更")
        self.assertEqual(set(results.values()), {"未變"})

    def test_page_that_cannot_be_fetched_keeps_the_local_file_and_is_not_moved(self) -> None:
        self.first_download()
        document = self.out / "debit_info" / "debit_info_TSBankGridPage-000001.pdf"
        raw_path = self.out / "_meta" / "html" / "debit_info_TSBankGridPage-000001.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path)}
        self.routes[DEBIT_INFO_PATHS[1]] = (500, b"boom")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        self.assertEqual(self.records()["debit_info_TSBankGridPage-000001.pdf"]["result"], "失敗")
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_page_that_lost_its_main_content_area_keeps_the_local_file(self) -> None:
        self.first_download()
        document = self.out / "debit_info" / "debit_info_debit-card.pdf"
        before = (document.read_bytes(), document.stat().st_mtime_ns)
        self.serve_debit_info({DEBIT_INFO_PATHS[4]: card_html_without_main_content()})
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((document.read_bytes(), document.stat().st_mtime_ns), before)
        self.assertEqual(self.records()["debit_info_debit-card.pdf"]["result"], "失敗")

    def test_local_files_that_are_not_one_of_the_seven_pages_are_not_judged_as_removed(self) -> None:
        self.first_download()
        stray = self.out / "debit_info" / "debit_info_old-page.pdf"
        stray.write_bytes(b"%PDF-1.4 stray")
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(stray.is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())
        self.assertNotIn("debit_info_old-page.pdf", self.records())



class RichartCardPageTests(ScriptTestCase):
    def test_prints_the_debit_card_page_and_the_credit_card_page_under_fixed_names(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(), sorted(["_meta/manifest.jsonl", *DEBIT_INFO_FILES, *RICHART_DEFAULT_FILES])
        )
        self.assertTrue((self.out / "richart" / "richart_debit-card.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertEqual(
            (self.out / "_meta" / "html" / "richart_credit-card.html").read_bytes(),
            self.richart_routes[RICHART_CREDIT_PATH][1],
        )

    def test_chrome_gets_the_main_container_only_with_the_page_url_as_base(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 假 Chrome 的輸出檔 = 假 PDF 檔頭 + 收到的 HTML
        received = (self.out / "richart" / "richart_debit-card.pdf").read_text(encoding="utf-8", errors="replace")
        self.assertIn("RICHART-DEBIT", received)
        self.assertIn('<img src="data:image/png;base64,AAAA">', received)
        for text in ("RICHART_SCRIPT_TEXT", "RICHART_INNER_SCRIPT_TEXT", "RICHART-NAV-TEXT", "RICHART-OUTSIDE-MODAL-TEXT", "RICHART-FOOTER-TEXT"):
            self.assertNotIn(text, received)
        self.assertIn(f'<base href="{self.richart_server.base_url}{RICHART_DEBIT_PATH}">', received)

    def test_page_without_the_main_container_is_a_failure_and_the_other_page_is_still_downloaded(self) -> None:
        self.richart_routes[RICHART_CREDIT_PATH] = (200, card_html_without_main_content().encode())
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        records = {r["filename"]: r for r in self.manifest() if r["category"] == "Richart 卡片頁"}
        self.assertEqual(records["richart_credit-card.pdf"]["result"], "失敗")
        self.assertIn("找不到主內容區", records["richart_credit-card.pdf"]["detail"])
        self.assertEqual(records["richart_debit-card.pdf"]["result"], "已下載")
        self.assertFalse((self.out / "richart" / "richart_credit-card.pdf").exists())

    def test_requests_go_to_the_richart_base_and_not_to_the_taishin_servers(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.richart_server.paths(), [RICHART_DEBIT_PATH, RICHART_CREDIT_PATH, RICHART_DEBIT_PATH, RICHART_CREDIT_PATH]
        )
        self.assertFalse([p for p in self.server.paths() if "RichartWeb" in p])
        self.assertFalse([p for p in self.mkp_server.paths() if "RichartWeb" in p])
        for _path, _time, user_agent in self.richart_server.requests:
            self.assertTrue(user_agent.startswith("llm-lab-fetch-taishin/"), user_agent)

    def test_richart_requests_are_spaced_by_at_least_the_configured_interval(self) -> None:
        self.serve_richart([discount_href("277")], [], {"277": "D277"})
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        times = [t for _path, t, _ua in self.richart_server.requests]
        self.assertEqual(len(times), 5)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, interval - 0.02)

    def test_redirect_to_another_domain_is_not_followed_and_fails_that_page(self) -> None:
        outside = urlparse(self.mkp_server.base_url).netloc
        self.richart_server.redirects[RICHART_CREDIT_PATH] = self.mkp_server.base_url + "/outside/page"
        self.mkp_routes["/outside/page"] = (200, richart_page_html("OUTSIDE", []).encode())
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.mkp_server.paths(), [], "外部網域不該收到請求")
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertTrue(failed)
        for record in failed:
            self.assertIn(f"轉址到外部網域 {outside}", record["detail"])
        self.assertFalse((self.out / "richart" / "richart_credit-card.pdf").exists())
        self.assertTrue((self.out / "richart" / "richart_debit-card.pdf").is_file())

    def test_rerun_without_update_skips_existing_card_pages_without_requesting_them_for_download(self) -> None:
        self.assertEqual(self.run_script().returncode, 0)
        pdf = self.out / "richart" / "richart_debit-card.pdf"
        os.utime(pdf, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.richart_server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(pdf.stat().st_mtime_ns, OLD_MTIME_NS)
        # 只剩收集優惠細則連結的那兩次請求
        self.assertEqual(self.richart_server.paths(), [RICHART_DEBIT_PATH, RICHART_CREDIT_PATH])
        results = {r["filename"]: r["result"] for r in self.manifest() if r["category"] == "Richart 卡片頁"}
        self.assertEqual(results, {"richart_debit-card.pdf": "已存在略過", "richart_credit-card.pdf": "已存在略過"})

    def test_card_page_that_cannot_be_fetched_leaves_the_local_file_alone_in_update_mode(self) -> None:
        self.assertEqual(self.run_script().returncode, 0)
        pdf = self.out / "richart" / "richart_debit-card.pdf"
        before = (pdf.read_bytes(), pdf.stat().st_mtime_ns)
        del self.richart_routes[RICHART_DEBIT_PATH]
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((pdf.read_bytes(), pdf.stat().st_mtime_ns), before)
        self.assertTrue((self.out / "_meta" / "html" / "richart_debit-card.html").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())
        card = {r["filename"]: r["result"] for r in self.manifest() if r["category"] == "Richart 卡片頁"}
        self.assertEqual(card["richart_debit-card.pdf"], "失敗")

    def test_card_page_with_the_same_main_content_is_unchanged_and_with_new_content_is_converted_again(self) -> None:
        self.assertEqual(self.run_script().returncode, 0)
        for file in (self.out / "richart").iterdir():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.richart_routes[RICHART_DEBIT_PATH] = (
            200,
            richart_page_html("RICHART-DEBIT", []).replace("RICHART-NAV-TEXT", "NAV-CHANGED").encode(),
        )
        self.richart_routes[RICHART_CREDIT_PATH] = (200, richart_page_html("RICHART-CREDIT-NEW", []).encode())
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = {r["filename"]: r["result"] for r in self.manifest() if r["category"] == "Richart 卡片頁"}
        self.assertEqual(records, {"richart_debit-card.pdf": "未變", "richart_credit-card.pdf": "內容變更"})
        self.assertEqual((self.out / "richart" / "richart_debit-card.pdf").stat().st_mtime_ns, OLD_MTIME_NS)
        self.assertIn("RICHART-CREDIT-NEW", (self.out / "_meta" / "html" / "richart_credit-card.html").read_text(encoding="utf-8"))
        self.assertIn("Richart 卡片頁：內容變更 1、未變 1", result.stdout)


class RichartDiscountTests(ScriptTestCase):
    def test_discounts_linked_from_either_page_are_downloaded_once_each_and_named_by_id(self) -> None:
        # 277 在兩頁都有、278 在同一頁連兩次（第二次帶 fragment 與別的 query）；/discount 是優惠列表，不是細則
        debit = [
            discount_href("277"),
            discount_href("278"),
            discount_href("278") + "&utm=x#notes",
            "/TSDIB_RichartWeb/discount",
        ]
        credit = [discount_href("277"), discount_href("350")]
        self.serve_richart(debit, credit, {"277": "D277", "278": "D278", "350": "D350"})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "richart_discounts").iterdir()),
            ["richart_discount_277.pdf", "richart_discount_278.pdf", "richart_discount_350.pdf"],
        )
        paths = self.richart_server.paths()
        for discount_id in ("277", "278", "350"):
            self.assertEqual(paths.count(RICHART_DISCOUNT_FORMAT.format(id=discount_id)), 1, discount_id)
        self.assertEqual(len(paths), 4 + 3, "兩個卡片頁各 2 次（下載、收集細則連結）加 3 則細則各 1 次")
        records = {r["filename"]: r for r in self.manifest() if r["category"] == "Richart 優惠細則"}
        self.assertEqual(sorted(records), ["richart_discount_277.pdf", "richart_discount_278.pdf", "richart_discount_350.pdf"])
        record = records["richart_discount_278.pdf"]
        self.assertEqual(record["url"], self.richart_server.base_url + RICHART_DISCOUNT_FORMAT.format(id="278"))
        self.assertEqual((record["result"], record["format"]), ("已下載", "PDF"))
        self.assertEqual(
            (self.out / "_meta" / "html" / "richart_discount_278.html").read_bytes(),
            self.richart_routes[RICHART_DISCOUNT_FORMAT.format(id="278")][1],
        )
        self.assertIn(
            "D278", (self.out / "richart_discounts" / "richart_discount_278.pdf").read_text(encoding="utf-8", errors="replace")
        )

    def test_links_to_other_domains_are_skipped_without_a_request_a_failure_or_a_manifest_row(self) -> None:
        outside = self.mkp_server.base_url + RICHART_DISCOUNT_FORMAT.format(id="999")
        hrefs = [discount_href("277"), outside, "http://example.invalid" + discount_href("998"), BAD_HREF, discount_href("abc")]
        self.serve_richart(hrefs, [], {"277": "D277"})
        self.mkp_routes[RICHART_DISCOUNT_FORMAT.format(id="999")] = (200, richart_page_html("D999", []).encode())
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "richart_discounts").iterdir()], ["richart_discount_277.pdf"])
        self.assertEqual(self.mkp_server.paths(), [])
        self.assertFalse([p for p in self.richart_server.paths() if "998" in p or "999" in p or "abc" in p])
        self.assertEqual(
            [r["filename"] for r in self.manifest() if r["category"] == "Richart 優惠細則"], ["richart_discount_277.pdf"]
        )

    def test_absolute_links_on_the_richart_domain_are_collected(self) -> None:
        absolute = self.richart_server.base_url + discount_href("277")
        self.serve_richart([absolute], [], {"277": "D277"})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "richart_discounts").iterdir()], ["richart_discount_277.pdf"])

    def test_existing_discount_names_do_not_change_when_the_list_grows(self) -> None:
        self.serve_richart([discount_href("277")], [], {"277": "D277"})
        self.assertEqual(self.run_script().returncode, 0)
        first = self.out / "richart_discounts" / "richart_discount_277.pdf"
        os.utime(first, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.serve_richart(
            [discount_href("277"), discount_href("278")], [discount_href("350")], {"277": "D277", "278": "D278", "350": "D350"}
        )
        self.richart_server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "richart_discounts").iterdir()),
            ["richart_discount_277.pdf", "richart_discount_278.pdf", "richart_discount_350.pdf"],
        )
        self.assertEqual(first.stat().st_mtime_ns, OLD_MTIME_NS)
        self.assertNotIn(RICHART_DISCOUNT_FORMAT.format(id="277"), self.richart_server.paths(), "已存在的細則不重新請求")

    def test_discount_page_failure_is_recorded_for_that_page_only(self) -> None:
        self.serve_richart([discount_href("277"), discount_href("278")], [], {"277": "D277"})
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        records = {r["filename"]: r for r in self.manifest() if r["category"] == "Richart 優惠細則"}
        self.assertEqual(records["richart_discount_277.pdf"]["result"], "已下載")
        self.assertEqual(records["richart_discount_278.pdf"]["result"], "失敗")
        self.assertIn(f"FAILED {self.richart_server.base_url + discount_href('278')}", result.stderr)

    def test_discount_main_content_is_what_chrome_receives(self) -> None:
        self.serve_richart([discount_href("277")], [], {"277": "D277"})
        self.assertEqual(self.run_script().returncode, 0)
        received = (self.out / "richart_discounts" / "richart_discount_277.pdf").read_text(encoding="utf-8", errors="replace")
        self.assertIn("D277", received)
        self.assertNotIn("RICHART-NAV-TEXT", received)
        self.assertIn(f'<base href="{self.richart_server.base_url}{discount_href("277")}">', received)


class RichartDiscountUpdateModeTests(ScriptTestCase):
    def first_download(self, debit: list[str], credit: list[str], discounts: dict[str, str]) -> None:
        """第一次下載（不開更新模式），把細則文件的修改時間設成很久以前，清掉請求紀錄。"""
        self.serve_richart(debit, credit, discounts)
        self.assertEqual(self.run_script().returncode, 0)
        for file in (self.out / "richart_discounts").iterdir():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.richart_server.requests.clear()

    def removed_dir(self) -> Path:
        """今天的下架資料夾 DIR/_meta/removed/<日期>/。"""
        return self.out / "_meta" / "removed" / date.today().isoformat()

    def records(self) -> dict[str, dict[str, str]]:
        """下載清單中 Richart 優惠細則的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "Richart 優惠細則"}

    def local_discounts(self) -> list[str]:
        """richart_discounts/ 裡的檔名（排序）。"""
        return sorted(p.name for p in (self.out / "richart_discounts").iterdir())

    def test_discount_with_the_same_main_content_is_unchanged_and_with_new_content_is_converted_again(self) -> None:
        self.first_download([discount_href("277"), discount_href("278")], [], {"277": "D277", "278": "D278-OLD"})
        self.serve_richart([discount_href("277"), discount_href("278")], [], {"277": "D277", "278": "D278-NEW"})
        self.richart_routes[discount_href("277")] = (
            200,
            richart_page_html("D277", []).replace("RICHART-NAV-TEXT", "NAV-CHANGED").encode(),
        )
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = self.records()
        self.assertEqual(records["richart_discount_277.pdf"]["result"], "未變")
        self.assertEqual(records["richart_discount_278.pdf"]["result"], "內容變更")
        self.assertEqual((self.out / "richart_discounts" / "richart_discount_277.pdf").stat().st_mtime_ns, OLD_MTIME_NS)
        self.assertIn("D278-NEW", (self.out / "_meta" / "html" / "richart_discount_278.html").read_text(encoding="utf-8"))
        self.assertIn("Richart 優惠細則：內容變更 1、未變 1", result.stdout)

    def test_discount_no_longer_linked_from_either_page_is_moved_with_its_html_and_recorded_as_removed(self) -> None:
        self.first_download(
            [discount_href("277"), discount_href("278")], [discount_href("350")], {"277": "D277", "278": "D278", "350": "D350"}
        )
        pdf_before = (self.out / "richart_discounts" / "richart_discount_278.pdf").read_bytes()
        self.serve_richart([discount_href("277")], [discount_href("350")], {"277": "D277", "350": "D350"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        removed = self.removed_dir()
        self.assertEqual(self.local_discounts(), ["richart_discount_277.pdf", "richart_discount_350.pdf"])
        self.assertFalse((self.out / "_meta" / "html" / "richart_discount_278.html").exists())
        self.assertEqual((removed / "richart_discounts" / "richart_discount_278.pdf").read_bytes(), pdf_before)
        self.assertTrue((removed / "html" / "richart_discount_278.html").is_file())
        self.assertTrue((removed / "print" / "richart_discount_278.html").is_file())
        self.assertEqual(self.records()["richart_discount_278.pdf"]["result"], "下架")
        self.assertIn("Richart 優惠細則：未變 2、下架 1", result.stdout)

    def test_discount_still_linked_from_one_of_the_pages_is_not_removed(self) -> None:
        self.first_download([discount_href("277")], [discount_href("277")], {"277": "D277"})
        self.serve_richart([], [discount_href("277")], {"277": "D277"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.local_discounts(), ["richart_discount_277.pdf"])
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_card_page_that_cannot_be_fetched_blocks_discount_removal_but_new_discounts_are_still_downloaded(self) -> None:
        self.first_download(
            [discount_href("277")], [discount_href("278")], {"277": "D277", "278": "D278"}
        )
        # 信用卡頁取不到（連結看不到 278）；簽帳金融卡頁成功，連到 277 與新的 350
        self.serve_richart([discount_href("277"), discount_href("350")], [], {"277": "D277", "278": "D278", "350": "D350"})
        del self.richart_routes[RICHART_CREDIT_PATH]
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            self.local_discounts(), ["richart_discount_277.pdf", "richart_discount_278.pdf", "richart_discount_350.pdf"]
        )
        self.assertFalse((self.out / "_meta" / "removed").exists())
        for text in ("Richart 優惠細則", "不搬任何檔案", self.richart_server.base_url + RICHART_CREDIT_PATH):
            self.assertIn(text, result.stderr)
        self.assertNotIn("下架", [r["result"] for r in self.manifest()])

    def assert_removal_blocked_when_only_this_page_fails(self, failing: str) -> None:
        """兩頁都不再連到 278，但 failing 那一頁這次取不到：278 不能算下架。"""
        self.first_download([discount_href("277")], [discount_href("278")], {"277": "D277", "278": "D278"})
        self.serve_richart([discount_href("277")], [discount_href("277")], {"277": "D277", "278": "D278"})
        del self.richart_routes[failing]
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.local_discounts(), ["richart_discount_277.pdf", "richart_discount_278.pdf"])
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_debit_card_page_failing_alone_blocks_discount_removal(self) -> None:
        self.assert_removal_blocked_when_only_this_page_fails(RICHART_DEBIT_PATH)

    def test_credit_card_page_failing_alone_blocks_discount_removal(self) -> None:
        self.assert_removal_blocked_when_only_this_page_fails(RICHART_CREDIT_PATH)

    def test_both_pages_fetched_but_no_discount_links_while_local_has_discounts_does_not_judge_removal(self) -> None:
        self.first_download([discount_href("277")], [discount_href("278")], {"277": "D277", "278": "D278"})
        self.serve_richart([], [])
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for text in ("Richart 優惠細則", "0 筆", "不搬任何檔案"):
            self.assertIn(text, result.stderr)
        self.assertEqual(self.local_discounts(), ["richart_discount_277.pdf", "richart_discount_278.pdf"])
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_no_discount_links_and_no_local_discounts_is_not_a_failure(self) -> None:
        self.assertEqual(self.run_script().returncode, 0)
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.out / "_meta" / "removed").exists())


class RightsPageTests(ScriptTestCase):
    def test_converts_each_rights_subpage_to_docx_with_unique_names_and_keeps_raw_html(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING"), NOTICE_DASH: card_html("NOTICE")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.files_under_out(),
            sorted(
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
                    *DEBIT_INFO_FILES,
                    *RICHART_DEFAULT_FILES,
                ]
            ),
        )
        self.assertTrue((self.out / "rights" / "rights_insurance_right0201.docx").read_bytes().startswith(b"PK"))
        self.assertEqual(
            (self.out / "_meta" / "html" / "rights_insurance_right0201.html").read_bytes(), self.routes[INSURANCE][1]
        )

    def test_menu_links_pdf_links_and_duplicate_anchors_are_not_fetched_again(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.run_script()
        # 權益頁的選單連結（權益頁自己、總覽、繳費）、PDF 連結、卡片頁連結都不下載；重複的錨點只抓一次
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, INSURANCE, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS, DEBIT_LIST_PATH, *DEBIT_DEFAULT_REQUESTS])

    def test_cards_and_rights_are_downloaded_in_one_run_into_separate_folders(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.assertEqual(self.run_script().returncode, 0)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file())
        self.assertTrue((self.out / "rights" / "rights_insurance_right0201.docx").is_file())
        self.assertEqual(len([r for r in self.manifest() if r["category"] in ("卡片", "權益")]), 2)

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
        self.assertEqual(len([r for r in self.manifest() if r["category"] == "權益"]), 46)


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
        # 總覽頁、權益頁、下載頁 3 頁、PDF 2 份、刷卡優惠列表 9 個分類各 1 頁、簽帳金融卡專區列表頁 1 頁、約定條款頁 1 頁、金融卡說明頁 7 頁
        self.assertEqual(len(times), 25)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, interval - 0.02)


class DownloadAreaManifestTests(ScriptTestCase):
    def test_record_has_the_same_fields_and_no_html_sha256(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_downloads([[TERMS]])
        self.assertEqual(self.run_script().returncode, 0)
        records = {r["filename"]: r for r in self.manifest()}
        self.assertEqual(sorted(records), sorted(["card_cg047_card001.pdf", "download_terms_1150.pdf", *DEBIT_INFO_DOCUMENTS, *RICHART_DEFAULT_DOCUMENTS]))
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
            sorted(["downloads/download_word_CR04131_1150B.pdf", *DEBIT_INFO_FILES, *RICHART_DEFAULT_FILES]),
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
        first = {r["filename"]: r for r in self.manifest() if r["category"] == "下載"}
        self.server.requests.clear()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [p for p in self.server.paths() if p.endswith(".pdf")], [], "已存在的 PDF 不該再請求"
        )
        second = {r["filename"]: r for r in self.manifest() if r["category"] == "下載"}
        self.assertEqual(sorted(second), sorted(first))
        for name, record in second.items():
            self.assertEqual(record["result"], "已存在略過")
            self.assertEqual(record["sha256"], first[name]["sha256"])
            if name in RICHART_DEFAULT_DOCUMENTS:
                # richart.tw 的卡片頁是網頁，清單有原始 HTML 的雜湊
                self.assertNotEqual(first[name]["html_sha256"], "")
                self.assertEqual(record["html_sha256"], first[name]["html_sha256"])
            else:
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
        # 總覽頁、權益頁、下載頁 2 頁（第 2 頁重複第 1 頁而停止）、重新下載 PDF 2 份、刷卡優惠列表 9 個分類各 1 頁、簽帳金融卡專區列表頁 1 頁、
        # 約定條款頁 1 頁、金融卡說明頁 7 頁（更新模式下已有的說明頁也重新取得）
        self.assertEqual(len(times), 24)
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
        self.assertIn("卡片：未變 1", result.stdout)
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
            sorted(
                [
                    f"_meta/html/offer_{wm(1)}.html",
                    f"_meta/html/offer_{wm(2)}.html",
                    "_meta/manifest.jsonl",
                    f"_meta/print/offer_{wm(1)}.html",
                    f"_meta/print/offer_{wm(2)}.html",
                    f"offers/offer_{wm(1)}.pdf",
                    f"offers/offer_{wm(2)}.pdf",
                    *DEBIT_INFO_FILES,
                    *RICHART_DEFAULT_FILES,
                ]
            ),
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
        records = [r for r in self.manifest() if r["category"] == "活動"]
        self.assertEqual(len(records), 1)
        return records[0]

    def test_activity_that_ended_before_today_is_skipped_and_recorded_as_expired(self) -> None:
        period = period_from_today(-60, -1)
        record = self.serve_one_activity(offer_detail_html("OFFER1", period=period))
        self.assertEqual(record["result"], "過期略過")
        self.assertEqual(record["period"], period)
        self.assertEqual(record["category"], "活動")
        self.assertEqual(self.files_under_out(), sorted(["_meta/html/offer_%s.html" % wm(1), "_meta/manifest.jsonl", *DEBIT_INFO_FILES, *RICHART_DEFAULT_FILES]))

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
        self.assertEqual(sorted(records), sorted(["card_cg010_card001.pdf", "card_cg047_card001.pdf", *DEBIT_INFO_DOCUMENTS, *RICHART_DEFAULT_DOCUMENTS]))
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
        self.assertEqual(sorted(records), sorted(["card_cg047_card001.pdf", "rights_insurance_right0201.docx", *DEBIT_INFO_DOCUMENTS, *RICHART_DEFAULT_DOCUMENTS]))
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
        self.assertEqual(len([r for r in self.manifest() if r["category"] == "卡片"]), 2)

    def test_prints_count_16_when_there_are_16_cards(self) -> None:
        cards = {CARD_PATH_FORMAT.format(cg=f"cg{n:03d}", card="card001"): card_html(f"CARD{n}") for n in range(16)}
        self.serve_cards(cards)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("找到 16 張卡片頁（預期 16）", result.stdout)
        self.assertEqual(len([r for r in self.manifest() if r["category"] == "卡片"]), 16)

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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, INSURANCE, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS, DEBIT_LIST_PATH, *DEBIT_DEFAULT_REQUESTS])
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
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        # 金融卡說明頁與 richart.tw 的卡片頁也要用 Chrome 列印，所以 7 個說明頁、2 個 richart 卡片頁和卡片頁一起失敗
        failed = [r for r in self.manifest() if r["result"] == "失敗"]
        self.assertEqual(sorted(r["filename"] for r in failed), sorted(["card_cg047_card001.pdf", *DEBIT_INFO_DOCUMENTS, *RICHART_DEFAULT_DOCUMENTS]))
        for record in failed:
            self.assertIn("TAISHIN_CHROME", record["detail"])
            self.assertIn(record["filename"], result.stderr)
            self.assertEqual(record["sha256"], "")

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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS, DEBIT_LIST_PATH, DEBIT_TERMS_PATH], "第二次只該請求列表頁")
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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS, DEBIT_LIST_PATH, DEBIT_TERMS_PATH])
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
        self.assertEqual([r["result"] for r in self.manifest() if r["category"] == "卡片"], ["已下載"])


class RequestPolicyTests(ScriptTestCase):
    def test_every_request_carries_an_identifiable_user_agent(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.run_script()
        # 總覽頁、卡片頁、權益頁、下載頁各 1 個，加刷卡優惠列表 9 個分類各 1 頁、簽帳金融卡專區列表頁 1 頁、約定條款頁 1 頁、金融卡說明頁 7 頁
        self.assertEqual(len(self.server.requests), 22)
        for _path, _time, user_agent in self.server.requests:
            self.assertTrue(user_agent.startswith("llm-lab-fetch-taishin/"), user_agent)

    def test_requests_are_spaced_by_at_least_the_configured_interval(self) -> None:
        self.serve_cards(
            {RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN"), DAQUANLIAN_2: card_html("DQL2")}
        )
        interval = 0.3
        self.assertEqual(self.run_script(interval=str(interval)).returncode, 0)
        times = [t for _path, t, _ua in self.server.requests]
        self.assertEqual(len(times), 24)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, interval - 0.02)

    def test_invalid_interval_is_rejected_before_any_request(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_script(interval="abc")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TAISHIN_REQUEST_INTERVAL_SEC", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.paths(), [])
        self.assertEqual(self.richart_server.paths(), [])

    def test_out_that_is_a_regular_file_is_rejected_before_any_request(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.out.write_text("not a directory")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--out", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.server.paths(), [])
        self.assertEqual(self.richart_server.paths(), [])


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
        self.assertEqual([r["filename"] for r in self.manifest() if r["category"] == "卡片"], ["card_cg047_card001.pdf"])

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
        self.assertEqual([r["filename"] for r in self.manifest() if r["category"] == "下載"], ["download_word_CR04131_1150B.pdf"])

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
        self.assertEqual([r["filename"] for r in self.manifest() if r["category"] == "卡片"], ["card_cg047_card001.pdf"])
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


def with_csrf(page: str, token: str) -> str:
    """在頁面的 <head> 開頭加上 <meta id="_csrf">（官網每次請求都可能換 token；主內容區以外）。"""
    return page.replace("<head>", f'<head><meta id="_csrf" content="{token}">', 1)


class UpdateModeWebPageTests(ScriptTestCase):
    """更新模式下，網頁類（卡片頁、權益子頁、活動頁）只在主內容區變了時才重新轉檔。"""

    def first_download(self) -> dict[str, Path]:
        """第一次下載（不開更新模式）後，把每份文件的修改時間設成很久以前。

        Returns:
            類別資料夾底下的檔名對本地檔案。
        """
        self.assertEqual(self.run_script().returncode, 0)
        folders = (self.out / name for name in ("cards", "rights", "offers"))
        saved = {p.name: p for folder in folders if folder.is_dir() for p in folder.iterdir()}
        for file in saved.values():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        self.server.requests.clear()
        self.mkp_server.requests.clear()
        return saved

    def run_update_without_converters(self) -> subprocess.CompletedProcess:
        """更新模式，Chrome 路徑不存在、PATH 上沒有 LibreOffice：任何一次轉檔都會讓那一頁失敗。"""
        empty_path = self.tmp / "empty_path"
        empty_path.mkdir(exist_ok=True)
        return self.run_update(chrome=str(self.tmp / "no-such-chrome"), path=str(empty_path))

    def records(self, category: str) -> dict[str, dict[str, str]]:
        """下載清單中某個類別的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == category}

    def test_card_page_whose_main_content_is_the_same_is_not_converted_and_nothing_is_touched(self) -> None:
        self.serve_cards({RICHART: with_csrf(card_html("RICHART"), "token-1")})
        saved = self.first_download()
        document = saved["card_cg047_card001.pdf"]
        raw_path = self.out / "_meta" / "html" / "card_cg047_card001.html"
        print_path = self.out / "_meta" / "print" / "card_cg047_card001.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path, print_path)}
        self.serve_cards({RICHART: with_csrf(card_html("RICHART"), "token-2")})
        result = self.run_update_without_converters()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(RICHART, self.server.paths(), "更新模式要重新取得原始 HTML 來比對")
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        record = self.records("卡片")["card_cg047_card001.pdf"]
        self.assertEqual(record["result"], "未變")
        self.assertEqual(record["sha256"], hashlib.sha256(before[document][0]).hexdigest())
        self.assertEqual(record["html_sha256"], hashlib.sha256(before[raw_path][0]).hexdigest())

    def test_rights_page_whose_main_content_is_the_same_is_not_converted_and_nothing_is_touched(self) -> None:
        self.serve_rights({INSURANCE: with_csrf(card_html("INSURANCE"), "token-1")})
        saved = self.first_download()
        document = saved["rights_insurance_right0201.docx"]
        raw_path = self.out / "_meta" / "html" / "rights_insurance_right0201.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path)}
        self.serve_rights({INSURANCE: with_csrf(card_html("INSURANCE"), "token-2")})
        result = self.run_update_without_converters()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        self.assertEqual(self.records("權益")["rights_insurance_right0201.docx"]["result"], "未變")

    def test_activity_page_whose_main_content_is_the_same_is_not_converted_and_nothing_is_touched(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): with_csrf(offer_detail_html("OFFER1"), "token-1")})
        saved = self.first_download()
        document = saved[f"offer_{wm(1)}.pdf"]
        raw_path = self.out / "_meta" / "html" / f"offer_{wm(1)}.html"
        print_path = self.out / "_meta" / "print" / f"offer_{wm(1)}.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path, print_path)}
        self.serve_details({detail_path(1): with_csrf(offer_detail_html("OFFER1"), "token-2")})
        result = self.run_update_without_converters()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(detail_path(1), self.mkp_server.paths())
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        record = self.records("活動")[f"offer_{wm(1)}.pdf"]
        self.assertEqual(record["result"], "未變")
        self.assertEqual(record["period"], "2099-01-01~2099-12-31")

    def test_card_page_with_a_new_main_content_is_converted_again_and_all_three_files_are_replaced(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        saved = self.first_download()
        new_page = with_csrf(card_html("RICHART-REVISED"), "token-2").encode()
        self.routes[RICHART] = (200, new_page)
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = saved["card_cg047_card001.pdf"]
        self.assertIn(b"RICHART-REVISED", document.read_bytes())
        self.assertEqual((self.out / "_meta" / "html" / "card_cg047_card001.html").read_bytes(), new_page)
        self.assertIn(b"RICHART-REVISED", (self.out / "_meta" / "print" / "card_cg047_card001.html").read_bytes())
        records = self.records("卡片")
        changed = records["card_cg047_card001.pdf"]
        self.assertEqual(changed["result"], "內容變更")
        self.assertEqual(changed["sha256"], hashlib.sha256(document.read_bytes()).hexdigest())
        self.assertEqual(changed["html_sha256"], hashlib.sha256(new_page).hexdigest())
        self.assertEqual(changed["downloaded_at"], time.strftime("%Y-%m-%d"))
        self.assertEqual(records["card_cg010_card001.pdf"]["result"], "未變")
        self.assertEqual(saved["card_cg010_card001.pdf"].stat().st_mtime_ns, OLD_MTIME_NS)
        self.assertEqual(
            sorted(p.name for p in (self.out / "cards").iterdir()), ["card_cg010_card001.pdf", "card_cg047_card001.pdf"]
        )

    def test_rights_page_with_a_new_main_content_is_converted_again(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        saved = self.first_download()
        self.routes[INSURANCE] = (200, card_html("INSURANCE-REVISED").encode())
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"INSURANCE-REVISED", saved["rights_insurance_right0201.docx"].read_bytes())
        self.assertEqual(self.records("權益")["rights_insurance_right0201.docx"]["result"], "內容變更")

    def test_activity_page_with_a_new_main_content_is_converted_again_and_its_period_is_recorded(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1")})
        saved = self.first_download()
        self.serve_details({detail_path(1): offer_detail_html("OFFER1-REVISED", period="2099-02-01~2099-12-31")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"OFFER1-REVISED", saved[f"offer_{wm(1)}.pdf"].read_bytes())
        record = self.records("活動")[f"offer_{wm(1)}.pdf"]
        self.assertEqual(record["result"], "內容變更")
        self.assertEqual(record["period"], "2099-02-01~2099-12-31")

    def test_failed_conversion_leaves_document_and_both_html_files_alone_and_the_next_run_tries_again(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        saved = self.first_download()
        document = saved["card_cg047_card001.pdf"]
        raw_path = self.out / "_meta" / "html" / "card_cg047_card001.html"
        print_path = self.out / "_meta" / "print" / "card_cg047_card001.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path, print_path)}
        self.routes[RICHART] = (200, card_html("FAKE-CHROME-FAIL").encode())
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        record = self.records("卡片")["card_cg047_card001.pdf"]
        self.assertEqual(record["result"], "失敗")
        self.assertIn("Chrome", record["detail"])
        self.assertEqual(sorted(p.name for p in (self.out / "_meta").iterdir()), ["html", "manifest.jsonl", "print"])
        self.routes[RICHART] = (200, card_html("RICHART-FIXED").encode())
        retry = self.run_update()
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertIn(b"RICHART-FIXED", document.read_bytes())
        self.assertEqual(self.records("卡片")["card_cg047_card001.pdf"]["result"], "內容變更")

    def test_failed_rights_conversion_leaves_the_files_alone(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        saved = self.first_download()
        document = saved["rights_insurance_right0201.docx"]
        raw_path = self.out / "_meta" / "html" / "rights_insurance_right0201.html"
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (document, raw_path)}
        self.routes[INSURANCE] = (200, card_html("INSURANCE-REVISED").encode())
        result = self.run_update_without_converters()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, path.name)
        record = self.records("權益")["rights_insurance_right0201.docx"]
        self.assertEqual(record["result"], "失敗")
        self.assertIn("LibreOffice", record["detail"])

    def test_page_that_cannot_be_fetched_or_has_no_main_content_leaves_the_files_alone(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        saved = self.first_download()
        before = {name: (file.read_bytes(), file.stat().st_mtime_ns) for name, file in saved.items()}
        self.routes[RICHART] = (500, b"boom")
        self.routes[DAQUANLIAN] = (200, card_html_without_main_content().encode())
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for name, file in saved.items():
            self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), before[name], name)
        records = self.records("卡片")
        self.assertEqual(records["card_cg047_card001.pdf"]["result"], "失敗")
        self.assertIn("500", records["card_cg047_card001.pdf"]["detail"])
        self.assertEqual(records["card_cg010_card001.pdf"]["result"], "失敗")
        self.assertIn("找不到主內容區", records["card_cg010_card001.pdf"]["detail"])

    def test_saved_html_without_a_document_is_converted_from_the_html_fetched_this_time(self) -> None:
        self.serve_cards({RICHART: card_html("FAKE-CHROME-FAIL")})
        self.assertEqual(self.run_script().returncode, 1)
        raw_path = self.out / "_meta" / "html" / "card_cg047_card001.html"
        self.assertTrue(raw_path.is_file())
        self.assertFalse((self.out / "cards" / "card_cg047_card001.pdf").exists())
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"RICHART", (self.out / "cards" / "card_cg047_card001.pdf").read_bytes())
        self.assertEqual(raw_path.read_bytes(), self.routes[RICHART][1])
        self.assertEqual(self.records("卡片")["card_cg047_card001.pdf"]["result"], "已下載")

    def test_saved_html_of_an_expired_activity_without_a_document_is_skipped_without_a_request(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", period=period_from_today(-60, -1))})
        self.assertEqual(self.run_script().returncode, 0)
        self.mkp_server.requests.clear()
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.mkp_server.paths(), [])
        record = self.records("活動")[f"offer_{wm(1)}.pdf"]
        self.assertEqual(record["result"], "過期略過")
        self.assertFalse((self.out / "offers" / f"offer_{wm(1)}.pdf").exists())

    def test_saved_html_of_an_active_activity_without_a_document_is_converted_from_the_html_fetched_this_time(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("FAKE-CHROME-FAIL")})
        self.assertEqual(self.run_script().returncode, 1)
        self.serve_details({detail_path(1): offer_detail_html("OFFER1")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"OFFER1", (self.out / "offers" / f"offer_{wm(1)}.pdf").read_bytes())
        self.assertEqual(self.records("活動")[f"offer_{wm(1)}.pdf"]["result"], "已下載")

    def test_requests_for_web_pages_in_update_mode_are_spaced_by_the_configured_interval(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART")})
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1")})
        self.first_download()
        interval = 0.3
        result = self.run_update(interval=str(interval))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        times = sorted(t for server in (self.server, self.mkp_server) for _path, t, _ua in server.requests)
        # 總覽頁、卡片頁、權益頁、權益子頁、下載頁、刷卡優惠列表 A 的 2 頁（第 2 頁沒有新連結而停止）與 B–I 各 1 頁、mkp 的活動頁、簽帳金融卡專區列表頁、約定條款頁、金融卡說明頁 7 頁
        self.assertEqual(len(times), 25)
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, interval - 0.02)

    def test_prints_the_count_of_each_result_for_web_pages(self) -> None:
        self.serve_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DAQUANLIAN")})
        self.first_download()
        self.routes[RICHART] = (200, card_html("RICHART-REVISED").encode())
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("卡片：內容變更 1、未變 1", result.stdout)


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


# 子行程的 date.today() 固定回後天（模擬再過兩天才執行更新模式）
SITECUSTOMIZE_CLOCK_DAY_AFTER_TOMORROW = """
import datetime as _dt
_real = _dt.date


class _Date(_real):
    @classmethod
    def today(cls):
        return _real.today() + _dt.timedelta(days=2)


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
            sorted(
                [
                    "rights/rights_insurance_right0201.docx",
                    "rights/rights_parking_right0301.docx",
                    *[f for f in DEBIT_INFO_FILES if f.startswith("debit_info/")],
                    "richart/richart_credit-card.pdf",
                    "richart/richart_debit-card.pdf",
                ]
            ),
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
            sorted(
                [
                    "downloads/download_dual-card_01.pdf",
                    "rights_attachments/attachment_dual-card_02.pdf",
                    *[f for f in DEBIT_INFO_FILES if f.endswith(".pdf")],
                    "richart/richart_credit-card.pdf",
                    "richart/richart_debit-card.pdf",
                ]
            ),
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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, *EMPTY_OFFER_REQUESTS, DEBIT_LIST_PATH, DEBIT_TERMS_PATH])
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
        self.assertEqual(self.server.paths(), [OVERVIEW_PATH, RIGHTS_LIST_PATH, DOWNLOAD_PAGE_1, DUAL_PDF, *EMPTY_OFFER_REQUESTS, DEBIT_LIST_PATH, DEBIT_TERMS_PATH])
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
        # 總覽頁 1、權益頁 1、子頁 1、下載頁 1、PDF 2 份、刷卡優惠列表 9 個分類各 1 頁、簽帳金融卡專區列表頁 1 頁、約定條款頁 1 頁、
        # 金融卡說明頁 7 頁，共 24 個請求
        self.assertEqual(len(requests), 24)
        for earlier, later in zip(requests, requests[1:]):
            self.assertGreaterEqual(later[1] - earlier[1], interval - 0.02)
        self.assertTrue(all(user_agent.startswith("llm-lab-fetch-taishin/") for _p, _t, user_agent in requests))


class UpdateModeRemovedFromListTests(ScriptTestCase):
    def download_cards(self, cards: dict[str, str]) -> None:
        """第一次下載（不開更新模式）這些卡片，清掉請求紀錄。

        Args:
            cards: 卡片頁路徑對頁面 HTML。
        """
        self.serve_cards(cards)
        self.assertEqual(self.run_script().returncode, 0)
        self.server.requests.clear()

    def removed_dir(self) -> Path:
        """今天的下架資料夾 DIR/_meta/removed/<日期>/。"""
        return self.out / "_meta" / "removed" / date.today().isoformat()

    def test_card_missing_from_the_list_is_moved_with_its_html_and_recorded_as_removed(self) -> None:
        self.download_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DQL")})
        pdf_before = (self.out / "cards" / "card_cg010_card001.pdf").read_bytes()
        html_before = (self.out / "_meta" / "html" / "card_cg010_card001.html").read_bytes()
        print_before = (self.out / "_meta" / "print" / "card_cg010_card001.html").read_bytes()
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        removed = self.removed_dir()
        self.assertFalse((self.out / "cards" / "card_cg010_card001.pdf").exists())
        self.assertFalse((self.out / "_meta" / "html" / "card_cg010_card001.html").exists())
        self.assertFalse((self.out / "_meta" / "print" / "card_cg010_card001.html").exists())
        self.assertEqual((removed / "cards" / "card_cg010_card001.pdf").read_bytes(), pdf_before)
        self.assertEqual((removed / "html" / "card_cg010_card001.html").read_bytes(), html_before)
        self.assertEqual((removed / "print" / "card_cg010_card001.html").read_bytes(), print_before)
        self.assertTrue((self.out / "cards" / "card_cg047_card001.pdf").is_file(), "還在列表裡的卡片不動")
        self.assertTrue((self.out / "_meta" / "html" / "card_cg047_card001.html").is_file())
        records = {r["filename"]: r for r in self.manifest() if r["category"] == "卡片"}
        self.assertEqual(records["card_cg010_card001.pdf"]["result"], "下架")
        self.assertEqual(records["card_cg047_card001.pdf"]["result"], "未變")
        self.assertIn("卡片：未變 1、下架 1", result.stdout)

    def test_rights_downloads_and_activities_missing_from_their_lists_are_moved_too(self) -> None:
        self.serve_rights({INSURANCE: card_html("INSURANCE"), PARKING: card_html("PARKING")})
        self.serve_downloads([[APPLICATION, TERMS]])
        self.serve_offers({"A": [[detail_path(1), detail_path(2)]]})
        self.serve_details({detail_path(n): offer_detail_html(f"OFFER{n}", period="2099-01-01~2099-12-31") for n in (1, 2)})
        self.assertEqual(self.run_script().returncode, 0)
        self.serve_rights({INSURANCE: card_html("INSURANCE")})
        self.serve_downloads([[APPLICATION]])
        self.serve_offers({"A": [[detail_path(1)]]})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        removed = self.removed_dir()
        moved = sorted(str(p.relative_to(removed)) for p in removed.rglob("*") if p.is_file())
        self.assertEqual(
            moved,
            [
                "downloads/download_terms_1150.pdf",
                f"html/offer_{wm(2)}.html",
                "html/rights_parking_right0301.html",
                f"offers/offer_{wm(2)}.pdf",
                f"print/offer_{wm(2)}.html",
                "print/rights_parking_right0301.html",
                "rights/rights_parking_right0301.docx",
            ],
        )
        results = {(r["category"], r["filename"]): r for r in self.manifest() if r["result"] == "下架"}
        self.assertEqual(
            sorted(results),
            [("下載", "download_terms_1150.pdf"), ("權益", "rights_parking_right0301.docx"), ("活動", f"offer_{wm(2)}.pdf")],
        )
        offer = results[("活動", f"offer_{wm(2)}.pdf")]
        self.assertEqual(offer["period"], "2099-01-01~2099-12-31")
        self.assertEqual(offer["html_sha256"], hashlib.sha256(self.mkp_routes[detail_path(2)][1]).hexdigest())
        self.assertEqual(offer["sha256"], hashlib.sha256((removed / "offers" / f"offer_{wm(2)}.pdf").read_bytes()).hexdigest())
        self.assertEqual(results[("下載", "download_terms_1150.pdf")]["html_sha256"], "")
        self.assertIn("下載：未變 1、下架 1", result.stdout)
        self.assertTrue((self.out / "offers" / f"offer_{wm(1)}.pdf").is_file())

    def test_no_move_without_update_mode(self) -> None:
        self.download_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DQL")})
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.out / "cards" / "card_cg010_card001.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())
        self.assertNotIn("下架", [r["result"] for r in self.manifest()])

    def test_every_card_missing_from_a_non_empty_list_is_moved_because_there_is_no_ratio_threshold(self) -> None:
        self.download_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DQL")})
        self.serve_cards({DAQUANLIAN_2: card_html("DQL2")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "cards").iterdir()), ["card_cg010_card002.pdf"]
        )
        self.assertEqual(
            sorted(p.name for p in (self.removed_dir() / "cards").iterdir()),
            ["card_cg010_card001.pdf", "card_cg047_card001.pdf"],
        )

    def test_destination_with_the_same_name_is_not_overwritten_and_the_moved_file_gets_a_time_suffix(self) -> None:
        self.download_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DQL")})
        moved_pdf = self.out / "cards" / "card_cg010_card001.pdf"
        moved_bytes = moved_pdf.read_bytes()
        occupied = self.removed_dir() / "cards" / "card_cg010_card001.pdf"
        occupied.parent.mkdir(parents=True)
        occupied.write_bytes(b"earlier removal")
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(occupied.read_bytes(), b"earlier removal")
        suffixed = [p for p in occupied.parent.iterdir() if p != occupied]
        self.assertEqual(len(suffixed), 1)
        self.assertRegex(suffixed[0].name, r"^card_cg010_card001_\d{6,}\.pdf$")
        self.assertEqual(suffixed[0].read_bytes(), moved_bytes)
        self.assertFalse(moved_pdf.exists())

    def test_list_request_failure_moves_nothing_in_that_category_and_names_the_reason_but_other_categories_proceed(self) -> None:
        self.download_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DQL")})
        self.serve_downloads([[APPLICATION, TERMS]])
        self.assertEqual(self.run_script().returncode, 0)
        self.routes[OVERVIEW_PATH] = (500, b"boom")
        self.serve_downloads([[APPLICATION]])
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for text in ("信用卡總覽", "500", "不搬任何檔案"):
            self.assertIn(text, result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "cards").iterdir()), ["card_cg010_card001.pdf", "card_cg047_card001.pdf"]
        )
        self.assertTrue((self.out / "_meta" / "html" / "card_cg010_card001.html").is_file())
        self.assertFalse((self.removed_dir() / "cards").exists())
        self.assertTrue((self.removed_dir() / "downloads" / "download_terms_1150.pdf").is_file())

    def test_list_that_parses_to_zero_entries_while_local_has_documents_is_treated_as_a_failed_list(self) -> None:
        self.download_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DQL")})
        self.serve_cards({})
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for text in ("信用卡總覽", "0 筆", "不搬任何檔案"):
            self.assertIn(text, result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "cards").iterdir()), ["card_cg010_card001.pdf", "card_cg047_card001.pdf"]
        )
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_files_that_are_not_documents_are_never_moved_and_are_not_in_the_manifest(self) -> None:
        self.download_cards({RICHART: card_html("RICHART")})
        stray = [self.out / "cards" / ".DS_Store", self.out / "cards" / "~$card.pdf", self.out / "cards" / "._card.pdf"]
        for file in stray:
            file.write_bytes(b"not a document")
        self.serve_cards({RICHART: card_html("RICHART")})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(all(file.is_file() for file in stray))
        self.assertFalse((self.out / "_meta" / "removed").exists())
        self.assertEqual([r["filename"] for r in self.manifest() if r["category"] == "卡片"], ["card_cg047_card001.pdf"])

    def test_empty_list_is_fine_when_the_local_folder_has_only_files_that_are_not_documents(self) -> None:
        (self.out / "cards").mkdir(parents=True)
        (self.out / "cards" / ".DS_Store").write_bytes(b"not a document")
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("0 筆", result.stderr)
        self.assertTrue((self.out / "cards" / ".DS_Store").is_file())

    def test_empty_activity_list_moves_no_activity_but_empty_list_for_a_category_without_local_documents_is_fine(self) -> None:
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1")})
        self.assertEqual(self.run_script().returncode, 0)
        self.serve_offers({})
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("刷卡優惠", result.stderr)
        self.assertTrue((self.out / "offers" / f"offer_{wm(1)}.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())
        # 卡片、權益、下載本來就沒有本地文件，列表是空的不算失敗；結束碼 1 只來自活動
        self.assertEqual(result.stderr.count("ERROR 列表"), 1)

    def test_failure_to_move_is_recorded_as_failed_and_exits_nonzero(self) -> None:
        self.download_cards({RICHART: card_html("RICHART"), DAQUANLIAN: card_html("DQL")})
        self.serve_cards({RICHART: card_html("RICHART")})
        # 今天的下架資料夾位置被一個檔案佔住，所以建不出資料夾
        (self.out / "_meta" / "removed").write_bytes(b"not a folder")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        record = {r["filename"]: r for r in self.manifest()}["card_cg010_card001.pdf"]
        self.assertEqual(record["result"], "失敗")
        self.assertIn("搬移失敗", record["detail"])
        self.assertTrue((self.out / "cards" / "card_cg010_card001.pdf").is_file(), "沒搬成功，原檔留著")


class UpdateModeAttachmentTests(ScriptTestCase):
    """更新模式下，權益附件跟著權益子頁上的連結走：沒有任何子頁還連到的搬走，內容變了的換掉。"""

    def serve_pages(self, pages: dict[str, list[str]]) -> None:
        """登記這些權益子頁（主內容區連到 hrefs）與它們連到的 PDF。

        Args:
            pages: 權益子頁路徑對它連到的 PDF 路徑清單；頁面內容隨 PDF 清單而異，所以換連結會被判成內容變更。
        """
        self.serve_rights({page: rights_page_with_pdfs(f"{page}-{hrefs}", hrefs) for page, hrefs in pages.items()})
        for href in {href for hrefs in pages.values() for href in hrefs}:
            self.routes[href] = (200, pdf_bytes(href))

    def first_download(self, pages: dict[str, list[str]]) -> None:
        """第一次下載（不開更新模式）這些權益子頁與它們連到的附件，清掉請求紀錄。

        Args:
            pages: 權益子頁路徑對它連到的 PDF 路徑清單。
        """
        self.serve_pages(pages)
        self.assertEqual(self.run_script().returncode, 0)
        self.server.requests.clear()

    def removed_dir(self) -> Path:
        """今天的下架資料夾 DIR/_meta/removed/<日期>/。"""
        return self.out / "_meta" / "removed" / date.today().isoformat()

    def attachment_records(self) -> dict[str, dict[str, str]]:
        """下載清單中權益附件的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "權益附件"}

    def test_attachment_that_no_subpage_links_to_any_more_is_moved_and_recorded_as_removed(self) -> None:
        self.first_download({DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2]})
        before = (self.out / "rights_attachments" / "attachment_dual-card_02.pdf").read_bytes()
        self.serve_pages({DUAL_PAGE: [DUAL_PDF]})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.out / "rights_attachments" / "attachment_dual-card_02.pdf").exists())
        self.assertEqual(
            (self.removed_dir() / "rights_attachments" / "attachment_dual-card_02.pdf").read_bytes(), before
        )
        self.assertTrue((self.out / "rights_attachments" / "attachment_dual-card_01.pdf").is_file())
        records = self.attachment_records()
        self.assertEqual(records["attachment_dual-card_02.pdf"]["result"], "下架")
        self.assertEqual(records["attachment_dual-card_01.pdf"]["result"], "未變")
        self.assertIn("權益附件：未變 1、下架 1", result.stdout)

    def test_attachment_with_the_same_content_keeps_its_bytes_and_modification_time_and_new_content_replaces_it(self) -> None:
        self.first_download({DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2]})
        folder = self.out / "rights_attachments"
        for file in folder.iterdir():
            os.utime(file, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        unchanged = folder / "attachment_dual-card_01.pdf"
        before = (unchanged.read_bytes(), unchanged.stat().st_mtime_ns)
        new_content = pdf_bytes(DUAL_PDF_2) + b"%revised\n"
        self.routes[DUAL_PDF_2] = (200, new_content)
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((unchanged.read_bytes(), unchanged.stat().st_mtime_ns), before)
        self.assertEqual((folder / "attachment_dual-card_02.pdf").read_bytes(), new_content)
        records = self.attachment_records()
        self.assertEqual(records["attachment_dual-card_01.pdf"]["result"], "未變")
        self.assertEqual(records["attachment_dual-card_02.pdf"]["result"], "內容變更")
        self.assertEqual(records["attachment_dual-card_02.pdf"]["sha256"], hashlib.sha256(new_content).hexdigest())

    def test_failed_download_of_an_existing_attachment_keeps_the_file_and_is_recorded_as_failed(self) -> None:
        self.first_download({DUAL_PAGE: [DUAL_PDF]})
        attachment = self.out / "rights_attachments" / "attachment_dual-card_01.pdf"
        before = attachment.read_bytes()
        self.routes[DUAL_PDF] = (500, b"boom")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(attachment.read_bytes(), before)
        self.assertEqual(self.attachment_records()["attachment_dual-card_01.pdf"]["result"], "失敗")

    def test_attachment_linked_from_several_subpages_stays_while_one_of_them_still_links_to_it(self) -> None:
        self.first_download({CO_BRAND_PAGE: [DUAL_PDF, CO_BRAND_PDF], DUAL_PAGE: [DUAL_PDF]})
        self.serve_pages({CO_BRAND_PAGE: [CO_BRAND_PDF], DUAL_PAGE: [DUAL_PDF]})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.out / "rights_attachments" / "attachment_dual-card_01.pdf").is_file())
        self.assertEqual(self.attachment_records()["attachment_dual-card_01.pdf"]["result"], "未變")
        self.assertFalse(self.removed_dir().exists())
        self.serve_pages({CO_BRAND_PAGE: [CO_BRAND_PDF], DUAL_PAGE: []})
        again = self.run_update()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertFalse((self.out / "rights_attachments" / "attachment_dual-card_01.pdf").exists())
        self.assertTrue((self.removed_dir() / "rights_attachments" / "attachment_dual-card_01.pdf").is_file())

    def test_attachment_of_a_subpage_that_left_the_rights_list_is_removed(self) -> None:
        self.first_download({CO_BRAND_PAGE: [CO_BRAND_PDF], DUAL_PAGE: [DUAL_PDF]})
        self.serve_pages({DUAL_PAGE: [DUAL_PDF]})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = self.attachment_records()
        self.assertEqual(records["attachment_TSCC-11312.pdf"]["result"], "下架")
        self.assertEqual(records["attachment_dual-card_01.pdf"]["result"], "未變")
        self.assertTrue((self.removed_dir() / "rights_attachments" / "attachment_TSCC-11312.pdf").is_file())

    def test_existing_attachment_that_is_now_in_the_download_area_is_recorded_as_duplicate_and_moved_away(self) -> None:
        # ASSUMPTION：內容已由下載區那一份匯入，不搬走的話同一份 PDF 會在知識庫裡出現兩次
        self.first_download({DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2]})
        before = (self.out / "rights_attachments" / "attachment_dual-card_01.pdf").read_bytes()
        self.serve_downloads([[DUAL_PDF]])
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.out / "rights_attachments" / "attachment_dual-card_01.pdf").exists())
        self.assertEqual(
            (self.removed_dir() / "rights_attachments" / "attachment_dual-card_01.pdf").read_bytes(), before
        )
        self.assertTrue((self.out / "downloads" / "download_dual-card_01.pdf").is_file())
        records = self.attachment_records()
        self.assertEqual(records["attachment_dual-card_01.pdf"]["result"], "重複略過")
        self.assertEqual(records["attachment_dual-card_01.pdf"]["url"], self.server.base_url + DUAL_PDF)
        self.assertIn("download_dual-card_01.pdf", records["attachment_dual-card_01.pdf"]["detail"])
        self.assertEqual(records["attachment_dual-card_02.pdf"]["result"], "未變")
        self.assertEqual(self.server.paths().count(DUAL_PDF), 1, "只有下載區那一份請求，附件不重複請求")
        self.assertIn("權益附件：未變 1、重複略過 1", result.stdout)

    def test_removal_is_not_judged_when_all_subpages_succeed_but_no_attachment_link_is_parsed_while_local_has_attachments(self) -> None:
        # 官網改版讓連結解析失效的可能高於所有附件同時下架，和列表頁「解析出 0 筆」的保護相同
        self.first_download({DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2]})
        self.serve_pages({DUAL_PAGE: []})
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for text in ("權益附件這次不判斷下架", "0 個", "rights_attachments/ 有 2 份"):
            self.assertIn(text, result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "rights_attachments").iterdir()),
            ["attachment_dual-card_01.pdf", "attachment_dual-card_02.pdf"],
        )
        self.assertFalse(self.removed_dir().exists())
        self.assertNotIn("下架", {r["result"] for r in self.attachment_records().values()})

    def test_zero_attachment_links_is_fine_when_there_are_no_local_attachments(self) -> None:
        self.first_download({DUAL_PAGE: []})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("權益附件這次不判斷下架", result.stderr)

    def test_removal_is_not_judged_when_a_subpage_request_failed_and_the_report_names_the_reason(self) -> None:
        self.first_download({CO_BRAND_PAGE: [CO_BRAND_PDF], DUAL_PAGE: [DUAL_PDF]})
        self.serve_pages({CO_BRAND_PAGE: [], DUAL_PAGE: [DUAL_PDF]})
        self.routes[DUAL_PAGE] = (500, b"boom")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue((self.out / "rights_attachments" / "attachment_TSCC-11312.pdf").is_file())
        self.assertNotIn("下架", {r["result"] for r in self.attachment_records().values()})
        self.assertFalse(self.removed_dir().exists())
        self.assertIn("權益附件這次不判斷下架", result.stderr)
        self.assertIn("rights_right_right0704.docx", result.stderr)

    def test_subpage_that_always_redirects_to_another_domain_does_not_block_the_removal_judgement(self) -> None:
        # 真實官網的 Visa、Mastercard、JCB 權益子頁每次都轉址到國際組織網站：它從來沒有內容，也不提供附件連結
        pages = {DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2], INSURANCE: []}
        self.serve_pages(pages)
        self.server.redirects[INSURANCE] = self.mkp_server.base_url + "/outside/page/"
        self.assertEqual(self.run_script().returncode, 1, "轉址到外部網域的子頁讓結束碼是 1，是既有行為")
        self.serve_pages({DUAL_PAGE: [DUAL_PDF], INSURANCE: []})
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("權益附件這次不判斷下架", result.stderr)
        self.assertFalse((self.out / "rights_attachments" / "attachment_dual-card_02.pdf").exists())
        self.assertTrue((self.removed_dir() / "rights_attachments" / "attachment_dual-card_02.pdf").is_file())
        self.assertEqual(self.attachment_records()["attachment_dual-card_02.pdf"]["result"], "下架")

    def test_removal_is_not_judged_when_a_subpage_conversion_failed_and_is_judged_on_the_next_successful_run(self) -> None:
        self.first_download({DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2]})
        self.serve_pages({DUAL_PAGE: [DUAL_PDF]})
        empty_path = self.tmp / "empty_path"
        empty_path.mkdir()
        result = self.run_update(path=str(empty_path))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.out / "rights_attachments" / "attachment_dual-card_02.pdf").is_file())
        self.assertIn("權益附件這次不判斷下架", result.stderr)
        self.assertEqual(self.attachment_records()["attachment_dual-card_02.pdf"]["result"], "未變")
        retry = self.run_update()
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertEqual(self.attachment_records()["attachment_dual-card_02.pdf"]["result"], "下架")
        self.assertFalse((self.out / "rights_attachments" / "attachment_dual-card_02.pdf").exists())

    def test_removal_is_not_judged_when_the_rights_list_failed(self) -> None:
        self.first_download({DUAL_PAGE: [DUAL_PDF]})
        self.routes[RIGHTS_LIST_PATH] = (500, b"boom")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.out / "rights_attachments" / "attachment_dual-card_01.pdf").is_file())
        self.assertIn("列表「信用卡權益」", result.stderr)
        self.assertIn("權益附件這次不判斷下架", result.stderr)
        self.assertFalse(self.removed_dir().exists())

    def test_no_removal_without_update_mode(self) -> None:
        self.first_download({DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2]})
        self.serve_pages({DUAL_PAGE: [DUAL_PDF]})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.out / "rights_attachments" / "attachment_dual-card_02.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_requests_for_attachments_in_update_mode_are_spaced_by_the_configured_interval(self) -> None:
        self.first_download({DUAL_PAGE: [DUAL_PDF, DUAL_PDF_2]})
        interval = 0.3
        self.assertEqual(self.run_update(interval=str(interval)).returncode, 0)
        requests = self.server.requests
        self.assertIn(DUAL_PDF, self.server.paths())
        for earlier, later in zip(requests, requests[1:]):
            self.assertGreaterEqual(later[1] - earlier[1], interval - 0.02)


class UpdateModeExpiredOfferTests(ScriptTestCase):
    """更新模式下，已有文件的活動重新判斷是否過期，過期的連同存檔搬到 _meta/removed/<日期>/。"""

    def removed_dir(self) -> Path:
        """今天的下架資料夾 DIR/_meta/removed/<日期>/。"""
        return self.out / "_meta" / "removed" / date.today().isoformat()

    def activity_records(self) -> dict[str, dict[str, str]]:
        """下載清單中活動類別的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "活動"}

    def test_activity_that_expired_since_the_first_download_is_moved_and_recorded_as_expired_removed(self) -> None:
        self.serve_offers({"A": [[detail_path(1), detail_path(2)]]})
        self.serve_details({detail_path(n): offer_detail_html(f"OFFER{n}") for n in (1, 2)})
        self.assertEqual(self.run_script().returncode, 0)
        pdf_before = (self.out / "offers" / f"offer_{wm(1)}.pdf").read_bytes()
        html_before = (self.out / "_meta" / "html" / f"offer_{wm(1)}.html").read_bytes()
        print_before = (self.out / "_meta" / "print" / f"offer_{wm(1)}.html").read_bytes()
        period = period_from_today(-60, -1)
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", period=period)})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        removed = self.removed_dir()
        self.assertFalse((self.out / "offers" / f"offer_{wm(1)}.pdf").exists())
        self.assertFalse((self.out / "_meta" / "html" / f"offer_{wm(1)}.html").exists())
        self.assertFalse((self.out / "_meta" / "print" / f"offer_{wm(1)}.html").exists())
        self.assertEqual((removed / "offers" / f"offer_{wm(1)}.pdf").read_bytes(), pdf_before)
        self.assertEqual((removed / "html" / f"offer_{wm(1)}.html").read_bytes(), html_before)
        self.assertEqual((removed / "print" / f"offer_{wm(1)}.html").read_bytes(), print_before)
        self.assertTrue((self.out / "offers" / f"offer_{wm(2)}.pdf").is_file(), "沒過期的活動不動")
        records = self.activity_records()
        expired = records[f"offer_{wm(1)}.pdf"]
        self.assertEqual(expired["result"], "過期移除", "同一次既內容變更又過期的，記過期移除")
        self.assertEqual(expired["period"], period)
        self.assertEqual(expired["url"], self.mkp_server.base_url + detail_path(1))
        self.assertEqual(records[f"offer_{wm(2)}.pdf"]["result"], "未變")
        self.assertIn("活動：未變 1、過期移除 1", result.stdout)

    def test_activity_that_is_still_listed_is_judged_again_even_when_its_main_content_is_unchanged(self) -> None:
        # 第一次下載時活動還沒過期；更新模式的子行程把 date.today() 固定在後天，頁面本身一個字都沒變
        self.serve_offers({"A": [[detail_path(1)]]})
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", period=period_from_today(-10, 1))})
        self.assertEqual(self.run_script().returncode, 0)
        clock = self.tmp / "clock"
        clock.mkdir()
        (clock / "sitecustomize.py").write_text(SITECUSTOMIZE_CLOCK_DAY_AFTER_TOMORROW, encoding="utf-8")
        result = self.run_update(extra_env={"PYTHONPATH": str(clock)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.out / "offers" / f"offer_{wm(1)}.pdf").exists())
        self.assertEqual(self.activity_records()[f"offer_{wm(1)}.pdf"]["result"], "過期移除")


class UpdateModeOfferImageTests(ScriptTestCase):
    """更新模式下，活動圖片跟著活動走：活動沒了圖片也搬走，名額少於 8 個才補。"""

    PAST = period_from_today(-60, -1)

    def removed_images_dir(self) -> Path:
        """今天的下架資料夾裡的圖片資料夾。"""
        return self.out / "_meta" / "removed" / date.today().isoformat() / "offer_images"

    def image_name(self, number: int, extension: str = "png") -> str:
        """第 number 個假活動主視覺的本地檔名。"""
        return f"offer_image_{wm(number)}_banner_image.{extension}"

    def first_download(self, banners: dict[int, str | None]) -> None:
        """第一次下載（不開更新模式）這些活動與它們的主視覺，清掉請求紀錄。

        Args:
            banners: 活動編號對主視覺路徑（None 表示沒有主視覺），同 serve_activities。
        """
        self.serve_activities(banners)
        self.serve_images({path: PNG_BYTES + path.encode() for path in banners.values() if path is not None})
        self.assertEqual(self.run_script().returncode, 0)
        self.mkp_server.requests.clear()

    def image_records(self) -> dict[str, dict[str, str]]:
        """下載清單中活動圖片類別的紀錄，檔名對紀錄。"""
        return {r["filename"]: r for r in self.manifest() if r["category"] == "活動圖片"}

    def test_banner_of_an_expired_activity_is_moved_to_the_removed_folder_and_recorded(self) -> None:
        banners = {1: banner_path(1), 2: banner_path(2)}
        self.first_download(banners)
        image_before = (self.out / "offer_images" / self.image_name(1)).read_bytes()
        self.serve_activities(banners, periods={1: self.PAST})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in (self.out / "offer_images").iterdir()), [self.image_name(2)])
        self.assertEqual((self.removed_images_dir() / self.image_name(1)).read_bytes(), image_before)
        records = self.image_records()
        self.assertEqual(records[self.image_name(1)]["result"], "下架")
        self.assertEqual(records[self.image_name(2)]["result"], "已存在略過")
        self.assertIn("活動圖片：已存在略過 1、下架 1", result.stdout)

    def test_shared_banner_stays_while_one_activity_uses_it_and_moves_when_both_are_gone(self) -> None:
        banners = {1: banner_path(1), 2: banner_path(1), 3: banner_path(3)}
        self.first_download(banners)
        self.serve_activities(banners, periods={1: self.PAST})
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual(
            sorted(p.name for p in (self.out / "offer_images").iterdir()), [self.image_name(1), self.image_name(3)]
        )
        self.assertFalse(self.removed_images_dir().exists())
        self.serve_activities(banners, periods={1: self.PAST, 2: self.PAST})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "offer_images").iterdir()], [self.image_name(3)])
        self.assertEqual([p.name for p in self.removed_images_dir().iterdir()], [self.image_name(1)])

    def test_banner_of_an_activity_missing_from_the_list_is_moved_too(self) -> None:
        banners = {1: banner_path(1), 2: banner_path(2)}
        self.first_download(banners)
        self.serve_offers({"A": [[detail_path(2)]]})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in (self.out / "offer_images").iterdir()], [self.image_name(2)])
        self.assertEqual([p.name for p in self.removed_images_dir().iterdir()], [self.image_name(1)])

    def test_banner_whose_activity_changed_its_main_visual_url_is_moved_and_the_new_one_is_downloaded(self) -> None:
        self.first_download({1: banner_path(1)})
        new_banner = banner_path(1).replace("banner_image", "banner_image_v2")
        # 主視覺在主內容區外，所以改版時主內容區也要不同，更新模式才會換掉存檔的 HTML
        self.serve_details(
            {detail_path(1): offer_detail_html("OFFER1-REVISED", banner=self.mkp_server.base_url + new_banner)}
        )
        self.serve_images({new_banner: PNG_BYTES + b"new"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_name = self.image_name(1).replace("banner_image", "banner_image_v2")
        self.assertEqual([p.name for p in (self.out / "offer_images").iterdir()], [new_name])
        self.assertEqual((self.out / "offer_images" / new_name).read_bytes(), PNG_BYTES + b"new")
        self.assertEqual([p.name for p in self.removed_images_dir().iterdir()], [self.image_name(1)])
        records = self.image_records()
        self.assertEqual(records[new_name]["result"], "已下載")
        self.assertEqual(records[self.image_name(1)]["result"], "下架")

    def test_activity_whose_only_change_is_the_main_visual_url_is_a_content_change_and_its_image_is_replaced(self) -> None:
        self.first_download({1: banner_path(1)})
        html_path = self.out / "_meta" / "html" / f"offer_{wm(1)}.html"
        new_banner = banner_path(1).replace("banner_image", "banner_image_v2")
        # 主內容區和第一次完全相同（同一個 OFFER1），只有主內容區外的主視覺網址不同
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", banner=self.mkp_server.base_url + new_banner)})
        self.serve_images({new_banner: PNG_BYTES + b"new"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        activity = next(r for r in self.manifest() if r["category"] == "活動")
        self.assertEqual(activity["result"], "內容變更")
        self.assertIn(new_banner.encode(), html_path.read_bytes(), "存檔的原始 HTML 換成新的")
        new_name = self.image_name(1).replace("banner_image", "banner_image_v2")
        self.assertEqual([p.name for p in (self.out / "offer_images").iterdir()], [new_name])
        self.assertEqual([p.name for p in self.removed_images_dir().iterdir()], [self.image_name(1)])
        self.assertEqual(self.image_records()[new_name]["result"], "已下載")
        self.assertEqual(self.image_requests(), [new_banner])

    def test_new_main_visual_with_the_same_base_name_replaces_the_old_file_instead_of_being_skipped(self) -> None:
        self.first_download({1: banner_path(1)})
        old_bytes = (self.out / "offer_images" / self.image_name(1)).read_bytes()
        # 新舊網址只有資料夾不同，檔名一樣，所以衍生出的本地檔名一樣
        new_banner = banner_path(1).replace(UPLOAD_PREFIX, UPLOAD_PREFIX + "v2/")
        self.assertEqual(new_banner.rsplit("/", 1)[1], banner_path(1).rsplit("/", 1)[1])
        self.serve_details({detail_path(1): offer_detail_html("OFFER1", banner=self.mkp_server.base_url + new_banner)})
        self.serve_images({new_banner: PNG_BYTES + b"new"})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [new_banner])
        self.assertEqual((self.out / "offer_images" / self.image_name(1)).read_bytes(), PNG_BYTES + b"new")
        self.assertEqual((self.removed_images_dir() / self.image_name(1)).read_bytes(), old_bytes)
        results = [r["result"] for r in self.manifest() if r["category"] == "活動圖片"]
        self.assertEqual(sorted(results), ["下架", "已下載"])
        # 下一次執行：主視覺網址沒變，不再請求
        self.mkp_server.requests.clear()
        again = self.run_update()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(self.image_requests(), [])
        self.assertEqual((self.out / "offer_images" / self.image_name(1)).read_bytes(), PNG_BYTES + b"new")

    def test_banner_of_a_still_valid_activity_with_the_same_url_is_not_requested_and_not_touched(self) -> None:
        banners = {1: banner_path(1), 2: banner_path(2)}
        self.first_download(banners)
        images = [self.out / "offer_images" / self.image_name(n) for n in (1, 2)]
        for image in images:
            os.utime(image, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
        before = [(image.read_bytes(), image.stat().st_mtime_ns) for image in images]
        self.serve_images({path: b"\x89PNG\r\n\x1a\nchanged on the server" for path in banners.values()})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [])
        self.assertEqual([(image.read_bytes(), image.stat().st_mtime_ns) for image in images], before)
        self.assertFalse((self.out / "_meta" / "removed").exists() and list((self.out / "_meta" / "removed").rglob("*.png")))

    def test_nothing_about_banners_is_judged_when_the_activity_list_was_not_fetched(self) -> None:
        banners = {1: banner_path(1), 2: banner_path(2)}
        self.first_download(banners)
        self.routes[offer_list_path("A", 1)] = (500, b"boom")
        result = self.run_update()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in (self.out / "offer_images").iterdir()), [self.image_name(1), self.image_name(2)]
        )
        self.assertTrue((self.out / "offers" / f"offer_{wm(1)}.pdf").is_file())
        self.assertFalse((self.out / "_meta" / "removed").exists())

    def test_activity_that_appears_in_front_does_not_push_out_the_existing_banners(self) -> None:
        banners = {n: banner_path(n) for n in range(1, 11)}
        self.first_download(banners)
        self.assertEqual(len(list((self.out / "offer_images").iterdir())), 8)
        self.serve_offers({"A": [[detail_path(n) for n in (11, *range(1, 11))]]})
        self.serve_details({detail_path(11): offer_detail_html("OFFER11", banner=self.mkp_server.base_url + banner_path(11))})
        self.serve_images({banner_path(11): PNG_BYTES})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [])
        self.assertEqual(
            sorted(p.name for p in (self.out / "offer_images").iterdir()), [self.image_name(n) for n in range(1, 9)]
        )
        self.assertFalse((self.out / "_meta" / "removed").exists() and list((self.out / "_meta" / "removed").rglob("*.png")))

    def test_slot_freed_by_an_expired_activity_is_filled_by_the_next_activity_in_discovery_order(self) -> None:
        banners = {n: banner_path(n) for n in range(1, 11)}
        self.first_download(banners)
        self.serve_activities(banners, periods={1: self.PAST})
        self.serve_images({banner_path(n): PNG_BYTES for n in (9, 10)})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [banner_path(9)])
        self.assertEqual(
            sorted(p.name for p in (self.out / "offer_images").iterdir()), [self.image_name(n) for n in range(2, 10)]
        )

    def test_activity_with_a_changed_banner_url_is_filled_before_the_others(self) -> None:
        banners = {n: banner_path(n) for n in range(1, 11)}
        self.first_download(banners)
        new_banner = banner_path(10).replace("banner_image", "banner_image_v2")
        self.serve_activities(banners, periods={1: self.PAST})
        # 活動 10 還沒有圖片（名額用滿），改版換了主視覺網址：它排在活動 9 前面
        self.serve_details(
            {detail_path(10): offer_detail_html("OFFER10-REVISED", banner=self.mkp_server.base_url + new_banner)}
        )
        self.serve_images({new_banner: PNG_BYTES, banner_path(9): PNG_BYTES})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [new_banner])
        self.assertIn(
            self.image_name(10).replace("banner_image", "banner_image_v2"),
            [p.name for p in (self.out / "offer_images").iterdir()],
        )
        self.assertNotIn(self.image_name(9), [p.name for p in (self.out / "offer_images").iterdir()])

    def test_banners_with_the_same_base_name_get_the_same_file_name_in_download_and_in_update(self) -> None:
        # 活動 8、9 的主視覺只有資料夾不同、檔名相同：兩個都要加雜湊後綴；第一次下載只取前 8 個（只有活動 8），
        # 但檔名要用全部活動的主視覺網址算，更新模式才認得剛下載的圖，不會搬走又重新下載
        banners = {n: banner_path(n) for n in range(1, 8)}
        banners[8] = f"{UPLOAD_PREFIX}dirB/dup_banner.png"
        banners[9] = f"{UPLOAD_PREFIX}dirC/dup_banner.png"
        self.first_download(banners)
        folder = self.out / "offer_images"
        names = sorted(p.name for p in folder.iterdir())
        self.assertEqual(len(names), 8)
        self.assertRegex(names[-1], r"^offer_image_dup_banner_[0-9a-f]{8}\.png$")
        for _ in range(2):
            result = self.run_update()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.image_requests(), [])
            self.assertEqual(sorted(p.name for p in folder.iterdir()), names)
            self.assertFalse((self.out / "_meta" / "removed").exists() and list((self.out / "_meta" / "removed").rglob("*.png")))
            self.assertEqual(self.image_records()[names[-1]]["result"], "已存在略過")

    def test_report_says_so_when_there_are_not_enough_candidates_to_fill_8_slots(self) -> None:
        self.first_download({1: banner_path(1), 2: banner_path(2), 3: None})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("活動圖片名額 2/8，沒有更多候選", result.stdout)

    def test_unsupported_format_banner_still_takes_a_slot_and_a_failed_download_does_not(self) -> None:
        banners = {1: banner_path(1, "svg"), **{n: banner_path(n) for n in range(2, 10)}}
        self.serve_activities(banners)
        # 活動 2 的圖片第一次下載失敗，沒有留檔
        self.serve_images({banner_path(n): PNG_BYTES for n in range(3, 10)})
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(len(list((self.out / "offer_images").iterdir())), 6, "活動 1 是 svg 不下載、活動 2 失敗、活動 9 沒有名額")
        self.mkp_server.requests.clear()
        self.serve_images({banner_path(2): PNG_BYTES, banner_path(9): PNG_BYTES})
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.image_requests(), [banner_path(2)], "svg 佔 1 個、現有 6 張佔 6 個，只剩 1 個名額，補活動 2")


if __name__ == "__main__":
    unittest.main()
