# 03: richart.tw 卡片頁與優惠細則

**What to build:** 下載腳本可以連 richart.tw，下載 Richart 的簽帳金融卡頁與信用卡頁，以及這兩頁連到的所有優惠細則頁（`/discount/discount-details?discount=<id>`），讓 Richart 卡（信用卡）與 Richart 簽帳金融卡各自的回饋細則都在知識庫裡。這兩種卡片最容易被客戶搞混，兩邊都要有資料才能對照（spec「收錄範圍」「下載腳本」，grill Q11、Q15）。

**Blocked by:** 01

**Status:** resolved

- [x] 新增第 4 個網域前綴給 `richart.tw`，環境變數 `TAISHIN_RICHART_BASE` 可改指向本機假 server；頁面上指向其他網域的連結略過（不下載、不算失敗）；請求間隔與轉址規則和現有的相同。
- [x] 下載簽帳金融卡頁、信用卡頁，存到 `richart/`，名稱 `richart_debit-card`、`richart_credit-card`。
- [x] 從這兩頁收集 `/discount/discount-details?discount=<id>` 的連結（新寫收集方式，現有的連結收集會丟掉 query），同一個 id 只下載一次，存到 `richart_discounts/`，名稱 `richart_discount_<id>`；細則清單增減時，既有細則的檔名不變。
- [x] richart.tw 頁面的主內容區由實作者從 HTML 判斷，寫進模組說明並標 ASSUMPTION；取主內容區後照 01 的方式轉檔（頁面內嵌的 base64 圖片不影響文字內容）。
- [x] 下載清單照現有欄位記錄。
- [x] 更新模式：內容沒變不重寫、細則頁從兩頁的連結中消失時搬到 `_meta/removed/<日期>/`；兩頁任一頁沒有成功取得，或兩頁都成功但解析出 0 則而本地有細則時，這次不判斷細則下架。卡片頁沒有下架判斷，取不到時本地檔案不動。
- [x] 測試沿用下載腳本子行程＋假 HTTP server、假 Chrome 的縫，涵蓋 `TAISHIN_RICHART_BASE`、外部網域略過、細則用 id 命名與去重、細則下架與兩種不判斷的條件；現有測試全綠。
- [x] 模組說明與 README 第 2 節同步。

## 實作結果（2026-11-03）

**做了什麼**

- `scripts/fetch_taishin.py`：新增第 4 個網域前綴 `RICHART_PREFIX`（`https://richart.tw`），環境變數 `TAISHIN_RICHART_BASE`，`Run.richart`、`Run.base("richart")`。請求間隔與轉址規則沿用同一個 `Fetcher`。
- 新類別「Richart 卡片頁」（`RICHART_CARDS`）：寫死的兩個網址（`collect_richart_cards`，不發請求），資料夾 `richart/`，名稱 `richart_debit-card`、`richart_credit-card`，PDF，取 `id="main-container"` 後走 01 的 `web_page_producer`／`web_page_refresher`。不在 `REMOVAL_CATEGORIES`：取不到時記失敗，本地文件與存檔 HTML 不動。
- 新類別「Richart 優惠細則」（`RICHART_DISCOUNTS`）：`collect_richart_discounts` 對兩個卡片頁各請求一次，`find_discount_links` 收 `discount-details?discount=<數字>` 的連結（不用會丟掉 query 的 `find_page_links`），只留 `discount` 一個 query、去重；網域和 richart 前綴不同的連結略過。資料夾 `richart_discounts/`，名稱 `richart_discount_<id>`。`Category` 新增 `match_query: bool = False`，True 時 `link_pattern` 比對「路徑?query」，所以名稱直接取 id，不會有網址雜湊後綴。
- 更新模式：細則在 `REMOVAL_CATEGORIES`。任一卡片頁取不到時，失敗紀錄放進 01 加的 `Run.collect_failures`，另一頁的細則照常處理、這次不判斷下架；兩頁都成功但 0 則而本地有細則時，由 `main` 既有的 0 筆保護擋下。
- `scripts/test_fetch_taishin.py`：新增 23 個測試（`RichartCardPageTests` 9、`RichartDiscountTests` 6、`RichartDiscountUpdateModeTests` 8）。richart.tw 用獨立的假 server（`self.richart_server`，`run_script` 一律設 `TAISHIN_RICHART_BASE`），`setUp` 預設登記兩個沒有細則連結的卡片頁（`serve_richart([], [])`），所以每個既有測試都會多下載這兩份文件。
- 既有測試改了 27 個（subTest 展開後 31 個失敗），都只改預期值：檔案清單加 `RICHART_DEFAULT_FILES`（6 處：`CardPageTests`、`DebitCardPageTests`、`DebitCardNamingTests`、`RightsPageTests`、`OfferListTests`、`OfferPeriodTests`）；下載清單的檔名或筆數加兩份 richart 文件（`DownloadAreaManifestTests`、`ManifestTests`、`RightsManifestTests`、`OverviewTests` 2 個、`RightsPageTests` 2 個、`OfferPeriodTests.serve_one_activity`、`UrlHandlingTests` 3 個、`UpdateModeRemovedFromListTests`）；`DownloadAreaFailureTests`、`LibreOfficeProfileTests`、`RightsAttachmentTests` 的檔案清單加 richart 檔；`FailureTests.assert_failed_page_is_reported` 加 `also_failed`（Chrome 不存在時 richart 兩頁也失敗）；`RerunTests` 的結果清單多兩個「已存在略過」；`DownloadAreaRerunTests` 對 richart 文件預期有 `html_sha256`（網頁類）。`self.server`（官網）的請求清單與數量斷言一處都沒改，因為 richart.tw 的請求不經過它。另在 `RequestPolicyTests` 的兩個「送出請求前被擋下」測試加了 richart server 也沒收到請求的斷言。
- 模組說明（兩個檔）與 README 第 2 節同步。
- 合併 `integration/debit-card`（ticket 02 已併入）時，`scripts/fetch_taishin.py`、`scripts/test_fetch_taishin.py`、README 各有衝突，兩邊的類別都保留：`CATEGORIES` 順序是 …、金融卡卡片頁、金融卡約定條款 PDF、金融卡說明頁、Richart 卡片頁、Richart 優惠細則；`REMOVAL_CATEGORIES` 加上約定條款 PDF 與 Richart 優惠細則。測試的 `setUp` 同時登記約定條款頁、7 個說明頁（02）與 richart 兩個卡片頁（03，在獨立的假 server，所以不進 `DEBIT_DEFAULT_REQUESTS`，那份請求清單只算 `self.server`）。02 把清單斷言改成「依類別篩選」的地方照 02 的版本；檔案清單與依檔名排序的斷言同時加 `DEBIT_INFO_FILES`／`DEBIT_INFO_DOCUMENTS` 與 `RICHART_DEFAULT_FILES`／`RICHART_DEFAULT_DOCUMENTS`。`assert_failed_page_is_reported` 的 `also_failed` 參數在 02 改寫「Chrome 不存在」測試後沒有呼叫端，已移除；該測試的預期失敗清單加上兩份 richart 文件。合併後第一次完整執行有 2 個失敗（`DebitInfoTests` 的兩個測試列出 `_meta/html`、`_meta/print` 的全部檔案，沒有算進 richart 的 2 份），改預期值後單獨重跑 `DebitInfoTests` 6 個全綠，再完整執行一次。

**紅燈輸出**

第一個測試（`RichartCardPageTests`，腳本還沒有 richart 類別時）：

```
AssertionError: Lists differ: ['_meta/manifest.jsonl'] != ['_meta/html/richart_credit-card.html', ... 'richart/richart_debit-card.pdf']
Ran 1 test in 1.564s
FAILED (failures=1)
```

細則的第一個測試（`RichartDiscountTests`，只有卡片頁類別時）：

```
FileNotFoundError: [Errno 2] No such file or directory: '.../taishin/richart_discounts'
Ran 1 test in 1.553s
FAILED (errors=1)
```

其餘新測試是實作完成後才補的（沒有逐個先看紅燈）。補驗證的方式是對腳本做 4 種破壞，確認對應測試會變紅：

| 破壞 | 變紅的測試 |
|---|---|
| 細則不在 `REMOVAL_CATEGORIES` | `RichartDiscountUpdateModeTests` 3 個（下架、卡片頁取不到時的新細則與不搬、0 則保護） |
| `collect_richart_discounts` 不登記 `run.collect_failures` | `RichartDiscountUpdateModeTests` 3 個（兩個單頁失敗、卡片頁取不到仍下載新細則） |
| 不檢查連結網域是否和 richart 前綴相同 | `test_links_to_other_domains_are_skipped_…`（1 個；外部網域的細則連結被請求而失敗） |
| `match_query=False` | `test_discounts_linked_from_either_page_…`（1 個；腳本在取名時 assert 失敗） |

**最後一次測試輸出**

- 合併前（只有 ticket 01 的 integration）：下載腳本三個測試檔（`scripts/test_fetch_papers.py scripts/test_fetch_documents.py scripts/test_fetch_taishin.py`）`Ran 264 tests in 591.829s`，`OK`（原 241 個加 23 個新測試）。
- 合併 ticket 02 之後：同三個測試檔 `Ran 289 tests in 792.990s`，`OK`。合併後第一次執行是 `Ran 289 tests in 795.001s`、`FAILED (failures=2)`，原因見上面的合併說明，改預期值後第二次全綠。
- 這張沒有動 `rag_lab`，主套件沒有跑。

**沒做到或有疑慮的地方**

- 沒有對真的 richart.tw 請求，頁面結構只用 2026-11-02 盤點的三份 HTML 檢查過：`id="main-container"` 各 1 個，導覽列與頁尾在它外面。
- 信用卡頁的「可每日切換方案」彈窗（`id="modalSwitchPlans"`，各方案的適用商店清單，約 2,100 字，共 7 段）在 `main-container` 外面。這些商店清單在盤點的 HTML 裡只出現在這個彈窗，不在任何細則頁。code-review 修正（2026-11-03，使用者同意）讓卡片頁轉檔和更新模式比對同時取 `main-container` 與 `modalSwitchPlans`（依頁面順序），所以現在在 PDF 裡；沒有這個彈窗的頁（簽帳金融卡頁、細則頁）照常只取 `main-container`。
- 盤點的信用卡頁與簽帳金融卡頁連到同一批 14 個細則 id（277, 278, 350, 353, 355, 357, 358, 359, 380, 385, 386, 387, 391, 399），所以信用卡頁沒有帶來額外的細則；spec 寫的「信用卡頁連到幾則還沒查」答案是：和簽帳金融卡頁相同的 14 則。已知 32 份的估計（spec「收錄範圍」）因此不會再增加。
- 每次執行都對兩個卡片頁多請求一次來收集細則連結（簽帳金融卡頁約 650 KB），沒有和卡片頁類別共用頁面內容。
- 失敗紀錄（細則類別、卡片頁取不到）的檔名是 `richart_discount_from_debit-card`／`richart_discount_from_credit-card`，url 是卡片頁網址；下載失敗時卡片頁類別另有自己的失敗紀錄，同一個卡片頁在清單裡會有兩筆失敗。

**ASSUMPTION**

- richart.tw 的主內容區是 `id="main-container"`（由三份盤點 HTML 判斷）。
- 細則連結以卡片頁整頁的 `<a href>` 收集，不限主內容區內。
- 指向其他網域的細則連結略過，清單沒有紀錄（不像權益附件有「外部網域略過」一行）。
- 細則 id 限數字。
- 絕對網址只有網域和（環境變數替換後的）richart 前綴相同才收，相對路徑照頁面網址解析。
- 兩個卡片頁在「下載」與「收集細則連結」各請求一次，不在類別之間傳遞頁面內容。
