# 03: 下載權益子頁並轉成 `.docx`

**What to build:** 下載腳本也會從信用卡權益頁找出所有權益說明子頁，例如保險、道路救援、不回饋項目，用 LibreOffice 把存下的 HTML 轉成 `.docx`，放進權益資料夾。這樣知識庫會用到 Word 的解析路徑。

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] 腳本從權益頁取出子頁連結並去除重複，2026-10-30 是 46 個。
- [ ] 每個子頁的原始 HTML 照 02 的方式保存，用 02 的方式取出主內容區（`id="centercontainer"`）存成本機 HTML，再用 PATH 上的 LibreOffice（依序找 `libreoffice`、`soffice`）轉成 `.docx`。本地檔名整批唯一。
- [ ] 下載清單記錄這一類的每一份文件，欄位與 02 相同。
- [ ] 找不到 LibreOffice 或轉檔失敗時，那一頁記為失敗，其他頁照常完成，最後以非零碼結束。
- [ ] 假 LibreOffice 夾具擴充成也接受轉成 docx。對其他參數維持嚴格檢查，主檔名以 `broken` 開頭時照舊模擬失敗。
- [ ] 以子行程測試上述行為；匯入用的假 LibreOffice 路徑（轉 PDF）的既有測試仍然全綠。
- [ ] 下載腳本的測試、主測試套件與既有下載腳本的測試都全綠。
