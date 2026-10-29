"""下載多格式擴充用的 11 份公開文件到本地資料夾。

為什麼存在：多格式擴充（PPT、Word、Excel、圖片）需要一批固定的文件做實機驗證。這些文件不進版本控管，
所以用這支腳本讓任何機器都能用一個指令重建同一批內容。

用法：
    python3 scripts/fetch_documents.py [--out DIR] [--group {documents,format_check}]
    預設輸出到 repo 根目錄下的 data，兩組都下載；--group 只下載其中一組。

關鍵設計決策：
- 清單（DOCUMENTS）寫死在腳本裡：URL、預期 SHA-256、檔名、格式、授權與出處、目標資料夾。
  documents 組 6 份放進 data/documents/（主知識庫），format_check 組 5 份放進 data/format_check/。
  檔名是本地存檔名，與 URL 結尾不一定相同（來源的 image-1.png 沒有辨識度，所以改名）。
- 先驗證參數（--group 的值、--out 不是一般檔案），再發任何網路請求。
- 下載後先在記憶體核對 SHA-256，相符才寫 .part 再改名；不符時還沒寫任何檔案。
- 檔案已存在且雜湊正確就略過；已存在但雜湊不符時中止並指出檔名，不覆蓋。
- 任何失敗（網路、HTTP、雜湊、既有檔案不符、本地檔案系統錯誤）都以非零碼結束並指出是哪一份，不略過後繼續。
- 網路失敗包含連線重設與讀 body 到一半斷線（http.client.IncompleteRead 不是 OSError，要一併攔）。
- 環境變數 FETCH_DOCUMENTS_BASE 取代清單 URL 的 https://raw.githubusercontent.com 前綴，
  只給測試指向本機假 server 用。

已知極限：
- URL 指向各 repo 的 main 分支，不是固定 commit。來源檔案被更換時，下載會因雜湊不符而中止，
  需要人工更新清單裡的雜湊。
- 整份文件讀進記憶體再核對雜湊；清單裡最大的檔案是 7.7 MB，沒有串流的必要。
- 下載是逐份循序進行，沒有請求間隔；11 份都在 raw.githubusercontent.com。

Dependencies: 僅標準函式庫。
"""

import argparse
import hashlib
import http.client
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# ==============================
# 設定
# ==============================

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data"
GROUPS = ("documents", "format_check")
USER_AGENT = "llm-lab-fetch-documents/1.0 (personal RAG evaluation corpus)"
TIMEOUT_SEC = 60

# 網路失敗的例外：連線／逾時／重設／HTTP 狀態錯誤（OSError，HTTPError 與 URLError 都是其子類）與讀 body
# 到一半斷線的 http.client.IncompleteRead 等（HTTPException，不是 OSError）
NETWORK_ERRORS = (OSError, http.client.HTTPException)

URL_PREFIX = "https://raw.githubusercontent.com"
# ASSUMPTION：環境變數 FETCH_DOCUMENTS_BASE 取代清單 URL 的 URL_PREFIX，唯一用途是讓測試把腳本指向本機假 server
URL_BASE = os.environ.get("FETCH_DOCUMENTS_BASE", URL_PREFIX).rstrip("/")


@dataclass(frozen=True)
class Document:
    """清單的一筆文件。folder 同時是組別名稱與 --out 底下的子資料夾名稱。"""

    name: str
    format: str
    folder: str
    url: str
    sha256: str
    license: str


DOCUMENTS: list[Document] = [
    # --- documents ---
    Document(
        name="RAGHack-EvaluatingAChatApp.pptx",
        format="PPT",
        folder="documents",
        url=URL_PREFIX + "/microsoft/RAG_Hack/main/slides/RAGHack-EvaluatingAChatApp.pptx",
        sha256="c9961ecdf07a5e2f58078b22e3d1f5e035ed780e288d6e707037b025ecd5252b",
        license="MIT（microsoft/RAG_Hack）",
    ),
    Document(
        name="docling_arch.pptx",
        format="PPT",
        folder="documents",
        url=URL_PREFIX + "/docling-project/docling/main/docs/assets/docling_arch.pptx",
        sha256="4abbca4284f66c89c802bcbd875b46c54e855f6467bba1c0f47b7b0a4afa30b0",
        license="MIT（docling-project/docling）",
    ),
    Document(
        name="Experimentations_for_Kg_creation.docx",
        format="Word",
        folder="documents",
        url=URL_PREFIX + "/neo4j-labs/llm-graph-builder/main/experiments/Experimentations%20for%20Kg%20creation.docx",
        sha256="60348fa44a766b949c67dd83d70f96a2faa1c3c9d35f4364a10914896ac7a3da",
        license="Apache-2.0（neo4j-labs/llm-graph-builder）",
    ),
    Document(
        name="LLM_Comparisons_with_one_pdf.docx",
        format="Word",
        folder="documents",
        url=URL_PREFIX + "/neo4j-labs/llm-graph-builder/main/experiments/LLM%20Comparisons%20with%20one%20pdf.docx",
        sha256="1db611a1f910fd45dae163b09c1b7a7911713a1db76f375c194bc06b3ef6fd30",
        license="Apache-2.0（neo4j-labs/llm-graph-builder）",
    ),
    Document(
        name="graphrag-auto-tune-diagram.png",
        format="圖片",
        folder="documents",
        url=URL_PREFIX + "/microsoft/graphrag/main/docs/img/auto-tune-diagram.png",
        sha256="9619b610f0e4f6ab70e29b2d06298f338065789a409d1403d642728c0cdb1ff4",
        license="MIT（microsoft/graphrag）",
    ),
    Document(
        name="graphrag-unified-search-app.png",
        format="圖片",
        folder="documents",
        url=URL_PREFIX + "/microsoft/graphrag/main/unified-search-app/images/image-1.png",
        sha256="3cc7610f742400dc5510cf47a5655c286590887659314192847c74da0f32ce29",
        license="MIT（microsoft/graphrag）",
    ),
    # --- format_check ---
    Document(
        name="2023-half-year-analyses-by-segment.xlsx",
        format="Excel",
        folder="format_check",
        url=URL_PREFIX + "/Unstructured-IO/unstructured/main/example-docs/2023-half-year-analyses-by-segment.xlsx",
        sha256="30d7708d6526c219907ef84e586203903c8b28828c6205fa4808a8effd47918b",
        license="Apache-2.0（Unstructured-IO/unstructured）",
    ),
    Document(
        name="xlsx_01.xlsx",
        format="Excel",
        folder="format_check",
        url=URL_PREFIX + "/docling-project/docling/main/tests/data/xlsx/sources/xlsx_01.xlsx",
        sha256="fd4e67c4474e6d8308b1e9a9006500bd8e055c1aa2a337d54e641c3b1f506cf2",
        license="MIT（docling-project/docling）",
    ),
    Document(
        name="legacy_sample.ppt",
        format="PPT（舊格式）",
        folder="format_check",
        url=URL_PREFIX + "/docling-project/docling/main/tests/data/ppt/sources/legacy_sample.ppt",
        sha256="d436b2d8b94f3fb4c9ef02fe646a59c7f045626b6719a6011b4444acebee9048",
        license="MIT（docling-project/docling）",
    ),
    Document(
        name="legacy_sample.doc",
        format="Word（舊格式）",
        folder="format_check",
        url=URL_PREFIX + "/docling-project/docling/main/tests/data/doc/sources/legacy_sample.doc",
        sha256="2cdaabb346fc7a013e91a03cf5211e7a9cc0154c06d4825fb01d9101923a12d4",
        license="MIT（docling-project/docling）",
    ),
    Document(
        name="legacy_sample.xls",
        format="Excel（舊格式）",
        folder="format_check",
        url=URL_PREFIX + "/docling-project/docling/main/tests/data/xls/sources/legacy_sample.xls",
        sha256="dc9ddd5d964c360bcb7400427c2b8d004b9a73a5b716997b2981aadcf33f4306",
        license="MIT（docling-project/docling）",
    ),
]


class FetchError(Exception):
    """某份文件無法完成下載或驗證；訊息需包含該文件的檔名。"""


# ==============================
# 既有檔案與下載
# ==============================


def check_existing(doc: Document, dest: Path) -> bool:
    """判斷 dest 是否已是正確的文件。

    Args:
        doc: 清單的一筆文件。
        dest: 最終檔案路徑。

    Returns:
        dest 存在且 SHA-256 相符為 True；不存在為 False。存在但雜湊不符時拋出 FetchError，不覆蓋。
    """
    if not dest.is_file():
        return False
    actual = hashlib.sha256(dest.read_bytes()).hexdigest()
    if actual != doc.sha256:
        raise FetchError(
            f"{doc.name}: 本地檔案 {dest} 的 SHA-256 與清單不符，不覆蓋；請自行確認後刪除再重跑\n"
            f"  預期: {doc.sha256}\n  實際: {actual}"
        )
    return True


def download(doc: Document, dest: Path) -> int:
    """下載 doc 到 dest：先在記憶體核對 SHA-256，相符才寫 .part 再改名。

    Args:
        doc: 清單的一筆文件。
        dest: 最終檔案路徑。

    Returns:
        寫入的位元組數。網路失敗或雜湊不符時拋出 FetchError，此時還沒寫任何檔案，不留下 dest 與 .part。
    """
    url = URL_BASE + doc.url.removeprefix(URL_PREFIX)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            body = resp.read()
    except NETWORK_ERRORS as exc:
        raise FetchError(f"{doc.name}: 下載失敗（{type(exc).__name__}: {exc}）") from exc
    actual = hashlib.sha256(body).hexdigest()
    if actual != doc.sha256:
        raise FetchError(f"{doc.name}: SHA-256 不符，來源內容與清單不同\n  預期: {doc.sha256}\n  實際: {actual}")
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(body)
    part.replace(dest)
    return len(body)


# ==============================
# 主程式
# ==============================


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令列參數。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        含 out（Path）與 group（str 或 None）的 Namespace。
    """
    parser = argparse.ArgumentParser(description="下載多格式擴充用的公開文件（核對 SHA-256、可重複執行）。")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"輸出資料夾（預設 {DEFAULT_OUT}）")
    parser.add_argument("--group", choices=GROUPS, default=None, help="只下載這一組（預設兩組都下載）")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """依序下載清單內的文件。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        0 成功；1 任何文件失敗（stderr 指出是哪一份）。
    """
    args = parse_args(argv)
    try:
        if args.out.exists() and not args.out.is_dir():
            raise FetchError(f"--out {args.out} 已存在但不是資料夾")
        for doc in DOCUMENTS:
            if args.group is not None and doc.folder != args.group:
                continue
            dest = args.out / doc.folder / doc.name
            try:
                if check_existing(doc, dest):
                    status, size = "exists", dest.stat().st_size
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    status, size = "downloaded", download(doc, dest)
            except OSError as exc:
                # 網路錯誤已在 download 轉成 FetchError；這裡只會是本地檔案系統（建資料夾、讀寫、改名）的錯誤
                raise FetchError(f"{doc.name}: 檔案系統錯誤（{type(exc).__name__}: {exc}）") from exc
            print(f"{status:10s} {doc.folder}/{doc.name}  {size} bytes")
    except FetchError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
