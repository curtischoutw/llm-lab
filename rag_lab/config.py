"""從環境變數（含 .env）讀取並驗證 RAG 實驗設定。

為什麼存在：四個模型端點（LLM、VLM、embedding、rerank）、儲存路徑與併發度都要能只靠
.env 切換，這樣搬到別台機器換大模型時，程式碼完全不用動。

關鍵設計決策：
- 欄位缺漏或格式錯誤一律在啟動時以 ConfigError 中止，不給預設值掩蓋。
- EMBED_DIM 必須明確填寫：它決定向量庫維度，與索引綁定，換 embedding 模型要重建索引。
- 查詢 context 的 token 分配由三個欄位決定：QUERY_MAX_TOTAL_TOKENS 是總上限，QUERY_MAX_ENTITY_TOKENS
  與 QUERY_MAX_RELATION_TOKENS 是圖譜 context 裡 entity 與 relation 各自的上限，其餘留給文字 chunk。
  後兩者可以是 0（LightRAG 照常執行，只是不放該類描述），但兩者相加必須小於總上限，否則 chunk 分不到 token。
- RERANK_BASE_URL／RERANK_MODEL／RERANK_API_KEY 三個欄位必填、規則與其他端點相同：查詢一律用 rerank，
  沒有開關；chunk_top_k 與分數門檻不在這裡設定，由 pipeline 固定為 20 與 0.0，不受行程環境的 CHUNK_TOP_K、MIN_RERANK_SCORE 影響。
- EMBED_QUERY_PREFIX 只套用在查詢端（LightRAG 會以 context="query" 呼叫），
  文件端不加前綴；Qwen3-Embedding 的官方用法即為此非對稱形式。
- 拒絕 rag_lab 沒有管理的 LightRAG／RAG-Anything／MinerU 環境變數（UNMANAGED_LIBRARY_ENV）：LightRAG 與
  RAG-Anything 在 import 時會從環境變數與目前工作目錄的 .env（load_dotenv(".env", override=False)）讀幾十個設定
  當預設值；MinerU 是 RAG-Anything 以子行程執行的 `mineru` 指令，繼承 rag_lab 行程的環境（.env 經 load_dotenv
  也進了行程環境），自己讀一批 MINERU_* 變數。這些變數會悄悄改變匯入與查詢結果、eval 結果檔也看不出來。
  環境裡出現名單內的變數就以 ConfigError 中止，訊息只列名稱、不印值。檢查函式 reject_unmanaged_library_env 有兩個呼叫點：get_settings（CLI 的每個子命令
  與 Python API 的 Session、ingest、query、evaluate 都在連線檢查之前被擋下），以及 rag_lab.pipeline 與
  rag_lab.models 在 import lightrag 之前（LightRAG 在 import 時就把這些變數讀成預設值，值不合法時 import 本身會拋
  ValueError 並帶出值，所以要搶在它之前）。檢查前先照 LightRAG 的方式載入目前工作目錄的 .env（override=False；
  LightRAG import 時也會做同一件事，只是時間點提前），repo 根目錄以外的 .env 也擋得到。變數只要「存在」就算，
  空字串也算（LightRAG 讀到空字串多半直接例外）。
  名單怎麼產生（升級 lightrag-hku 或 raganything 時照做一次）：
  1. 在 site-packages 的 lightrag（不含 api、tools、evaluation 與 kg 下的外部資料庫實作）與 raganything 裡，
     搜尋 os.getenv／os.environ／get_env_value，列出所有讀取的變數。
  2. 只收「會改變匯入或查詢結果」且「rag_lab 沒有明確傳入」的變數。rag_lab 明確傳入的參數
     （QueryParam 的 max_total_tokens、max_entity_tokens、max_relation_tokens、chunk_top_k、enable_rerank，
     LightRAG 的 min_rerank_score、llm_model_max_async、max_parallel_insert、embedding_func_max_async，
     RAGAnythingConfig 的 working_dir、parser_output_dir、parser、parse_method）對應的變數
     （MAX_TOTAL_TOKENS、MAX_ENTITY_TOKENS、MAX_RELATION_TOKENS、CHUNK_TOP_K、RERANK_BY_DEFAULT、MIN_RERANK_SCORE、
     MAX_ASYNC、MAX_PARALLEL_INSERT、EMBEDDING_FUNC_MAX_ASYNC、WORKING_DIR、OUTPUT_DIR、PARSER、PARSE_METHOD）不收。
     例外：MINERU_PARSE_METHOD 要收，RAGAnythingConfig.__post_init__ 在 PARSE_METHOD 沒設時會用它蓋掉明確傳入的 parse_method。
  3. 不收的類別：log 與 tracing（LOG_*、VERBOSE、LIGHTRAG_PERFORMANCE_TIMING_LOGS、LANGFUSE_*、DISPLAY_CONTENT_STATS）；
     API key 與 endpoint（rag_lab 的 models 一律明確傳 base_url 與 api_key；*_API_KEY、OPENAI_API_BASE、
     AZURE_*、AWS_* 等）；逾時與批次大小，只影響速度與失敗與否、不影響內容（LLM_TIMEOUT、EMBEDDING_TIMEOUT、
     EMBEDDING_BATCH_NUM、EMBEDDING_USE_BASE64、LIBREOFFICE_CONVERT_TIMEOUT）；rag_lab 不會走到的功能
     （MAX_GRAPH_NODES 只用在 LightRAG 自己的圖譜查詢介面；MAX_CONCURRENT_FILES、SUPPORTED_FILE_EXTENSIONS、
     RECURSIVE_FOLDER_PROCESSING 只用在 RAG-Anything 的批次資料夾處理；音訊與視訊相關的 ENABLE_AUDIO_PROCESSING、
     ENABLE_VIDEO_PROCESSING、VIDEO_*、WHISPER_*；OLLAMA_EMULATING_*；RAGANYTHING_PUBLIC_ASSET_* 只加欄位不改內容）；
     HISTORY_TURNS（1.4.16 裡沒有任何程式讀它，rag_lab 也不傳對話歷史）；Postgres、Neo4j、Mongo 等外部資料庫的連線變數
     （rag_lab 用的是 LightRAG 預設的檔案型儲存）。
  MinerU 的名單另外產生（升級 mineru 時照做一次）：
  1. 在 site-packages 的 mineru、mineru_vl_utils、mineru_llama_cpp 裡搜尋 MINERU_，涵蓋 os.getenv、os.environ.get、
     os.environ[...]、os.environ.setdefault，以及先存成常數或參數再讀的寫法（例如 MODEL_SOURCE_ENV_VAR、
     get_op_num_threads(name)、env_flag_enabled(name)）；另搜不含 MINERU_ 字樣的 os.environ／getenv 讀取，確認沒有漏。
  2. 只收「rag_lab 實際走得到」且「會改變解析結果」的變數。走得到與否看 RAG-Anything 怎麼呼叫：
     `mineru -p <檔案> -o <輸出> -m auto -b pipeline`，沒有 -l -s -e -f -t -d -u --source，所以 backend 是 pipeline、
     method 是 auto，公式與表格開關由 mineru 的 CLI 預設（開）決定。vlm 與 hybrid 後端才讀的變數
     （MINERU_VLM_TABLE_ENABLE、MINERU_VLM_FORMULA_ENABLE、MINERU_HYBRID_BATCH_RATIO、MINERU_LMDEPLOY_BACKEND、
     MINERU_VLLM_DEVICE、MINERU_VL_*、MINERU_VLM_END_TOKEN）不收；rag_lab 改 MINERU_BACKEND 時要重新審。
  3. 不收的類別：速度與記憶體（MINERU_PROCESSING_WINDOW_SIZE、MINERU_VIRTUAL_VRAM_SIZE、MINERU_PDF_RENDER_*、
     MINERU_INTRA_OP_NUM_THREADS、MINERU_INTER_OP_NUM_THREADS、MINERU_ENABLE_PIPELINE_INFERENCE_LOCKS、
     MINERU_API_MAX_CONCURRENT_REQUESTS、MINERU_LMDEPLOY_DEVICE）；log 與除錯輸出（MINERU_LOG_LEVEL、
     MINERU_SEAL_OCR_DEBUG*）；本機 API 服務的啟動、逾時與維運（MINERU_LOCAL_API_*、MINERU_TASK_RESULT_*、
     MINERU_API_*、MINERU_ROUTER_*、MINERU_GRADIO_*）。逾時類的變數逾時會讓 mineru 失敗，不會悄悄改變內容。
  已知極限：名單只涵蓋環境變數。MinerU 還會讀 `~/mineru.json`（或 MINERU_TOOLS_CONFIG_JSON 指的檔案）裡的
  latex-delimiter-config、llm-aided-config、models-dir、model-source，那是檔案設定，rag_lab 不檢查。
  MINERU_DEVICE_MODE 與 MINERU_MODEL_SOURCE 是否「會改變解析結果」是判斷（不同裝置的運算子實作、不同來源的模型權重
  可能有差異），無法從原始碼證明，依「寧可多擋」收進名單。

Dependencies: python-dotenv（由 raganything 帶入）。
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from dotenv import load_dotenv

# ==============================
# rag_lab 沒有管理的 LightRAG／RAG-Anything／MinerU 環境變數
# ==============================

# 名單對應的套件與版本；升級這三個套件時照模組 docstring 的步驟重新產生名單，再更新這裡
UNMANAGED_LIBRARY_ENV_VERSIONS = {"lightrag-hku": "1.4.16", "raganything": "1.4.3", "mineru": "3.4.5"}

UNMANAGED_LIBRARY_ENV = frozenset(
    {
        # LightRAG：查詢
        "TOP_K",
        "COSINE_THRESHOLD",
        "RELATED_CHUNK_NUMBER",
        "KG_CHUNK_PICK_METHOD",
        # LightRAG：匯入（切塊、實體抽取、描述合併）
        "CHUNK_SIZE",
        "CHUNK_OVERLAP_SIZE",
        "MAX_GLEANING",
        "MAX_EXTRACT_INPUT_TOKENS",
        "SUMMARY_LANGUAGE",
        "ENTITY_TYPES",
        "SUMMARY_MAX_TOKENS",
        "SUMMARY_CONTEXT_SIZE",
        "SUMMARY_LENGTH_RECOMMENDED",
        "FORCE_LLM_SUMMARY_ON_MERGE",
        "MAX_SOURCE_IDS_PER_ENTITY",
        "MAX_SOURCE_IDS_PER_RELATION",
        "SOURCE_IDS_LIMIT_METHOD",
        "MAX_FILE_PATHS",
        # LightRAG：儲存位置（設了就改用另一組儲存資料，查詢看不到原本的知識庫）
        "WORKSPACE",
        # RAG-Anything：哪些內容要處理、描述時帶多少前後文、檔案路徑怎麼寫進索引、解析方法的舊變數名稱
        "ENABLE_IMAGE_PROCESSING",
        "ENABLE_TABLE_PROCESSING",
        "ENABLE_EQUATION_PROCESSING",
        "CONTEXT_WINDOW",
        "CONTEXT_MODE",
        "MAX_CONTEXT_TOKENS",
        "INCLUDE_HEADERS",
        "INCLUDE_CAPTIONS",
        "CONTEXT_FILTER_CONTENT_TYPES",
        "CONTENT_FORMAT",
        "USE_FULL_PATH",
        "MINERU_PARSE_METHOD",
        # MinerU（`mineru -b pipeline -m auto` 子行程讀的）：設定檔位置、推論裝置、公式與表格的開關與模型、模型來源
        "MINERU_TOOLS_CONFIG_JSON",
        "MINERU_DEVICE_MODE",
        "MINERU_FORMULA_ENABLE",
        "MINERU_TABLE_ENABLE",
        "MINERU_OCR_DET_MASK_INLINE_FORMULA_ENABLE",
        "MINERU_TABLE_MERGE_ENABLE",
        "MINERU_FORMULA_CH_SUPPORT",
        "MINERU_MODEL_SOURCE",
    }
)


def reject_unmanaged_library_env() -> None:
    """環境裡有 rag_lab 沒管理的 LightRAG／RAG-Anything／MinerU 變數就中止。

    先照 LightRAG 的方式載入目前工作目錄的 .env（override=False），名單檢查才看得到那份檔案的內容。
    必須在 import lightrag 與 raganything 之前呼叫：它們在 import 時就把這些變數讀成預設值，
    值不合法（例如 TOP_K=abc）時 import 本身就會拋 ValueError，訊息還會帶出值。

    Raises:
        ConfigError: 有名單內的變數；field 與訊息列出名稱（依字母排序），不含值。
    """
    load_dotenv(dotenv_path=".env", override=False)
    present = sorted(UNMANAGED_LIBRARY_ENV & os.environ.keys())
    if present:
        raise ConfigError(
            "、".join(present),
            "是 rag_lab 沒有管理的 LightRAG／RAG-Anything／MinerU 設定，會悄悄改變匯入或查詢結果；"
            "請從環境變數與 .env 刪掉它們，或改用 rag_lab 的設定欄位（見 README 的設定說明）",
        )


# ==============================
# 例外與工具
# ==============================


class ConfigError(ValueError):
    """設定缺漏或格式錯誤。訊息只含欄位名稱與原因，不含欄位值（可能是金鑰）。

    Attributes:
        field: 出問題的環境變數名稱；名單檢查一次列出多個時以「、」連接。
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


def _non_negative_int(name: str) -> int:
    raw = _required(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(name, "必須是整數") from exc
    if value < 0:
        raise ConfigError(name, "必須大於或等於 0")
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
    rerank_base_url: str
    rerank_model: str
    rerank_api_key: str
    working_dir: str
    parser_output_dir: str
    llm_max_async: int
    llm_max_tokens: int
    vlm_max_tokens: int
    query_max_total_tokens: int
    query_max_entity_tokens: int
    query_max_relation_tokens: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """讀取 .env 與環境變數並驗證。

    Returns:
        Settings：同一個 process 內只解析一次。

    Raises:
        ConfigError: 任一必要欄位缺漏或格式不合法，或環境裡有 rag_lab 沒管理的 LightRAG／RAG-Anything／MinerU 變數。
    """
    load_dotenv()
    reject_unmanaged_library_env()
    query_max_total_tokens = _positive_int("QUERY_MAX_TOTAL_TOKENS")
    query_max_entity_tokens = _non_negative_int("QUERY_MAX_ENTITY_TOKENS")
    query_max_relation_tokens = _non_negative_int("QUERY_MAX_RELATION_TOKENS")
    if query_max_entity_tokens + query_max_relation_tokens >= query_max_total_tokens:
        raise ConfigError(
            "QUERY_MAX_ENTITY_TOKENS",
            "加上 QUERY_MAX_RELATION_TOKENS 必須小於 QUERY_MAX_TOTAL_TOKENS，否則文字 chunk 分不到 token",
        )
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
        rerank_base_url=_url("RERANK_BASE_URL"),
        rerank_model=_required("RERANK_MODEL"),
        rerank_api_key=_required("RERANK_API_KEY"),
        working_dir=_required("WORKING_DIR"),
        parser_output_dir=_required("PARSER_OUTPUT_DIR"),
        llm_max_async=_positive_int("LLM_MAX_ASYNC"),
        llm_max_tokens=_positive_int("LLM_MAX_TOKENS"),
        vlm_max_tokens=_positive_int("VLM_MAX_TOKENS"),
        query_max_total_tokens=query_max_total_tokens,
        query_max_entity_tokens=query_max_entity_tokens,
        query_max_relation_tokens=query_max_relation_tokens,
    )
