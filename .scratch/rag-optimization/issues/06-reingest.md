# 06: 刪除舊知識庫並全量重匯

**What to build:** 使用者確認之後刪除舊知識庫，用新設定（中文、領域實體類型、標頭與依標題切塊、4B embedding、新檔名）全量重匯 `data/taishin_credit_card/`，記錄時間與記憶體（spec：「重匯」；grill-notes 決定 16、17）。

**Blocked by:** 01, 02, 03, 04, 05

**Status:** ready-for-human（刪除前要使用者確認；重匯要使用者先設定記憶體上限）

- [ ] 確認前置條件：`iogpu.wired_limit_mb` 讀到 26000（使用者開機後自己設）；`.env` 已有 `KB_LANGUAGE`、`KB_ENTITY_TYPES`、`DOCUMENT_HEADERS_FILE`、4B embedding。
- [ ] 列出 `rag_storage/` 與 `output/rag_opt/kb_copy/` 的大小與檔案數，以及其他 `output/rag_opt/kb_*` 副本，交使用者確認。確認之前不刪。
- [ ] 刪除之後，用 4B embedding 啟動 8081 server（不開 thinking），開 watchdog（`output/crash_repro/tools/watchdog.sh <dir> 27 3`）。
- [ ] 依 README 的方式逐一匯入每個類別資料夾。記錄每個資料夾的開始與結束時間、各階段時間、wired 峰值、失敗文件。
- [ ] 中途 OOM 或觸發 watchdog：停下來回報，不自行調整上限。
- [ ] 完成後記錄 chunk、實體、關係的數量，並和舊知識庫（2,341／18,297／37,027）對照。抽 3 個 chunk 確認開頭有標頭、實體名稱與描述是中文、實體類型是新的 10 類。
- [ ] 記錄檔放在 `output/rag_opt/reingest/`（gitignore），結果寫進下方。
