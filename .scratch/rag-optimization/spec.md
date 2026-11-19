# 台新知識庫的回答品質優化：一次重匯

**Status:** ready-for-agent

grill 與實驗紀錄在 `grill-notes.md`（決定 1–20），下面引用的「決定 N」都指那份檔案。ADR：`docs/adr/0001-single-bundled-reingest.md`。

## Problem Statement

台新知識庫 28 題 eval（mix＋rerank，Gemma 4 26B A4B，加回答附加指示）的結果是內容 ✓ 16、最終 ✓ 8。2026-11-18～19 的歸因與實驗結果：

- 內容沒有 ✓ 的 12 題裡，5 題是來源檔的 chunk 沒有被檢索到（a 類），1 題是被 token 上限截掉（b_trunc），6 題是正確內容已經在 context 裡，但答案被同一份文件裡別的產品、年度或活動干擾，或者模型漏寫、寫錯（c 類）。
- a 類的共同點：檢索到的是別張卡片的文件。chunk 切開之後，內容裡沒有卡片名稱。
- 查詢端三個實驗（thinking、chunk_top_k 40、逐項回答指示）都沒有淨增 4 題，不採用（決定 18）。
- embedding 比較：Qwen3-Embedding-4B 的 chunk 檢索前 10 名覆蓋 70／84 句，現行 0.6B 是 59／84（決定 19）。

匯入端目前的設定：LightRAG 用英文抽實體與描述（`SUMMARY_LANGUAGE` 沒設），實體類型是通用預設，切塊只依 token 數（1,200 token、重疊 100），檔名（例如 `card_cg047_card001.pdf`）看不出是哪張卡片。

## Solution

把下列匯入端改動放進同一次全量重匯（ADR 0001），再用 28 題 eval 加雙判讀和基準比較：

1. 每份文件產生**卡片標籤**（卡別＋適用卡片，定義見 GLOSSARY），放進檔名與每個 chunk 的標頭。
2. **依標題切塊**：在 MinerU 標出的標題處切開，chunk 標頭是卡片標籤加章節名稱。
3. 實體抽取與描述的**語言改成繁體中文**。
4. **實體類型**改成信用卡領域的 10 類。
5. **embedding 換成 Qwen3-Embedding-4B**。

重匯直接取代 `rag_storage`，刪除前列清單給使用者確認（決定 16）。不重新爬官網（決定 4）。管線裡每一步只用本機模型，Claude 只負責設計、寫程式與判讀（決定 10）。

## User Stories

1. As a 使用者, I want 每份文件的檔名帶卡別與卡片名稱, so that 看檔名就知道文件屬於哪張卡。
2. As a 使用者, I want 卡片標籤先交給我抽查再用, so that 標錯的卡片不會進知識庫。
3. As a 使用者, I want 每個 chunk 開頭寫出卡片標籤與章節名稱, so that 檢索時問題裡的卡片名稱能比對到正確文件的 chunk。
4. As a 使用者, I want chunk 在標題處切開, so that 一個 chunk 不會混到兩個章節的產品或年度。
5. As a 使用者, I want 圖譜的實體與描述用繁體中文, so that 中文問題抽出的關鍵字和圖譜的語言一致。
6. As a 使用者, I want 實體類型是卡片、權益、回饋方案等領域類型, so that 圖譜依信用卡的概念分類。
7. As a 使用者, I want 語言、實體類型、標頭檔都在 .env 設定, so that 其他知識庫可以用不同的值，不用改程式。
8. As a 使用者, I want 之後用 `scripts/fetch_taishin.py` 抓新文件時自動用新檔名, so that 增量更新不會產生舊格式的檔名。
9. As a 使用者, I want 刪除舊知識庫之前先看到要刪的清單, so that 我確認之後才刪。
10. As a 使用者, I want 重匯時記錄每個階段的時間與記憶體峰值, so that 知道 4B embedding 和中文抽取實際花多少時間。
11. As a 使用者, I want 重匯後的 eval 用同樣的 28 題、同樣的判讀方式和基準比較, so that 能判斷這次重匯有沒有效。

## Implementation Decisions

### 卡片標籤（決定 5、6，GLOSSARY「卡片標籤」）

- 標籤有兩個欄位：
  - 卡別：信用卡、金融卡，或兩者都有。
  - 適用卡片：一張或多張卡片名稱，或「全部信用卡」「全部金融卡」。
- 產生方式：程式從 manifest 網址、類別資料夾與 `_meta/html` 的官網頁面產生。
  - 卡片頁（`cards/`、`debit_cards/`、`richart/`）：網址的 `cgXXX` 或頁面標題對應卡名。
  - 其他有頁面快照的文件（權益、活動等）：在頁面內文比對已知卡名清單。
  - 沒有頁面快照的 52 份（下載 19、權益附件 20、活動圖片 9、金融卡約定條款 PDF 4）：如果 manifest 或 `fetch_taishin.py` 記得它是從哪個頁面連過去的，沿用那個頁面的標籤；查不到就列進待人工確認清單。
  - 比對不到時不猜，列進待人工確認清單。
- 標籤檔：`data/taishin_credit_card/_meta/document_labels.json`，key 是相對於 `data/taishin_credit_card/` 的路徑，值含卡別、適用卡片清單、簡短卡名（檔名用）與標頭文字。使用者抽查之後才給下游使用。
- 檔名格式：`<卡別>_<簡短卡名｜多卡｜全部>_<原檔名>`，例如 `信用卡_台新Richart卡_card_cg047_card001.pdf`。卡別兩者都有時寫「信用卡及金融卡」。

### 改檔名（決定 6；grill 時使用者決定檔名也要改）

- `scripts/fetch_taishin.py` 的 `document_filename`（`scripts/fetch_taishin.py:2513`）改成產生新格式。之後新抓的文件也用新檔名。
- 新格式套用在所有會放進資料夾、會被匯入的文件，包含活動圖片（`IMAGES`，`fetch_taishin.py:2092` 起比較新舊 banner 檔名的地方也要跟著改）。
- 一次性遷移腳本：改 `data/taishin_credit_card/` 底下現有文件的檔名、manifest 的 `filename`、`eval/questions.taishin.jsonl` 的 `source`。manifest 裡 11 筆沒有實體檔的紀錄也照同一規則改；產生不了標籤的保留原檔名並列出。`_meta/html`、`_meta/print` 的快照檔名要不要改，依 `fetch_taishin.py` 怎麼對照決定，以增量更新照常運作為準。
- 遷移腳本要可以重跑：已經是新檔名的不再改。

### chunk 標頭與依標題切塊（決定 13）

- rag_lab 新增選填設定 `DOCUMENT_HEADERS_FILE`，指向一個 JSON 檔，key 是文件檔名，值是標頭文字。台新知識庫用 `data/taishin_credit_card/_meta/document_headers.json`（ticket 02 產生）。
  - 沒設：下面所有改寫都不做，匯入行為和現在完全一樣。
  - 有設，但匯入的文件不在檔裡：在 `parse_document` 就讓該文件匯入失敗，報告寫出原因。不會在沒有標頭的情況下匯入。
- 依標題切塊（`rag_lab` 自訂 LightRAG 的 `chunking_func`）：
  - `LabRAGAnything.parse_document` 把 content list 裡有 `text_level` 的文字項目標成標題（加 markdown `#` 記號），並在文件最前面放一段標頭，用固定的標記行包起來，讓 chunker 能從文件內容讀出標頭（LightRAG 呼叫 `chunking_func` 時不傳檔名）。標記行的格式由 ticket 04 定，不能是一般文件會出現的文字。
  - 自訂 chunker 在標題處切開。一節超過 1,200 token 時，在節內依 token 數再切，重疊 100。
  - 每個 chunk 的開頭是「卡片標籤＋章節名稱」。標頭超過 150 token 時，標頭改寫成「適用 N 張卡（清單見本文件第一段）」，完整清單只放在第一個 chunk。
  - 短節：少於 100 token 的節併進下一節，標頭列出兩個章節名稱；最後一節太短時併進前一節；合併後超過 1,200 token 時照一般規則在節內再切（使用者 2026-11-19 選 (c)）。
- 表格與圖片：RAG-Anything 把它們另外做成 chunk，不經過 `chunking_func`。在 `parse_document` 把卡片標籤加進 `table_caption`／`image_caption`，讓這些 chunk 的內容也帶卡片名稱。
- 文件 ID 不變：RAG-Anything 依原始 content list 算 ID 與解析快取，`parse_document` 只改回傳的那一份（和現行的表格縮小做法相同）。
- 已知後果：自訂 `chunking_func` 之後，RAG-Anything 不會再幫文字 chunk 標頁碼（`page_idx`）。`rag_lab` 目前沒有用到頁碼。

### 語言與實體類型（決定 5）

- rag_lab 新增兩個設定，經 `build_rag` 的 `addon_params` 傳給 LightRAG：
  - `KB_LANGUAGE`：這次設 `Traditional Chinese`。
  - `KB_ENTITY_TYPES`：逗號分隔，這次設「卡片,權益,回饋方案,回饋規則,費用,約定條款,活動,商店或通路,支付工具,機構」。
- 兩個都必填，缺少時以 ConfigError 中止（和現有欄位的規則相同）。`SUMMARY_LANGUAGE`、`ENTITY_TYPES` 仍然留在拒絕名單裡。
- 語言同時影響查詢時的關鍵字抽取（`lightrag/prompt.py:387`），所以重匯之後，查詢也用中文抽關鍵字。

### embedding（決定 20）

- `EMBED_MODEL=mlx-community/Qwen3-Embedding-4B-4bit-DWQ`、`EMBED_DIM=2560`，查詢前綴沿用現行的 Qwen 指令。
- 要一起更新的地方：`.env`、`.env.example`、`README.md` 的 server 啟動指令、`scripts/vlm_server.py` 與 `scripts/smoke_test.py` 裡寫到 0.6B 的地方。

### 重匯（決定 16、17）

- 刪除前列出 `rag_storage/` 與 `output/rag_opt/kb_copy/` 的大小與檔案數，交給使用者確認。刪除之後無法換回舊知識庫；舊的 eval 答案保留在 `eval_results/`。
- 檔名改了，MinerU 的解析快取對不上，所有文件都要重新解析。
- 記憶體上限 `iogpu.wired_limit_mb=26000`（每次開機由使用者設定），watchdog 門檻 27 GB、每 3 秒取樣。
- 記錄：每個資料夾的匯入時間、各階段時間（rag_lab 的 StageTimer）、wired 峰值、chunk／實體／關係數。

### 驗收（決定 1、11）

- 28 題 eval，只跑 mix，跑 1 次。兩位判讀者（sonnet）各自判讀，用 `output/rag_opt/compare_judges.py` 逐題比對。
- 基準：重新判讀的基準 `output/rag_opt/judging/base_judge_{A,B}.md`（內容 ✓ 17／16、最終 ✓ 8／9）。
- 目標：內容 ✓ ≥20、最終 ✓ ≥12，兩位判讀者都同意的變好題數減變差題數 ≥4，原本 ✓ 的題目不能變錯（決定 1；以兩位判讀者都同意變差的題目計）。
- 另外用 `output/rag_opt/probe28.py` 重跑 a／b／c 歸因，來源檔名改成新檔名。
- 沒達標時不回滾（舊知識庫已刪），結果寫進 ticket，由使用者決定下一步（例如在新知識庫上重試 E1、E2，或考慮補前後文摘要，決定 14）。

### 已確認：短節的處理

1. **短節怎麼處理**：948 節少於 100 token。
   - (a) 每個標題各自一個 chunk：chunk 數從 2,341 增加到約 2,600 以上，實體抽取的 LLM 呼叫跟著增加，很多 chunk 的標頭比內文還長。
   - (b) 相鄰的節合併到接近 1,200 token：chunk 數接近現在，但一個 chunk 又會混到好幾節，c1 類干擾回來。
   - (c) 少於 100 token 的節併進下一節，標頭列出兩個章節名稱；其他節各自一個 chunk。
   - 使用者選 (c)（2026-11-19）。最後一節太短時併進前一節；合併後超過 1,200 token 時照一般規則在節內再切。

## Testing Decisions

- 好的測試只看外部行為：給定 content list 與設定，檢查產生的 chunk 內容與數量、設定錯誤時的錯誤訊息；不檢查內部函式的呼叫順序。
- 新增的測試沿用現有的假端點（`tests/fake_openai_server.py`、`tests/fake_mineru.py`），參考 `tests/test_pipeline.py`、`tests/test_cli.py` 的寫法。
- 要測的行為：
  - 切塊：標題處切開；超長節再切；短節合併（少於 100 token 併進下一節、最後一節併進前一節）；標頭內容；標頭超過 150 token 的改寫；沒有標題的文件。
  - `DOCUMENT_HEADERS_FILE`：沒設時和現在一樣；文件不在檔裡時匯入失敗。
  - `KB_LANGUAGE`、`KB_ENTITY_TYPES`：缺少時 ConfigError；值有傳進 LightRAG 的 `addon_params`。
  - 改檔名：`document_filename` 的新格式；遷移腳本重跑不會重複改名。
- 卡片標籤的正確性靠使用者抽查，不寫自動測試。
- 重匯與 eval 是實機量測。

## Out of Scope

- 重新爬官網（決定 4）。
- 查詢端改動（thinking、chunk_top_k、回答指示），決定 18。
- 用 Gemma 補前後文摘要（決定 14）。
- 換 reranker、換生成用的 LLM（決定 8）。
- bge-m3 的 pooling 問題、rag_lab 收下被長度截斷的答案、eval 啟動時 17 分鐘的空檔（grill-notes「範圍外發現」）。

## Further Notes

- 依 4B 的實測速度，重匯光 embedding 就約 12.7 小時；加上 Gemma 用中文抽實體，總時間沒有實測過。Qwen 時期全量匯入（當時約 300 份）每份耗時加總 26.3 小時（`.scratch/taishin-credit-card-kb/issues/08`）。
- 依 MinerU 現有輸出統計（351 份 content list）：`text_level` 1 有 31 個、2 有 2,332 個，22 份文件沒有標題；依標題切出約 2,580 節，中位數 167 token，948 節少於 100 token，105 節超過 1,200 token。現行知識庫是 2,341 個 chunk。
