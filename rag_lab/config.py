"""從環境變數（含 .env）讀取並驗證 RAG 實驗設定。

為什麼存在：三個模型端點（LLM、VLM、embedding）、儲存路徑與併發度都要能只靠
.env 切換，這樣搬到別台機器換大模型時，程式碼完全不用動。

關鍵設計決策：
- 欄位缺漏或格式錯誤一律在啟動時以 ConfigError 中止，不給預設值掩蓋。
- EMBED_DIM 必須明確填寫：它決定向量庫維度，與索引綁定，換 embedding 模型要重建索引。
- EMBED_QUERY_PREFIX 只套用在查詢端（LightRAG 會以 context="query" 呼叫），
  文件端不加前綴；Qwen3-Embedding 的官方用法即為此非對稱形式。

Dependencies: python-dotenv（由 raganything 帶入）。
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from dotenv import load_dotenv

# ==============================
# 例外與工具
# ==============================


class ConfigError(ValueError):
    """設定缺漏或格式錯誤。訊息只含欄位名稱與原因，不含欄位值（可能是金鑰）。

    Attributes:
        field: 出問題的環境變數名稱。
    """

    def __init__(self, field: str, reason: str):
        super().__init__(f"{field} {reason}")
        self.field = field


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(name, "缺少必要環境變數（參考 .env.example）")
    return value


def _url(name: str) -> str:
    value = _required(name)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(name, "不是合法的 http(s) URL")
    return value.rstrip("/")


def _positive_int(name: str) -> int:
    raw = _required(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(name, "必須是整數") from exc
    if value <= 0:
        raise ConfigError(name, "必須大於 0")
    return value


# ==============================
# 設定物件
# ==============================


@dataclass(frozen=True)
class Settings:
    """實驗設定。欄位語意見 .env.example。"""

    llm_base_url: str
    llm_model: str
    llm_api_key: str
    vlm_base_url: str
    vlm_model: str
    vlm_api_key: str
    embed_base_url: str
    embed_model: str
    embed_api_key: str
    embed_dim: int
    embed_max_token_size: int
    embed_max_async: int
    embed_query_prefix: str
    working_dir: str
    parser_output_dir: str
    llm_max_async: int
    llm_max_tokens: int
    vlm_max_tokens: int
    query_max_total_tokens: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """讀取 .env 與環境變數並驗證。

    Returns:
        Settings：同一個 process 內只解析一次。

    Raises:
        ConfigError: 任一必要欄位缺漏或格式不合法。
    """
    load_dotenv()
    return Settings(
        llm_base_url=_url("LLM_BASE_URL"),
        llm_model=_required("LLM_MODEL"),
        llm_api_key=_required("LLM_API_KEY"),
        vlm_base_url=_url("VLM_BASE_URL"),
        vlm_model=_required("VLM_MODEL"),
        vlm_api_key=_required("VLM_API_KEY"),
        embed_base_url=_url("EMBED_BASE_URL"),
        embed_model=_required("EMBED_MODEL"),
        embed_api_key=_required("EMBED_API_KEY"),
        embed_dim=_positive_int("EMBED_DIM"),
        embed_max_token_size=_positive_int("EMBED_MAX_TOKEN_SIZE"),
        embed_max_async=_positive_int("EMBED_MAX_ASYNC"),
        # .env 內以字面 \n 表示換行
        embed_query_prefix=os.environ.get("EMBED_QUERY_PREFIX", "").replace("\\n", "\n"),
        working_dir=_required("WORKING_DIR"),
        parser_output_dir=_required("PARSER_OUTPUT_DIR"),
        llm_max_async=_positive_int("LLM_MAX_ASYNC"),
        llm_max_tokens=_positive_int("LLM_MAX_TOKENS"),
        vlm_max_tokens=_positive_int("VLM_MAX_TOKENS"),
        query_max_total_tokens=_positive_int("QUERY_MAX_TOTAL_TOKENS"),
    )
