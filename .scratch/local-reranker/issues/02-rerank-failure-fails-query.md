# 02: rerank 失敗時讓查詢失敗

**What to build:** rerank 沒有正常完成時，使用者會看到查詢失敗與原因，不會拿到一個沒有經過 rerank 的答案。LightRAG 在 rerank 發生例外、回傳空結果、回傳 index 超出範圍時，都會改用原本的排序並讓查詢成功；rag_lab 要把這些情況改成查詢失敗。規格見 `.scratch/local-reranker/spec.md` 的「失敗處理」。

**Blocked by:** 01

**Status:** resolved

- [x] 以下情況都記成 rerank 失敗：請求例外、HTTP 錯誤（含候選 chunk 為空白時 mlx-vlm 回的 400）、回傳空結果、回傳的 index 超出範圍。
- [x] 有失敗的那次查詢以查詢失敗結束：`query` 用既有的查詢失敗結束碼，Python API 拋出既有的查詢失敗例外，`eval` 把該格記成失敗格。訊息包含 endpoint 回報的錯誤，不含 API key。
- [x] 失敗只算在發生當下的那一次查詢：`eval` 某一格失敗後，下一格 rerank 正常時照常成功（測試驗證）。
- [x] 以 CLI 子行程縫與 Python API 縫測試；假 server 的 `/v1/rerank` 能被指定回 500、回空結果、回超出範圍的 index。
- [x] 做法比照 ticket 12（台新知識庫）處理 RAG-Anything 吞掉寫入失敗的方式：在 rag_lab 這一層記錄、在結果層判定。
- [x] 架構文件的查詢流程補上 rerank 的失敗處理。
- [x] 每個新測試都先在改程式前看過紅燈；主測試套件 `python -m unittest` 全綠。
- [x] 不對 127.0.0.1:8080／8081 發請求，不讀 `.env`。


## 實作結果（2026-11-01）

### 做了什麼

- `rag_lab/models.py`：`rerank_model_func` 自己判定失敗，四種情況都算：請求例外、HTTP 錯誤（`generic_rerank_api` 內建重試 3 次後仍失敗）、回傳空結果、回傳的 index 超出 `0..len(documents)-1`（只要有一項超出就算失敗，即使其他項正常；LightRAG 對這種情況會靜默略過該項）。判定後先記進「目前這次查詢」的失敗清單，再以 `EndpointError("Rerank", 位址, 原因)` 拋出（LightRAG 照舊吞掉它，查詢繼續跑完）。新增 `collect_rerank_failures()`（context manager）與私有 `_fail_rerank`。
- `rag_lab/pipeline.py`：`_answer` 與 VLM 增強路徑用 `models.collect_rerank_failures()` 包住 LightRAG 的查詢，查詢結束後 `_raise_if_rerank_failed` 檢查清單，有失敗就拋 `PipelineError`（`查詢失敗（mode=…）：rerank 失敗：<端點位址與端點回報的錯誤>`）。CLI `query` 經 `main` 轉成結束碼 1；`eval` 的 `_evaluate` 原本就把每格例外記成 `Cell.error`；Python API 拋 `PipelineError`（既有的查詢失敗例外）。檔頭「已知極限」裡「rerank 失敗沒有處理」那一條改成現在的偵測範圍與極限。
- 做法比照 ticket 12：在 rag_lab 這一層（rerank 函式）記錄、在結果層（`_answer`／VLM 路徑）判定。差別是 ticket 12 的計數是模組層級、取前後差；這裡用 `ContextVar` 綁定單次查詢（見下）。
- 文件：`docs/architecture.md` 查詢流程段落補上失敗處理（原本寫「目前不處理，是 ticket 02」的句子改寫），模組表與測試表補列；README 的 reranker 說明補一句失敗行為。
- 測試夾具 `tests/fake_openai_server.py`：把 ticket 01 加的 `fail_rerank`（沒有任何測試使用）換成 `rerank_fault`（`"http500"`／`"empty"`／`"out_of_range"`）與 `rerank_fault_query`（設為字串時只有 query 含該字串的請求出錯，讓同一個 server 上某一題失敗、其餘題目正常）。`out_of_range` 回的是正常項目加一項 index 等於候選數的項目。`tests/test_python_api.py` 的 DRIVER 加 `query_poisoned` 步驟，`run_api` 加 `question_texts` 參數（evaluate 用的題目，預設與原本相同的一題）。

### 失敗只算在那一次查詢：為什麼這樣做在這個 repo 正確

- 查詢在這個 repo 裡不會並行：`Session` 的每個方法都是 `asyncio.Runner.run(...)` 同步執行完才返回；`_evaluate` 是依題目、模式順序的 for 迴圈、逐格 await；一個 process 同時只有一個 Session。所以「進入查詢前換一份新清單、離開時還原」就足以保證不帶到下一次。
- 仍選 `ContextVar` 而不是模組層級計數：重疊的查詢（例如使用者自己用 `asyncio` 在同一個 event loop 同時呼叫內部函式）也各算各的；清單隨查詢區塊結束而還原，沒有需要「清零」的地方可以忘記。LightRAG 在查詢途中建立的子 task 會繼承 context，寫入的是同一個 list，所以 mix／local／global／hybrid／naive 五種模式與 VLM 增強路徑都測到（`rerank_model_func` 沒有被 LightRAG 的限流 worker 包住，是在查詢 task 內直接 await）。
- 同一次查詢內 rerank 失敗多次時，訊息會去重後一起列出（實測每次查詢只呼叫 rerank 一次，這是預防）。

### 怎麼驗證

測試縫只有 CLI 子行程與 Python API（子行程內呼叫公開函式）；都是新測試，沒有改動既有測試的斷言。

- `tests.test_pipeline.QueryRerankFailureTest`（CLI `query`，5 個測試）：500 + 端點錯誤訊息出現在 stderr；rerank 端點連不上（位址指向已關閉埠）；空結果（naive／local／global／hybrid／mix 五種模式各一個 subTest）；一項 index 超出範圍（其餘正常）；`--vlm-enhanced`。每個都斷言結束碼 1、stdout 沒有答案、stderr 含 `rerank`、stdout＋stderr 不含 API key。
- `tests.test_eval.EvalRerankFailureTest`（CLI `eval`）：三題，中間一題的 rerank 回空結果：該題五格記成失敗（格內含 `rerank`）、前後兩題十格是 `pong`、結束碼 1、`完成：15 格，失敗 5 格`、結果檔與輸出不含 API key。後面那題成功就是「失敗沒有帶到下一格」的驗證。
- `tests.test_python_api.QueryRerankFailureTest`（模組函式與 `Session` 各跑一次）：`query` 拋 `PipelineError`（訊息含 `rerank` 與端點回報的 `injected rerank failure`），同一個 process 的下一次 `query` 成功；`evaluate` 三題中間一題失敗，前後成功，之後的 `query` 也成功。

### 紅燈紀錄

- 先寫測試（只有假 server 夾具已改），在 `rag_lab` 沒改之前跑：
  - `QueryRerankFailureTest`：5 個測試、9 個失敗（空結果 5 個 subTest、其餘 4 個），全部是 `AssertionError: 0 != 1 : pong`（`--vlm-enhanced` 是 `: The square in the image is red.`）：查詢成功、拿到沒經過 rerank 的答案；stderr 只有 LightRAG 的 `Error during reranking ... using original chunks` log。
  - `EvalRerankFailureTest`：`AssertionError: 0 != 1`（沒有任何格失敗）。
  - `python_api.QueryRerankFailureTest`：4 個失敗：`query_poisoned ok `（沒有拋例外）、evaluate 的失敗題整列是 `pong`。
- 「失敗不帶到下一次」的測試在實作完成後做了一次變異驗證（沒進 repo）：暫時把 `collect_rerank_failures` 的清單改成模組層級、永不清空的 `_STICKY`（`diff` 顯示只有 `_STICKY: list[str] = []` 與 `failures = _STICKY` 兩處不同），跑 `EvalRerankFailureTest` 與 `python_api.QueryRerankFailureTest`：5 個失敗（eval 後面那題的五格變成失敗：`['**失敗**：PipelineError: 查詢失敗（mode=naive）…'] != ['pong', ...]`；Python API 的 `query` 與 `evaluate` 都在下一次呼叫失敗）。還原後（`diff` 與原檔相同）三組測試全綠。
- 改程式後這三組測試：`Ran 8 tests in 71.086s` / `OK`。

### 最後一次主套件結果

`/Users/curtis/GitHub/llm-lab/.venv/bin/python -m unittest`（worktree 根目錄，基於 90221e7 加本 ticket 的變更）：

```
Ran 160 tests in 680.224s
OK
```

（152 個既有測試 + 本 ticket 8 個新測試。integration 分支 tip 仍是 90221e7，merge 進來是 Already up to date，所以這個結果就是 merge 後的結果。）

### 發現與疑慮

- `generic_rerank_api` 自帶 tenacity 重試（3 次、指數等待、最少 4 秒）。reranker 回 HTTP 錯誤或連不上時，一次失敗的 rerank 要約 8 秒才失敗，eval 一題五格全失敗就是約 40 秒（沒有改動這個行為；重試對暫時性錯誤有用）。測試因此把 eval 的失敗案例用「空結果」（不重試）、500 與連不上只在單次 `query` 測。
- 「候選 chunk 為空白時 mlx-vlm 回 400」沒有單獨測：假 server 在 document 為空白時本來就回 400（ticket 01），但要在整合流程裡讓候選 chunk 真的是空白不容易製造；400 與 500 走同一條 `response.status != 200` 路徑，已由 500 的測試涵蓋。
- 偵測只涵蓋 rerank 函式看得到的情況；回傳格式正確、index 在範圍內但排序品質差，看不出來（寫在 `pipeline.py` 的已知極限）。
- 沒有在開始查詢前檢查 rerank 端點可達（`models.check_reachable` 只認 LLM、VLM、Embedding）：連不上時要等重試約 8 秒才失敗，訊息有位址。若要快速失敗，之後可以把 Rerank 加進 `check_reachable`；這超出 ticket 範圍，沒有做。
- `rerank_fault="out_of_range"` 的假 server 回應是「正常項目 + 一項 index 超出範圍」，LightRAG 對這種回應原本會靜默略過超出的那一項、其餘照常排序；這是最容易被漏掉的一種，所以特別選它。
- 整個 `query` 遇到 rerank 失敗時，LightRAG 仍會繼續呼叫 LLM 產生答案（它不知道失敗），答案被丟棄；多花一次 LLM 呼叫。要避免得讓 rerank 函式的例外穿過 LightRAG，做不到（它一律吞掉）。

### ASSUMPTION

- 錯誤類別沿用 `PipelineError`（既有的查詢失敗例外，CLI 結束碼 1），沒有新增例外類別。
- 訊息格式：`查詢失敗（mode=…）：rerank 失敗：Rerank 端點 <位址> 失敗：<原因>`；HTTP 錯誤的原因取自 `generic_rerank_api` 拋出的 `ClientResponseError` 文字（含端點回應內容與請求網址）。API key 只在請求標頭，不會進入這些文字，測試驗證輸出不含 key。
- 同一次查詢內 rerank 多次失敗時，訊息列出不重複的原因，不分次拋出。
- 假 server 的故障規則（`rerank_fault`／`rerank_fault_query`）由我決定，取代 ticket 01 未被使用的 `fail_rerank`。
- rerank 失敗優先於 LightRAG 自己的查詢失敗訊息：兩者同時發生時只報 rerank 失敗。
