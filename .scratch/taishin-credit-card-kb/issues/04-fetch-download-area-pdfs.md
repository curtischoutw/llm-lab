# 04: 下載文件下載區的 PDF

**What to build:** 下載腳本也會翻完信用卡文件下載區的每一頁，把所有 PDF 原樣放進下載資料夾。約定條款、保險證、費用表、機場接送規則、申請書與授權書都會進入知識庫。

**Blocked by:** 03

**Status:** resolved

- [x] 從文件下載頁的第 1 頁開始往後翻，直到某一頁沒有新的 PDF 連結為止；PDF 網址去除重複。
- [x] PDF 不轉檔，原樣存檔。本地檔名整批唯一，下載清單記錄每一份（沒有原始 HTML 的 SHA-256 欄位值）。
- [x] 某一份 PDF 下載失敗時，其他照常完成，最後以非零碼結束；下載頁本身失敗時，以非零碼結束並指出是哪一個列表。
- [x] 以子行程測試翻頁、去除重複與失敗處理。
- [x] 下載腳本的測試、主測試套件與既有下載腳本的測試都全綠。

## 實作結果（2026-10-30）

做了什麼：
- `scripts/fetch_taishin.py`：新增「下載」類別（`DOWNLOADS`，資料夾 `DIR/downloads/`，本地檔名 `download_<檔名>.pdf`）。從 `/TSB/personal/common/download/index.html?nav1=credit&nav2=file-download&page=N` 的第 1 頁往後翻，某一頁沒有新的 PDF 連結就停（官網超過最後一頁時重複最後一頁，所以目前 2 頁會發 3 個請求）；只收和列表頁同一個網域、路徑以 `.pdf` 結尾的連結，補上網域後去重；PDF 不轉檔，確認開頭是 `%PDF-` 後原樣存檔（先寫暫時檔再換名），清單 `html_sha256` 為空字串。
- 沒有複製平行的邏輯：`Category` 新增 `collect`（怎麼從列表頁找出文件網址）與 `produce`（怎麼把一份文件寫成檔案）兩個函式欄位，另有 `Run`（資料根目錄、網域前綴、發請求的物件、轉檔工具）。卡片與權益改用 `collect_from_one_page` 與 `web_page_producer`；清單、略過、失敗處理、請求間隔、列表失敗處理（`fetch_document`、`main`）三個類別共用。原本的 `convert` 欄位併進 `web_page_producer`。
- 本地檔名：前綴 `download_` 讓 `-_11407.pdf` 變成 `download_-_11407.pdf`（不以 `-` 開頭）；字母、數字、底線、`.`、`-` 以外的字元換成底線；同類別內兩個網址組出同一個檔名（不分大小寫）時，兩者都加上完整網址 SHA-256 的前 8 碼。路徑中 ASCII 以外的字元先做百分比編碼才送出請求。
- `scripts/test_fetch_taishin.py`：假 server 新增 `fallback`，文件下載頁用它模擬超過最後一頁重複最後一頁；預設的下載頁是只有第 1 頁、沒有 PDF；新增 14 個測試（61 個全部）；更新 7 個既有測試的請求清單與數量（每次執行多請求 1 個下載頁）。沒有對官網發請求。

紅燈時的輸出：
- 第一個測試（翻頁、停止條件、原樣存檔，腳本尚未實作）：`AssertionError: Lists differ: [] != ['/TSB/personal/common/download/index.html?nav1=credit&nav2=file-download&page=1', ...]`，`FAILED (failures=1)`。實作後通過。
- 實作類別後，既有測試出現 7 個失敗，都是腳本多請求 1 個下載頁造成的請求清單與數量差 1（預期中的行為改變），期望值已更新。
- 檔名含空白與中文的測試：實作初版（`local_name` 沒有百分比解碼）時 `FileNotFoundError: .../download_費用_表.pdf`，加上 `unquote` 後通過。
- 其餘測試（去重、檔名唯一、清單、失敗處理、翻頁上限、再次執行、請求間隔）在實作後才寫，寫完就通過。為了確認它們會變紅，暫時做了 6 個變異，都已還原：
  - 拿掉 `%PDF-` 檢查：2 個失敗；
  - 停止條件改成「頁面沒有任何連結」而不是「沒有新連結」：10 個失敗，都因為每一頁都重複最後一頁，翻到上限 20 頁；
  - 拿掉同網域檢查：9 個失敗（外部網站的 PDF 被下載、失敗）；
  - 拿掉檔名衝突的網址雜湊：1 個失敗；
  - 檔名不做百分比解碼：1 個失敗；
  - 不對路徑做百分比編碼：1 個失敗（`InvalidURL`）。

最後一次測試輸出：
- `scripts/test_fetch_taishin.py`：`Ran 61 tests in 47.761s`，`OK`
- 主測試套件：`Ran 116 tests in 381.491s`，`OK`
- `scripts/test_fetch_documents.py` 與 `scripts/test_fetch_papers.py`：`Ran 25 tests in 12.532s`，`OK`

沒做到或有疑慮：
- 沒有對真的台新官網驗證。下載頁的結構只依官網結構筆記第 4 節做假頁面；真實的 19 個 PDF 與 2 頁留給 ticket 06 的實機下載驗證。
- 不檢查 PDF 是否完整或能開啟，只看開頭。

ASSUMPTION：
- 翻頁上限 `DOWNLOAD_MAX_PAGES = 20`（`scripts/fetch_taishin.py:107`；目前實際 2 頁）。翻滿上限仍有新的 PDF 時，視為下載頁失敗（非零碼、指出「文件下載」），那一類不下載任何 PDF，不是無限翻頁，也不是下載已收集的部分。
- 下載頁任何一頁失敗（HTTP、網路、不是 UTF-8），同樣視為整個列表失敗，已翻過的頁面收集到的 PDF 不下載（沿用 02、03 的「列表頁失敗，那一類沒有任何網址」；`scripts/fetch_taishin.py:514`）。
- PDF 存檔前只確認內容以 `%PDF-` 開頭，不是的話那一份記為失敗、不存檔（`scripts/fetch_taishin.py:585`）。
- 資料夾名 `downloads`、清單類別名「下載」、列表名稱「文件下載」（`scripts/fetch_taishin.py:640`）；spec 沒有指定資料夾名。
- 只收和下載頁同一個網域的 PDF 連結（`scripts/fetch_taishin.py:509`）；官網筆記中的 19 個都是同網域的相對路徑。
- 找到的 PDF 數不是 19 時只印出實際數量，不中止（與卡片、權益相同）。
