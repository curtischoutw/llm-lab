"""匯入對照表：記錄每份處理成功的文件的絕對路徑、文件 ID、匯入時間與來源資料夾。

為什麼存在：LightRAG 的文件狀態只記檔名、不記路徑，知識庫裡也沒有「某個路徑對應哪個版本」的紀錄。
增量更新（替換、移除、清答案快取）要靠這張表判斷一個路徑上的文件是新的、變了，還是沒變
（spec：.scratch/incremental-update/spec.md「匯入端：對照表」）。

關鍵設計決策：
- 檔案是 `WORKING_DIR/rag_lab_documents.json`，格式是公開契約（測試與使用者都可以直接讀寫）：
  `{"version": 1, "documents": {"<絕對路徑>": {"doc_id": …, "ingested_at": <ISO 8601>, "source_folder": <絕對路徑>}}}`。
  跟著 `WORKING_DIR` 走，換知識庫就換一份對照表。
- 沒有檔案視為空表；檔案存在但讀不了、不是合法 JSON 或格式不符一律拋 RegistryError 並指出檔案路徑，
  不當成空表（空表會讓所有文件看起來都是新的，之後的刪除與替換判斷都會錯）。
- 寫入先寫同資料夾的暫存檔再 os.replace 改名，避免留下寫到一半的檔案；失敗時清掉暫存檔並拋 RegistryError。
- 本模組不 import rag_lab.pipeline（避免循環 import），錯誤型別是自己的 RegistryError，由 pipeline 轉成 PipelineError。

Dependencies: 標準函式庫。
"""

import json
import os
from pathlib import Path

# ==============================
# 常數與例外
# ==============================

REGISTRY_FILENAME = "rag_lab_documents.json"
REGISTRY_TMP_FILENAME = "rag_lab_documents.json.tmp"
REGISTRY_VERSION = 1
# 每筆紀錄必有的欄位，值都是字串
ENTRY_FIELDS = ("doc_id", "ingested_at", "source_folder")


class RegistryError(Exception):
    """對照表讀不了、格式不符或寫不進去；訊息含檔案路徑。"""


# ==============================
# 讀寫
# ==============================


def registry_path(working_dir: str | Path) -> Path:
    """對照表檔案路徑。

    Args:
        working_dir: WORKING_DIR。

    Returns:
        `<working_dir>/rag_lab_documents.json`。
    """
    return Path(working_dir) / REGISTRY_FILENAME


def _validate(content: object) -> dict[str, dict[str, str]]:
    """檢查對照表內容的格式。

    Args:
        content: json.loads 的結果。

    Returns:
        路徑 → 紀錄的 dict（原物件，不複製）。

    Raises:
        ValueError: 格式不符；訊息說明哪裡不符。
    """
    if not isinstance(content, dict):
        raise ValueError("最外層必須是物件")
    if content.get("version") != REGISTRY_VERSION:
        raise ValueError(f"version 必須是 {REGISTRY_VERSION}")
    documents = content.get("documents")
    if not isinstance(documents, dict):
        raise ValueError("documents 必須是物件")
    for path, entry in documents.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{path} 的紀錄必須是物件")
        for name in ENTRY_FIELDS:
            if not isinstance(entry.get(name), str) or not entry[name]:
                raise ValueError(f"{path} 的紀錄缺少字串欄位 {name}")
    return documents


def load(working_dir: str | Path) -> dict[str, dict[str, str]]:
    """讀出對照表。

    Args:
        working_dir: WORKING_DIR。

    Returns:
        路徑 → {"doc_id", "ingested_at", "source_folder"}；檔案不存在時是空 dict。

    Raises:
        RegistryError: 檔案存在但讀不了、不是合法的 JSON 或格式不符（訊息含檔案路徑）。
    """
    path = registry_path(working_dir)
    if not path.exists():
        return {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return _validate(content)
    except OSError as exc:
        raise RegistryError(f"無法讀取對照表 {path}：{exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"對照表 {path} 不是合法的 JSON：{exc}") from exc
    except UnicodeDecodeError as exc:
        raise RegistryError(f"對照表 {path} 不是合法的 UTF-8 文字：{exc}") from exc
    except ValueError as exc:
        raise RegistryError(f"對照表 {path} 格式不符：{exc}") from exc


def save(working_dir: str | Path, documents: dict[str, dict[str, str]]) -> None:
    """寫出對照表：先寫暫存檔再改名。

    Args:
        working_dir: WORKING_DIR（必須已存在）。
        documents: 路徑 → {"doc_id", "ingested_at", "source_folder"}。

    Raises:
        RegistryError: 暫存檔寫不進去或改名失敗（訊息含檔案路徑）；暫存檔會被清掉。
    """
    path = registry_path(working_dir)
    tmp = path.with_name(REGISTRY_TMP_FILENAME)
    content = {"version": REGISTRY_VERSION, "documents": documents}
    try:
        tmp.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        if tmp.is_file():
            tmp.unlink()
        raise RegistryError(f"無法寫入對照表 {path}：{exc.strerror or exc}") from exc
