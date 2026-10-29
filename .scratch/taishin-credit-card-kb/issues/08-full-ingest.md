# 08: 全量匯入

**What to build:** 把所有下載到的文件匯入主知識庫，並記錄完整的實測數據。全量匯入要跑好幾個小時，可以和寫題目檔同時進行。

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] 照 README 啟動兩個 MLX server，以 zsh 執行 watchdog（門檻 22 GB），smoke test 三項 PASS。
- [ ] 依類別逐一匯入：卡片、權益、下載、活動、活動圖片。試匯入過的 7 份應該被略過；原始 HTML 與下載清單不會被匯入。
- [ ] 所有文件匯入成功；有失敗時記下文件名稱與原因並回報。
- [ ] 記錄每份文件的耗時、Office 轉檔時間、總時間、wired 記憶體峰值、匯入後圖譜的實體與關係數。
- [ ] 輸出與 log 存在 `output/` 底下新的資料夾；驗證完關閉 server 與 watchdog。
