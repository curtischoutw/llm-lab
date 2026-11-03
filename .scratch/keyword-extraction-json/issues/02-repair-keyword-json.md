# 02: 抽關鍵字的輸出 JSON 有小錯時照常查詢，解析不出關鍵字格式時以指出原因的錯誤失敗

**What to build:** 使用者查詢時（`query`、`eval`、Python API），LLM 抽關鍵字的輸出就算 JSON 有小錯（例如陣列少了 `]`），只要能解析出關鍵字，查詢照常完成。輸出合法時，交給 LightRAG 的關鍵字和現在相同。解析不出關鍵字的格式時，查詢以錯誤失敗，訊息寫明是抽關鍵字的輸出不是合法的 JSON，並附輸出開頭。

背景與數據見 `01-investigate-invalid-keyword-json.md` 的「調查結果」：失敗來自 openai SDK 的嚴格驗證（`chat.completions.parse()` 用 pydantic 驗證 `GPTKeywordExtractionFormat`）擋在 LightRAG 的 `json_repair` 之前；mlx-lm 0.32.0 server 不支援 `response_format`；50 個基底問題中 1 題失敗，同一個問法每次都失敗。

**Blocked by:** None (can start immediately)。排程（使用者 2026-11-03 決定）：在 C 線截斷重匯的量測結束之後、金融卡 ticket 05 的新基準 eval 之前做，讓金融卡前後兩次 eval 用同一套程式。

**Status:** resolved

## 行為

- 請求不變：抽關鍵字的請求照現在一樣帶 `response_format`（同一份 JSON schema）。`.env` 可以把 LLM 換成支援限制輸出格式的後端（`rag_lab/models.py` 模組說明），這些後端照常收到 schema。改的只有回應怎麼解析。
- 現在的機制：LightRAG 的 openai binding 看到 `keyword_extraction=True` 就加上 `response_format=GPTKeywordExtractionFormat`（pydantic 類別），只要 kwargs 有 `response_format` 就改走 `chat.completions.parse()`（`lightrag/llm/openai.py:294–295`、`338–346`），由 SDK 驗證。實作者要找出「請求帶同一份 schema、但不由 SDK 嚴格驗證、拿到模型原文」的做法（例如改傳 dict 形式的 JSON schema，SDK 對非 pydantic 的 `response_format` 不解析；這是推測，要用測試確認），寫成 ASSUMPTION。
- 解析原文的步驟和 LightRAG 相同：先 `remove_think_tags`，再 `json_repair.loads`（`lightrag/operate.py:3468–3470`）。
- 整理成 LightRAG 要的格式（輸出合法時結果和現在相同）：
  - 解析結果不是物件 → 失敗。
  - `high_level_keywords`、`low_level_keywords` 兩個欄位都不存在、或都不是陣列 → 失敗。
  - 欄位是陣列時保留其中的字串項目，非字串項目丟掉；欄位不存在或不是陣列時當成空陣列。
  - 兩個欄位都是空陣列但格式正確（合法 JSON）→ 不算失敗，照現在交給 LightRAG（問題少於 50 字元時 LightRAG 改用整題當關鍵字，50 字元以上回固定的 `fail_response`，`operate.py:3228–3233`）。這個行為不在這張票改。
- 失敗時拋 `models.EndpointError`（和現在 LLM 失敗相同的類別與格式「LLM 端點 <位址> 失敗：<原因>」），原因寫「抽關鍵字的輸出不是合法的 JSON：」加輸出開頭最多 200 字元，不含 API key。所以 `query` 結束碼 1、`eval` 記成該格的失敗、Python API 拋例外，捕捉點都不用改。
- 不加重試，不改 temperature 等生成參數。其他 LLM 呼叫（實體抽取、答案生成、VLM 增強）不受影響。
- 依賴：rag_lab 會直接 import `json_repair`（LightRAG 的相依套件，已安裝；`requirements.txt` 的慣例是由 raganything 帶入的套件不另列）。使用者 2026-11-03 同意新增這個直接依賴。

## 驗收

- [x] 測試沿用假 OpenAI server 的縫（CLI 子行程＋Python API）。假 server 現在以「請求帶 `response_format`」辨識關鍵字請求（`tests/fake_openai_server.py:232`），改完後請求仍帶 `response_format`，辨識方式不變。
- [x] 假 server 對關鍵字請求回「`low_level_keywords` 陣列少了 `]`」的輸出時，`query` 結束碼 0；Python API 同樣成功。
- [x] 回無法解析成物件的內容（例如純文字）時，`query` 結束碼 1，stderr 含「抽關鍵字的輸出不是合法的 JSON」與輸出開頭；`eval` 記成該格失敗；Python API 拋 `EndpointError`。
- [x] 假 server 收到的關鍵字請求仍帶 `response_format`，schema 的欄位與現在相同。
- [x] 現有測試全綠。既有測試的預期值若因這張票的行為改變而要改，在 ticket 的實作結果逐項寫明改了哪個測試、為什麼，不放寬判斷。
- [x] `docs/architecture.md` 描述查詢流程與 `models.py` 的段落同步。

## 實作結果（2026-11-03）

改動：
- `rag_lab/models.py`：`llm_model_func` 收到 `keyword_extraction=True` 時，把 `response_format` 設成 dict 形式的 schema（`KEYWORD_RESPONSE_FORMAT`），呼叫後用 `_parse_keyword_output`（`remove_think_tags` → `json_repair.loads` → 整理成兩個字串陣列）解析，回傳整理後的 JSON 字串給 LightRAG；解析不出時拋 `EndpointError("LLM", 位址, "抽關鍵字的輸出不是合法的 JSON：" + 輸出前 200 字元)`。原本的 LLM 呼叫與錯誤包裝抽成 `_complete`，其他 LLM 呼叫走同一個函式，行為不變。
- `tests/fake_openai_server.py`：新增 `keywords_reply`，讓測試指定關鍵字請求回的原文；辨識關鍵字請求的方式不變（請求帶 `response_format`）。
- `tests/test_python_api.py`：driver 新增 `query_error` 步驟（印出 `query` 拋出的例外類別與訊息）。
- `tests/test_keyword_json.py`（新）：13 個測試，涵蓋 CLI `query`、Python API（模組函式與 `Session`）、`eval`。
- `docs/architecture.md`：查詢流程新增關鍵字抽取的段落；`models.py`、假 server、測試表格三處同步。

驗證：
- 新測試在舊的 `models.py` 上 13 個中有 9 個失敗（15 筆失敗，含 subTest），在新程式上全過；沒變的 4 個（合法輸出的關鍵字、兩個欄位都是空陣列、不重試、schema 內容）是用來確認行為沒變，舊程式上本來就過。
- 完整測試：`.venv/bin/python -m unittest`，Ran 282 tests，OK（1216 秒）。專案用 unittest，`.venv` 沒有安裝 pytest。
- 既有測試的預期值沒有改。

ASSUMPTION（票裡「推測」的部分，用測試確認）：
- 「`response_format` 傳 dict 時 SDK 不嚴格驗證、回傳模型原文」：確認。`test_a_missing_bracket_is_repaired_and_the_repaired_keywords_are_used_for_retrieval` 在假 server 回少 `]` 的輸出時，`query` 結束碼 0，且修好的低階關鍵字（標記字串）出現在送去 embedding 的請求裡。openai SDK 的 `chat.completions.parse()` 對 dict 形式的 `response_format` 不解析回應（`openai/lib/_parsing/_completions.py` 的 `has_rich_response_format`），`lightrag/llm/openai.py:338–346` 仍走 `parse()`，回傳的 `message.content` 是原文。
- 「請求帶的 schema 和現在相同」：確認。`test_the_keyword_request_still_carries_the_same_json_schema` 檢查假 server 收到的 `response_format`（`type`、`json_schema.name`、`strict`、`schema` 的欄位與標題）；這個測試在改動前的程式上也通過，預期值取自改動前的請求內容。schema 用 SDK 的公開函式 `openai.pydantic_function_tool` 產生，不 import SDK 的私有模組。
- 假 mlx-lm server 以外的後端（真的支援限制輸出格式的後端）沒有實測，只確認請求內容與改動前相同。

與票面敘述不同之處：
- 驗收第 3 項寫「Python API 拋 `EndpointError`」。實際拋出的是 `PipelineError`，訊息是「查詢失敗（mode=mix）：Query failed: LLM 端點 … 失敗：抽關鍵字的輸出不是合法的 JSON：…」。原因：LightRAG 的 `aquery_llm` 把查詢途中的 LLM 例外轉成失敗狀態，`pipeline._answer` 再轉成 `PipelineError`；現有的 `fail_keywords`、`fail_chat` 失敗也是這個路徑。票的行為段落寫「捕捉點都不用改」，所以沒有改 `pipeline.py`；測試斷言 `PipelineError` 且訊息含 `EndpointError` 的完整文字。`query` 結束碼 1、`eval` 記成該格失敗不受影響。若要讓 Python API 直接拋 `EndpointError`，要改 `pipeline._answer`，不在這張票的範圍。

範圍外的發現：
- 模型輸出空字串時，openai binding 自己拋 `InvalidResponseError: Received empty content from OpenAI API`（重試 3 次後），這是現有行為，錯誤訊息不含「抽關鍵字的輸出不是合法的 JSON」。這張票沒有改，測試也沒有涵蓋。

## Comments

- 2026-11-03 使用者同意 rag_lab 直接 import `json_repair`（不列入 `requirements.txt`，沿用由 raganything 帶入的慣例）。
