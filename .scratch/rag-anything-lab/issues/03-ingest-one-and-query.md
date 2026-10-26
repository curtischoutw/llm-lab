# 03: 匯入 1 篇論文並問答

**What to build:** 第一條完整路徑：用 `ingest` 把一篇 PDF 匯入（MinerU 解析、圖片由 VLM 描述、LLM 抽取實體與關係、embedding 建向量），再用 `query` 以 mix 模式回答問題。對真實本地 MLX server 驗證。

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [x] 第一次真實執行前，先重跑現有冒煙測試，三個端點全過；任一項失敗就停下來回報錯誤輸出與可行選項，不換框架、不寫 workaround。
- [x] 啟動 LLM server 時帶 `--max-tokens 4096` 與 `--prompt-cache-bytes 4GB`；VLM 與 embedding 在同一個 server 啟動，且透過 `scripts/vlm_server.py` 啟動（把 MLX buffer cache 上限設為 1 GB）。
- [ ] `ingest <單一 PDF>` 印出 MinerU 解析耗時與建圖耗時；MinerU 第一次執行的模型下載時間單獨標示。（解析與建圖耗時已印出；模型在 2026-10-25 已下載，下載時間未量測，CLI 也不單獨標示下載時間）
- [x] 圖片、表格、公式有被處理；至少有一張圖的描述來自 VLM，貼出該描述並判斷與原圖相符。
- [x] 重複 `ingest` 同一篇不會重複建立資料。
- [x] `query "<問題>"` 預設 mix 模式，印出答案；查詢端 embedding 帶可設定的 instruction 前綴，文件端不帶。
- [x] LLM、VLM、embedding 任一端點不可達時，錯誤訊息指出是哪一個端點與其位址。
- [x] LLM 並行請求數預設為低值並可由設定調整。
- [x] embedding 並行請求數可由設定（`EMBED_MAX_ASYNC`）調整，經 `lightrag_kwargs` 明確傳入；本機預設 1。
- [x] 查詢 context 的 token 上限可由設定（`QUERY_MAX_TOTAL_TOKENS`）調整，entity／relation 上限依 LightRAG 預設比例縮放；本機預設 12000。
- [x] 使用者不需要先 activate venv：CLI 確保專案 venv 的 bin 目錄在 PATH 上，MinerU 能被找到；以直接呼叫 venv 的 python 執行 `ingest` 驗證。
- [x] MinerU 的後端在 Mac（無 CUDA）上實測挑選（候選：pipeline），回報各自的解析耗時與選擇理由；模型預先下載與解析耗時分開量測。
- [x] 以計數或內容檢查驗證「圖片描述確實來自 VLM」（VLM 失敗時匯入不會報錯，描述會變成原始 dict 的 fallback 文字）；貼出 VLM 成功呼叫次數。
- [x] `query` 使用可回報失敗的查詢介面（`aquery_llm`），失敗時以非零碼結束並印出原例外文字，不得把 `None` 當成空答案。
- [x] 重複匯入的處理避開「failed 重複紀錄」與「卡在 handling」問題（先解析取得文件 ID，已完整處理就不再匯入）；重複匯入後 `get_status_counts()` 不拋錯。
- [x] 對真實 server 驗證 mix 模式的關鍵字抽取不會因 4B 輸出不是乾淨 JSON 而失敗；若失敗，回報實際錯誤並停下來，不自行加 workaround。
- [x] 驗證真實 embedding server 接受 LightRAG 預設的 `encoding_format=base64`；不接受時回報，由使用者決定是否改設定。
- [x] 快速測試（對假 server）涵蓋重複匯入與端點不可達的訊息，並通過；貼出實際輸出。
- [x] 回報實測的解析耗時、建圖耗時、LLM 並行數，供之後調整參考。

## 本機 server 啟動條件（2026-10-26 GPU 記憶體調查結論）

32 GB 的 Mac 上，以下條件下完整 ingest 一篇論文（2410.05779）能跑完：wired 最高 16 GB，`mlx_vlm.server` 最高 5.8 GB，`mlx_lm.server` 最高約 10 GB。缺任何一項，ingest 都曾因 Metal GPU 記憶體不足（`kIOGPUCommandBufferCallbackErrorOutOfMemory`）而失敗。紀錄在 `output/crash_repro/`（gitignore）。

```sh
mlx_lm.server --host 127.0.0.1 --port 8080 \
  --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --max-tokens 4096 --prompt-cache-bytes 4GB

~/.local/share/pipx/venvs/mlx-vlm/bin/python scripts/vlm_server.py --mlx-cache-limit-gb 1 \
  --host 127.0.0.1 --port 8081 \
  --model mlx-community/Qwen3-VL-4B-Instruct-4bit \
  --embedding-model mlx-community/Qwen3-Embedding-0.6B-8bit
```

`.env`：`LLM_MAX_ASYNC=1`、`EMBED_MAX_ASYNC=1`、`QUERY_MAX_TOTAL_TOKENS=12000`。

- `LLM_MAX_ASYNC=2` 時，兩個長請求同時生成（參考文獻段落的 chunk 會生成到 4096 token 上限），`mlx_lm.server` 會衝爆。
- `mlx_vlm.server` 的 embedding 路徑不清 MLX cache，連續的小型 embedding 請求會讓已釋放的 buffer 累積到 11–13 GB，即使並行數是 1 也一樣。`scripts/vlm_server.py` 用 `mx.set_cache_limit` 限制這部分。
- `--prompt-cache-bytes 4GB` 用來限制 LLM 的 prompt cache（實測最高 3.7 GB）。它不是 OOM 的根因，只是讓上限可預期。
- 未驗證：`EMBED_MAX_ASYNC` 在 cache 限制下提高到 8 是否一樣穩定。

## 實測結果（2026-10-26，論文 2410.05779，32 GB Mac）

紀錄在 `output/ticket03_run/` 與 `output/backend_bench/`（gitignore）。重複 ingest 的 stdout、30000 上限查詢的 rc、端點不可達的訊息、base64 請求的回應、快速測試結果只出現在執行時的終端輸出，沒有存成紀錄檔。

**MinerU 後端**（MLX server 關閉時單獨跑；模型已預先下載：pipeline 用 PDF-Extract-Kit-1.0 2.4 GB、VLM 用 MinerU2.5-Pro-2605-1.2B 2.2 GB，下載時間未量測）

| 後端 | 解析耗時 | 圖／表／公式 |
|---|---|---|
| pipeline | 51 s | 6／6／2 |
| hybrid-engine | 140 s | 6／6／2 |
| vlm-engine | 711 s（推論引擎為 transformers，未安裝 MinerU 的 mlx 引擎） | 5／6／2 |

選 pipeline：耗時最短，抽出的圖、表、公式數量與 hybrid-engine 相同。vlm-engine 搭配 mlx 引擎的耗時未測。

**ingest**（`LLM_MAX_ASYNC=1`、`EMBED_MAX_ASYNC=1`，以 `PATH=/usr/bin:/bin:/usr/sbin:/sbin` 直接呼叫 venv 的 python）

- MinerU 解析 36.2 s；建圖 643.8 s；多模態 786.5 s（14 項）；總耗時 1472 s。
- 圖譜：實體 354、關係 468（belongs_to 183）。文件狀態 processed=1。
- VLM 成功 6 次、失敗 0 次（論文共 6 張圖）。
- Figure 1 的 VLM 描述與原圖大致相符：Deduplication、LLM Profiling、Entity & Rel Extraction、Index Graph，以及 low-level keys（Beekeeper、Honey Bee）和 high-level keys（Agriculture、Environmental Impact）都正確。描述多出一個原圖沒有的「generation module」：原圖右側只有 Retrieved Content。
- wired 記憶體最高 17 GB。
- 重複 ingest：4 s 結束並印出「已完整處理過，略過」，儲存檔大小不變，沒有 dup- 紀錄，`get_status_counts()` 正常。

**query**（mix）

- `QUERY_MAX_TOTAL_TOKENS` 為 30000（LightRAG 預設）時：關鍵字抽取成功，但答案的 prompt 有 29,678 token，prefill 約 150 s，`mlx_lm.server` 從 5.9 GB 增加到 14 GB，開始生成時 GPU 記憶體不足（`kIOGPUCommandBufferCallbackErrorOutOfMemory`）。CLI 以 rc=1 結束，並印出原始錯誤。
- `QUERY_MAX_TOTAL_TOKENS=12000` 時：prompt 11,966 token，查詢 55 s，rc=0；wired 最高 11 GB；答案與論文的 dual-level retrieval 描述一致。

**其他**

- 真實 embedding server（mlx-vlm）收到 `encoding_format=base64` 回 HTTP 200，內容仍是 float list；LightRAG 收到 list 時直接轉 float32，不需改設定。
- 端點不可達（server 關閉時）：`EndpointError: LLM 端點 http://127.0.0.1:8080/v1 失敗：無法連線（[Errno 61] Connection refused）`，rc=1。
- 未啟用 venv 時 query 也需要 mineru 在 PATH 上：RAG-Anything 初始化時會跑 `mineru --version`，所以 PATH 處理改在初始化時進行。
- 快速測試：`Ran 36 tests ... OK`。
