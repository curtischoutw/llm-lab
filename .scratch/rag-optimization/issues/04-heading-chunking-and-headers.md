# 04: 依標題切塊與 chunk 標頭

**What to build:** rag_lab 新增選填設定 `DOCUMENT_HEADERS_FILE`，並以自訂的 LightRAG `chunking_func` 在標題處切塊，每個 chunk 開頭放「卡片標籤＋章節名稱」；表格與圖片 chunk 也帶標籤（spec：「chunk 標頭與依標題切塊」）。

**Blocked by:** 無（真實標頭檔由 02 產生，用在 06；這張的離線檢查用自己寫的測試標頭）

**Status:** ready-for-agent

- [ ] `DOCUMENT_HEADERS_FILE`：選填，指向 JSON（key 是檔名，值是標頭文字）。檔案不存在或格式錯誤時 ConfigError。沒設時下面的改寫與自訂 chunker 都不啟用，匯入行為和現在完全一樣（chunk 內容與數量相同）。
- [ ] 有設、但匯入的文件不在檔裡：在 `parse_document` 讓該文件記成失敗，報告寫出原因，不寫入知識庫。
- [ ] `LabRAGAnything.parse_document`（只在有設 `DOCUMENT_HEADERS_FILE` 時）：把有 `text_level` 的文字項目標成標題，在最前面放用固定標記行包起來的標頭（chunker 從內容讀標頭，因為 LightRAG 不傳檔名給 `chunking_func`；標記行不能是一般文件會出現的文字），並把標籤加進 `table_caption`／`image_caption`。只改回傳的 content list，文件 ID 與解析快取不變（照現行 `tables.limit_table_sizes` 的做法）。
- [ ] 自訂 chunker：在標題處切開；一節超過 `chunk_token_size`（1,200）時在節內依 token 再切，重疊 100；每個 chunk 開頭是標頭加章節名稱；標頭超過 150 token 時照 spec 改寫，完整清單只放在第一個 chunk；少於 100 token 的節併進下一節、標頭列出兩個章節名稱，最後一節太短時併進前一節，合併後超過 1,200 token 時照一般規則再切。沒有標題的文件整份依 token 切，每個 chunk 仍帶標頭。
- [ ] chunker 的實作放在獨立模組（例如 `rag_lab/chunking.py`），由 `build_rag` 傳給 LightRAG。只在 `DOCUMENT_HEADERS_FILE` 有設時換掉預設 chunker。
- [ ] 用 MinerU 現有輸出（例如 `card_cg047_card001` 的 content list）和一段測試標頭離線跑一次 chunker，回報 chunk 數、token 分布，並列出 3 個 chunk 的開頭給使用者看。
- [ ] 測試（不測內部呼叫順序）：標題處切開、超長節再切、短節合併、標頭內容、標頭超過 150 token 的改寫、沒有標題的文件、沒設 `DOCUMENT_HEADERS_FILE` 時行為不變、文件不在標頭檔時失敗。`.venv/bin/python -m unittest` 全綠（README:543；改到 `scripts/fetch_taishin.py` 時加跑 README:549 的下載腳本測試）。
- [ ] 更新 pipeline 模組 docstring：新的切塊方式，以及自訂 chunker 之後文字 chunk 不再有頁碼（`page_idx`）。
