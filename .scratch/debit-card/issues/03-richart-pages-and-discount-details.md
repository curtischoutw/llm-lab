# 03: richart.tw 卡片頁與優惠細則

**What to build:** 下載腳本可以連 richart.tw，下載 Richart 的簽帳金融卡頁與信用卡頁，以及這兩頁連到的所有優惠細則頁（`/discount/discount-details?discount=<id>`），讓 Richart 卡（信用卡）與 Richart 簽帳金融卡各自的回饋細則都在知識庫裡。這兩種卡片最容易被客戶搞混，兩邊都要有資料才能對照（spec「收錄範圍」「下載腳本」，grill Q11、Q15）。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 新增第 4 個網域前綴給 `richart.tw`，環境變數 `TAISHIN_RICHART_BASE` 可改指向本機假 server；頁面上指向其他網域的連結略過（不下載、不算失敗）；請求間隔與轉址規則和現有的相同。
- [ ] 下載簽帳金融卡頁、信用卡頁，存到 `richart/`，名稱 `richart_debit-card`、`richart_credit-card`。
- [ ] 從這兩頁收集 `/discount/discount-details?discount=<id>` 的連結（新寫收集方式，現有的連結收集會丟掉 query），同一個 id 只下載一次，存到 `richart_discounts/`，名稱 `richart_discount_<id>`；細則清單增減時，既有細則的檔名不變。
- [ ] richart.tw 頁面的主內容區由實作者從 HTML 判斷，寫進模組說明並標 ASSUMPTION；取主內容區後照 01 的方式轉檔（頁面內嵌的 base64 圖片不影響文字內容）。
- [ ] 下載清單照現有欄位記錄。
- [ ] 更新模式：內容沒變不重寫、細則頁從兩頁的連結中消失時搬到 `_meta/removed/<日期>/`；兩頁任一頁沒有成功取得，或兩頁都成功但解析出 0 則而本地有細則時，這次不判斷細則下架。卡片頁沒有下架判斷，取不到時本地檔案不動。
- [ ] 測試沿用下載腳本子行程＋假 HTTP server、假 Chrome 的縫，涵蓋 `TAISHIN_RICHART_BASE`、外部網域略過、細則用 id 命名與去重、細則下架與兩種不判斷的條件；現有測試全綠。
- [ ] 模組說明與 README 第 2 節同步。
