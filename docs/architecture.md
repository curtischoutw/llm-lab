# 專案架構

這份文件說明 repo 裡每個目錄放什麼、每支程式負責什麼，以及知識庫建好之後怎麼使用。怎麼安裝、怎麼啟動 server、實測數據，見 [README](../README.md)。

## 1. 整體流程

```
data/ 底下的文件（PDF、Office 文件、圖片）
      │  python -m rag_lab ingest
      ▼
MinerU 解析（文字、圖、表、公式） ──► output/<文件>_<雜湊>/   解析結果與切出的圖片
      │
      ▼
LightRAG 建圖：LLM 抽實體與關係，embedding 建向量
VLM／LLM 描述圖、表、公式，併入同一張圖（太大的表格先縮短、依列切成小表，每張各自描述）
      │
      ▼
rag_storage/   知識圖譜＋向量庫＋快取（＝知識庫本體）
      │  python -m rag_lab query／eval，或從 Python 用 rag_lab.pipeline.Session
      ▼
檢索（naive／local／global／hybrid／mix） → reranker 重新排序候選 chunk → 依 token 上限截斷成 context → LLM 依 context 產生答案
```

查詢時，LightRAG 取得候選 chunk（向量相似度與圖譜關聯）之後、依 token 上限截斷之前，會先把候選 chunk 的內容連同問題送到 reranker 的 `POST {RERANK_BASE_URL}/rerank`，依回傳的分數由高到低重新排序，保留分數最高的 `chunk_top_k`（LightRAG 預設 20）個，再依 token 上限截斷；所以排在前面的是和問題最相關的 chunk，而不是向量相似度最高的。所有查詢入口一律如此（`query`、`query --vlm-enhanced`、`eval`、`Session.query`／`evaluate`、模組函式），沒有開關；匯入不使用。rerank 函式（`models.rerank_model_func`）必須在建立 LightRAG 實例時傳入（`pipeline.build_rag`），初始化之後才設不會對 mix 生效。目前 rerank 失敗（端點沒回應、回錯誤）時 LightRAG 會記錄錯誤並改用原本的排序，查詢照常成功；讓它變成查詢失敗是 `.scratch/local-reranker/` 的 ticket 02。

`ingest` 接受 PDF、PPT、Word、Excel 與 8 種圖片格式（副檔名清單在 `rag_lab/formats.py`）。解析由 RAG-Anything 的 `parse_document` 依副檔名分派：圖片直接交給 MinerU；`.png`、`.jpg`、`.jpeg` 以外的圖片先由 RAG-Anything 用 Pillow 轉成 png；Office 文件（.ppt .pptx .doc .docx .xls .xlsx）先由 RAG-Anything 呼叫 PATH 上的 LibreOffice（`libreoffice`，找不到再試 `soffice`）轉成 PDF，寫在 `PARSER_OUTPUT_DIR` 底下，再交給 MinerU。專案只決定放行哪些副檔名，不判斷怎麼解析。沒有安裝 LibreOffice 時，RAG-Anything 的原始錯誤（含安裝方式）成為那份文件的匯入失敗原因，專案沒有改寫它。

三個模型與 reranker 都經由 HTTP 端點呼叫（前三個是 OpenAI 相容端點），端點寫在 `.env`：

| 用途 | 本機的 server | 什麼時候會呼叫 |
|---|---|---|
| LLM | `mlx_lm.server`（port 8080） | 建圖時抽實體、描述表格與公式；查詢時抽關鍵字、產生答案 |
| VLM | `scripts/vlm_server.py`（port 8081） | 建圖時描述圖片；`query --vlm-enhanced` 時看檢索到的圖片 |
| embedding | 同上（port 8081） | 建圖時把 chunk、實體、關係轉成向量；查詢時把問題轉成向量 |
| reranker | 同上（port 8081，啟動時加 `--reranker-model BAAI/bge-reranker-v2-m3`） | 查詢時重新排序候選 chunk；匯入不呼叫 |

## 2. 目錄

「進版控」為否的路徑不會被 git 追蹤，只存在你的機器上。

| 路徑 | 放什麼 | 進版控 | 怎麼產生 | 能不能刪 |
|---|---|---|---|---|
| `rag_lab/` | 主程式（Python 套件），見第 3 節 | 是 | — | 不能 |
| `examples/` | 從 Python 呼叫 `rag_lab` 的範例 | 是 | — | 不能 |
| `scripts/` | 維運工具：下載台新信用卡內容、論文與其他格式的文件，啟動 VLM server，檢查端點；另有 macOS 上 LibreOffice 用的 fontconfig 設定 | 是 | — | 不能 |
| `tests/` | 自動測試與測試用的假 server、假 MinerU、假 LibreOffice | 是 | — | 不能 |
| `eval/` | `eval` 指令的題目檔（JSONL）：範例 `questions.example.jsonl`（論文）、`questions.formats.jsonl`（`data/documents/` 的 6 份文件，其中 2 題跨格式題同時問到論文）、`questions.format_check.jsonl`（`data/format_check/`，只用在暫時的知識庫） | 是 | 手寫 | 範例檔被測試引用，不能刪；另外兩份是 README 第 5 節實測數據的題目 |
| `docs/` | 這份架構文件；`docs/agents/` 是給 Claude Code 技能讀的設定（issue tracker 位置、triage 標籤、domain 文件的讀法） | 是 | 手寫 | 不能 |
| `.scratch/rag-anything-lab/` | 主程式的規格 `spec.md` 與 7 張 ticket（`issues/`）。ticket 03–07 末尾有實測結果段落，README 的數據出自這裡 | 是 | 手寫 | 不建議：設計決策與實測結果記錄在這裡 |
| `.scratch/architecture-and-python-api/` | 這份架構文件、Python 範例、`Session` API 的規格與 5 張 ticket（01–05） | 是 | 手寫 | 不建議，理由同上 |
| `.scratch/taishin-credit-card-kb/` | 台新信用卡知識庫的規格與 9 張 ticket（01–09） | 是 | 手寫 | 不建議，理由同上 |
| `.scratch/multi-format-documents/` | 支援 PPT、Word、Excel、圖片的規格與 6 張 ticket（01–06）；ticket 05、06 末尾有實測結果段落 | 是 | 手寫 | 不建議，理由同上 |
| `GLOSSARY.md` | 專案用語（文件、格式、知識庫、權益、回饋方案、切換等）的定義與要避免的說法 | 是 | 手寫 | 不建議：規格與 ticket 依這些用語撰寫 |
| `.env.example` | 所有設定欄位與註解，預設值對應本機 MLX server | 是 | — | 不能 |
| `requirements.txt` | 專案 venv 的相依套件：`raganything==1.4.3` 鎖定版本，`lightrag-hku<1.5` 與 `mineru[core]<4` 只限制上限，其餘由 raganything 帶入 | 是 | — | 不能 |
| `CLAUDE.md` | 給 Claude Code 的專案說明 | 是 | — | 不能 |
| `.env` | 實際使用的設定（含 API 金鑰欄位） | 否 | 從 `.env.example` 複製後修改 | 刪了所有指令都會因缺設定而失敗 |
| `.venv/` | 專案的 Python 3.12 虛擬環境 | 否 | `python -m venv` ＋ `pip install -r requirements.txt` | 可以，照 README 第 1 節重建 |
| `data/papers/` | 前一版知識庫用的 5 篇 arXiv PDF；2026-10-30 已刪除，可用腳本重新下載 | 否 | `scripts/fetch_papers.py` | 可以，重新下載即可 |
| `data/documents/` | 前一版知識庫用的 6 份文件（PPT 2、Word 2、圖片 2）；2026-10-30 已刪除，可用腳本重新下載 | 否 | `scripts/fetch_documents.py` | 可以，重新下載即可 |
| `data/format_check/` | 已刪除（2026-10-30），可用腳本重新下載。原本是 5 份格式驗證用文件：Excel 2，舊格式 .ppt、.doc、.xls 各 1。和 `data/documents/` 分開，用資料夾匯入時不會混在一起 | 否 | `scripts/fetch_documents.py --group format_check` | 可以，重新下載即可 |
| `data/corpus/` | 前一版知識庫匯入論文用的資料夾，放指向 `data/papers/` 其中 3 篇的 symlink；2026-10-30 已刪除 | 否 | README 第 4 節的 `ln -sf` | 可以，不影響已建好的知識庫 |
| `rag_storage/` | **知識庫本體**：知識圖譜、向量庫、文件狀態、LLM 快取（路徑由 `.env` 的 `WORKING_DIR` 決定） | 否 | `ingest` | 刪了就要重新 `ingest`。前一版知識庫（3 篇論文約 1.7 小時，6 份文件約 0.7 小時）已在 2026-10-30 刪除，台新信用卡知識庫建立中 |
| `rag_storage.before-formats/` | 前一版知識庫匯入 `data/documents/` 之前的備份；2026-10-30 已刪除 | 否 | ticket 06 手動複製 | — |
| `output/<文件>_<雜湊>/`、`output/office/<主檔名>_<雜湊>/`、`output/<主檔名>.pdf` | MinerU 的解析結果：Markdown、content list、切出來的圖片（路徑由 `PARSER_OUTPUT_DIR` 決定）。PDF 與圖片在 `<文件>_<雜湊>/`；Office 文件從 ticket 10 起，LibreOffice 轉出的 PDF 與解析結果都在 `office/<主檔名>_<雜湊>/`，雜湊是原檔絕對路徑 md5 的前 8 碼；ticket 10 之前匯入的 Office 文件，轉出的 PDF 留在 `output/<主檔名>.pdf` | 否 | `ingest` | 不建議：知識庫記錄的是這裡圖片的絕對路徑，`--vlm-enhanced` 查詢要讀這些圖片 |
| `output/` 其他子目錄 | 開發過程的量測紀錄與 log（`ticket03_run/`、`ticket05_run/`、`formats_check_run/`、`formats_main_run/`、`crash_repro/`、`backend_bench/` 等），ticket 的實測段落引用它們當證據；`crash_repro/tools/watchdog.sh` 是記憶體監控腳本 | 否 | 開發時手動產生 | 可以，但會失去原始證據 |
| `eval_results/` | `eval` 產生的 Markdown 對照表，檔名 `eval_<時間戳記>.md` | 否 | `eval` | 可以 |
| `.claude/` | Claude Code 的本機設定與 subagent 用的 worktree | 否 | Claude Code | 不影響專案的程式 |

`rag_storage/` 裡的檔案（LightRAG 與 RAG-Anything 的格式，不要手動編輯）：

| 檔案 | 內容 |
|---|---|
| `graph_chunk_entity_relation.graphml` | 知識圖譜：實體（節點）與關係（邊）。`graph` 指令讀這個檔 |
| `vdb_chunks.json`、`vdb_entities.json`、`vdb_relationships.json` | 向量庫：chunk、實體、關係各自的 embedding |
| `kv_store_full_docs.json`、`kv_store_text_chunks.json` | 原文與切好的 chunk |
| `kv_store_full_entities.json`、`kv_store_full_relations.json`、`kv_store_entity_chunks.json`、`kv_store_relation_chunks.json` | 每份文件抽出的實體與關係，以及它們出自哪些 chunk |
| `kv_store_doc_status.json` | 每份文件的處理狀態；`ingest` 依它判斷哪篇已完成、可以略過 |
| `kv_store_llm_response_cache.json` | LLM 回應快取；同一個問題再問一次會直接命中，不呼叫 LLM |
| `kv_store_parse_cache.json` | RAG-Anything 的解析快取，重複匯入同一個檔案時不重跑 MinerU |

## 3. 程式碼

每個檔案開頭的 docstring 有完整的設計決策與已知極限，這裡只列職責與主要介面。

### 3.1 `rag_lab/`：主程式

模組之間的依賴（箭頭指向被 import 的一方）：

```
__main__ ──► config
   │  ├────► formats
   │  ├────► evaluation
   │  ├────► pipeline ──► models ──► config
   │  │         ├───────► config
   │  │         ├───────► tables
   │  │         └───────► evaluation
   │  └────► graph_report
```

`__main__` 啟動時只 import `config`、`formats`、`evaluation`；只在執行對應子命令時才 import `pipeline`、`graph_report`，所以設定錯誤、題目檔格式錯誤能在載入 LightRAG／torch 之前就回報。

| 檔案 | 職責 | 主要介面 |
|---|---|---|
| `__init__.py` | 套件根，刻意不 import 任何子模組 | — |
| `__main__.py` | CLI 入口：解析參數、驗證輸入、呼叫 `pipeline`／`graph_report`、格式化輸出、決定結束碼（0 成功、1 執行失敗、2 用法或輸入錯誤、3 設定錯誤） | `main(argv)`；子命令 `ingest`、`query`、`graph`、`eval` |
| `formats.py` | 支援的格式清單（PDF、PPT、Word、Excel 與 8 種圖片副檔名），專案裡只定義這一次；CLI 的資料夾過濾與錯誤訊息都從這裡取值。只靠標準函式庫，所以輸入路徑驗證能在載入 LightRAG／torch 之前完成 | `FORMATS`、`SUPPORTED_EXTENSIONS`、`is_supported(path)`、`describe_supported()` |
| `config.py` | 從 `.env` 與環境變數讀設定並驗證；必填欄位缺漏或格式錯就拋錯，不給預設值（只有 `EMBED_QUERY_PREFIX` 是選填，預設空字串） | `get_settings() -> Settings`、`ConfigError` |
| `models.py` | 把三個 OpenAI 相容端點包成 RAG-Anything 需要的模型函式、把 rerank 端點包成 LightRAG 的 rerank 函式；失敗包成帶端點名稱與位址的錯誤；計數圖、表、公式描述的失敗與描述後的內容寫入索引的失敗（RAG-Anything 自己會吞掉） | `llm_model_func`、`vision_model_func`、`build_embedding_func()`、`rerank_model_func`、`check_reachable(...)`、`EndpointError` |
| `tables.py` | 把太大的表格縮短（拿掉值為 1 的 `rowspan`／`colspan`），仍超過 800 token 就依列切成小表，每張重複表頭列；只靠標準函式庫。`pipeline.LabRAGAnything.parse_document` 在 RAG-Anything 算好文件 ID、存好解析快取之後，才對回傳給呼叫端的 content list 套用它，所以文件 ID 與解析快取不變 | `limit_table_sizes(content_list, count_tokens)`、`TABLE_BODY_MAX_TOKENS` |
| `pipeline.py` | 核心流程：建立 RAGAnything 實例（`LabRAGAnything`：切大表格、計數寫入失敗）、匯入（解析、建圖、多模態描述）、查詢、批次比較；把 LightRAG 會吞掉的錯誤轉成可偵測的失敗（圖表公式描述或多模態寫入失敗的文件，整批結束後改記成 `failed`）；`Session` 讓同一個 process 只初始化一次、依序呼叫 | `Session`（`ingest`、`query`、`evaluate`、`close`）、模組函式 `ingest(documents) -> IngestSummary`、`query(question, mode, vlm_enhanced=False) -> str`、`evaluate(questions) -> list[list[Cell]]`、`PipelineError`、`SessionError`、`SessionClosedError` |
| `evaluation.py` | `eval` 的題目檔讀取驗證與 Markdown 對照表排版，不需要任何模型 | `load_questions(path)`、`render_report(...)`、`RETRIEVAL_MODES`、`QuestionFileError` |
| `graph_report.py` | 直接讀 `rag_storage/` 的 graphml，抽樣列出實體與關係，不需要模型 server | `load_graph(working_dir)`、`format_report(graph, sample_size, seed)` |

### 3.2 `scripts/`：維運工具

都是獨立腳本，不屬於 `rag_lab` 套件。

| 檔案 | 用途 | 用哪個 Python 執行 |
|---|---|---|
| `fetch_papers.py` | 下載 5 篇 RAG 論文到 `data/papers/`，先比對 arXiv 標題，已存在的完整檔案會略過 | 專案 venv 或系統 python3（只用標準函式庫） |
| `fetch_documents.py` | 下載 11 份公開文件（PPT、Word、Excel、圖片）：6 份到 `data/documents/`，5 份到 `data/format_check/`；先寫 `.part`，SHA-256 相符才改名，已存在且雜湊正確的檔案會略過，可用 `--group` 只下載一組 | 專案 venv 或系統 python3（只用標準函式庫） |
| `vlm_server.py` | 啟動 VLM＋embedding 的 `mlx_vlm.server`，先把 MLX 的 GPU cache 上限設為 1 GB，避免 ingest 時記憶體不足 | pipx 安裝的 mlx-vlm 的 python |
| `smoke_test.py` | 確認三個端點都能用：chat、看 base64 圖片、embedding 維度 | 專案 venv |
| `test_fetch_papers.py` | `fetch_papers.py` 的離線測試（對本機假 arXiv server） | `python -m unittest scripts.test_fetch_papers` |
| `test_fetch_documents.py` | `fetch_documents.py` 的離線測試（對本機假 HTTP server）：雜湊核對、斷線與 HTTP 失敗、本地檔案系統錯誤、略過已存在的檔案、`--group`、清單與 spec 表格的對照 | `python -m unittest scripts/test_fetch_documents.py` |

### 3.3 `tests/`：自動測試

測試只從子行程進入，只看結束碼、輸出和產生的檔案，測試本身的 process 不 import `rag_lab`。子行程有三種：CLI（`python -m rag_lab ...`）、範例（`python -m examples...`），以及 `test_python_api.py` 以 `python -c` 執行的一段程式（在子行程裡呼叫 `rag_lab.pipeline` 的公開介面並印出每一步的結果）。模型與 MinerU 都用假的，不需要開 server，`python -m unittest` 一次跑完。

| 檔案 | 內容 |
|---|---|
| `__init__.py` | 測試套件的說明：測試從子行程進入、模型用假 server |
| `fake_openai_server.py` | 假的 OpenAI 相容 server：chat、vision、embedding、rerank 都回固定且合法的內容，並記錄收到的請求（含 `Authorization` 標頭）；可注入故障（`fail_chat`、`fail_vision`、`fail_chat_containing`、`fail_embed_containing`、`fail_rerank` 等），rerank 的順序可由 `rerank_promote`／`rerank_demote` 指定 |
| `fake_mineru.py` | 假的 `mineru` 指令：依主檔名寫出固定的解析結果（PDF、圖片與假 LibreOffice 轉出的 PDF 相同）（文字、一張圖、一個表、一條公式）；主檔名以 `bigtable` 開頭時表格換成 60 列 × 6 欄的大表格（`bigspan` 開頭的版本有一格 rowspan 跨到表尾），以 `spans` 開頭時小表格的儲存格帶 `rowspan=1 colspan=1`；PDF 裡有假 LibreOffice 寫的來源標記行時，多輸出一段 `Converted from Office document: <來源第一行>`，讓主檔名相同的 Office 文件分辨得出來；設了 `FAKE_MINERU_VERSION_LOG` 時記錄每次 `--version`，用來計算初始化次數 |
| `fake_libreoffice.py` | 假的 `libreoffice`／`soffice` 指令：收到 `--headless --convert-to pdf --outdir <dir> <檔案>` 時在 `<dir>` 寫出 `<主檔名>.pdf`，內容含輸入檔第一行的來源標記；引數形式不符時以非零碼結束；主檔名以 `broken` 開頭時以非零碼結束，模擬轉檔失敗。`test_pipeline.py` 的 `PipelineCase` 以兩個名稱放在 PATH 最前面；「沒有 LibreOffice」的測試把 PATH 改成只有假 mineru 的資料夾 |
| `test_cli.py` | 設定驗證、子命令註冊、結束碼；提供其他測試共用的 `run_cli`、`valid_env` |
| `test_fake_server.py` | 以 `scripts/smoke_test.py` 當客戶端對假 server 執行，確認假 server 符合同一份介面（smoke test 曾對真 server 通過，所以把它當作介面的定義）；不連真 server |
| `test_pipeline.py` | `ingest`、`query` 的完整流程（含各種圖片與 Office 格式、資料夾挑選與略過、不支援格式的錯誤、沒有 LibreOffice 的錯誤、轉檔失敗、重複匯入、失敗重試、大表格切成小表、描述與寫入失敗、端點不可達、查詢總 token 上限與 entity／relation 上限、rerank 的請求與順序）；提供共用的 `PipelineCase`、產生各格式小圖的 `write_image`（用 Pillow）與寫出 Office 替身檔的 `write_office`（內容是一行文字，不是真的 Office 檔：假 LibreOffice 與假 mineru 都不讀內容） |
| `test_graph.py` | `graph` 指令的抽樣與可重現性 |
| `test_eval.py` | `eval` 指令的題目檔驗證與結果表 |
| `test_python_api.py` | 在同一個 process 裡依序呼叫 `rag_lab.pipeline` 的模組函式與 `Session`：連續呼叫、每次 ingest 的統計獨立、同一個 `Session` 只初始化一次並在關閉後釋放實例、誤用時的 `SessionError`、開 `Session` 失敗後不留狀態、忘了 `close()` 時的收尾、匯入圖片與 Office 文件、不支援的格式整批被拒絕、大表格切成小表與描述失敗後的重試 |
| `test_examples.py` | 實際執行 `examples/` 的範例，確認在一個 `Session` 裡連續提問能跑完 |

### 3.4 `examples/`：範例

| 檔案 | 內容 |
|---|---|
| `query_from_python.py` | 開一個 `Session`，對已建好的知識庫逐題提問並印出問答，見第 4.2 節 |

## 4. 知識庫建好之後怎麼使用

以下都要在 repo 根目錄執行，並先開好兩個模型 server（README 第 3 節）。只有 `graph` 不需要 server。

### 4.1 命令列

```sh
.venv/bin/python -m rag_lab query "What are the two retrieval levels in LightRAG?"   # 問一題，預設 mix 模式
.venv/bin/python -m rag_lab query --mode naive "..."                                # 指定檢索模式
.venv/bin/python -m rag_lab eval eval/questions.example.jsonl                       # 題目檔 × 五種模式，寫出對照表
.venv/bin/python -m rag_lab graph                                                   # 抽樣看知識圖譜
.venv/bin/python -m rag_lab ingest data/papers/2005.11401.pdf                       # 再加一篇論文進知識庫
```

五種檢索模式的差別：

| 模式 | 檢索什麼 |
|---|---|
| `naive` | 只用向量搜尋找相似的 chunk，不用知識圖譜 |
| `local` | 用 LLM 從問題抽出的低層關鍵字（具體名詞）找相關實體，再帶出這些實體的關係與出處 chunk |
| `global` | 用高層關鍵字（主題、概念）找相關關係，再帶出關係兩端的實體與出處 chunk |
| `hybrid` | `local` ＋ `global` |
| `mix` | `hybrid` 再加上 `naive` 的向量 chunk；預設模式 |

### 4.2 在自己的 Python 程式裡呼叫

`rag_lab.pipeline` 提供同步的 `Session` 與三個模組函式，CLI 也是呼叫這三個函式。設定一律讀 `.env`，不用另外傳。

**Session**：在同一個 `Session` 裡依序呼叫，知識庫只在開 `Session` 時載入一次。

```python
from pathlib import Path

from rag_lab.pipeline import Session

with Session() as session:
    summary = session.ingest([Path("data/papers/2310.11511.pdf")])  # Self-RAG 論文
    answer = session.query("What is Self-RAG?", mode="mix")
```

| 方法 | 回傳 | 失敗時 |
|---|---|---|
| `query(question, mode, vlm_enhanced=False)` | 答案字串 | `mode` 不是五種檢索模式之一拋 `ValueError`（LightRAG 另外接受的 `bypass` 不檢索，這裡不允許）；開始前端點不可達拋 `EndpointError`；查詢失敗（含查詢途中 LLM 失敗）或沒有答案拋 `PipelineError`；`vlm_enhanced=True` 時 VLM 呼叫失敗拋 `EndpointError` |
| `ingest(documents: list[Path])` | `IngestSummary`：每篇的耗時與錯誤、圖譜統計、這一次的 VLM 與描述統計 | 單篇失敗記在該篇的 `error`、圖表公式描述或多模態寫入失敗也記在該篇的 `error`（同時文件在索引裡改記成 `failed`，重新執行會重試）並彙整在 `description_error`，都不拋例外；`documents` 裡有任何一份不是支援的格式（`rag_lab/formats.py`），在呼叫任何模型或解析之前拋 `PipelineError`，整批都不匯入；開始前端點不可達拋 `EndpointError` |
| `evaluate(questions: list[Question])` | `cells[i][j]`：第 i 題在第 j 種模式的答案或錯誤 | 單格失敗記在該格的 `error`，不拋例外；開始前 LLM 或 embedding 端點不可達拋 `EndpointError` |
| `close()` | — | 離開 `with` 時自動呼叫；重複呼叫不做事 |

開 `Session()` 時就會檢查 LLM 與 embedding 端點並初始化知識庫：設定有誤拋 `rag_lab.config.ConfigError`，端點不可達拋 `EndpointError`，初始化失敗拋 `PipelineError`。

`Session` 的規則，違反時拋 `SessionError`（關閉後呼叫拋它的子類 `SessionClosedError`）：
- 同一個 process 同一時間只能開一個 `Session`。LightRAG 的共用狀態是 process 層級的，要先 `close()` 前一個。
- 只能在建立它的執行緒使用；建立它的執行緒已經結束時，其他執行緒可以呼叫 `close()`。
- 不能在已經有執行中 event loop 的地方使用（Jupyter、async 函式）。替代寫法：把開 `Session` 與所有呼叫寫成一個同步函式，再用 `await asyncio.to_thread(該函式)` 執行。
- 忘了 `close()` 時，process 結束前會自動收尾（寫回快取與索引），並在 stderr 印出警告。

`SessionError` 不繼承 `PipelineError`：它代表程式寫錯，要改程式，不是匯入或查詢失敗。

**模組函式**：`query(...)`、`ingest(...)`、`evaluate(...)` 的參數、回傳與失敗行為跟 `Session` 的同名方法相同，差別是每次呼叫都會開一個 `Session`、呼叫一次、再關閉，等於每次都重新載入知識庫。適合只做一件事的情況（CLI 就是這樣用）。已經開著 `Session` 時呼叫模組函式，會因為「同時只能開一個」而拋 `SessionError`。

完整範例是 [`examples/query_from_python.py`](../examples/query_from_python.py)，下面是節錄（省略 `main()` 與每題之間的空行）：

```python
from rag_lab.pipeline import Session

QUESTIONS = [
    "What are the two retrieval levels in LightRAG?",
    "What is the main idea of RAG-Anything?",
]

with Session() as session:
    for question in QUESTIONS:
        answer = session.query(question, mode="mix")
        print(f"Q: {question}")
        print(f"A: {answer}")
```

執行（在 repo 根目錄）：

```sh
.venv/bin/python -m examples.query_from_python
```

一定要用 `python -m`，從 repo 根目錄執行：
- `import rag_lab` 要靠 repo 根目錄在 `sys.path` 上。直接執行 `python examples/query_from_python.py` 只會把 `examples/` 加進 `sys.path`，會出現 `ModuleNotFoundError`。
- `WORKING_DIR` 的預設值（`.env.example`）是 `./rag_storage`，相對於目前目錄。

自己寫的程式也一樣：放在 `examples/` 底下，或放在 repo 根目錄的其他資料夾，然後用 `python -m <資料夾>.<檔名>` 執行。

已知極限：
- `Session` 讀的是開啟當下的索引。開著的期間如果另一個 process（例如另一個終端機的 `python -m rag_lab ingest`）匯入新論文，這個 `Session` 看不到，要關掉重開。
- 呼叫途中按 Ctrl-C 中斷後，不保證 `Session` 的狀態一致；中斷後應關閉 `Session` 再開新的。
- 本機 4B LLM 每題 52–66 秒；同一個問題再問一次會命中 LLM 快取，4 秒（README 第 5 節）。

## 5. 設定

所有欄位與註解在 `.env.example`；搬機器、換模型時要改哪些欄位，見 README 第 6 節。改程式之外的東西（端點、模型、路徑、並行數、查詢 token 上限）都只改 `.env`。

查詢時的 rerank 由 `RERANK_BASE_URL`、`RERANK_MODEL`、`RERANK_API_KEY` 三個必填欄位設定（驗證規則同其他端點），不能關閉；eval 對照表表頭的「固定查詢設定」與 `RERANK_MODEL` 記下當時用的 reranker。

查詢 context 的 token 分配由三個欄位決定：`QUERY_MAX_TOTAL_TOKENS`（總上限）、`QUERY_MAX_ENTITY_TOKENS` 與 `QUERY_MAX_RELATION_TOKENS`（圖譜 context 裡 entity 與 relation 描述各自的上限），其餘留給文字 chunk。`config.get_settings` 檢查兩個上限是 0 以上的整數、相加小於總上限；`pipeline.query_kwargs` 把三個值原樣交給 LightRAG 的 `QueryParam`（CLI 的 `query` 與 `eval`、`Session.query`、`pipeline.query`、`pipeline.evaluate`、VLM 增強查詢都走同一個函式），不依 LightRAG 預設比例縮放。
