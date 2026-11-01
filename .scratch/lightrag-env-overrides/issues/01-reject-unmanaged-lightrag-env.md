# 01: 出現 rag_lab 沒有管理的 LightRAG／RAG-Anything 環境變數時，拒絕啟動

**What to build:** 使用者執行 rag_lab 的匯入、查詢或 eval 時，如果環境變數或 `.env` 裡有會改變 LightRAG／RAG-Anything 行為、但 rag_lab 沒有明確指定的設定（例如 `TOP_K`、`COSINE_THRESHOLD`、`CHUNK_SIZE`、`WORKSPACE`），rag_lab 在連線檢查之前就失敗，錯誤訊息列出這些變數的名稱（不印值），並說明要刪掉它們，或改成 rag_lab 的設定欄位。現在這些變數會讓檢索或匯入的結果改變，但不會報錯；eval 結果檔也看不出來。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 名單內任一變數出現在環境變數或 `.env` 時，`ingest`、`query`、`eval` 子命令與 Python API（`Session`）都失敗，訊息列出變數名稱，不含值。
- [ ] rag_lab 已經明確傳給 LightRAG／RAG-Anything 的參數（`max_total_tokens`、`max_entity_tokens`、`max_relation_tokens`、`chunk_top_k`、`enable_rerank`、`min_rerank_score`、`llm_model_max_async`、`max_parallel_insert`、`embedding_func_max_async`、`working_dir`、`parser_output_dir`、`parser`、`parse_method`）對應的變數不在名單內；`.env` 裡的 `WORKING_DIR` 仍然可以用。
- [ ] 名單沒有出現時，行為和現在相同：現有測試全綠。
- [ ] 名單與它對應的 LightRAG／RAG-Anything 版本寫在 README 的設定說明裡；升級這兩個套件時要重新產生名單。
- [ ] 測試沿用既有的縫（CLI 子行程＋Python API）：用環境變數放入一個名單內的變數，確認失敗與訊息內容。

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
