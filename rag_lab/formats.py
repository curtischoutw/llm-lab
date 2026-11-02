"""支援的文件格式：專案裡唯一的一份清單。

為什麼存在：ingest 要判斷哪些檔案能匯入、單一檔案不支援時要在錯誤訊息裡列出支援的格式、
報告要區分哪些格式解析前會先轉成 PDF（Office），資料夾裡哪些檔案算文件（CLI 展開資料夾與 Python API 檢查
來源資料夾共用同一套規則）。這些都從同一份清單取值，之後新增格式只改這裡。這個模組只靠標準函式庫，CLI 在載入 lightrag
之前就能用它驗證輸入路徑。

關鍵設計決策：
- 以副檔名判定，大小寫不分；不讀檔案內容。
- 專案只決定「放行哪些副檔名」，不判斷怎麼解析：解析由 RAG-Anything 的 `parse_document` 依副檔名分派。

Dependencies: 標準函式庫。
"""

from pathlib import Path

# ==============================
# 格式清單
# ==============================

# 格式名稱（見 GLOSSARY.md）對應的副檔名；順序就是錯誤訊息裡列出的順序
FORMATS: dict[str, tuple[str, ...]] = {
    "PDF": (".pdf",),
    "PPT": (".ppt", ".pptx"),
    "Word": (".doc", ".docx"),
    "Excel": (".xls", ".xlsx"),
    "圖片": (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"),
}

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(ext for extensions in FORMATS.values() for ext in extensions)

# 資料夾內檔名以這些開頭的檔案不是文件：`.` 是隱藏檔（.DS_Store、macOS 的 ._ AppleDouble 檔），
# `~$` 是 Office 開檔時產生的鎖定檔。它們可能帶著支援的副檔名，匯入只會在轉檔或解析時失敗
NOT_A_DOCUMENT_PREFIXES: tuple[str, ...] = (".", "~$")

# 解析前要先由 LibreOffice 轉成 PDF 的格式（報告的解析階段標籤因此不同）
OFFICE_FORMATS: tuple[str, ...] = ("PPT", "Word", "Excel")
OFFICE_EXTENSIONS: tuple[str, ...] = tuple(ext for name in OFFICE_FORMATS for ext in FORMATS[name])


def is_supported(path: Path) -> bool:
    """判斷檔案的副檔名是否屬於支援的格式。

    Args:
        path: 檔案路徑。

    Returns:
        副檔名（大小寫不分）在 SUPPORTED_EXTENSIONS 內時為 True。
    """
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def is_office(path: Path) -> bool:
    """判斷檔案是不是 Office 格式（PPT、Word、Excel），這些格式解析前要先轉成 PDF。

    Args:
        path: 檔案路徑。

    Returns:
        副檔名（大小寫不分）在 OFFICE_EXTENSIONS 內時為 True。
    """
    return path.suffix.lower() in OFFICE_EXTENSIONS


def describe_supported() -> str:
    """列出所有支援的副檔名，給錯誤訊息用。

    Returns:
        以空白分隔的副檔名，例如「.pdf .png」。
    """
    return " ".join(SUPPORTED_EXTENSIONS)


def list_folder(folder: Path) -> tuple[list[Path], list[Path]]:
    """列出資料夾（不遞迴）裡的文件與不支援格式的檔案。

    檔名以 NOT_A_DOCUMENT_PREFIXES 開頭的檔案不算文件，兩份清單都不列。

    Args:
        folder: 資料夾路徑（必須存在）。

    Returns:
        (依檔名排序的支援格式文件, 依檔名排序的不支援格式檔案)；路徑是 folder 底下的子路徑，沒有 resolve。
    """
    documents: list[Path] = []
    unsupported: list[Path] = []
    for file in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(NOT_A_DOCUMENT_PREFIXES)):
        (documents if is_supported(file) else unsupported).append(file)
    return documents, unsupported
