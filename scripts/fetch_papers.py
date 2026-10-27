"""下載 RAG 主題 arXiv 論文到本地資料夾，作為可重現的評估語料。

為什麼存在：後續匯入與評估（ticket 03–06）需要同一批含圖表的論文。PDF 不進版本控管，
所以用這支腳本讓任何人都能用一個指令重建語料。

用法：
    python3 scripts/fetch_papers.py [--out DIR] [--ids ID [ID ...]]
    預設輸出到 repo 根目錄下的 data/papers；--ids 只能是下方清單的子集。

關鍵設計決策：
- 先驗證所有 ID 格式與是否在清單內，再發任何網路請求；不合法就非零碼結束並指出該 ID。
- 以 arXiv 官方 API（export.arxiv.org/api/query）一次取回全部標題，與 PAPERS 的預期標題
  比對；任何一篇不符就中止，一篇都不下載。標題比對在每次執行都做，包含檔案已存在時。
- 檔案已存在且完整（%PDF 開頭、尾端有 %%EOF）就略過；下載先寫 .part 並核對
  Content-Length，確認完整才改名，避免中斷後留下殘缺檔被當成完整。
- 任何失敗（網路、HTTP、標題不符、檔案殘缺）都以非零碼結束並指出是哪個 ID，不略過後繼續。
- 遵守 arXiv 使用規範：所有對 arXiv 的請求之間至少間隔 3 秒，並帶可辨識的 User-Agent。
- 網路失敗包含連線重設與讀 body 到一半斷線（http.client.IncompleteRead 不是 OSError，要一併攔）。
- 環境變數 FETCH_PAPERS_ARXIV_BASE 可改寫 arXiv 位址，只給測試指向本機假 server 用。
- 頁數不依賴第三方 PDF 套件：解壓縮 ObjStm 後讀取頁面樹根節點的 /Count。

已知極限：
- 頁數是從 PDF 結構啟發式解析（取所有 /Type /Pages 節點中最大的 /Count），找不到
  節點時顯示 "?"；ObjStm 若不是 Flate 壓縮會拋 zlib.error（arXiv 的 pdfTeX 產物沒有此情況）。
- 只支援新式 arXiv ID（YYMM.NNNNN）；不鎖定版本，下載的是當下最新版。

Dependencies: 僅標準函式庫。
"""

import argparse
import http.client
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

# ==============================
# 設定
# ==============================

# (arXiv ID, 預期標題)。RAG-Anything 的 ID 由官方 API 以標題查出（2025-10-14 發表）。
PAPERS: dict[str, str] = {
    "2005.11401": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    "2404.16130": "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
    "2410.05779": "LightRAG: Simple and Fast Retrieval-Augmented Generation",
    "2310.11511": "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
    "2510.12323": "RAG-Anything: All-in-One RAG Framework",
}

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "papers"
# ASSUMPTION：環境變數 FETCH_PAPERS_ARXIV_BASE 可改寫 arXiv 位址，唯一用途是讓測試把腳本指向本機假 server
ARXIV_BASE = os.environ.get("FETCH_PAPERS_ARXIV_BASE", "https://export.arxiv.org").rstrip("/")
API_URL = f"{ARXIV_BASE}/api/query"
PDF_URL = ARXIV_BASE + "/pdf/{id}"
USER_AGENT = "llm-lab-fetch-papers/1.0 (personal RAG evaluation corpus)"
MIN_INTERVAL_SEC = 3.0
TIMEOUT_SEC = 60

ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}$")
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# 網路失敗的例外：連線／逾時／重設（OSError，URLError 與 TimeoutError 都是其子類）與讀 body 到一半
# 斷線的 http.client.IncompleteRead 等（HTTPException，不是 OSError）
NETWORK_ERRORS = (OSError, http.client.HTTPException)


class FetchError(Exception):
    """某個 arXiv ID 無法完成下載或驗證；訊息需包含該 ID。"""


# ==============================
# 參數與 ID 驗證
# ==============================


def validate_ids(ids: list[str]) -> None:
    """確認每個 ID 格式合法且在 PAPERS 清單內。

    Args:
        ids: 使用者指定或預設的 arXiv ID 清單。

    Returns:
        None。第一個不合法的 ID 會讓函式拋出 FetchError，訊息含該 ID。
    """
    for arxiv_id in ids:
        if not ID_PATTERN.match(arxiv_id):
            raise FetchError(f"{arxiv_id}: 不是合法的 arXiv ID 格式（預期 YYMM.NNNNN，不含版本號）")
        if arxiv_id not in PAPERS:
            raise FetchError(f"{arxiv_id}: 不在論文清單內，沒有預期標題可比對，不下載")


# ==============================
# arXiv 請求（含節流）
# ==============================


class ArxivClient:
    """對 arXiv 發請求的薄包裝，保證請求之間至少間隔 MIN_INTERVAL_SEC。"""

    def __init__(self) -> None:
        self._last_request = 0.0

    def open(self, url: str):
        """節流後開啟 URL。

        Args:
            url: 完整 URL。

        Returns:
            urllib 回應物件（呼叫端負責關閉）。HTTP／網路錯誤直接拋出。
        """
        wait = self._last_request + MIN_INTERVAL_SEC - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        self._last_request = time.monotonic()
        return urllib.request.urlopen(req, timeout=TIMEOUT_SEC)


def fetch_titles(client: ArxivClient, ids: list[str]) -> dict[str, str]:
    """用 arXiv 官方 API 取回各 ID 的標題。

    Args:
        client: 帶節流的請求端。
        ids: 要查詢的 arXiv ID。

    Returns:
        {不含版本號的 ID: 標題}。API 查無的 ID 不會出現在結果裡。

    Raises:
        FetchError: 網路失敗（連線、逾時、讀到一半斷線）；訊息列出涉及的 ID。
    """
    query = urllib.parse.urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    try:
        with client.open(f"{API_URL}?{query}") as resp:
            root = ET.fromstring(resp.read())
    except NETWORK_ERRORS as exc:
        raise FetchError(f"標題查詢失敗（{type(exc).__name__}: {exc}）；涉及 ID: {', '.join(ids)}") from exc
    titles: dict[str, str] = {}
    for entry in root.findall("a:entry", ATOM_NS):
        entry_id = entry.findtext("a:id", namespaces=ATOM_NS) or ""
        match = re.search(r"/abs/(\d{4}\.\d{4,5})(?:v\d+)?$", entry_id)
        if match:
            titles[match.group(1)] = entry.findtext("a:title", namespaces=ATOM_NS) or ""
    return titles


def normalize_title(title: str) -> str:
    """壓縮空白並轉小寫，讓標題比對不受換行與大小寫影響。

    Args:
        title: 原始標題。

    Returns:
        正規化後的標題。
    """
    return " ".join(title.split()).casefold()


def verify_titles(ids: list[str], actual: dict[str, str]) -> None:
    """比對 API 取回的標題與預期標題。

    Args:
        ids: 要驗證的 ID。
        actual: fetch_titles 的結果。

    Returns:
        None。任何一個 ID 查無或標題不符就拋出 FetchError（含該 ID 與兩邊標題）。
    """
    for arxiv_id in ids:
        if arxiv_id not in actual:
            raise FetchError(f"{arxiv_id}: arXiv API 查無此 ID，不下載")
        if normalize_title(actual[arxiv_id]) != normalize_title(PAPERS[arxiv_id]):
            raise FetchError(
                f"{arxiv_id}: 標題不符，不下載\n  預期: {PAPERS[arxiv_id]}\n  實際: {' '.join(actual[arxiv_id].split())}"
            )


# ==============================
# PDF 檢查與下載
# ==============================


def is_complete_pdf(path: Path) -> bool:
    """判斷檔案是否為完整 PDF：%PDF 開頭且尾端 1 KiB 內有 %%EOF。

    Args:
        path: PDF 路徑。

    Returns:
        完整為 True；不存在或殘缺為 False。
    """
    if not path.is_file():
        return False
    with path.open("rb") as f:
        head = f.read(5)
        f.seek(0, 2)
        f.seek(max(f.tell() - 1024, 0))
        tail = f.read()
    return head == b"%PDF-" and b"%%EOF" in tail


def count_pages(path: Path) -> int | None:
    """從 PDF 結構解析頁數：取所有 /Type /Pages 節點中最大的 /Count。

    Args:
        path: PDF 路徑。

    Returns:
        頁數；解析不到時為 None。
    """
    data = path.read_bytes()
    haystacks = [data]
    for m in re.finditer(rb"<<[^<>]*?/Type\s*/ObjStm[^<>]*?>>\s*stream\r?\n", data):
        end = data.find(b"endstream", m.end())
        haystacks.append(zlib.decompressobj().decompress(data[m.end():end]))
    counts = []
    for hay in haystacks:
        for node in re.finditer(rb"<<[^<>]*?/Type\s*/Pages\b[^<>]*?>>", hay):
            count = re.search(rb"/Count\s+(\d+)", node.group(0))
            if count:
                counts.append(int(count.group(1)))
    return max(counts) if counts else None


def download_pdf(client: ArxivClient, arxiv_id: str, dest: Path) -> None:
    """下載 PDF 到 dest：先寫 .part，核對長度與完整性後改名。

    Args:
        client: 帶節流的請求端。
        arxiv_id: 不含版本號的 arXiv ID。
        dest: 最終檔案路徑。

    Returns:
        None。網路失敗、長度不符或內容殘缺時拋出 FetchError，且不留下 dest。
    """
    part = dest.with_name(dest.name + ".part")
    try:
        with client.open(PDF_URL.format(id=arxiv_id)) as resp:
            expected = resp.headers.get("Content-Length")
            body = resp.read()
    except NETWORK_ERRORS as exc:
        raise FetchError(f"{arxiv_id}: 下載失敗（{type(exc).__name__}: {exc}）") from exc
    if expected is not None and int(expected) != len(body):
        raise FetchError(f"{arxiv_id}: 下載長度不符（Content-Length={expected}，實收 {len(body)}）")
    part.write_bytes(body)
    if not is_complete_pdf(part):
        part.unlink()
        raise FetchError(f"{arxiv_id}: 下載內容不是完整 PDF")
    part.replace(dest)


# ==============================
# 主程式
# ==============================


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令列參數。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        含 out（Path）與 ids（list[str]）的 Namespace。
    """
    parser = argparse.ArgumentParser(description="下載 RAG 主題 arXiv 論文（逐篇驗證標題、可重複執行）。")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"輸出資料夾（預設 {DEFAULT_OUT}）")
    parser.add_argument("--ids", nargs="+", default=list(PAPERS), help="只處理這些 ID（需在清單內）")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """依序驗證 ID、比對標題、下載缺少的 PDF 並印出標題與頁數。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        0 成功；1 任何 ID 驗證或下載失敗（stderr 指出是哪個 ID）。
    """
    args = parse_args(argv)
    try:
        validate_ids(args.ids)
        client = ArxivClient()
        verify_titles(args.ids, fetch_titles(client, args.ids))
        args.out.mkdir(parents=True, exist_ok=True)
        for arxiv_id in args.ids:
            dest = args.out / f"{arxiv_id}.pdf"
            if is_complete_pdf(dest):
                status = "exists"
            else:
                download_pdf(client, arxiv_id, dest)
                status = "downloaded"
            pages = count_pages(dest)
            print(f"{status:10s} {arxiv_id}  pages={pages if pages is not None else '?'}  {PAPERS[arxiv_id]}")
    except FetchError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
