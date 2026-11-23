# 02: 文件改用帶卡片標籤的檔名，產生標頭檔

**What to build:** `scripts/fetch_taishin.py` 改用新檔名格式，並寫一次性遷移腳本改現有檔案、manifest 與 eval 題目的來源；同時從標籤檔產生 rag_lab 用的標頭檔（spec：「改檔名」「chunk 標頭與依標題切塊」）。

**Blocked by:** 01

**Status:** resolved（已 merge 進 feat/rag-optimization，ba8c9f8）

- [x] `document_filename`（`scripts/fetch_taishin.py:2513`）產生 `<卡別>_<簡短卡名｜多卡｜全部>_<原檔名>`，所有會被匯入的類別都套用，包含活動圖片（`IMAGES`；`fetch_taishin.py:2092` 起比較新舊 banner 檔名的地方要一起改，其他呼叫點在 2113、2144、2540、2706、2788、2913）。新抓的文件在下載當下就能產生標籤（用 01 的同一套規則），不用另外跑 01 的腳本。
- [x] 查明 `fetch_taishin.py` 怎麼對照既有檔案、manifest 與 `_meta/html`、`_meta/print` 快照（判斷「已存在就略過」「未變」），改完之後增量更新照常運作：對遷移後的資料跑一次不連網的檢查（或測試），確認不會把已存在的文件當成新文件重抓。
- [x] 遷移腳本：改 `data/taishin_credit_card/` 底下文件的檔名、manifest 的 `filename`、`eval/questions.taishin.jsonl` 的 `source`（含逗號分隔的多個來源）。manifest 裡 11 筆沒有實體檔的紀錄照同一規則改，產生不了標籤的保留原檔名並列出。可以重跑，已經是新檔名的不再改。改之前備份 manifest 與題目檔。
- [x] 從標籤檔產生標頭檔 `data/taishin_credit_card/_meta/document_headers.json`：key 是新檔名，值是標頭文字。檢查沒有兩份文件的新檔名相同。
- [x] 測試：`document_filename` 的新格式；遷移腳本重跑不會重複改名。`.venv/bin/python -m unittest` 全綠（README:543；改到 `scripts/fetch_taishin.py` 時加跑 README:549 的下載腳本測試）。
- [x] 回報改名的文件數，以及 `eval/questions.taishin.jsonl` 改了哪幾題的 `source`。

## 實作紀錄

- `document_filename` 不直接算出新檔名：卡片標籤要比對全部類別的頁面（卡名清單來自所有卡片頁，附件與活動圖片沿用連到它的頁面），
  新文件的標籤要到所有類別下載完才算得出來。所以新文件這次執行裡叫原檔名，執行最後由 `scripts/rename_documents.py` 的 `migrate`
  （遷移腳本也是它）依標籤改名；`document_filename` 回傳資料夾裡現有的檔名（已改過名的回新檔名），增量更新因此照常運作。
- `_meta/html`、`_meta/print` 快照不改名：它們的名稱由網址決定，`fetch_taishin.py` 不用文件檔名對照快照（下架搬走時還原成原檔名）。
- `fetch_taishin.py` 新增 `--keep-names`（不改檔名，只下載）；`scripts/test_fetch_taishin.py` 既有案例預設加它，改檔名的案例在 `LabelledFileNameTests`。
- 遷移腳本：`python3 scripts/rename_documents.py --dry-run` 看會改什麼；實際執行要給 `--backup-dir`。
- ASSUMPTION：簡短卡名含空白（「Gogoro Rewards聯名卡」）視為安全；檔名超過 200 位元組時簡短卡名改用「多卡」（目前最長 102 位元組）。
