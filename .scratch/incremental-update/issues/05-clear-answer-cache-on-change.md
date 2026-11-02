# 05: 知識庫有改動時清掉答案快取

**What to build:** 每份文件處理完，只要那份文件的處理對知識庫做了寫入或刪除（不論最後成功或失敗，含替換失敗後的清除與 prune 的刪除），就立刻清掉 LLM 快取裡所有查詢答案的項目，保留查詢關鍵字與匯入用的抽取快取；之後同一題會用新的知識庫重新回答。知識庫沒有改動的文件不觸發。報告寫出這次清掉的筆數（spec「匯入端：答案快取」，grill Q4、Q25）。

**Blocked by:** 01、02、04

**Status:** resolved

- [x] 新增、替換、prune 刪除之後：先前問過的題目再問一次，會重新呼叫假 LLM 生成答案（從假 server 的請求紀錄觀察）。
- [x] 替換失敗（寫了一半的內容已清除）與新文件失敗之後：同樣清掉答案快取。判準照 spec「詞彙」：解析完成、開始寫進 LightRAG 之後失敗的算有改動；解析階段就失敗的（例如假 mineru 回錯誤）不清。
- [x] 沒變、共用版本的新增或刪除（知識庫沒有改動）：同一題再問仍命中答案快取。
- [x] 清除在每份文件處理完時發生，不等整批結束：用外部看得到的方式驗證（例如一批兩份，第一份處理完、第二份處理中時讓假 server 停住並結束子行程，再問先前的題目會重新生成答案）。
- [x] 關鍵字快取保留：同一題再問時，不重新呼叫抽關鍵字。
- [x] 抽取快取保留：prune 刪掉一份文件後再匯入同一份，不重新呼叫實體抽取（從假 server 的請求紀錄觀察）。
- [x] 只清查詢答案的項目，不用 LightRAG 清全部快取的功能。
- [x] 報告寫出清掉的筆數；CLI 與 Python API 行為相同。
- [x] README 寫明這個行為；現有測試全綠。

## Comments

- 實作：`pipeline._clear_answer_cache(rag)` 列出 `rag.lightrag.llm_response_cache` 裡 `cache_type == "query"` 的 key，用公開的 `delete` 刪掉、`index_done_callback` 立刻寫檔，回傳筆數。不用 `aclear_cache`（它 drop 整個快取）。
- 「有改動」由 `_KnowledgeBaseChange` 在呼叫之前標記，每份文件一個：`_ingest_one` 在 `process_document_complete` 之前、清先前失敗舊紀錄的 `adelete_by_doc_id` 之前標記；`_remove_version` 在查過共用版本、要呼叫 `adelete_by_doc_id` 之前標記（所以替換的補刪、替換的舊版本刪除、prune 刪除都涵蓋；別的路徑還用同一個版本而沒有刪除時不標記）。`_ingest` 的每份文件迴圈與 `_prune_missing` 的每份文件迴圈在該份處理完（成功或失敗）後，標記了就清，筆數累計到 `IngestSummary.answer_cache_cleared`。清除在記對照表之前，所以對照表寫不進去時答案快取也已經清過。
- 公開介面：`IngestSummary.answer_cache_cleared`；CLI 報告多一行 `清掉答案快取 N 筆`（新增、替換、沒變、來源已不在、已刪除之後，每次都印）。
- 測試在 `tests/test_answer_cache.py`（CLI 與 Python API）。答案快取是否被清，從假 server 的請求紀錄看同一題再問有沒有送出答案請求與關鍵字請求。「每份文件處理完就清」：資料夾裡 `a.pdf` 被替換、`stall-b.pdf` 在假 mineru 解析時睡著（`tests/fake_mineru.py` 新增 `stall` 開頭的檔名，建立 `FAKE_MINERU_STALLED` 指定的旗標檔後睡 10 分鐘），測試等到旗標檔出現就結束整個行程群組，再問先前的題目會重新生成答案。`tests/test_python_api.py` 的 driver 新增 `cache:<檔名>` 步驟。抽取快取保留由 `test_the_extraction_cache_survives_the_clearing` 與 `tests/test_prune.py` 既有的同類測試涵蓋。
- ASSUMPTION：清除筆數寫進報告（spec 已標 ASSUMPTION）；每種模式的每個問題各算一筆（同一題用 mix 與 naive 各問一次是 2 筆）。
- ASSUMPTION：呼叫過刪除就算有改動，即使刪除回報失敗（失敗不保證儲存沒被動到）；spec「詞彙」的「呼叫過刪除」也這樣寫。
- ASSUMPTION：列舉查詢答案項目用 JsonKVStorage 的私有欄位 `_data` 與 `_storage_lock`（LightRAG 1.4.16 的 BaseKVStorage 沒有列出所有 key 的公開方法）；以項目的 `cache_type` 欄位判斷，不解析 key 字串。換成別種 KV 儲存後端時這段要重寫（已寫在 pipeline 模組說明的已知極限）。
- ASSUMPTION：清除失敗（例如寫檔失敗）不吞掉，例外往上拋，整個 ingest 失敗。
- 測試夾具踩到的點：兩個資料夾的同名檔案要用 `textonly` 開頭才會得到相同的文件 ID（不然圖片路徑不同，ID 就不同），沒用的話「共用版本」的測試實際上測的是兩份不同的文件。
- 範圍外：`tests/test_prune.py` 的「prune 只移除這個路徑」測試用 `shared.pdf`（沒有 `textonly` 前綴），依本張測試一開始的實測（同樣的建檔方式，新路徑被當成真的新文件、清掉了答案快取），兩個路徑應該得到不同的文件 ID，沒有真的測到共用版本（這是推論，沒有另外驗證；它的斷言在兩種情況下都成立）；`tests/test_answer_cache.py` 有用 `textonly` 的版本。README 沒有 ticket 03（用檔名遷移）的說明，原本那句「用檔名遷移……還沒做」已隨這張 ticket 一起拿掉。
