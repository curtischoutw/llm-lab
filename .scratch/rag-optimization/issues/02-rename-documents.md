# 02: 文件改用帶卡片標籤的檔名，產生標頭檔

**What to build:** `scripts/fetch_taishin.py` 改用新檔名格式，並寫一次性遷移腳本改現有檔案、manifest 與 eval 題目的來源；同時從標籤檔產生 rag_lab 用的標頭檔（spec：「改檔名」「chunk 標頭與依標題切塊」）。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `document_filename`（`scripts/fetch_taishin.py:2513`）產生 `<卡別>_<簡短卡名｜多卡｜全部>_<原檔名>`。新抓的文件在下載當下就能產生標籤（用 01 的同一套規則），不用另外跑 01 的腳本。
- [ ] 查明 `fetch_taishin.py` 怎麼對照既有檔案、manifest 與 `_meta/html` 快照（判斷「已存在就略過」「未變」），改完之後增量更新照常運作：對遷移後的資料跑一次不連網的檢查（或測試），確認不會把已存在的文件當成新文件重抓。
- [ ] 遷移腳本：改 `data/taishin_credit_card/` 底下文件的檔名、manifest 的 `filename`、`eval/questions.taishin.jsonl` 的 `source`（含逗號分隔的多個來源）。可以重跑，已經是新檔名的不再改。改之前備份 manifest 與題目檔。
- [ ] 從標籤檔產生標頭檔 `data/taishin_credit_card/_meta/document_headers.json`：key 是新檔名，值是標頭文字。檢查沒有兩份文件的新檔名相同。
- [ ] 測試：`document_filename` 的新格式；遷移腳本重跑不會重複改名。`pytest` 全綠。
- [ ] 回報改名的文件數，以及 `eval/questions.taishin.jsonl` 改了哪幾題的 `source`。
