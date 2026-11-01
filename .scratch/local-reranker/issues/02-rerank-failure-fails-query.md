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


## code-review 修正

範圍 5fafdbf..c5db0b4 的 code-review 找到 8 項問題，全部成立，修在分支 `fix/r-code-review`。測試縫沿用 CLI 子行程與 Python API，沒有新增縫。

### 8 項怎麼處理

1. **rerank 失敗後的答案被寫進 LLM 快取**：和第 4 項一起修。rerank 失敗現在在 LLM 呼叫與快取寫入之前中止，快取裡沒有那筆答案。測試 `QueryRerankFailureCacheTest`（mix、naive）：同一題先 rerank 失敗、再 rerank 成功（marker 排最前面），第二次要重新送出答案請求且 prompt 含 marker。
2. **快取 key 不含 `RERANK_MODEL`、`LLM_MODEL`**：不改 LightRAG 的快取。README 的 `eval` 段落與第 5 節的快取說明寫明：換 `RERANK_MODEL` 或 `LLM_MODEL` 後，要先刪掉 `kv_store_llm_response_cache.json` 裡 key 含 `:query:` 的項目，eval 結果才可比較。`docs/architecture.md` 同步。沒有測試（純文件）。
3. **查詢前沒有檢查 Rerank 端點**：`models.check_reachable` 加 `"Rerank"`；`_query`、`_evaluate`、模組函式 `query`／`evaluate`（開 Session 之前）都檢查，匯入不檢查。測試：CLI `query`（naive、mix、`--vlm-enhanced`）、`eval`、Python API（模組函式與 Session × query／evaluate）在 rerank 端點連不上時失敗、訊息含 `Rerank` 與位址、假 server 沒收到任何請求；`ingest` 不受影響。
4. **rerank 失敗後仍生成答案**：採用 BaseException 做法。`models.RerankFailure` 繼承 `BaseException`，`rerank_model_func` 判定失敗時拋出，穿過 LightRAG；`pipeline._answer` 與 VLM 增強路徑攔下，轉成 `PipelineError`。原本的 `ContextVar` 失敗清單（`collect_rerank_failures`、`_fail_rerank`、`_raise_if_rerank_failed`）整組移除。測試：rerank 失敗時假 server 沒有收到任何答案請求（naive、mix、`--vlm-enhanced`；關鍵字抽取請求在 rerank 之前，不算）。
5. **rerank 回應驗證不足**：新增 `models._rerank_problem`，筆數不等於 `min(top_n, 候選數)`、index 不是範圍內的 int（bool 不算）、index 重複、relevance_score 不是有限的 int／float（bool、字串、null、NaN、inf 都不算）都算失敗。測試 `test_a_malformed_rerank_response_fails_the_query` 15 個子案例，加一個對照組（整數分數、分數相同、順序不照分數排的合法回應要成功）。假 server 新增 `rerank_results`（函式，回傳 results 欄位的原始內容）。
6. **LightRAG 讀行程環境的 `MIN_RERANK_SCORE`、`CHUNK_TOP_K`**：建立 LightRAG 時明確傳 `min_rerank_score=0.0`，`query_kwargs` 明確傳 `chunk_top_k=20`（常數 `pipeline.CHUNK_TOP_K`、`MIN_RERANK_SCORE`）。測試 `QueryRerankEnvironmentTest`：環境有 `MIN_RERANK_SCORE=0.9`、`CHUNK_TOP_K=1` 時，rerank 請求的 `top_n` 仍是 20，分數 0.5 的 chunk 仍進得了 prompt（naive、mix）。
7. **rerank 與 LightRAG 自己同時失敗只報 rerank**：第 4 項改成提前中止之後，兩者不可能同時發生：rerank 發生在答案階段之前，rerank 失敗就中止，後面的階段不會執行；反過來，rerank 之前的階段（關鍵字抽取、檢索）先失敗時 rerank 不會被呼叫。所以不需要合併兩種訊息，說明寫在 `pipeline.py` 檔頭與架構文件。
8. **eval 表頭寫死 `enable_rerank=True`**：「固定查詢設定」由 `pipeline.query_kwargs(settings)` 產生（扣掉三個 token 上限，它們在表頭各佔一行），現在是 `vlm_enhanced=False、enable_rerank=True、chunk_top_k=20`。表頭測試加 `chunk_top_k=20` 的斷言（原有斷言都保留）。

### 第 4 項：為什麼 BaseException 做法可行

查 lightrag-hku 1.4.16 從 rerank 到 `aquery_llm` 的呼叫鏈：

- `aquery_llm`（lightrag.py:2884）→ `kg_query`（operate.py:3164）／`naive_query`（operate.py:4953）→ `_build_query_context`（operate.py:4239）→ `_build_context_str`（operate.py:4056）→ `process_chunks_unified`（utils.py:2755）→ `apply_rerank_if_enabled`（utils.py:2671）。全程在同一個 task 裡直接 `await`，沒有 `asyncio.gather`、`create_task`、限流 worker 或 `finally` 包住 rerank 呼叫。
- `aquery_llm` 的 `except` 是 `except Exception`（lightrag.py:3007），`apply_rerank_if_enabled` 也是（utils.py:2750），都不會攔到 BaseException。LightRAG 裡的 `except BaseException`（operate.py:2661、2780）在實體／關係合併（匯入）路徑，不在查詢路徑。
- VLM 增強路徑：`RAGAnything.aquery_vlm_enhanced`（raganything/query.py:390）先用 `only_need_prompt=True` 呼叫 `lightrag.aquery`（沒有 LLM 呼叫、沒有快取），rerank 在那一步，中止時還沒到 VLM；路徑上沒有 `except`。
- Python 3.12 的 `asyncio.Task.__step`（asyncio/tasks.py:324–332）只對 `CancelledError`、`KeyboardInterrupt`、`SystemExit` 特別處理，其他 `BaseException` 用 `set_exception` 存起來；而且這裡的 `RerankFailure` 在 `_answer`／VLM 路徑就被攔下，不會抵達 task 的邊界。
- 不是 `CancelledError`，所以 LightRAG 限流 worker 對 `CancelledError` 的特殊處理不會碰到它；`generic_rerank_api` 自帶的 tenacity 重試只重試 `Exception`，`RerankFailure` 是在它外面拋的。

實際驗證靠測試：CLI（naive、mix、`--vlm-enhanced`）、`eval`、Python API 的 rerank 失敗測試全部通過，且假 server 沒收到答案請求。

### 紅燈紀錄

每個新測試都先在改程式前跑過：

- 第 1、4 項：`test_no_answer_generation_request_is_sent_when_rerank_fails` 3 個子案例失敗（答案請求照樣送出，VLM 路徑也是）、`QueryRerankFailureCacheTest` 2 個測試失敗（`0 != 1`：第二次命中前一次失敗留下的快取，沒有重新生成答案）。
- 第 5 項：15 個子案例中 8 個失敗（index 是 bool、index 重複、筆數不足、分數是字串／null／bool／NaN／inf）；其餘 7 個（results 不是 list、物件、缺 index、缺 relevance_score、index 是字串／浮點數／負數）在舊程式碼就已經算失敗，因為 `generic_rerank_api` 內就以空結果或 `KeyError` 結束，或舊的 index 範圍檢查擋下；它們是回歸保護，沒有紅燈。
- 第 3 項：CLI 3 個子案例、`eval` 1 個、Python API 4 個子案例失敗；`ingest` 不檢查 rerank 的測試本來就通過（對照組）。
- 第 6 項：`QueryRerankEnvironmentTest` 的 4 個子案例失敗（naive 的 `top_n` 是 1 而不是 20、prompt 的 Document Chunks 是空的；mix 因 `top_n=1` 與回應筆數不合而被判定 rerank 失敗）。
- 第 8 項：表頭測試因缺 `chunk_top_k=20` 失敗。
- 沒有用「暫時改程式」的方式看紅燈：所有紅燈都是新測試對上未修改的程式碼。

為了讓第 3 項的測試通過，`assert_failed_because_of_rerank` 的 `"rerank"` 斷言改成不分大小寫（連線檢查階段的訊息是 `EndpointError: Rerank 端點 ...`，不含小寫的 rerank）；其他斷言不變。

### 最後一次主套件結果

`/Users/curtis/GitHub/llm-lab/.venv/bin/python -m unittest`（worktree 根目錄，基於 integration 的 c5db0b4 加本次修正；integration tip 仍是 c5db0b4，merge 進來是 Already up to date，所以這個結果就是 merge 後的結果）：

```
Ran 171 tests in 745.608s
OK
```

（160 個既有測試 + 11 個新測試。）

### 疑慮

- 第 5 項的筆數檢查假設 reranker 會遵守 `top_n`（回傳剛好 `min(top_n, 候選數)` 筆）。假 server 這樣做，mlx-vlm 0.7.10 是否如此沒有驗證（不能對 8081 發請求），ticket 03 的實機驗證要確認；如果它忽略 `top_n` 回全部候選，候選數超過 20 時每次查詢都會被判定 rerank 失敗。
- `results` 不是 list 時，錯誤訊息是「回傳空結果」而不是「results 不是 list」：`generic_rerank_api` 把非 list 轉成空結果，要分辨得自己實作 HTTP，spec 規定不這樣做。
- LightRAG 還會讀其他行程環境變數當查詢預設值（例如 `TOP_K`、`COSINE_THRESHOLD`、`RELATED_CHUNK_NUMBER`、`KG_CHUNK_PICK_METHOD`；`MAX_TOTAL_TOKENS` 等三個 token 上限已由 `.env` 明確指定），這次只處理 code-review 點名的兩個，其餘沒有動。
