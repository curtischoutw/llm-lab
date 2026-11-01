# 01: 查詢時用 reranker 重新排序候選 chunk

**What to build:** 使用者在 `.env` 設定 reranker 的位址、模型與 API key 之後，所有查詢（CLI 的 `query`、`eval`、`query --vlm-enhanced`，Python API 的 `pipeline.query`／`pipeline.evaluate`／`Session.query`／`Session.evaluate`）都先把 LightRAG 的候選 chunk 送到 rerank endpoint 重新排序，再依 token 上限截斷成 context。匯入流程不受影響。規格見 `.scratch/local-reranker/spec.md`。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 新增 `RERANK_BASE_URL`、`RERANK_MODEL`、`RERANK_API_KEY` 三個必填欄位，驗證規則與現有的 `*_BASE_URL`／`*_MODEL`／`*_API_KEY` 相同；缺漏或格式錯誤時 CLI 在啟動時中止，結束碼與既有設定錯誤相同。
- [x] rerank 函式在建立 LightRAG 實例時傳入（初始化之後才設定，mix 等圖譜模式不會用到），所有查詢都開 enable_rerank；程式說明文字裡寫著「不開 rerank」的地方一併更新。
- [x] 請求帶設定的模型名稱與 API key，documents 是候選 chunk 的內容；回傳的順序反映在答案請求的 prompt 裡（見 spec 的「要驗的行為」第 2 項）。
- [x] 上一項以 CLI 子行程縫（`query` 的 mix、`query --vlm-enhanced`、`eval`）與 Python API 縫（四個函式）測試；假 OpenAI server 新增 `/v1/rerank`，記錄請求並依測試指定的規則回傳順序。
- [x] 匯入不呼叫 rerank endpoint（測試驗證）。
- [x] eval 對照表的「固定查詢設定」加上 `RERANK_MODEL` 的值（測試驗證）。
- [x] `.env.example` 加上三個欄位與建議值（`RERANK_BASE_URL` 指向 VLM／embedding server，`RERANK_MODEL=BAAI/bge-reranker-v2-m3`）；CLI 測試裡的設定欄位字面清單加上三個欄位，既有的 `.env.example` 一致性測試通過。
- [x] README：設定說明加上三個欄位；8081 server 的啟動指令加上 `--reranker-model BAAI/bge-reranker-v2-m3`。架構文件：查詢流程補上 rerank 這一步。
- [x] 每個新測試都先在改程式前看過紅燈；主測試套件 `python -m unittest`（repo 根目錄、專案 venv）全綠。
- [x] 不對 127.0.0.1:8080／8081 發請求，不讀 `.env`；實機驗證是 ticket 03。

## 實作結果（2026-11-01）

### 做了什麼

- `rag_lab/config.py`：`RERANK_BASE_URL`、`RERANK_MODEL`、`RERANK_API_KEY` 三個必填欄位，驗證沿用 `_url`／`_required`；缺漏或格式錯誤時和其他欄位一樣以 `ConfigError` 中止（結束碼 3）。
- `rag_lab/models.py`：新增 `rerank_model_func(query, documents, top_n)`，用 LightRAG 內建的 `generic_rerank_api` 送請求到 `{RERANK_BASE_URL}/rerank`，帶設定的模型名稱與 API key，回傳 index＋relevance_score。
- `rag_lab/pipeline.py`：`build_rag` 把 `rerank_model_func` 放進 `lightrag_kwargs`（建立 LightRAG 時傳入）；`query_kwargs` 的 `enable_rerank` 改成 `True`。`query`、`query --vlm-enhanced`、`eval`、`Session.query`／`evaluate`、模組函式都走這一處。檔頭與函式說明裡寫「不開 rerank」的地方都已更新。
- `rag_lab/__main__.py`：eval 對照表的「固定查詢設定」改成 `enable_rerank=True`，並加一行 `RERANK_MODEL`。
- `.env.example`：三個欄位與建議值（`http://127.0.0.1:8081/v1`、`BAAI/bge-reranker-v2-m3`、`local-mlx`）。
- README：設定與 server 說明加上 reranker、8081 server 啟動指令加 `--reranker-model BAAI/bge-reranker-v2-m3`、第 6 節欄位表加三個欄位。`docs/architecture.md`：流程圖與說明補上 rerank 這一步、端點表、`models.py`／測試檔的說明。
- 測試：`tests/fake_openai_server.py` 新增 `/v1/rerank`（記錄請求與 `Authorization` 標頭；`rerank_promote`／`rerank_demote` 指定順序；`fail_rerank` 回 500；預設保持候選順序）。`tests/test_cli.py` 的設定欄位字面清單加三個欄位與有效值。新測試：`QueryTest` 兩個（請求內容、匯入不呼叫）、`QueryRerankOrderTest`（mix、`--vlm-enhanced`）、`EvalRerankTest`、`python_api.QueryRerankTest`（模組函式與 Session × query／evaluate）；`test_eval` 的表頭測試改成 `enable_rerank=True` 並加 `RERANK_MODEL` 斷言。

### 怎麼驗證 rerank 順序反映在 prompt

用 `multichunk.pdf`（約 20 個文字 chunk，每個約 3,800 字元），`QUERY_MAX_TOTAL_TOKENS=3000`、entity／relation 上限各 100，prompt 只放得下 1 個 chunk。`RERANK_MARKER`（`Fake Entity 7-200 relates to Fake Entity 7-201.`）落在其中一個 chunk 的中段（不在 chunk 之間的重疊範圍）。每次查詢用不同題目（LLM 快取 key 不含 rerank 順序）。
1. 假 server 保持候選順序：marker 不在答案請求的 prompt。
2. `rerank_promote=marker`（含 marker 的 chunk 排最前面）：marker 在 prompt。
3. `rerank_demote=marker`（排最後面）：marker 不在 prompt。

同一組斷言用在 CLI `query`（mix）、`query --vlm-enhanced`、`eval`（五種模式，promote 時至少一個 prompt 含 marker、其餘情況沒有任何 prompt 含）、Python API 四個函式（`pipeline.query`／`evaluate`、`Session.query`／`evaluate`，各開一份索引副本避開 LLM 快取）。

### 紅燈紀錄（改程式之前或暫時還原實作後）

- 設定欄位：先改 `tests/test_cli.py`，跑 `tests.test_cli` 11 個測試，8 個子案例失敗（`RERANK_BASE_URL` 無效值 4 個、三個欄位缺漏各 1 個、`.env.example` 一致性 1 個），之後才改 `config.py` 與 `.env.example`。
- `QueryTest` 的「請求內容」與「匯入不呼叫」兩個測試：實作前都失敗（`mix 查詢沒有呼叫 rerank endpoint`）。
- eval 表頭測試：實作前失敗（`enable_rerank=True` 不在表頭）。
- `QueryRerankOrderTest`（2 個）、`EvalRerankTest`、`QueryRerankTest`：寫在 `query_kwargs` 已改成 `enable_rerank=True` 之後（共用同一處，沒有辦法單獨留著其中一個入口不改），所以紅燈是暫時把 `enable_rerank` 改回 `False` 觀察到的：4 個測試、7 個失敗（`QueryRerankOrderTest` 兩個、`EvalRerankTest` 一個、`QueryRerankTest` 四個子案例），觀察後立即改回 `True`。
- 假 server 的 `/v1/rerank` 沒有獨立測試，由上面這些測試經 HTTP 邊界使用它。

### 最後一次主套件結果

`.venv/bin/python -m unittest`（repo 根目錄，用主 repo 的 `.venv`：worktree 內沒有 `.venv`，`python -m` 的工作目錄在前，匯入的是 worktree 的 `rag_lab`）：

```
Ran 152 tests in 610.032s
OK
```

（merge integration 分支 tip 之後的結果見最後一個 commit 的回報。）

### 發現與疑慮

- LightRAG 在 rerank 失敗時（請求例外、HTTP 錯誤、回傳空結果、index 超出範圍）記錄錯誤後改用原本的排序，查詢照常成功。這一版沒有處理，是 ticket 02；在 02 完成前，rerank 端點沒開時查詢不會報錯，只是沒有 rerank。
- `generic_rerank_api` 的請求會帶 `top_n`（LightRAG 傳入 `chunk_top_k`＝20）。mlx-vlm 0.7.10 的 rerank endpoint 是否接受 `top_n` 沒有在這個 ticket 驗證（不能對 8081 發請求），ticket 03 實機驗收要確認；spec 的實驗是否帶 `top_n` 也不確定。
- `generic_rerank_api` 用 aiohttp 預設逾時（總計 5 分鐘），沒有自己設定；reranker 卡住時查詢最多等 5 分鐘才會（照上一點的行為）退回原順序。
- `scripts/smoke_test.py` 沒有檢查 rerank endpoint（範圍外：只准動 rag_lab、tests、`.env.example`、README、架構文件）。
- 全套測試約 10 分鐘（152 個測試）。

### ASSUMPTION

- `RERANK_BASE_URL` 和其他三個端點一樣結尾含 `/v1`，rerank 請求送到 `{RERANK_BASE_URL}/rerank`（spec 說 endpoint 是 `/v1/rerank`，但沒有說 `.env` 的欄位含不含 `/v1`）。
- 假 server 的 rerank 規則：預設保持輸入順序（分數遞減）；`rerank_promote`／`rerank_demote` 是「document 內容含指定字串」；`top_n` 有帶就只回前 `top_n` 個；`documents` 含空字串回 400（模擬 mlx-vlm）。
- `rerank_model_func` 沒有把例外包成 `EndpointError`：失敗處理是 ticket 02。
- README 沒有寫 reranker 的實測效果、記憶體與查詢時間：那些數據來自實機驗收（ticket 03）。
