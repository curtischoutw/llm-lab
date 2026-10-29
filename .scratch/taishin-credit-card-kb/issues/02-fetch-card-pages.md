# 02: 下載卡片頁（tracer bullet）

**What to build:** 使用者執行新的下載腳本，就能從信用卡總覽頁找出所有卡片頁，各自列印成 PDF 放進卡片資料夾，原始 HTML 另存在不會被匯入的位置，並得到一份下載清單。這張也建立整支腳本共用的行為，後續的類別都沿用：請求間隔、User-Agent、失敗處理、再次執行時略過、網址前綴與 Chrome 路徑的替換。

**Blocked by:** 01（新腳本要用 01 合併進 main 的假 LibreOffice 夾具與既有下載腳本的慣例）

**Status:** resolved

- [x] 腳本從總覽頁取出卡片頁連結並去除重複。找到的數量不是 16 時，印出實際數量，但不中止。
- [x] 每張卡從原始 HTML 取出主內容區（`id="centercontainer"`），拿掉 `<script>` 與 `<style>`，包成帶 `<base href>`（指回原網址）與固定列印用 CSS 的本機 HTML，存在不會被匯入的位置，再用 headless Chrome 列印成 PDF，使用暫時的使用者資料夾。找不到主內容區時，那一頁記為失敗，原因寫「找不到主內容區」。做法與實測數字見 spec 的「主內容區與列印前處理」。本地檔名由網址路徑組成，加上類別前綴，整批唯一。
- [x] 每一頁的原始 HTML 保存在不會被匯入的位置。
- [x] 下載清單一行一份文件，記錄網址、類別、本地檔名、格式、下載日期、匯入檔案的 SHA-256、原始 HTML 的 SHA-256、結果（已下載、已存在略過、失敗及原因）。
- [x] 腳本自己發出的每個 HTTP 請求之間至少 2 秒；間隔可以用環境變數調小，只給測試用。請求帶有可辨識的 User-Agent。
- [x] `www` 網域的網址前綴與 Chrome 路徑可以用環境變數替換。找不到 Chrome 時，那一頁記為失敗，訊息指出環境變數名稱。
- [x] 單頁失敗時其他頁照常完成，最後列出所有失敗的頁面並以非零碼結束。總覽頁本身失敗時，以非零碼結束並指出是哪一個列表。
- [x] 再次執行時，已存在的檔案略過並記入清單。
- [x] 只用標準函式庫；檔頭 docstring 寫明：Chrome 透過 `<base href>` 自行載入圖片，這些請求不受間隔控制；直接列印原網址會漏掉收合區與彈窗（spec 的實測數字）。
- [x] 新增假 Chrome 夾具：接受列印成 PDF 的參數，輸入是本機 HTML 檔，寫出小 PDF，並把收到的 HTML 內容一起寫進輸出檔。參數不符時以非零碼結束，並印出收到的參數。
- [x] 以子行程測試：交給 Chrome 的 HTML 含主內容區的文字（包括預設收合的區塊與彈窗），不含官網的 script、樣式表與主內容區以外的文字（例如導覽選單）；沒有主內容區的頁面記為失敗。
- [x] 以子行程測試上述行為：本機假 HTTP server，只看結束碼、輸出、產生的檔案、清單內容與假 server 收到的請求。請求間隔用假 server 記錄的時間檢查。
- [x] 下載腳本的測試、主測試套件與既有下載腳本的測試都全綠。

## 實作結果（2026-10-30）

做了什麼：
- 新增 `scripts/fetch_taishin.py`：從總覽頁取出卡片頁連結（去重），逐頁下載原始 HTML，取出 `id="centercontainer"`、拿掉 `<script>` 與 `<style>`，包成帶 `<base href>` 與固定列印 CSS 的本機 HTML，用 headless Chrome（暫時的使用者資料夾）列印成 PDF。輸出結構：`DIR/cards/*.pdf`（匯入用）、`DIR/_meta/html/`（原始 HTML）、`DIR/_meta/print/`（交給 Chrome 的 HTML）、`DIR/_meta/manifest.jsonl`（下載清單）。預設 `DIR` 是 `data/taishin_credit_card`。
- 共用行為：請求間隔（`TAISHIN_REQUEST_INTERVAL_SEC`，預設 2 秒，從前一個請求結束起算）、User-Agent、單頁失敗後繼續並在最後列出、總覽頁失敗指出列表名稱、再次執行略過已存在的 PDF（不發請求）、`TAISHIN_WWW_BASE` 與 `TAISHIN_CHROME` 環境變數。
- 新增 `tests/fake_chrome.py`（假 Chrome 夾具）與 `scripts/test_fetch_taishin.py`（23 個子行程測試）。
- 以真的 Chrome 對一個本機 HTML 檔（不含官網內容）執行同一組參數，確認參數有效：結束碼 0，產出 12,582 bytes、檔頭 `%PDF-1.4` 的 PDF。沒有對官網發請求。

紅燈時的輸出：
- 第 1 輪（只有 5 個測試，腳本尚未存在）：`Ran 5 tests in 1.117s`、`FAILED (failures=2)`；失敗原因 `can't open file '.../scripts/fetch_taishin.py': [Errno 2] No such file or directory`。另 3 個是假 Chrome 夾具本身的測試，已通過。
- 第 2 輪（加入主內容區與清單測試）：這 4 個測試寫完就通過，因為第 1 輪的實作已經涵蓋。為了確認測試會變紅，暫時拿掉 `<script>`／`<style>` 的移除，`ChromeInputTests` 出現 `AssertionError: 'INNER_SCRIPT_TEXT' unexpectedly found`，還原後通過。
- 第 3 輪（加入失敗處理、再次執行、請求策略）：`Ran 22 tests in 14.401s`、`FAILED (failures=9)`。9 個失敗是總覽頁失敗、五種單頁失敗、兩個再次執行、間隔環境變數無效值；User-Agent、間隔與卡片數量的測試在實作前就已通過。實作後 22 個全部通過，之後補上 `--out` 是一般檔案的測試。

最後一次測試輸出：
- `scripts/test_fetch_taishin.py`：`Ran 23 tests in 14.979s`，`OK`
- 主測試套件：`Ran 116 tests in 394.074s`，`OK`
- `scripts/test_fetch_documents.py` 與 `scripts/test_fetch_papers.py`：`Ran 25 tests in 13.091s`，`OK`

沒做到或有疑慮：
- 沒有對真的台新官網驗證。主內容區的取出只用假頁面測試；真實卡片頁的結構（巢狀 `div`、未關閉標籤）只靠探索筆記，沒有拿 `samples/` 的真實樣本跑過，ticket 06 的實機下載才會驗證。
- 列印的 PDF 文字量（spec 的 31 頁、34,576 字）沒有在這張驗證，同樣留給 ticket 06。
- 權益（ticket 03）用的 LibreOffice 與其假夾具擴充不在這張範圍。

ASSUMPTION：
- 下載清單用 JSON Lines（`manifest.jsonl`），每次執行整份重寫，只含這次執行處理的文件。ticket 03–05 加入其他類別後，同一次執行會一起寫入。
- 略過的文件，下載日期取本地 PDF 的修改日期；`sha256` 與 `html_sha256` 從本地檔案重新計算，原始 HTML 不存在時 `html_sha256` 為空字串。
- 本地檔名格式 `card_cg047_card001`（類別前綴加網址路徑最後兩段），因為同一個 `cgNNN` 底下可以有 `card001` 與 `card002`。
- 以「本地 PDF 已存在」判斷略過；失敗的頁面沒有 PDF，下次執行會重新下載。
- 請求間隔從前一個請求結束起算，不是從開始起算。
- `TAISHIN_REQUEST_INTERVAL_SEC` 不是數字或為負數時以結束碼 2 結束；`--out` 是一般檔案時以結束碼 2 結束；兩者都在發請求之前檢查。
- 只定義 `TAISHIN_WWW_BASE`。`mkpcard`、`mkp` 的前綴等 ticket 04、05 需要時再加。
- Chrome 找不到或無法執行的判斷：執行時拋出 `OSError`，不預先檢查路徑。Chrome 對不存在的輸入檔也回傳結束碼 0 但不產生 PDF，所以另外檢查 PDF 是否存在。
