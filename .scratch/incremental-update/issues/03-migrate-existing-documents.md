# 03: 既有文件的遷移：對照表沒有這個路徑時，用檔名找舊版本

**What to build:** 對照表建立之前就匯入的文件（現有知識庫的 311 份），內容改了之後再次 `ingest`，也能被替換：rag_lab 用檔名到 LightRAG 的文件狀態找已完成的文件，排除已對照到別的路徑的 ID，剛好一份才當作舊版本（spec「匯入端：對照表」的規則 3）。

**Blocked by:** 02

**Status:** resolved

- [x] 對照表沒有這個路徑、這次的 ID 沒有完整匯入、檔名在文件狀態剛好對到一份：照 02 替換，報告記「替換」。
- [x] 候選排除已經對照到別的路徑的文件 ID。
- [x] 檔名對到 0 份：當作新增（grill Q22）。
- [x] 檔名對到多份：不替換也不新增，報告記成失敗，訊息列出候選的文件 ID，結束碼 1。
- [x] CLI 與 Python API 行為相同；現有測試全綠。

## Comments

- 實作在 `pipeline._find_legacy_version(rag, document, known)`，由 `_ingest_one` 在「這次的 ID 沒完整匯入、對照表沒有這個路徑」時呼叫：取文件狀態裡 processed 的項目，留下 `file_path == document.name`、ID 沒出現在對照表任何一筆、而且 `is_document_fully_processed` 的候選。1 份 → 當作 `old_id` 走 02 的替換；0 份 → `None`，走一般匯入記「新增」；多份 → 拋 `PipelineError`（`_ingest` 轉成該篇的 `report.error`，沒有分類、沒有寫對照表），訊息列出候選 ID。候選查找在「清掉同 ID 的舊失敗紀錄」之前，多份失敗時知識庫完全沒動。
- 測試在 `tests/test_migrate.py`（CLI 與 Python API；用「先匯入再刪對照表」造出對照表建立之前的狀態）。
- ASSUMPTION：「已完成」以 `rag.is_document_fully_processed` 判斷（文字與多模態都處理完），不只看 status 是 processed。
- ASSUMPTION：比對的檔名是 `document.name`；RAG-Anything 預設（`use_full_path` 關）把原檔的檔名（Office 也是原檔名，不是轉出的 PDF）記進文件狀態，測試以 PDF 驗證，沒有另外用 Office 文件驗證。
- ASSUMPTION：多份候選時整篇記成失敗，不順便處理後面「這次的 ID 已有失敗紀錄」的清除；下次修正後重跑即可。

### code-review 修正 8：已處理文件的狀態每批只載入一次（2026-11-02）

`_find_legacy_version` 每份新文件都重新載入全部 PROCESSED 文件的狀態，整批總工作量是 O(N²)。

- 新增 `_ProcessedByFileName`：每批 `_ingest` 第一次需要時載入一次，依檔名建索引（文件 ID 排序）；`_find_legacy_version` 查索引。候選仍逐一用 `is_document_fully_processed` 查現況，所以批次途中被刪掉的舊版本不會被選中。對外行為不變。
- 唯一的差異（極端情況）：同一批裡，前一份文件匯入後描述失敗（文件狀態暫時還是 processed、沒進對照表），後一份同檔名但不同資料夾的文件，舊做法會把前者當候選，新做法（索引是批次開始時的狀態）不會。舊做法在這種情況算對到一份舊版本去替換，不是設計過的行為。
- 夾具：`tests/delete_failure/sitecustomize.py` 多支援 `COUNT_STATUS_LOADS_FILE`（每次呼叫 `get_docs_by_status` 記一行狀態）。
- 測試：`MigrateStatusLoadsCliTest`，4 份新文件的整批載入次數要等於 1 份新文件的整批（先紅：4 對 1）。
