"""支援的文件格式：專案裡唯一的一份清單。

為什麼存在：ingest 要判斷哪些檔案能匯入、單一檔案不支援時要在錯誤訊息裡列出支援的格式。
這些都從同一份清單取值，之後新增格式只改這裡。這個模組只靠標準函式庫，CLI 在載入 lightrag
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
    "圖片": (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"),
}

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(ext for extensions in FORMATS.values() for ext in extensions)


def is_supported(path: Path) -> bool:
    """判斷檔案的副檔名是否屬於支援的格式。

    Args:
        path: 檔案路徑。

    Returns:
        副檔名（大小寫不分）在 SUPPORTED_EXTENSIONS 內時為 True。
    """
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def describe_supported() -> str:
    """列出所有支援的副檔名，給錯誤訊息用。

    Returns:
        以空白分隔的副檔名，例如「.pdf .png」。
    """
    return " ".join(SUPPORTED_EXTENSIONS)
