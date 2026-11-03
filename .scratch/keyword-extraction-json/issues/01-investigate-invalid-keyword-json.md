# 01: 調查查詢時抽關鍵字的 JSON 不合法、查詢直接失敗

**What to build:** 這張是調查票，不改程式。要回答：查詢時 LLM 抽關鍵字輸出不合法的 JSON 導致查詢失敗，發生頻率多高、能不能從根本上避免，以及修法會不會改變其他查詢的結果。調查結果決定要不要再開實作票。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 找出 LightRAG 1.4.16 抽關鍵字的 prompt、解析 JSON 的程式碼位置，以及解析失敗時的行為（直接讓查詢失敗、重試，或改用別的方式）。
- [x] 查 `mlx_lm.server`（pipx 安裝的 mlx-lm 0.32.0）支不支援限制輸出格式（例如 OpenAI 的 `response_format` 或 JSON schema）。要看原始碼，不能只看文件。
- [x] 量頻率：用現有的 4B 模型，對 eval 題目和 2026-11-01 方案 C 實驗的子問題，只跑抽關鍵字（不檢索、不生成）各 N 次。N 由調查者決定，要寫出理由。記錄不合法的次數與輸出的樣子。需要啟動 port 8080 的 LLM server。
- [x] 列出可行的修法與代價，至少比較：限制輸出格式（如果 server 支援）、在 rag_lab 解析失敗時讓錯誤訊息指出原因、換模型。不能只加重試來掩蓋。
- [x] 結果寫在這張票的「調查結果」段落：事實和推測分開寫，每個結論都要附出處（檔案:行號或 log 路徑）。

## 已知的事實

- 2026-11-01 方案 C 的第一次 probe：雙幣卡子問題「在海外刷卡，台新雙幣卡的回饋率與上限是多少？…」，抽關鍵字時模型輸出的 JSON 不合法，LightRAG 解析失敗，查詢失敗。換一種問法後成功。當時的 log 複製到 `output/keyword_json/probe_20261101_pg3.err`（gitignore）。
- 3 次完整 eval（共 300 格）沒有發生過。

## 調查結果（2026-11-03）

量測的檔案都在 `output/keyword_json/`（gitignore）：腳本 `measure_keywords.py`、`measure_variants.py`，結果 `run1.jsonl`、`variants.jsonl`。LLM server 用 README 第 3 節的啟動指令（`mlx_lm.server ... --max-tokens 4096 --prompt-cache-bytes 4GB`，沒有 `--temp`），log 在 `output/keyword_json/lm_server.log`。

用語：
- **查詢路徑**：和真實查詢相同的呼叫，`llm_model_func(prompt, keyword_extraction=True)`，經過 openai SDK 的 `chat.completions.parse()`。
- **原始輸出**：同一個 prompt 不帶 `keyword_extraction`，用 `chat.completions.create()` 取回模型輸出的原文。
- **嚴格驗證**：`GPTKeywordExtractionFormat.model_validate_json`，和 SDK 在查詢路徑上用的驗證相同。
- **openai binding**：LightRAG 呼叫 OpenAI 相容 API 的模組 `lightrag/llm/openai.py`。

### 失敗的路徑（事實）

- LightRAG 抽關鍵字時呼叫 `use_model_func(kw_prompt, keyword_extraction=True)`（`lightrag/operate.py:3465`）。openai binding 看到 `keyword_extraction` 就加上 `response_format=GPTKeywordExtractionFormat`（`lightrag/llm/openai.py:294–295`），改用 openai SDK 的 `chat.completions.parse()`（`openai.py:338–346`）。
- SDK 收到回應後用 pydantic 嚴格驗證（`model_validate_json`；traceback 見 `output/keyword_json/probe_20261101_pg3.err` 第 100–109 行）。JSON 不合法時拋 `ValidationError`，rag_lab 的 `llm_model_func` 轉成 `EndpointError`，查詢失敗。
- LightRAG 自己解析關鍵字時用 `json_repair.loads`（`operate.py:3470`），能修好缺括號這類錯誤；解析不出東西時回傳空關鍵字（`operate.py:3473`、`3477`），不讓查詢失敗。SDK 的嚴格驗證先拋例外，所以這段容錯走不到。
- 兩種關鍵字都是空的時候，LightRAG 在問題少於 50 個字元時改用整個問題當關鍵字，50 個字元以上時直接回傳固定的 `fail_response` 當成答案（`operate.py:3228–3233`），不拋例外。

### mlx_lm.server 不支援限制輸出格式（事實）

- pipx 安裝的 mlx-lm 0.32.0：`mlx_lm/server.py` 沒有出現 `response_format`（0 次），`mlx_lm/*.py` 也沒有 `json_schema`、`grammar`。server 讀取的請求欄位列在 `server.py:1159–1194`，`response_format` 不在其中。查詢路徑的失敗訊息和原始輸出的嚴格驗證錯誤逐字相同（`probe_20261101_pg3.err:109` 與 `run1.jsonl` 的 subq:12），符合「server 不理會 `response_format`、兩種呼叫產生同一段輸出」。
- `--temp` 預設 0.0（`server.py:1840–1843`），temperature 0 時用 greedy sampler（`mlx_lm/sample_utils.py:49`）。rag_lab 與 openai binding 都沒有傳 `temperature`（`rag_lab/`、`lightrag/llm/openai.py` 各 0 筆）；`lightrag/constants.py:86` 的 `DEFAULT_TEMPERATURE = 1.0` 不在這條路徑上。所以用上面的啟動指令時，抽關鍵字是 greedy decoding。

### 頻率（事實）

- 第一輪（`run1.jsonl`）：50 個問題 = 台新 eval 20 題、formats 10 題、format_check 6 題、example 2 題，加上 2026-11-01 方案 C 的 11 個子問題與當時失敗的 1 個問法。每題走 1 次查詢路徑（`keyword_extraction=True`，和真實查詢相同）＋3 次取原始輸出，共 200 次呼叫。
  - 失敗 1 題，就是 2026-11-01 失敗的問法「在海外刷卡，台新雙幣卡的回饋率與上限是多少？歐洲國家的實體商店消費有沒有回饋？」。查詢路徑失敗，3 次原始輸出逐字相同、都沒通過嚴格驗證。
  - 50 題的 3 次原始輸出逐字相同（0 題不一致）；查詢路徑的成敗和原始輸出的嚴格驗證結果 50 題都一致。
  - 失敗的輸出：`low_level_keywords` 陣列最後少了 `]`（`... "Foreign transaction"\n}`）。`json_repair.loads` 修回 5 個 high-level、6 個 low-level 關鍵字。
- N 的理由：temperature 0 時同一個問題重複問結果不變（上一條），重複次數不會增加樣本。所以第二輪改成增加不同的問題文字：50 題各加 4 種不改意思的寫法（前面加「請問」、後面加「謝謝！」、全形問號改半形、前面加「我是台新的持卡人，」），共 200 個（`variants.jsonl`）。結果 0 個不合法，包括失敗那題的 4 種寫法。
- 合計：50 個基底問題中 1 題失敗；它們的 200 個改寫 0 個失敗。改寫和基底問題不獨立，以基底問題算是 1/50，只有 1 次失敗，樣本不夠定出比例，只能說「少見」。250 個問題文字的輸出都能由 `json_repair` 解出關鍵字。兩輪共 400 次呼叫，每次中位數 1.30 秒，最長 3.01 秒。
- 推測：失敗和問題文字綁在一起，不是隨機發生。同一個問法每次都失敗，前面加「請問」等改寫就成功；客戶用到那個問法時，重問同一句不會好。

### 修法比較

| 修法 | 能不能避免 | 對其他查詢的影響 | 代價 |
|---|---|---|---|
| 限制輸出格式（server 端 JSON schema） | 目前做不到：mlx-lm 0.32.0 server 不讀 `response_format`，也沒有 grammar 選項 | — | 要改 server 或換推論 server，超出 rag_lab |
| rag_lab 抽關鍵字時改用 `json_repair` 解析，解不出兩種關鍵字時以明確的錯誤失敗 | 能救回這次量到的 1 題（缺括號） | 合法的輸出解出的關鍵字和現在相同：兩輪中 347 個通過嚴格驗證的原始輸出，`json_repair.loads` 與 `json.loads` 的結果全部相同。LightRAG 的關鍵字快取，鍵由模式、問題與語言算出（`operate.py:3424–3428`），存的是解析後的兩個清單（`operate.py:3484`），所以既有的快取不受影響（推測，未實測） | `llm_model_func` 要分出關鍵字的路徑；要自己檢查解析結果，否則解不出時 LightRAG 會對 50 字以上的問題回固定的失敗答案而不報錯 |
| 只改錯誤訊息，指出是抽關鍵字的 JSON 不合法 | 不能，查詢照樣失敗 | 無 | 最小；使用者知道原因，可以換問法 |
| 換模型 | 未知 | 2026-11-02 的 8B 實驗：mix ✓ 9→7，抽出的關鍵字多是英文（`proposal-answer-quality.md` 第 8 節） | 已決定不採用 |
| 重試 | 不能：temperature 0 時重試得到同樣的輸出 | 調高 temperature 才會不同，會改變所有查詢的關鍵字 | 違反「不能只加重試來掩蓋」 |

### 建議

開一張實作票做第 2 種：rag_lab 抽關鍵字時不交給 SDK 嚴格驗證，自己用 `json_repair` 解析，解出的兩種關鍵字都是空的或格式不對時拋錯誤，訊息寫明「抽關鍵字的輸出不是合法的 JSON」並附輸出開頭。理由：失敗少見（50 個基底問題中 1 題），但每次都發生在同一個問法上、而且整題失敗；LightRAG 本來就打算用 `json_repair` 容錯，是 SDK 的嚴格驗證擋在前面。測試沿用假 OpenAI server 的縫：假 server 回缺括號的 JSON 時查詢成功、回無法解析的內容時以指出原因的錯誤失敗。

## Comments
