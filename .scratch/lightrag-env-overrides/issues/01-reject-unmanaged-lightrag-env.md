# 01: 出現 rag_lab 沒有管理的 LightRAG／RAG-Anything 環境變數時，拒絕啟動

**What to build:** 使用者執行 rag_lab 的匯入、查詢或 eval 時，如果環境變數或 `.env` 裡有會改變 LightRAG／RAG-Anything 行為、但 rag_lab 沒有明確指定的設定（例如 `TOP_K`、`COSINE_THRESHOLD`、`CHUNK_SIZE`、`WORKSPACE`），rag_lab 在連線檢查之前就失敗，錯誤訊息列出這些變數的名稱（不印值），並說明要刪掉它們，或改成 rag_lab 的設定欄位。現在這些變數會讓檢索或匯入的結果改變，但不會報錯；eval 結果檔也看不出來。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 名單內任一變數出現在環境變數或 `.env` 時，`ingest`、`query`、`eval` 子命令與 Python API（`Session`）都失敗，訊息列出變數名稱，不含值。
- [x] rag_lab 已經明確傳給 LightRAG／RAG-Anything 的參數（`max_total_tokens`、`max_entity_tokens`、`max_relation_tokens`、`chunk_top_k`、`enable_rerank`、`min_rerank_score`、`llm_model_max_async`、`max_parallel_insert`、`embedding_func_max_async`、`working_dir`、`parser_output_dir`、`parser`、`parse_method`）對應的變數不在名單內；`.env` 裡的 `WORKING_DIR` 仍然可以用。
- [x] 名單沒有出現時，行為和現在相同：現有測試全綠。
- [x] 名單與它對應的 LightRAG／RAG-Anything 版本寫在 README 的設定說明裡；升級這兩個套件時要重新產生名單。
- [x] 測試沿用既有的縫（CLI 子行程＋Python API）：用環境變數放入一個名單內的變數，確認失敗與訊息內容。

## 做法的選擇

使用者在 2026-11-02 選了第 1 種（拒絕啟動）。當時列出的 3 種：

1. **拒絕啟動**（上面的驗收條件）：設定錯了會立刻知道；代價是要維護一份名單，升級套件時要更新。
2. **rag_lab 明確指定所有相關參數**：把 `top_k`、`cosine_threshold`、`related_chunk_number`、`chunk_token_size` 等都用目前的預設值傳入，環境變數就影響不到。要決定的參數約 20 個，而且之後 LightRAG 新增的變數仍然會漏掉。
3. **只寫進文件**：不改程式；環境變數照樣能改變結果，而且不會報錯。

## 已查到的事實（LightRAG 1.4.16、RAG-Anything 1.4.3）

- 兩個套件在 import 時都會呼叫 `load_dotenv(dotenv_path=".env", override=False)`。讀的是**目前工作目錄**的 `.env`，不是 repo 根目錄的。rag_lab 的 `get_settings()` 也呼叫 `load_dotenv()`。
- 這些預設值在 import 時就從環境變數讀進來：`QueryParam` 的類別預設值（`TOP_K`、`CHUNK_TOP_K`、`MAX_*_TOKENS`、`HISTORY_TURNS`、`RERANK_BY_DEFAULT`），以及 `LightRAG`、`RAGAnythingConfig` 的 dataclass 欄位預設值。
- 會影響結果、rag_lab 沒有明確指定的變數（不完整，實作時從原始碼產生完整名單）：
  - 查詢：`TOP_K`、`COSINE_THRESHOLD`、`RELATED_CHUNK_NUMBER`、`KG_CHUNK_PICK_METHOD`、`HISTORY_TURNS`。
  - 匯入：`CHUNK_SIZE`、`CHUNK_OVERLAP_SIZE`、`MAX_GLEANING`、`MAX_EXTRACT_INPUT_TOKENS`、`SUMMARY_LANGUAGE`、`ENTITY_TYPES`、`SUMMARY_MAX_TOKENS`、`SUMMARY_CONTEXT_SIZE`、`FORCE_LLM_SUMMARY_ON_MERGE`、`MAX_SOURCE_IDS_PER_ENTITY`、`MAX_SOURCE_IDS_PER_RELATION`。
  - 儲存位置：`WORKSPACE`。設定之後，LightRAG 會改用另一組儲存資料，查詢看不到原本的知識庫。
  - RAG-Anything：`ENABLE_IMAGE_PROCESSING`、`ENABLE_TABLE_PROCESSING`、`ENABLE_EQUATION_PROCESSING`、`CONTEXT_WINDOW`、`CONTEXT_MODE`、`MAX_CONTEXT_TOKENS`、`CONTENT_FORMAT`。
- 2026-11-01 檢查：`.env` 和 `.env.example` 裡，和上面名單（加上 rag_lab 已指定的參數）同名的變數只有 `WORKING_DIR`，rag_lab 會明確傳入。所以目前的知識庫與 3 次 eval 沒有受到影響。只比對了變數名稱，沒有讀取 `.env` 的值。

## Comments

ASSUMPTION（2026-11-02，實作時採用最簡單的解）：

- 「出現」的定義是變數名稱存在於環境，值是空字串也算。理由：LightRAG 讀到空字串多半在 import 時直接例外，視為沒設反而讓錯誤更晚出現。
- 檢查前先照 LightRAG 的方式載入目前工作目錄的 `.env`（`load_dotenv(".env", override=False)`）。這讓 rag_lab 在 repo 根目錄以外的工作目錄也擋得到那裡的 `.env`；代價是 `get_settings` 現在也會把工作目錄 `.env` 裡的其他變數載入環境，但 LightRAG import 時本來就會這樣做，順序上 repo 根目錄的 `.env` 仍然優先。
- `graph` 子命令也套用檢查（它走同一個 `get_settings`）。它不用 LightRAG，但為了不讓同一個環境在某些子命令能跑、某些不能，沒有另外開例外。
- 名單版本與已安裝套件版本的對照測試（`test_the_list_was_generated_for_the_installed_library_versions`）是 ticket 沒要求的額外測試，用來落實「升級套件時要重新產生名單」；升級後它會失敗，這是預期的提醒。
- 與 ticket 的「已查到的事實」的差異：`HISTORY_TURNS` 沒收（1.4.16 裡沒有任何程式讀它，rag_lab 也不傳對話歷史）；多收了 `SUMMARY_LENGTH_RECOMMENDED`、`SOURCE_IDS_LIMIT_METHOD`、`MAX_FILE_PATHS`、`INCLUDE_HEADERS`、`INCLUDE_CAPTIONS`、`CONTEXT_FILTER_CONTENT_TYPES`、`USE_FULL_PATH`，以及 `MINERU_PARSE_METHOD`（`RAGAnythingConfig.__post_init__` 在 `PARSE_METHOD` 沒設時會用它蓋掉 rag_lab 明確傳入的 `parse_method="auto"`，所以「rag_lab 已指定」不代表安全）。

範圍外發現（沒有處理）：MinerU 子行程繼承行程環境，它自己讀的 `MINERU_*` 變數（例如裝置模式、表格與公式開關）會影響解析結果，不在 lightrag-hku／raganything 的原始碼裡，所以這份名單沒有涵蓋。建議另開 ticket 審 MinerU 的環境變數。

## 實作結果

做了什麼：

- `rag_lab/config.py`：新增 `UNMANAGED_LIBRARY_ENV`（31 個變數）、`UNMANAGED_LIBRARY_ENV_VERSIONS` 與 `reject_unmanaged_library_env()`；`get_settings` 在驗證必填欄位之前呼叫它。名單的產生步驟、收錄與排除標準寫在模組說明。
- `rag_lab/pipeline.py`、`rag_lab/models.py`：在 import lightrag 之前呼叫同一個檢查。實測發現：`TOP_K=abc` 這類不合法的值會讓 `import lightrag` 自己拋 `ValueError`，而且訊息帶出值，所以只在 `get_settings` 檢查不夠。
- 錯誤訊息格式：`設定錯誤：A、B 是 rag_lab 沒有管理的 LightRAG／RAG-Anything 設定……`，只有名稱；CLI 結束碼 3（既有的 `EXIT_CONFIG_ERROR`），Python API 拋既有的 `ConfigError`。
- 測試：`tests/test_cli.py` 的 `UnmanagedLightragEnvTest`（7 個：三個子命令、值不外洩、一次列出全部、空字串、連線檢查之前、已明確傳入的 13 個變數不被拒絕、工作目錄的 `.env`、名單版本）；`tests/test_python_api.py` 的 `UnmanagedLightragEnvTest`（模組函式與 `Session`，端點全部指向已關閉的埠，驗證拋 `ConfigError` 而不是 `EndpointError`，且沒有建立 `WORKING_DIR`）。
- 文件：README 第 1 節新增名單與版本；`docs/architecture.md` 的 `config.py` 職責、測試表與第 5 節。
- 檢查：本機 `.env` 與目前行程環境裡沒有名單內的變數（只用 `grep -c` 比對名稱）。

名單（31 個，lightrag-hku 1.4.16、raganything 1.4.3）：

- LightRAG 查詢：`TOP_K`、`COSINE_THRESHOLD`、`RELATED_CHUNK_NUMBER`、`KG_CHUNK_PICK_METHOD`
- LightRAG 匯入：`CHUNK_SIZE`、`CHUNK_OVERLAP_SIZE`、`MAX_GLEANING`、`MAX_EXTRACT_INPUT_TOKENS`、`SUMMARY_LANGUAGE`、`ENTITY_TYPES`、`SUMMARY_MAX_TOKENS`、`SUMMARY_CONTEXT_SIZE`、`SUMMARY_LENGTH_RECOMMENDED`、`FORCE_LLM_SUMMARY_ON_MERGE`、`MAX_SOURCE_IDS_PER_ENTITY`、`MAX_SOURCE_IDS_PER_RELATION`、`SOURCE_IDS_LIMIT_METHOD`、`MAX_FILE_PATHS`
- LightRAG 儲存：`WORKSPACE`
- RAG-Anything：`ENABLE_IMAGE_PROCESSING`、`ENABLE_TABLE_PROCESSING`、`ENABLE_EQUATION_PROCESSING`、`CONTEXT_WINDOW`、`CONTEXT_MODE`、`MAX_CONTEXT_TOKENS`、`INCLUDE_HEADERS`、`INCLUDE_CAPTIONS`、`CONTEXT_FILTER_CONTENT_TYPES`、`CONTENT_FORMAT`、`USE_FULL_PATH`、`MINERU_PARSE_METHOD`
