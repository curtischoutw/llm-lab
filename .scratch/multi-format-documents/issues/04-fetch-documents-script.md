# 04: 下載腳本

**What to build:** 使用者用一個指令下載 spec「選定的文件」裡的 11 份公開文件：6 份放進 `data/documents/`（主知識庫用），5 份放進 `data/format_check/`（格式驗證知識庫用）。每份都核對 SHA-256，任何機器重建時拿到的都是同一份內容。可以只下載其中一組。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [ ] 和既有的論文下載腳本同類，只用標準函式庫；腳本裡寫死清單，每筆包含 URL、預期的 SHA-256、檔名、格式、授權與出處、目標資料夾。清單內容照 spec 的兩張表。
- [ ] SHA-256 由實作者實際下載每個檔案算出，寫進清單；實作結果記錄下載日期。
- [ ] 先驗證參數，再發出網路請求；可以只下載一組（主知識庫或格式驗證）。
- [ ] 下載先寫成 `.part`，核對 SHA-256 後才改名。雜湊不符時，以非零碼結束並指出是哪一份，`.part` 不改名成正式檔案。
- [ ] 已存在且雜湊正確的檔案略過。已存在但雜湊不符時，以非零碼結束並指出檔名，不自動覆蓋。
- [ ] 網路或 HTTP 失敗時，以非零碼結束並指出是哪一份，不略過後繼續。
- [ ] 帶可辨識的 User-Agent；可用環境變數改寫下載位址的前綴，只給測試指向本機假 server 用。
- [ ] 測試對本機假 HTTP server 執行（比照論文下載腳本的測試），涵蓋上面每個行為，以及檔案放進正確的資料夾。先紅後綠，貼出失敗輸出。
- [ ] 實際執行一次腳本，下載全部 11 份到兩個資料夾，貼出輸出；再執行一次，確認全部略過。
- [ ] README：下載新文件的指令與授權說明（只在本地研究使用）。架構文件：新的兩個資料夾、新腳本、新測試。
- [ ] 主測試套件與下載腳本的測試全綠，貼出實際輸出。

## 實作結果（2026-10-28）

- 新增 `scripts/fetch_documents.py`（下載腳本）與 `scripts/test_fetch_documents.py`（17 個測試）。用法：`python3 scripts/fetch_documents.py [--out DIR] [--group {documents,format_check}]`。
- SHA-256 是 2026-10-28 從 `raw.githubusercontent.com` 實際下載 11 個 URL 後以 `hashlib.sha256` 算出，寫進腳本的 `DOCUMENTS`。11 個 URL 全部下載成功，沒有失效的。
- 測試縫：下載腳本子行程對本機假 HTTP server。清單帶真實雜湊、假 server 送不出符合的內容，所以測試用 `python -c` driver 載入腳本、把 `DOCUMENTS` 換成小清單再呼叫 `main`；這是測試唯一碰到腳本內部的地方（`Document` 的欄位名稱）。腳本實際使用的清單另有 3 個測試，對照 spec 的兩張表。
- 先紅後綠，每一輪的失敗輸出：
  - 下載到正確資料夾、User-Agent、輸出檔名（3 個測試）：腳本不存在，`ModuleNotFoundError: No module named 'fetch_documents'`，3 個 FAIL。
  - 雜湊不符：第一版只下載不核對，`AssertionError: 0 != 1 : downloaded documents/a.pptx ... downloaded documents/b.docx ... downloaded format_check/c.xlsx`（預期結束碼 1，而且 b.docx 不該有正式檔案）。
  - 網路失敗（HTTP 404、讀 body 到一半斷線、連不上 server，3 個測試）：stderr 是 Python traceback（`HTTPError: HTTP Error 404`、`IncompleteRead(200 bytes read, 1200 more expected)`、`ConnectionRefusedError`），沒有文件名稱，3 個 FAIL。
  - 略過已存在的檔案：`AssertionError: 8 != 4 : 第二次執行不該發出請求`；既有檔案雜湊不符：`AssertionError: 0 != 1`（腳本直接覆蓋）。
  - `--group`（2 個測試）：`Lists differ: ['documents/a.pptx', 'documents/b.docx', 'format_check/c.xlsx', ...] != ['documents/a.pptx', 'documents/b.docx']`；`--out` 是一般檔案：stderr 是 traceback（`'Traceback' unexpectedly found`）；實際清單對照 spec：`Lists differ: [] != [('documents', 'PPT', ...)]`。
  - 以下測試在寫出時就是綠的，沒有紅燈：未知的 `--group`（argparse 的 `choices` 已經處理）、殘留的 `.part` 會被重新下載取代（本來就會覆寫）、清單的雜湊格式與檔名唯一（清單填入前是在空清單上迴圈，由「清單對照 spec」那個紅燈涵蓋）。
- 實際執行：`python3 scripts/fetch_documents.py --out data`（`data/` 在 gitignore 內），第一次 11 份全部 `downloaded`、結束碼 0；第二次 11 份全部 `exists`、結束碼 0；`git status` 沒有出現下載的檔案。下載後用 `shasum -a 256` 對照，11 份與清單一致。
- 最終測試：主套件 `python -m unittest` 93 個 OK（329.1 s）；`python -m unittest scripts/test_fetch_papers.py scripts/test_fetch_documents.py` 23 個 OK（11.7 s，論文腳本 6 個、文件腳本 17 個）。
- 文件：README 在「下載論文」之後加「下載其他格式的文件」（指令、`--group`、授權表、只在本地研究使用）與測試指令；`docs/architecture.md` 加兩個資料夾、新腳本、新測試。
- ASSUMPTION：
  - 本地檔名：`Experimentations_for_Kg_creation.docx`、`LLM_Comparisons_with_one_pdf.docx`（來源檔名的空白改底線）、`graphrag-auto-tune-diagram.png`、`graphrag-unified-search-app.png`（來源是 `image-1.png`，沒有辨識度）。ticket 05、06 的題目檔 `source` 欄位要用這些名稱。
  - 失敗時刪除 `.part`（雜湊不符、網路失敗都一樣），不保留供檢查。
  - 逐份循序處理，第一份失敗就停止，後面的不再下載。已存在且雜湊不符的檔案也是輪到那一份時才檢查，不先掃過全部。
  - 沒有請求間隔、沒有重試。
  - 授權欄寫成「授權（repo）」，沒有另外的「出處」欄位；出處由 URL 與 repo 名稱表達。
  - URL 指向各 repo 的 `main` 分支，不是固定 commit；來源更換時靠雜湊不符中止。
  - 測試 driver 取代 `DOCUMENTS`，而不是另加一個「改寫清單」的環境變數，避免在正式腳本留下可繞過雜湊清單的入口。
- 沒做到：沒有做「暫時拿掉某段實作確認測試轉紅」的反向檢查，只有上面的先紅後綠。
