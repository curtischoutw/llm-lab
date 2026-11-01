# 02: MinerU 讀的 `MINERU_*` 環境變數也會改變匯入結果，要決定要不要納入拒絕名單

**What to build:** 使用者執行 `ingest` 時，環境變數或 `.env` 裡的 `MINERU_*` 變數（例如 `MINERU_TABLE_ENABLE`、`MINERU_FORMULA_ENABLE`、`MINERU_DEVICE_MODE`）會傳到 MinerU 子行程，改變解析結果（表格、公式有沒有被辨識），但 rag_lab 不會報錯，匯入報告也看不出來。ticket 01 的拒絕名單只涵蓋 lightrag-hku 與 raganything 原始碼讀的變數，沒有這些。這張先調查，再照 ticket 01 的做法（拒絕啟動）決定哪些要收進名單。

**Blocked by:** 01（已完成）

**Status:** resolved

- [x] 從已安裝的 MinerU 原始碼產生完整清單：所有讀取的 `MINERU_*` 變數（包含 `os.getenv`、`os.environ.get`、`os.environ[...]` 等寫法），每個變數附檔案:行號與預設值。
- [x] 分類：會改變解析結果的（例如表格、公式、OCR 的開關），只影響效能或記錄的（例如 log 等級、執行緒數、`MINERU_API_*`、`MINERU_GRADIO_*`）。分類理由寫在 ticket 裡。
- [x] 確認 rag_lab 呼叫 MinerU 時（RAG-Anything 以子行程執行 `mineru`），哪些變數實際會被讀到：rag_lab 用的後端與解析方法只走其中一部分程式路徑。
- [x] 會改變解析結果、且實際會被讀到的變數，收進 ticket 01 的名單：出現在環境變數或 `.env` 時，`ingest` 與 Python API 的匯入失敗，訊息只列名稱、不含值。
- [x] 查詢（`query`、`eval`）不呼叫 MinerU：決定這些變數在查詢時要不要也拒絕，寫出理由。
- [x] README 的名單段落加上這些變數與 MinerU 版本；升級 MinerU 時要重新產生。
- [x] 測試沿用 ticket 01 的縫（CLI 子行程＋Python API），現有測試全綠。

## 已知的事實（2026-11-02）

- ticket 01 的 implementer 回報：MinerU 子行程繼承 rag_lab 行程的環境；rag_lab 的 `load_dotenv()` 會把 `.env` 的內容放進行程環境，所以 `.env` 裡的 `MINERU_*` 也會傳到子行程。
- 已安裝的 MinerU 是 3.4.5（`.venv`）。用 `os.getenv(` 與 `os.environ.get(` 兩種寫法搜尋，找到 25 個不同的 `MINERU_*` 名稱，例如 `MINERU_TABLE_ENABLE`、`MINERU_FORMULA_ENABLE`、`MINERU_TABLE_MERGE_ENABLE`、`MINERU_VLM_TABLE_ENABLE`、`MINERU_DEVICE_MODE`、`MINERU_TOOLS_CONFIG_JSON`。`os.environ[...]` 與其他寫法沒有搜尋，這份清單不完整。
- 已經匯入、解析快取命中的文件不會重新解析，所以這些變數只影響新匯入或解析快取沒命中的文件。

## Comments

ASSUMPTION（2026-11-02，實作時採用）：

- `MINERU_DEVICE_MODE` 與 `MINERU_MODEL_SOURCE` 是否「會改變解析結果」無法從原始碼證明：前者換推論裝置（cuda、mps、cpu），不同裝置的運算子實作可能讓 layout、OCR、公式的輸出有差異；後者決定模型權重從 huggingface、modelscope 還是本機資料夾（`local`，路徑來自 `mineru.json` 的 `models-dir`）載入，權重可能不同。依「寧可多擋」收進名單。代價：在中國大陸需要 `MINERU_MODEL_SOURCE=modelscope` 的使用者要改在 `~/mineru.json` 的 `model-source` 設定。
- `MINERU_VIRTUAL_VRAM_SIZE`、`MINERU_PROCESSING_WINDOW_SIZE` 只改批次大小與一次處理的頁數，歸類為效能。批次大小是否會讓輸出有浮點誤差等級的差異無法證明，沒有收進名單；這兩個變數也不會切換功能或模型，其他同類（`MINERU_PDF_RENDER_THREADS`、`MINERU_INTRA_OP_NUM_THREADS`）一併歸為效能。
- `MINERU_LMDEPLOY_DEVICE` 在 pipeline 路徑只有 `corex`（關閉 OCR 偵測的批次，`pipeline_analyze.py:371`）與 `ascend`（本機 API 改用 spawn 啟動，`api_client.py:141`）兩個值有作用，都是特定硬體的行為，歸為效能。這台機器是 Apple Silicon，走不到。
- 逾時類變數（`MINERU_PDF_RENDER_TIMEOUT`、`MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS`、`MINERU_TASK_RESULT_*`）逾時時 mineru 以錯誤結束（例如 `pdf_image_tools.py:316` 拋 `TimeoutError`），失敗是明確的，不會悄悄改變內容，歸為維運。
- 查詢（`query`、`eval`）也拒絕，理由：(1) ticket 01 的檢查在 `get_settings` 與 import 前，所有入口一視同仁，最簡單也最一致；(2) 同一個環境若 `ingest` 被擋、`query` 能跑，使用者會在兩個子命令得到不同的結論，`eval` 結果檔又看不出這個變數存在；(3) 查詢雖然不解析文件，但 `mineru --version` 檢查在查詢時一樣會執行（`rag_lab/pipeline.py` 模組說明），`MINERU_TOOLS_CONFIG_JSON` 這類變數會在那裡被 mineru 讀到。代價：只做查詢的人也要先刪掉這些變數。
- 「rag_lab 實際走得到」以 RAG-Anything 1.4.3 的 `MineruParser._run_mineru_command` 組出的指令為準：`mineru -p <檔> -o <輸出> -m auto -b pipeline`，沒有 `-l -s -e -f -t -d -u --source`（`raganything/parser.py:1301-1330`；`rag_lab/pipeline.py:143,425` 傳 `backend="pipeline"`、`pipeline.py:230` 傳 `parse_method="auto"`）。公式與表格因此用 mineru CLI 的預設（開），環境變數 `MINERU_FORMULA_ENABLE`、`MINERU_TABLE_ENABLE` 會蓋掉它。vlm 與 hybrid 後端才讀的變數，若 rag_lab 日後改 `MINERU_BACKEND`，要重新審。
- 從 `mineru` CLI 到實際推論的環境傳遞：CLI 啟動本機 API 服務時以 `os.environ.copy()` 為底（`api_client.py:392`），只覆寫 `MINERU_API_OUTPUT_ROOT`、`MINERU_API_MAX_CONCURRENT_REQUESTS`、`MINERU_API_DISABLE_ACCESS_LOG`、`MINERU_API_SHUTDOWN_ON_STDIN_EOF`，其餘變數照樣傳到做推論的行程。這是讀原始碼的結論，沒有實際跑真的 mineru 驗證。
- 與 ticket 的「已知的事實」的差異：ticket 說用兩種寫法搜到 25 個名稱；改成搜所有 `MINERU_` 字樣、再人工看常數與 `get_int_env(name)`、`env_flag_enabled(name)` 這類間接讀法，在 `mineru`、`mineru_vl_utils`、`mineru_llama_cpp` 三個套件共找到 51 個不同的 `MINERU_*` 名稱（`mineru_llama_cpp` 沒有）。

範圍外發現（沒有處理）：

- MinerU 也讀 `~/mineru.json`（路徑可由 `MINERU_TOOLS_CONFIG_JSON` 改）：`latex-delimiter-config`、`llm-aided-config`（LLM 輔助標題分級）、`models-dir`、`model-source`、`config_version` 等會改變解析結果。這是檔案設定，不是環境變數，rag_lab 沒有檢查。這台機器的 home 底下有 `~/mineru.json`（沒有讀內容）。要不要檢查它的內容或把它的雜湊記進匯入報告，是另一個決定。
- mineru 還讀不帶 `MINERU_` 前綴的變數（例如 `TORCH_*`、`OMP_NUM_THREADS`、`TOKENIZERS_PARALLELISM`、`HF_*`、`VLLM_USE_V1`、`FTLANG_CACHE`、`GRADIO_ALLOWED_PATHS`、`REQUEST_TIMEOUT`），本 ticket 沒有逐個審；其中多數是硬體或下載設定。

## 清單

查詢範圍：`mineru`（3.4.5）、`mineru_vl_utils`（1.2.1）、`mineru_llama_cpp`（0.2.0）三個套件的 `.py`，路徑前綴 `.venv/lib/python3.12/site-packages/`；共 51 個不同的 `MINERU_*` 名稱，下表依分類列出。檔案:行號是主要讀取點（同一變數多處讀取時列出和 rag_lab 路徑有關的）。

### A. 會改變解析結果、rag_lab 走得到：收進名單（8 個）

| 變數 | 檔案:行號 | 預設值 | 理由 |
|---|---|---|---|
| `MINERU_TOOLS_CONFIG_JSON` | `mineru/utils/config_reader.py:14`、`mineru/utils/models_download_utils.py:25` | `mineru.json`（home 底下） | 換成另一個設定檔，等於換 LaTeX 分隔符、LLM 輔助標題分級、模型資料夾與來源 |
| `MINERU_DEVICE_MODE` | `mineru/utils/config_reader.py:106` | 自動偵測（cuda、mps、npu 等、最後 cpu） | 換推論裝置（ASSUMPTION，見上） |
| `MINERU_FORMULA_ENABLE` | `mineru/utils/config_reader.py:141`（pipeline 用：`backend/pipeline/batch_analyze.py:66`） | 未設時用 CLI 參數（rag_lab 沒傳 `-f`，等於開） | 開關公式辨識，直接改變有沒有公式內容 |
| `MINERU_TABLE_ENABLE` | `mineru/utils/config_reader.py:147`（`batch_analyze.py:67`） | 同上 | 開關表格辨識 |
| `MINERU_OCR_DET_MASK_INLINE_FORMULA_ENABLE` | `mineru/utils/config_reader.py:153`（`batch_analyze.py:80`，建構子預設 `True`） | 未設時 `True` | 決定 OCR 偵測前是否遮住行內公式，改變文字與公式區塊的切法 |
| `MINERU_TABLE_MERGE_ENABLE` | `mineru/backend/utils/runtime_utils.py:19`（pipeline 呼叫：`backend/pipeline/model_json_to_middle_json.py:8`） | `true` | 開關跨頁表格合併，改變表格個數與內容 |
| `MINERU_FORMULA_CH_SUPPORT` | `mineru/backend/pipeline/model_init.py:62` | `False`（`unimernet_small`） | `true` 時換成 `pp_formulanet_plus_m` 公式辨識模型 |
| `MINERU_MODEL_SOURCE` | `mineru/utils/models_download_utils.py:14,214`、`mineru/cli/models_download.py:17,64,82` | 未設時看 `mineru.json` 的 `model-source`，再沒有就自動偵測 huggingface／modelscope | 決定模型權重來源，`local` 時用 `models-dir`（ASSUMPTION，見上） |

### B. 只影響速度或記憶體：不收（9 個）

| 變數 | 檔案:行號 | 預設值 | 理由 |
|---|---|---|---|
| `MINERU_PROCESSING_WINDOW_SIZE` | `mineru/utils/config_reader.py:159`（`backend/pipeline/pipeline_analyze.py:207`） | `64` | 一次處理的頁數；每份文件在它的最後一頁處理完才收尾（`pipeline_analyze.py:301-302`），跨頁處理（含表格合併）不受視窗大小影響 |
| `MINERU_VIRTUAL_VRAM_SIZE` | `mineru/utils/model_utils.py:218`（`pipeline_analyze.py:353`） | 自動偵測（Apple Silicon 為 1 GB，batch ratio 1） | 只決定批次比例與清記憶體時機 |
| `MINERU_PDF_RENDER_TIMEOUT` | `mineru/utils/os_env_config.py:11` | `300` | 渲染逾時；逾時拋 `TimeoutError`（`utils/pdf_image_tools.py:316`） |
| `MINERU_PDF_RENDER_THREADS` | `mineru/utils/os_env_config.py:16` | `3` | 渲染行程數 |
| `MINERU_INTRA_OP_NUM_THREADS` | `mineru/model/table/rec/slanet_plus/table_structure.py:33`、`mineru/model/table/rec/unet_table/table_structure_unet.py:34` | `-1`（不設） | onnxruntime 執行緒數 |
| `MINERU_INTER_OP_NUM_THREADS` | 同上 `:34`、`:35` | `-1` | 同上 |
| `MINERU_ENABLE_PIPELINE_INFERENCE_LOCKS` | `mineru/backend/pipeline/model_init.py:28` | `False` | 推論鎖的實驗開關，只影響多執行緒競爭 |
| `MINERU_LMDEPLOY_DEVICE` | `mineru/backend/pipeline/pipeline_analyze.py:371`、`model_init.py:322`、`mineru/cli/api_client.py:141`、`mineru/cli/common.py:37`、`mineru/backend/vlm/vlm_analyze.py:184`、`mineru/model/vlm/lmdeploy_server.py:57` | 空字串 | pipeline 路徑只對 `corex`（關 OCR 偵測批次）與 `ascend`（本機 API 用 spawn）有作用，特定硬體 |
| `MINERU_API_MAX_CONCURRENT_REQUESTS` | `mineru/utils/config_reader.py:177` | `3` | 本機 API 並行請求數；非正整數時 mineru 拋 `ValueError` |

### C. log 與除錯輸出：不收（4 個）

| 變數 | 檔案:行號 | 預設值 | 理由 |
|---|---|---|---|
| `MINERU_LOG_LEVEL` | `mineru/cli/client.py:59`、`fast_api.py:74`、`gradio_app.py:29` | `INFO` | log 等級 |
| `MINERU_SEAL_OCR_DEBUG_DIR` | `mineru/model/ocr/pytorch_paddle.py:118` | 未設 | 印章 OCR 的除錯圖輸出資料夾，不改結果 |
| `MINERU_SEAL_OCR_DEBUG` | `mineru/model/ocr/pytorch_paddle.py:122` | 空字串 | 同上的開關 |
| `MINERU_VL_DEBUG_ENABLE` | `mineru_vl_utils/mineru_client.py:533` | 空字串 | VLM 用戶端除錯，pipeline 路徑走不到 |

### D. 本機 API 服務、router、Gradio 的啟動與維運：不收（21 個）

`MINERU_LOCAL_API_LAUNCH_MODE`（`cli/api_client.py:43,113,138`，預設 `subprocess`）、`MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS`（`api_client.py:80`，300）、`MINERU_TASK_RESULT_TIMEOUT_SECONDS`（`api_client.py:91`，3600）、`MINERU_TASK_RESULT_DOWNLOAD_TIMEOUT_SECONDS`（`api_client.py:103`，600）、`MINERU_API_OUTPUT_ROOT`（`cli/fast_api.py:338`；`api_client.py:393` 會覆寫）、`MINERU_API_SHUTDOWN_ON_STDIN_EOF`（`fast_api.py:115`；`api_client.py:401` 覆寫）、`MINERU_API_ENABLE_FASTAPI_DOCS`（`fast_api.py:215`，true）、`MINERU_API_ENABLE_VLM_PRELOAD`（`fast_api.py:250`，false）、`MINERU_API_TASK_RETENTION_SECONDS`（`fast_api.py:323`）、`MINERU_API_TASK_CLEANUP_INTERVAL_SECONDS`（`fast_api.py:331`）、`MINERU_API_DISABLE_ACCESS_LOG`（`fast_api.py:1447`；`api_client.py:397` 覆寫）、`MINERU_API_PUBLIC_BIND_EXPOSED`（`fast_api.py:92`）、`MINERU_API_ALLOW_PUBLIC_HTTP_CLIENT`（`fast_api.py:93`）、`MINERU_ROUTER_PUBLIC_BIND_EXPOSED`、`MINERU_ROUTER_ALLOW_PUBLIC_HTTP_CLIENT`（`cli/router.py:77,78`）、`MINERU_ROUTER_UPSTREAM_URLS_JSON`、`MINERU_ROUTER_LOCAL_GPUS`、`MINERU_ROUTER_WORKER_HOST`、`MINERU_ROUTER_ENABLE_VLM_PRELOAD`、`MINERU_ROUTER_WORKER_ARGS_JSON`（`router.py:317-324`）、`MINERU_GRADIO_DEFAULT_LOCALE`（`cli/gradio_app.py:264`，`zh`）。理由：只影響服務怎麼啟動、等多久、log 與介面語言；`mineru` CLI 在本機自己啟動的 API 服務不經過 router 與 Gradio。逾時類在逾時時以錯誤結束，不會悄悄改變內容。

### E. 只有 vlm、hybrid 後端才讀：rag_lab 走不到，不收（9 個）

`MINERU_VLM_TABLE_ENABLE`（`mineru/backend/vlm/model_output_to_middle_json.py:111`、`vlm_middle_json_mkcontent.py:898`、`backend/hybrid/hybrid_model_output_to_middle_json.py:266`，預設 `True`）、`MINERU_VLM_FORMULA_ENABLE`（`vlm_middle_json_mkcontent.py:897`，`True`；`cli/common.py:731,826` 等只在 vlm、hybrid 分支寫入）、`MINERU_HYBRID_BATCH_RATIO`（`backend/hybrid/hybrid_analyze.py:852`）、`MINERU_LMDEPLOY_BACKEND`（`backend/vlm/vlm_analyze.py:192`、`model/vlm/lmdeploy_server.py:62`）、`MINERU_VLLM_DEVICE`（`backend/vlm/utils.py:185`）、`MINERU_VL_SERVER`（`mineru_vl_utils/vlm_client/http_client.py:81`）、`MINERU_VL_API_KEY`（`http_client.py:88`）、`MINERU_VL_MODEL_NAME`（`http_client.py:110`）、`MINERU_VLM_END_TOKEN`（`http_client.py:338`，`<|im_end|>`）。判斷依據：pipeline 的輸出用 `pipeline_middle_json_mkcontent.union_make`（`cli/client_side_output.py:_select_union_make`），不呼叫 vlm 的 `union_make`。

## 實作結果

做了什麼：

- `rag_lab/config.py`：`UNMANAGED_LIBRARY_ENV` 從 31 個增加到 39 個（新增 A 類 8 個），`UNMANAGED_LIBRARY_ENV_VERSIONS` 加 `"mineru": "3.4.5"`；錯誤訊息改為「LightRAG／RAG-Anything／MinerU」；模組說明補上 MinerU 名單的產生步驟、收錄與排除標準，移除「MinerU 不在名單內」的已知極限，改寫成「只涵蓋環境變數，不涵蓋 `~/mineru.json`」。檢查函式與呼叫點（`get_settings`、`pipeline`／`models` 在 import lightrag 之前）沒有變，所以 CLI 三個子命令與 Python API 全部入口都套用。
- 測試（沿用 ticket 01 的縫）：`tests/test_cli.py` 新增 4 個測試（A 類 8 個變數 × 3 個子命令被拒絕且不印值、工作目錄 `.env` 的 MinerU 變數被拒絕、B～E 類 11 個代表性變數不被拒絕、名單涵蓋三個套件）；`tests/test_python_api.py` 的既有測試加入 `MINERU_TABLE_ENABLE`（模組函式與 `Session`，驗證拋 `ConfigError` 而不是 `EndpointError`）。新的拒絕測試在舊實作下失敗（30 個失敗），「不被拒絕」的測試在舊實作下本來就通過，它的用途是固定名單的邊界。
- 文件：README 第 1 節的名單段落（39 個、MinerU 一行、版本、重新產生的條件、`~/mineru.json` 的極限）；`docs/architecture.md` 的 `config.py` 職責、測試表與第 5 節。
- 檢查：本機 `.env` 與目前行程環境裡沒有 `MINERU_` 開頭的變數（只用 `grep -c` 與 `env | grep -c`，結果 0）。

