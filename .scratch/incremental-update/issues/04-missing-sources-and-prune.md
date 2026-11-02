# 04: 來源已不在：只列出，加 `--prune` 才刪

**What to build:** 使用者執行 `ingest <資料夾>` 時，之前從這個資料夾匯入、現在檔案不在的文件，列在報告的「來源已不在（未刪）」；加 `--prune` 才從知識庫刪掉，而且只刪之前從這個資料夾匯入的，報告記「已刪除」。Python API 指定來源資料夾與 prune 時行為相同（spec「匯入端：替換與移除」「匯入端：介面」）。

**Blocked by:** 01、02（刪除前查共用版本、刪除時保留抽取快取，和 02 刪舊版本用同一段邏輯，沿用 02 的實作）

**Status:** resolved

- [x] 不加 prune：來源已不在（以檔案系統判斷）的文件只列出路徑，知識庫與對照表不變；沒有其他失敗時結束碼 0。
- [x] Python API 指定了來源資料夾時，對照表記的來源資料夾是指定的資料夾；沒指定時是檔案所在的資料夾（spec「匯入端：對照表」）。
- [x] 加 prune：逐一刪除（保留 LLM 抽取快取），移除對照表那一筆，報告記「已刪除」；每份文件只歸一類，不再算「來源已不在」。
- [x] 只處理來源資料夾等於這次資料夾的紀錄；其他資料夾匯入的文件不受影響。
- [x] 刪除前先查對照表：還有別的路徑指向同一個文件 ID 時，不刪知識庫的內容，只移除這個路徑的那一筆，報告仍記「已刪除」。
- [x] 資料夾不存在或已沒有支援的文件時：CLI 照現行規則以結束碼 2 結束，不做移除（grill Q24）；Python API 指定的來源資料夾不存在或沒有支援的文件時拋使用錯誤（不論有沒有給 prune），和 CLI 相同。
- [x] 匯入單一檔案時不檢查移除；單一檔案加 `--prune` 以結束碼 2 結束並說明原因；Python API 沒有來源資料夾卻給 prune 時拋使用錯誤。
- [x] 刪除失敗：報告記成失敗並寫出原因，結束碼 1。
- [x] README 寫明 `--prune` 的行為與建議的使用順序（先不加、看清單、再加）；現有測試全綠。

## Comments

- 實作：`pipeline._ingest(rag, documents, settings, source_folder, prune)`。匯入完之後，指定了來源資料夾才檢查：`_missing_sources` 取對照表裡 `source_folder` 字串等於這次資料夾、而 `Path(key).exists()` 為 False 的鍵（只比對字串與路徑，不假設路徑在來源資料夾底下，所以 symlink 檔 resolve 後在資料夾外也找得到）。沒給 prune 列在 `IngestSummary.missing`；給了就 `_prune_missing` 逐一呼叫 02 的 `_remove_version`（共用版本檢查、保留抽取快取），成功才從對照表移除並寫檔、記入 `removed`；失敗記入 `remove_failed`（路徑 → 「型別：訊息」），知識庫與對照表那一筆不動，其餘文件照常處理。每份文件只歸一類：prune 時 `missing` 永遠是空的。
- 修正 01 的 ASSUMPTION 2：`_record_success` 的 `source_folder` 現在記 `ingest <資料夾>` 的資料夾（resolve 後）；單一檔案或 Python API 沒指定時記檔案實體路徑所在的資料夾；Python API 指定了就記指定的。已完整匯入、ID 相同但來源資料夾不同的文件，只改那一筆的 `source_folder`（`doc_id`、`ingested_at` 不動）。
- 公開介面：模組函式與 `Session.ingest` 新增 keyword 參數 `source_folder: Path | None = None`、`prune: bool = False`；CLI 新增 `ingest --prune`。報告印「來源已不在（未刪）N 份」「已刪除 N 份」（只在 ingest 資料夾時印），刪除失敗印 `刪除失敗：<路徑>：<原因>` 到 stderr，結束碼 1。
- 防呆放在 `pipeline._require_valid_sync`（模組函式與 `Session.ingest` 都在動手之前呼叫）：來源資料夾不存在、不是資料夾或沒有支援的文件，或沒有來源資料夾卻給 prune，拋 `PipelineError`。「資料夾裡哪些檔案算文件」的規則從 `__main__` 搬到 `formats.list_folder`（含 `NOT_A_DOCUMENT_PREFIXES`），CLI 與 API 共用，行為不變。
- 測試在 `tests/test_prune.py`（CLI 與 Python API）；`tests/test_python_api.py` 的 driver 新增 `sync:`、`into:`、`bare_prune:` 步驟。
- ASSUMPTION：「來源已不在」以 `Path(key).exists()` 判斷。symlink 檔被刪掉但它指向的實體檔案還在時，對照表的路徑仍存在，不算來源已不在（spec 規定用對照表記的路徑判斷）。
- ASSUMPTION：參數名稱 `source_folder`、`prune`、結果欄位 `missing`、`removed`、`remove_failed` 由實作決定（spec 允許）。
- ASSUMPTION：對照表在 prune 刪除後寫不進去時，立刻拋 `PipelineError`（訊息寫出該文件已從知識庫刪掉、對照表沒更新，重跑同一個 `ingest --prune` 即可，因為刪除回 `not_found` 視為成功），後面的文件不再處理；這時 `IngestSummary` 不會回傳。
- 範圍外：刪除後清查詢答案快取是 ticket 05；README「還沒做」那一條仍適用。
