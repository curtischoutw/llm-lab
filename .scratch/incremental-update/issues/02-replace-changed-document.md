# 02: 替換變更的文件：先匯入新版本，成功後刪舊版本

**What to build:** 同一個路徑上的文件內容改了，使用者再次 `ingest` 後，知識庫裡只剩新版本，查詢不會再檢索到舊內容；報告記「替換」。新版本匯入失敗時，寫了一半的新內容被刪掉，舊版本留著（spec「匯入端：對照表」的規則 2、「匯入端：替換與移除」）。

**Blocked by:** 01

**Status:** resolved

- [x] 對照表記的 ID 不等於這次的 ID：先匯入新版本，成功後刪除舊版本（保留 LLM 抽取快取），更新對照表；報告記「替換」。
- [x] 替換後查詢只看得到新版本的內容（從假 server 收到的 context 觀察）。
- [x] 新版本匯入失敗（含圖、表、公式描述失敗而文字已寫入）：刪掉新版本已寫進知識庫的部分，不為它留下失敗紀錄（整批結束後補記失敗狀態的流程要排除它）；舊版本與對照表不變；報告記成失敗並說明舊版本仍在，結束碼 1。
- [x] 清除寫了一半的部分本身失敗：報告寫出兩個文件 ID 與原因，結束碼 1。
- [x] 替換失敗後再次 ingest 且成功：記「替換」。
- [x] 刪除舊版本失敗：報告記成失敗，訊息寫出新舊兩個文件 ID，結束碼 1。
- [x] 替換中斷後（新版本已完整匯入、舊版本沒刪、對照表仍指向舊 ID）再次 ingest：補刪舊 ID，記「替換」。
- [x] 對照表記的 ID 已不在知識庫：照一般匯入新版本，不刪任何東西，記「新增」。
- [x] 刪舊版本前先查對照表：還有別的路徑指向同一個 ID 時，不刪知識庫的內容，只改寫這個路徑的那一筆。
- [x] 新文件（不是替換）匯入失敗時維持現行行為（保留失敗紀錄，下次清掉再重匯）。
- [x] 匯入單一檔案時也會替換。CLI 與 Python API 行為相同；現有測試全綠。

## Comments

- 替換實作在 `pipeline._ingest_one`；刪除寫成 `_remove_version(rag, known, key, doc_id)`：先查對照表有沒有別的路徑指向同一個 ID，沒有才 `adelete_by_doc_id(..., delete_llm_cache=False)`；它不改對照表，ticket 04 的 `--prune` 可以直接重用。報告多了「替換」（`IngestReport.outcome == "replaced"`、`IngestSummary.replaced`、CLI 的「替換 N 份」）。這張取代 ticket 01 的 ASSUMPTION 1（路徑相同、ID 不同照一般匯入）。
- 新增 `IngestReport.mark_failed`：只有新文件的描述或寫入失敗會設，整批結束後的 `_mark_swallowed_failures` 改成只處理它；替換失敗的新版本已被刪掉，不會被補記失敗紀錄。
- 測試在 `tests/test_replace.py`（CLI 與 Python API）。假 mineru 新增 `% fake version: <文字>` 標記行，讓同一個路徑能造出內容不同的新版本。
- ASSUMPTION：兩個刪除失敗的分支用新夾具 `tests/delete_failure/sitecustomize.py` 注入（`FAIL_NTH_DELETE=N` 讓 LightRAG 第 N 次 `adelete_by_doc_id` 回 `fail`，做法同 `wall_clock_fast`），不是 spec 列的「假 server 注入」。理由：刪除階段只讀寫本機儲存，重建圖譜時送給假 server 的 embedding 文字與匯入時相同，server 無法只讓刪除階段出錯。
- ASSUMPTION：「記的舊 ID 已不在知識庫」以 `doc_status.get_by_id(old_id) is None` 判斷；舊版本在文件狀態裡但不是 processed（例如 failed）時走替換，照常刪除。
- ASSUMPTION：刪除回報 `not_found` 視為成功（目標狀態已達成，例如補刪時舊版本已被刪掉）。
- ASSUMPTION：解析階段失敗（MinerU 失敗）的錯誤訊息不加「舊版本仍在」。這時沒有新文件 ID，也沒有寫入任何東西，舊版本與對照表都沒動。
- ASSUMPTION：`description_error` 的彙總訊息改成「新文件記成失敗；替換的文件已清掉新版本、舊版本仍在」，因為替換失敗的文件沒有失敗紀錄。
- 範圍外：替換後同一題的答案仍會命中 LightRAG 的答案快取（ticket 05），所以 `tests/test_replace.py` 每次查詢用不同題目。
