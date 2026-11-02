# 03: richart.tw 卡片頁與優惠細則

**What to build:** 下載腳本可以連 richart.tw，下載 Richart 的簽帳金融卡頁與信用卡頁，以及這兩頁連到的所有優惠細則頁（`/discount/discount-details?discount=<id>`），讓 Richart 卡（信用卡）與 Richart 簽帳金融卡各自的回饋細則都在知識庫裡。這兩種卡片最容易被客戶搞混，兩邊都要有資料才能對照（spec「收錄範圍」「下載腳本」，grill Q11、Q15）。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 網域允許清單加上 `richart.tw`；其他網域仍然拒絕；請求間隔與轉址規則和現有的相同。
- [ ] 下載簽帳金融卡頁、信用卡頁；從這兩頁收集優惠細則頁的連結，同一個細則 id 只下載一次。
- [ ] richart.tw 頁面的主內容區由實作者從 HTML 判斷，寫進模組說明並標 ASSUMPTION；取主內容區後照 01 的方式轉檔（頁面內嵌的 base64 圖片不影響文字內容）。
- [ ] 本地名稱有 `debit_` 前綴（信用卡頁也是這個類別，前綴代表「這次金融卡 spec 收的」，ASSUMPTION）；下載清單照現有欄位記錄。
- [ ] 更新模式：內容沒變不重寫、細則頁從兩頁的連結中消失時搬到 `_meta/removed/<日期>/`；兩頁任一頁沒有成功取得時，這次不判斷細則下架。
- [ ] 測試沿用下載腳本子行程＋假 HTTP server、假 Chrome 的縫，涵蓋網域限制、細則去重、細則下架；現有測試全綠。
- [ ] 模組說明與 README 第 2 節同步。
