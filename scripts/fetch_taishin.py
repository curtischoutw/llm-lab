"""下載台新銀行信用卡的官網內容到本地資料夾，作為知識庫的來源文件。

為什麼存在：知識庫要用台新信用卡的卡片頁、權益說明、文件下載區與刷卡優惠活動頁（約 140 份）。
這些內容不進版本控管，所以用這支腳本讓任何機器都能用一個指令重建同一批內容。

用法：
    python3 scripts/fetch_taishin.py [--out DIR]
    預設輸出到 repo 根目錄下的 data/taishin_credit_card。

目前涵蓋的類別：
- 卡片：總覽頁列出的卡片頁，列印成 PDF，放在 DIR/cards/。
- 權益：權益頁列出的權益說明子頁，用 LibreOffice 轉成 .docx，放在 DIR/rights/。
- 下載：文件下載區每一頁列出的 PDF（約定條款、費用表、申請書等），不轉檔、原樣存檔，放在 DIR/downloads/。

輸出結構：
- DIR/<類別資料夾>/：匯入知識庫的文件，每個類別一個資料夾（ingest 不遞迴，一次匯入一個資料夾）。
- DIR/_meta/html/：每一個網頁（卡片頁、權益子頁）的原始 HTML；下載區的 PDF 不是網頁，沒有。
- DIR/_meta/print/：取出主內容區後交給 Chrome 或 LibreOffice 的本機 HTML。
- DIR/_meta/manifest.jsonl：下載清單，一行一份文件。_meta 不會被匯入。

關鍵設計決策：
- 直接列印原網址會漏掉收合區與彈窗：2026-10-30 實測 Richart 卡片頁的 PDF 只有 2 頁、1,074 字，
  原始 HTML 的可見文字是 36,767 字，「23:59」與「天天刷」都是 0 次。官網 CSS 讓預設收合的區塊與彈窗在列印時不顯示。
  所以先從原始 HTML 取出主內容區（卡片頁是 id="centercontainer"），拿掉其中的 <script> 與 <style>，
  包成只帶固定列印用 CSS 與 <base href>（指回原網址）的本機 HTML，再交給 Chrome。
  這樣列印出的版面是純 HTML 的排版，不像官網。
- 找不到主內容區的頁面記為失敗，原因寫「找不到主內容區」，不退回列印整頁。
- 權益子頁和卡片頁共用同一套流程（下載、取主內容區、轉檔、清單、略過、失敗處理），只有轉檔的外部命令不同：
  `<libreoffice 或 soffice> --headless --convert-to "docx:MS Word 2007 XML" --outdir <資料夾> <HTML 檔>`。
  目標一定要寫完整的濾鏡名稱：2026-10-30 實測，LibreOffice 把 HTML 當成 Writer/Web 文件開啟，
  目標只寫 docx 會回報 "no export filter"。LibreOffice 沿用 RAG-Anything 的找法，在 PATH 上依序找
  libreoffice、soffice；找不到時，每一個權益子頁各自記為失敗。轉檔不受官網 CSS 影響，取主內容區是為了去掉導覽選單。
- 本地檔名由網址路徑組成並加類別前綴（卡片 card_cg047_card001，權益 rights_insurance_right0201，
  下載 download_word_CR04131_1150B），整批唯一。前綴也讓以 - 開頭的 PDF 檔名（真實有 -_11407.pdf）不會變成以 - 開頭。
  檔名中字母、數字、底線、. 與 - 以外的字元換成底線；同一類別裡兩個網址組出同一個檔名時（不分大小寫），兩者都加上完整網址的
  SHA-256 前 8 碼，所以檔名只取決於這一批網址。
- 文件下載區：從第 1 頁起用 `?nav1=credit&nav2=file-download&page=N` 往後翻，直到某一頁沒有新的 PDF 連結為止。
  官網超過最後一頁時回 200 並重複最後一頁（2026-10-30 調查：page=3 與 page=99 都等於 page=2），不是空清單，
  所以「沒有新連結」會在最後一頁的下一頁停下來（目前 2 頁，發 3 個請求）。
  PDF 的 href 是只有路徑的相對網址，補上列表頁的網域；只收和列表頁同一個網域、路徑以 .pdf 結尾的連結，網址去除重複。
  PDF 是不可信資料：存檔前確認內容以 `%PDF-` 開頭，不是的話（例如錯誤頁的 HTML）那一份記為失敗，不存檔。
- 單頁失敗（HTTP、網路、轉檔、檔案系統）時記下原因，其他頁照常處理；最後列出所有失敗的頁面並以非零碼結束。
  列表頁（總覽頁、權益頁、文件下載頁的任何一頁）本身失敗時，那一類沒有任何網址，指出是哪一個列表；
  其他類別照常處理，最後以非零碼結束。
- 再次執行時，本地檔案已存在就略過（不發請求）並記入清單；要更新內容時刪除資料夾後重新下載。
- 請求間隔：腳本自己發出的每個 HTTP 請求之間至少 TAISHIN_REQUEST_INTERVAL_SEC 秒（預設 2）。
  這個環境變數只給測試調小。
- 環境變數 TAISHIN_WWW_BASE 取代 https://www.taishinbank.com.tw 前綴，只給測試指向本機假 server 用。
  TAISHIN_CHROME 指定 Chrome 執行檔，預設是 macOS 上 Google Chrome 的標準安裝路徑。
- Chrome 列印時使用暫時的使用者資料夾，不用使用者自己的 Chrome profile。
- 下載的內容是不可信資料：腳本不執行它們；外部命令用參數列表呼叫。

已知極限：
- Chrome 與 LibreOffice 透過 <base href> 自行載入圖片，這些請求不受腳本的間隔控制。
- 官網改版時，列表頁的連結格式或 id="centercontainer" 可能失效；總覽頁找到的卡片數不是 16、
  權益頁找到的子頁數不是 46、下載區找到的 PDF 數不是 19 時，腳本會印出實際數量提醒，但不中止。
- 翻頁上限 DOWNLOAD_MAX_PAGES（ASSUMPTION：20，目前實際只有 2 頁）。翻滿上限仍有新的 PDF 時，
  視為下載頁失敗（官網改版或不再重複最後一頁的徵兆），而不是無限翻頁。
- 只確認 PDF 以 `%PDF-` 開頭，不檢查檔案是否完整、能不能開啟（ASSUMPTION）。

Dependencies: 僅標準函式庫；列印需要 Google Chrome，轉 .docx 需要 LibreOffice。
"""

import argparse
import hashlib
import html
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

# ==============================
# 設定
# ==============================

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "taishin_credit_card"
USER_AGENT = "llm-lab-fetch-taishin/1.0 (personal RAG knowledge base)"
TIMEOUT_SEC = 60
CHROME_TIMEOUT_SEC = 180

WWW_PREFIX = "https://www.taishinbank.com.tw"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_INTERVAL_SEC = 2.0

OFFICE_COMMANDS = ("libreoffice", "soffice")
OFFICE_TIMEOUT_SEC = 180
# 目標要寫完整的濾鏡名稱：HTML 是 Writer/Web 文件，只寫 docx 會回報 "no export filter"
DOCX_TARGET = "docx:MS Word 2007 XML"

FORMAT_PDF = "PDF"
FORMAT_DOCX = "DOCX"

# 文件下載區：翻頁上限（ASSUMPTION，目前實際 2 頁）與 PDF 檔頭
DOWNLOAD_MAX_PAGES = 20
PDF_MAGIC = b"%PDF-"

# 網路失敗的例外：連線／逾時／重設／HTTP 狀態錯誤（OSError，HTTPError 與 URLError 都是其子類）與讀 body
# 到一半斷線的 http.client.IncompleteRead 等（HTTPException，不是 OSError）
NETWORK_ERRORS = (OSError, http.client.HTTPException)

CHROME_ENV = "TAISHIN_CHROME"
INTERVAL_ENV = "TAISHIN_REQUEST_INTERVAL_SEC"
WWW_BASE_ENV = "TAISHIN_WWW_BASE"

# 固定的列印用 CSS：圖片不超出頁寬，表格有框線
PRINT_CSS = "img{max-width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #999;padding:2px}"

RESULT_DOWNLOADED = "已下載"
RESULT_SKIPPED = "已存在略過"
RESULT_FAILED = "失敗"


class FetchError(Exception):
    """某一頁無法完成下載或轉檔；訊息是寫進清單的失敗原因。"""


@dataclass
class Record:
    """下載清單的一行：一份文件的來源、本地檔案與結果。"""

    url: str
    category: str
    filename: str
    format: str
    downloaded_at: str
    sha256: str
    html_sha256: str
    result: str
    detail: str


# ==============================
# HTTP
# ==============================


class Fetcher:
    """腳本自己發出的 HTTP 請求：帶 User-Agent，每個請求之間至少間隔 interval 秒。"""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._last_end = float("-inf")

    def get(self, url: str) -> bytes:
        """GET url。

        Args:
            url: 完整網址。

        Returns:
            回應 body。網路失敗或 HTTP 狀態錯誤時拋出 FetchError。
        """
        wait = self._last_end + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return resp.read()
        except NETWORK_ERRORS as exc:
            raise FetchError(f"下載失敗（{type(exc).__name__}: {exc}）") from exc
        finally:
            self._last_end = time.monotonic()


# ==============================
# HTML 解析：連結與主內容區
# ==============================


class _AnchorCollector(HTMLParser):
    """收集 <a href>（script 與 style 的內容由 HTMLParser 當成文字，不會被解析成標籤）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def find_page_links(list_html: str, list_url: str, link_pattern: re.Pattern[str]) -> list[str]:
    """從列表頁取出子頁的網址。

    Args:
        list_html: 列表頁 HTML。
        list_url: 列表頁網址，用來解析相對路徑。
        link_pattern: 子頁連結的路徑格式；選單、PDF 等其他連結不符合就不收。

    Returns:
        去除重複、保留出現順序的子頁完整網址（不含 query）。
    """
    collector = _AnchorCollector()
    collector.feed(list_html)
    seen: dict[str, None] = {}
    for href in collector.hrefs:
        absolute = urljoin(list_url, href)
        if link_pattern.match(urlparse(absolute).path) and not urlparse(absolute).query:
            seen[absolute] = None
    return list(seen)


class _MainContentFinder(HTMLParser):
    """找出 id 等於 target_id 的元素，記下它的起訖位置。

    只數同名標籤的開始與結束（例如 div），所以內容裡未關閉的 <p>、<li> 不影響配對。
    """

    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=False)
        self.target_id = target_id
        self.tag: str | None = None
        self.depth = 0
        self.start: tuple[int, int] | None = None
        self.end: tuple[int, int] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.end is not None:
            return
        if self.start is None:
            if dict(attrs).get("id") == self.target_id:
                self.tag, self.depth, self.start = tag, 1, self.getpos()
        elif tag == self.tag:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.start is None or self.end is not None or tag != self.tag:
            return
        self.depth -= 1
        if self.depth == 0:
            self.end = self.getpos()


def extract_main_content(page_html: str, element_id: str) -> str | None:
    """取出 id 等於 element_id 的元素（含自身），並拿掉其中的 <script> 與 <style>。

    Args:
        page_html: 原始 HTML。
        element_id: 主內容區的 id。

    Returns:
        主內容區的 HTML；找不到、或元素沒有結束標籤時為 None。
    """
    finder = _MainContentFinder(element_id)
    finder.feed(page_html)
    finder.close()
    if finder.start is None or finder.end is None:
        return None
    offsets = [0]
    for line in page_html.split("\n"):
        offsets.append(offsets[-1] + len(line) + 1)
    begin = offsets[finder.start[0] - 1] + finder.start[1]
    close = offsets[finder.end[0] - 1] + finder.end[1]
    stop = page_html.index(">", close) + 1
    fragment = page_html[begin:stop]
    fragment = re.sub(r"(?is)<script\b[^>]*>.*?</script\s*>", "", fragment)
    return re.sub(r"(?is)<style\b[^>]*>.*?</style\s*>", "", fragment)


def build_print_html(main_content: str, base_url: str) -> str:
    """把主內容區包成可列印的本機 HTML。

    Args:
        main_content: 主內容區的 HTML。
        base_url: 原網址，寫進 <base href> 讓相對路徑的圖片可以載入。

    Returns:
        完整的 HTML 文件。
    """
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<base href="{html.escape(base_url, quote=True)}">'
        f"<style>{PRINT_CSS}</style></head><body>{main_content}</body></html>"
    )


# ==============================
# 轉檔
# ==============================


def print_to_pdf(chrome: str, html_path: Path, pdf_path: Path, work_dir: Path) -> None:
    """用 headless Chrome 把本機 HTML 檔列印成 PDF，使用暫時的使用者資料夾。

    Args:
        chrome: Chrome 執行檔路徑。
        html_path: 要列印的本機 HTML 檔。
        pdf_path: 最終 PDF 路徑；列印成功才會出現。
        work_dir: 放暫時資料夾的位置（與 pdf_path 同一個檔案系統）。

    Raises:
        FetchError: Chrome 不存在、列印失敗、逾時或沒有產出 PDF。
    """
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        tmp_pdf = Path(tmp) / "page.pdf"
        command = [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--print-to-pdf={tmp_pdf}",
            html_path.resolve().as_uri(),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=CHROME_TIMEOUT_SEC)
        except subprocess.TimeoutExpired as exc:
            raise FetchError(f"Chrome 列印逾時（{CHROME_TIMEOUT_SEC} 秒）") from exc
        except OSError as exc:
            raise FetchError(
                f"無法執行 Chrome（{chrome}）：{exc}；用環境變數 {CHROME_ENV} 指定 Chrome 執行檔的路徑"
            ) from exc
        if completed.returncode != 0:
            raise FetchError(f"Chrome 列印失敗（結束碼 {completed.returncode}）：{completed.stderr.strip()[-300:]}")
        if not tmp_pdf.is_file() or tmp_pdf.stat().st_size == 0:
            raise FetchError("Chrome 結束碼為 0，但沒有產出 PDF")
        tmp_pdf.replace(pdf_path)


def find_office() -> str | None:
    """在 PATH 上依序找 libreoffice、soffice（沿用 RAG-Anything 的找法）。

    Returns:
        第一個找到的命令路徑；都找不到時為 None。
    """
    for name in OFFICE_COMMANDS:
        found = shutil.which(name)
        if found:
            return found
    return None


def convert_to_docx(office: str | None, html_path: Path, docx_path: Path, work_dir: Path) -> None:
    """用 LibreOffice 把本機 HTML 檔轉成 .docx。

    Args:
        office: LibreOffice 命令路徑；None 表示 PATH 上找不到。
        html_path: 要轉檔的本機 HTML 檔；LibreOffice 輸出的檔名由它的主檔名決定。
        docx_path: 最終 .docx 路徑（主檔名必須和 html_path 相同）；轉檔成功才會出現。
        work_dir: 放暫時資料夾的位置（與 docx_path 同一個檔案系統）。

    Raises:
        FetchError: 找不到 LibreOffice、轉檔失敗、逾時或沒有產出 .docx。
    """
    if office is None:
        raise FetchError(f"找不到 LibreOffice（PATH 上沒有 {' 或 '.join(OFFICE_COMMANDS)}）")
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        command = [office, "--headless", "--convert-to", DOCX_TARGET, "--outdir", tmp, str(html_path.resolve())]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=OFFICE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired as exc:
            raise FetchError(f"LibreOffice 轉檔逾時（{OFFICE_TIMEOUT_SEC} 秒）") from exc
        except OSError as exc:
            raise FetchError(f"無法執行 LibreOffice（{office}）：{exc}") from exc
        if completed.returncode != 0:
            raise FetchError(
                f"LibreOffice 轉檔失敗（結束碼 {completed.returncode}）：{completed.stderr.strip()[-300:]}"
            )
        tmp_docx = Path(tmp) / docx_path.name
        if not tmp_docx.is_file() or tmp_docx.stat().st_size == 0:
            raise FetchError("LibreOffice 結束碼為 0，但沒有產出 .docx")
        tmp_docx.replace(docx_path)


# ==============================
# 一次執行共用的東西與類別
# ==============================


@dataclass(frozen=True)
class Tools:
    """轉檔用的外部命令：Chrome 的路徑，以及 PATH 上找到的 LibreOffice（找不到為 None）。"""

    chrome: str
    office: str | None


@dataclass(frozen=True)
class Run:
    """一次執行共用的設定：資料根目錄、官網網域前綴、發請求的物件、轉檔工具。"""

    out: Path
    www: str
    fetcher: Fetcher
    tools: Tools


@dataclass(frozen=True)
class Category:
    """一個類別：從哪個列表頁找文件、文件怎麼取得、放在哪個資料夾。

    collect 的參數是 (執行設定, 類別)，回傳文件的完整網址（去除重複、保留順序），列表頁失敗時拋出 FetchError。
    produce 的參數是 (執行設定, 類別, 網址, 本地名稱, 最終檔案, 清單紀錄)，把文件寫到最終檔案、
    補上紀錄的 html_sha256（有原始 HTML 的類別），失敗時拋出 FetchError。
    local_name 由 name_prefix 和 link_pattern 的各個群組以底線接起來，例如卡片 card_cg047_card001。
    """

    name: str
    list_label: str
    list_name: str
    list_path: str
    link_pattern: re.Pattern[str]
    expected_count: int
    unit: str
    name_prefix: str
    folder: str
    extension: str
    fmt: str
    keeps_html: bool
    collect: Callable[["Run", "Category"], list[str]]
    produce: Callable[["Run", "Category", str, str, Path, "Record"], None]

    def local_name(self, url: str) -> str:
        """由文件網址組出本地檔名（不含副檔名）；路徑先做百分比解碼，字母、數字、底線、. 與 - 以外的字元換成底線。"""
        match = self.link_pattern.match(unquote(urlparse(url).path))
        assert match is not None, url
        parts = (re.sub(r"[^\w.-]", "_", group) for group in match.groups())
        return "_".join((self.name_prefix, *parts))

    def local_names(self, urls: list[str]) -> dict[str, str]:
        """為一批網址組出本地檔名；檔名相同（不分大小寫）的網址都加上完整網址的 SHA-256 前 8 碼。

        Args:
            urls: 這個類別的文件網址。

        Returns:
            網址對本地檔名（不含副檔名）；值在整批中不重複。
        """
        names = {url: self.local_name(url) for url in urls}
        counts = Counter(name.lower() for name in names.values())
        return {
            url: name if counts[name.lower()] == 1 else f"{name}_{hashlib.sha256(url.encode()).hexdigest()[:8]}"
            for url, name in names.items()
        }


# ==============================
# 列表頁與取得文件
# ==============================


def decode_page(raw: bytes) -> str:
    """把頁面的位元組解成 UTF-8 文字。

    Args:
        raw: 回應 body。

    Returns:
        頁面文字。不是 UTF-8 時拋出 FetchError。
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError(f"頁面不是 UTF-8（{exc}）") from exc


def sha256_of(path: Path) -> str:
    """回傳檔案內容的 SHA-256 十六進位字串。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_from_one_page(run: Run, category: Category) -> list[str]:
    """從單一列表頁取出子頁網址（卡片、權益）。

    Args:
        run: 一次執行共用的設定。
        category: 要找文件的類別。

    Returns:
        子頁完整網址。列表頁失敗時拋出 FetchError。
    """
    list_url = run.www + category.list_path
    return find_page_links(decode_page(run.fetcher.get(list_url)), list_url, category.link_pattern)


def find_pdf_links(list_html: str, list_url: str, link_pattern: re.Pattern[str]) -> list[str]:
    """從文件下載頁取出 PDF 的網址。

    Args:
        list_html: 下載頁 HTML。
        list_url: 下載頁網址，用來解析相對路徑，也限定只收同一個網域。
        link_pattern: PDF 連結的路徑格式。

    Returns:
        去除重複、保留出現順序的 PDF 完整網址；路徑中 ASCII 以外的字元已做百分比編碼，網址才能送出請求。
    """
    collector = _AnchorCollector()
    collector.feed(list_html)
    host = urlparse(list_url).netloc
    seen: dict[str, None] = {}
    for href in collector.hrefs:
        parsed = urlparse(urljoin(list_url, href))
        if parsed.netloc == host and link_pattern.match(parsed.path):
            seen[urlunparse(parsed._replace(path=quote(parsed.path, safe="/%"), fragment=""))] = None
    return list(seen)


def collect_from_paged_downloads(run: Run, category: Category) -> list[str]:
    """從文件下載頁的第 1 頁往後翻，直到某一頁沒有新的 PDF 連結為止。

    官網超過最後一頁時回 200 並重複最後一頁，所以停止條件是「沒有新連結」，不是空清單。

    Args:
        run: 一次執行共用的設定。
        category: 文件下載類別；list_path 含 query，翻頁時在後面加 &page=N。

    Returns:
        所有頁面的 PDF 完整網址（去除重複）。任何一頁失敗，或翻滿 DOWNLOAD_MAX_PAGES 頁仍有新的 PDF 時拋出 FetchError。
    """
    list_url = run.www + category.list_path
    found: dict[str, None] = {}
    for number in range(1, DOWNLOAD_MAX_PAGES + 1):
        page_url = f"{list_url}&page={number}"
        try:
            page_links = find_pdf_links(decode_page(run.fetcher.get(page_url)), page_url, category.link_pattern)
        except FetchError as exc:
            raise FetchError(f"第 {number} 頁（{page_url}）：{exc}") from exc
        new = [link for link in page_links if link not in found]
        if not new:
            return list(found)
        found.update(dict.fromkeys(new))
    raise FetchError(f"翻到上限 {DOWNLOAD_MAX_PAGES} 頁仍有新的 PDF 連結，停止翻頁")


def web_page_producer(
    convert: Callable[[Tools, Path, Path, Path], None],
) -> Callable[[Run, Category, str, str, Path, Record], None]:
    """產生「下載網頁、取出主內容區、轉檔」的 produce 函式。

    Args:
        convert: 轉檔函式，參數是 (工具, 本機 HTML, 最終檔案, 暫時資料夾的位置)，失敗時拋出 FetchError。

    Returns:
        可放進 Category.produce 的函式。
    """

    def produce(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> None:
        raw_path = run.out / "_meta" / "html" / f"{name}.html"
        print_path = run.out / "_meta" / "print" / f"{name}.html"
        for folder in (raw_path.parent, print_path.parent):
            folder.mkdir(parents=True, exist_ok=True)
        raw = run.fetcher.get(url)
        raw_path.write_bytes(raw)
        record.html_sha256 = hashlib.sha256(raw).hexdigest()
        main_content = extract_main_content(decode_page(raw), "centercontainer")
        if main_content is None:
            raise FetchError("找不到主內容區")
        print_path.write_text(build_print_html(main_content, url), encoding="utf-8")
        convert(run.tools, print_path, target, run.out / "_meta")

    return produce


def save_pdf(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> None:
    """下載 PDF，確認檔頭是 %PDF- 後原樣存檔（先寫暫時檔，成功才換成最終檔案）。

    Args:
        run: 一次執行共用的設定。
        category: PDF 所屬的類別（未使用，為了符合 Category.produce 的參數）。
        url: PDF 完整網址。
        name: 本地名稱（未使用，為了符合 Category.produce 的參數）。
        target: 最終檔案路徑。
        record: 清單紀錄（PDF 沒有原始 HTML，不改它）。

    Raises:
        FetchError: 下載失敗，或內容不是以 %PDF- 開頭（例如伺服器回了錯誤頁的 HTML）。
    """
    data = run.fetcher.get(url)
    if not data.startswith(PDF_MAGIC):
        raise FetchError(f"下載的內容不是 PDF（開頭不是 {PDF_MAGIC.decode()}，共 {len(data)} bytes）")
    with tempfile.TemporaryDirectory(dir=run.out / "_meta") as tmp:
        tmp_pdf = Path(tmp) / "download.pdf"
        tmp_pdf.write_bytes(data)
        tmp_pdf.replace(target)


CARDS = Category(
    name="卡片",
    list_label="總覽頁",
    list_name="信用卡總覽",
    list_path="/TSB/personal/credit/intro/overview/",
    link_pattern=re.compile(r"^/TSB/personal/credit/intro/overview/(cg\d+)/(card\d+)/$"),
    expected_count=16,
    unit="張卡片頁",
    name_prefix="card",
    folder="cards",
    extension="pdf",
    fmt=FORMAT_PDF,
    keeps_html=True,
    collect=collect_from_one_page,
    produce=web_page_producer(
        lambda tools, html_path, target, work_dir: print_to_pdf(tools.chrome, html_path, target, work_dir)
    ),
)
RIGHTS = Category(
    name="權益",
    list_label="權益頁",
    list_name="信用卡權益",
    list_path="/TSB/personal/credit/intro/rights/",
    # 子頁是權益頁底下 <群組>/<頁名>/ 兩層；選單只連到權益頁自己，不符合這個格式。頁名可以是 -00001 這種怪名字
    link_pattern=re.compile(r"^/TSB/personal/credit/intro/rights/([^/]+)/([^/]+)/$"),
    expected_count=46,
    unit="個權益子頁",
    name_prefix="rights",
    folder="rights",
    extension="docx",
    fmt=FORMAT_DOCX,
    keeps_html=True,
    collect=collect_from_one_page,
    produce=web_page_producer(
        lambda tools, html_path, target, work_dir: convert_to_docx(tools.office, html_path, target, work_dir)
    ),
)
DOWNLOADS = Category(
    name="下載",
    list_label="下載頁",
    list_name="文件下載",
    list_path="/TSB/personal/common/download/index.html?nav1=credit&nav2=file-download",
    # PDF 在 /TSB/export/sites/TSB/ 底下有三種前綴；任何以 .pdf 結尾的路徑都收，檔名（含 - 或 _ 開頭的）取最後一段
    link_pattern=re.compile(r"^/(?:.*/)?([^/]+)\.pdf$", re.IGNORECASE),
    expected_count=19,
    unit="個 PDF",
    name_prefix="download",
    folder="downloads",
    extension="pdf",
    fmt=FORMAT_PDF,
    keeps_html=False,
    collect=collect_from_paged_downloads,
    produce=save_pdf,
)
CATEGORIES = (CARDS, RIGHTS, DOWNLOADS)


def fetch_document(run: Run, category: Category, url: str, name: str) -> Record:
    """取得一份文件：已存在就略過，否則呼叫類別的 produce。

    Args:
        run: 一次執行共用的設定。
        category: 這份文件所屬的類別。
        url: 文件完整網址。
        name: 本地名稱（不含副檔名）。

    Returns:
        下載清單的一筆紀錄；失敗時 result 是「失敗」，detail 是原因。
    """
    filename = f"{name}.{category.extension}"
    record = Record(url, category.name, filename, category.fmt, date.today().isoformat(), "", "", RESULT_FAILED, "")
    target = run.out / category.folder / filename
    try:
        if target.is_file():
            raw_path = run.out / "_meta" / "html" / f"{name}.html"
            record.downloaded_at = date.fromtimestamp(target.stat().st_mtime).isoformat()
            record.sha256 = sha256_of(target)
            record.html_sha256 = sha256_of(raw_path) if category.keeps_html and raw_path.is_file() else ""
            record.result = RESULT_SKIPPED
            return record
        target.parent.mkdir(parents=True, exist_ok=True)
        (run.out / "_meta").mkdir(parents=True, exist_ok=True)
        category.produce(run, category, url, name, target, record)
        record.sha256 = sha256_of(target)
        record.result = RESULT_DOWNLOADED
    except FetchError as exc:
        record.detail = str(exc)
    except OSError as exc:
        record.detail = f"檔案系統錯誤（{type(exc).__name__}: {exc}）"
    return record


# ==============================
# 主程式
# ==============================


def write_manifest(out: Path, records: list[Record]) -> None:
    """把這次執行的紀錄寫成下載清單（JSON Lines，一行一份文件）。

    Args:
        out: 資料根目錄。
        records: 紀錄清單。
    """
    manifest = out / "_meta" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令列參數。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        含 out（Path）的 Namespace。
    """
    parser = argparse.ArgumentParser(description="下載台新銀行信用卡官網的內容，作為知識庫的來源文件。")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"輸出資料夾（預設 {DEFAULT_OUT}）")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """下載總覽頁列出的卡片頁、權益頁列出的權益子頁與文件下載區的 PDF。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        0 全部成功；1 有任何一頁或列表失敗（stderr 指出是哪一個）；2 命令列或環境變數設定錯誤。
    """
    args = parse_args(argv)
    www = os.environ.get(WWW_BASE_ENV, WWW_PREFIX).rstrip("/")
    chrome = os.environ.get(CHROME_ENV, DEFAULT_CHROME)
    try:
        interval = float(os.environ.get(INTERVAL_ENV, DEFAULT_INTERVAL_SEC))
    except ValueError:
        print(f"ERROR 環境變數 {INTERVAL_ENV} 必須是數字（秒）", file=sys.stderr)
        return 2
    if interval < 0:
        print(f"ERROR 環境變數 {INTERVAL_ENV} 不可以是負數", file=sys.stderr)
        return 2
    if args.out.exists() and not args.out.is_dir():
        print(f"ERROR --out {args.out} 已存在但不是資料夾", file=sys.stderr)
        return 2
    run = Run(args.out, www, Fetcher(interval), Tools(chrome, find_office()))

    records: list[Record] = []
    failed_lists: list[str] = []
    for category in CATEGORIES:
        list_url = www + category.list_path
        try:
            urls = category.collect(run, category)
        except FetchError as exc:
            print(f"ERROR 列表「{category.list_name}」（{list_url}）失敗：{exc}", file=sys.stderr)
            failed_lists.append(category.list_name)
            continue
        print(f"{category.list_label}找到 {len(urls)} {category.unit}（預期 {category.expected_count}）")
        names = category.local_names(urls)
        records.extend(fetch_document(run, category, url, names[url]) for url in urls)

    write_manifest(args.out, records)
    for r in records:
        print(f"{r.result} {r.category} {r.filename}")
    failed = [r for r in records if r.result == RESULT_FAILED]
    for r in failed:
        print(f"FAILED {r.url}（{r.filename}）：{r.detail}", file=sys.stderr)
    return 1 if failed or failed_lists else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
