# 11: 實機驗收：讓台新知識庫跟上官網

**What to build:** 對真實官網跑一次更新模式，再同步知識庫，確認知識庫跟上官網、答案用到新內容（spec「Testing Decisions」的實機驗收）。由主對話執行，需要開 server。

**Blocked by:** 01–10；`.scratch/chunk-truncation/issues/01`（同一段 server 使用時間的先後）

**Status:** ready-for-human

- [ ] 備份整個 `rag_storage`。
- [ ] 6 個資料夾逐一 `ingest` 建好對照表（預期全部「沒變」，不呼叫模型）；記錄耗時（grill Q19）。
- [ ] 對官網跑更新模式，記錄各類別的新增、內容變更、未變、下架、過期移除、失敗數量與耗時。
- [ ] 6 個資料夾再逐一 `ingest`（不加 `--prune`），記錄各分類數量、耗時、GPU 記憶體峰值（watchdog 門檻 22 GB）。
- [ ] 「來源已不在」的清單給使用者確認；確認後加 `--prune` 重跑。
- [ ] 抽題 eval（mix）確認答案用到新內容；題目與參考答案若因官網改版過時，列出並由使用者決定是否更新題目檔。
- [ ] 結果寫進這張 ticket 與 README 第 5 節。
