# 01: 對照表：匯入時記下路徑與文件 ID，報告分新增與沒變

**What to build:** 使用者執行 `ingest`（單一檔案或資料夾）或 Python API 的 ingest 後，`WORKING_DIR` 裡有 rag_lab 的對照表，記著每份處理成功的文件的絕對路徑、文件 ID、匯入時間、來源資料夾。報告與 ingest 的回傳結果開始分類，這張先有「新增」與「沒變」。這是後面替換、移除、清快取的基礎（spec：`.scratch/incremental-update/spec.md`「匯入端：對照表」，對照表的檔名與格式見該節）。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 第一次匯入一份文件：報告記「新增」，對照表有一筆；來源資料夾在 `ingest <資料夾>` 時是那個資料夾，匯入單一檔案時是它所在的資料夾。路徑照 CLI 現行方式取絕對路徑，Python API 相同。
- [x] 再次匯入同一份、內容沒變：報告記「沒變」，不呼叫模型，對照表那一筆保留。
- [x] 對照表有這個路徑、ID 相同，但那份沒有完整匯入（例如先前失敗）：照一般匯入，成功記「新增」。
- [x] 沒有對照表的知識庫（現有的知識庫）匯入沒變的文件：補上對照表那一筆，報告記「沒變」。
- [x] 新的路徑、內容和已對照的另一個路徑相同：記「新增」，補上對照表，知識庫沒有寫入。
- [x] 對照表先寫暫存檔再改名。對照表壞掉（不是合法 JSON 或格式不符）時，ingest 在處理任何文件之前失敗並指出檔案路徑，不當成空表；寫入失敗時 ingest 失敗，不吞掉。兩者 CLI 結束碼 1，Python API 拋 `PipelineError`。
- [x] CLI 輸出與 ingest 的回傳結果都有分類的數量與清單；既有的報告欄位不變。
- [x] 測試沿用 CLI 子行程＋Python API 的縫與假 server，可以直接讀寫對照表檔；現有測試全綠。
- [x] README 的 ingest 說明與架構文件寫明對照表的位置、格式與用途。

## Comments

- 新增 `rag_lab/registry.py`（對照表讀寫）；`pipeline._ingest` 載入對照表、分類並逐份寫回；`IngestReport.outcome`、`IngestSummary.added`／`unchanged` 與 CLI 的「新增 N 份／沒變 N 份」清單；測試在 `tests/test_registry.py`（CLI 與 Python API 涵蓋驗收條件的每一條）。
- ASSUMPTION：路徑已在對照表、ID 不同（內容變了）時，ticket 02 之前一律照一般匯入、記「新增」並更新那一筆，舊版本仍留在知識庫。
- ASSUMPTION：來源資料夾記文件所在的資料夾（Python API 的來源資料夾參數由 ticket 04 加入）；`ingest <資料夾>` 時兩者相同，資料夾裡的 symlink 檔除外。
- ASSUMPTION：對照表建立前就匯入的文件，補登時 `ingested_at` 記補登的時間。
- ASSUMPTION：寫入失敗時，那份文件已匯入知識庫、後面的文件不再處理，前面文件的收尾做完才拋 `PipelineError`。
