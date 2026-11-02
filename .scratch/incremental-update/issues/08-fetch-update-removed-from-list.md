# 08: 更新模式：官網列表裡沒有的，搬到 `DIR/_meta/removed/<日期>/`

**What to build:** 更新模式下，卡片、權益子頁、下載區、活動四個列表類別，這次列表裡沒有、本地有的文件，連同它在 `DIR/_meta/html/`、`DIR/_meta/print/` 的檔案，搬到 `DIR/_meta/removed/<日期>/`（保留原本的相對路徑），清單記「下架」；之後 `ingest` 就看得到它不在了。某個類別的列表頁沒有成功取得時，那個類別這次不搬任何檔案，報告寫明原因（spec「下載腳本：更新模式」的下架判斷與搬移）。

**Blocked by:** 06

**Status:** resolved

- [x] 列表少了一份：文件與它的 `_meta/html`、`_meta/print` 檔案搬到 `DIR/_meta/removed/<日期>/`，文件到 `<類別資料夾>/<檔名>`，原始 HTML 與列印用 HTML 照原本的扁平存放到 `html/<名稱>.html`、`print/<名稱>.html`，清單記「下架」。
- [x] 目的地已有同名檔時，在檔名後加時間，不覆寫（ASSUMPTION，見 spec）。
- [x] 列表頁請求失敗或逾時：那個類別不搬任何檔案，報告寫明類別與原因；其他類別照常。
- [x] 不設下架數量的比例門檻；但列表頁回應成功、解析出 0 筆而本地有這個類別的文件時，當成列表頁沒有成功取得，不搬任何檔案，報告寫明。
- [x] `_meta` 底下的檔案不會被 `ingest` 挑出（確認現有行為：`_meta` 在資料根目錄，ingest 不遞迴）。
- [x] 測試沿用假 HTTP server；現有測試全綠。

## Comments

### 實作結果（2026-11-02）

更新模式下，卡片、權益、下載、活動四個類別的列表裡沒有、本地有的文件，連同 `_meta/html`、`_meta/print` 的檔案搬到 `DIR/_meta/removed/<日期>/`，清單記「下架」；列表沒有成功取得（含成功但解析出 0 筆而本地有文件）時該類別不搬，stderr 寫明並以結束碼 1 結束。

- `scripts/fetch_taishin.py`：`RESULT_REMOVED`、`REMOVAL_CATEGORIES`、`local_documents`／`free_destination`／`move_removed`／`remove_missing`、`document_filename`（從 `fetch_document` 抽出共用）；模組說明與 README 同步。
- `scripts/test_fetch_taishin.py`：`UpdateModeRemovedFromListTests`（9 個）。縫沿用下載腳本子行程＋假 HTTP server。
- `ingest` 不挑 `_meta`：`rag_lab/__main__.py` 展開資料夾時只取第一層的檔案（`iterdir` 加 `is_file`），`_meta` 是資料根目錄底下的資料夾；`tests/test_pipeline.py` 已有子資料夾不遞迴的測試，沒有另外新增。

ASSUMPTION：

- 下架判斷：類別資料夾第一層的檔名不在這次列表算出的檔名集合內。同類別兩個網址組出同名而加網址雜湊後綴時，列表增減會改變後綴，舊檔名會被當成下架、新檔名當成新增。
- 目的地同名時，在副檔名前加 `_<HHMMSS 加微秒>`。
- 「下架」清單紀錄的網址是空字串（本地只有檔案；不去翻上一次的清單）；下載日期取原檔修改日期，sha256、html_sha256、period 取搬走的文件與存檔 HTML。
- 搬移時的檔案系統錯誤，那一份記「失敗」（結束碼 1），已搬走的部分不還原。
- 「解析出 0 筆」的判斷在 `collect` 之後：回傳 0 筆網址、且類別資料夾有檔案；翻頁失敗等 `collect` 拋出的錯誤走原本的列表失敗流程。兩者都不設定 `Run.found`，所以依賴它的類別（活動圖片）行為與列表失敗相同。
- 紅燈說明：第一個測試先紅後綠；其餘 8 個測試在同一輪實作後才執行，第一次就綠。事後把 0 筆的判斷關掉做變異檢查，兩個相關測試轉紅，還原後全綠。

範圍外發現：

- 無新的。權益附件、活動圖片的下架與活動過期仍待 09、10。
