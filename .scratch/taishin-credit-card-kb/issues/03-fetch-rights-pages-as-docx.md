# 03: 下載權益子頁並轉成 `.docx`

**What to build:** 下載腳本也會從信用卡權益頁找出所有權益說明子頁，例如保險、道路救援、不回饋項目，用 LibreOffice 把存下的 HTML 轉成 `.docx`，放進權益資料夾。這樣知識庫會用到 Word 的解析路徑。

**Blocked by:** 02

**Status:** resolved

- [x] 腳本從權益頁取出子頁連結並去除重複，2026-10-30 是 46 個。
- [x] 每個子頁的原始 HTML 照 02 的方式保存，用 02 的方式取出主內容區（`id="centercontainer"`）存成本機 HTML，再用 PATH 上的 LibreOffice（依序找 `libreoffice`、`soffice`）轉成 `.docx`。本地檔名整批唯一。
- [x] 下載清單記錄這一類的每一份文件，欄位與 02 相同。
- [x] 找不到 LibreOffice 或轉檔失敗時，那一頁記為失敗，其他頁照常完成，最後以非零碼結束。
- [x] 假 LibreOffice 夾具擴充成也接受轉成 docx。對其他參數維持嚴格檢查，主檔名以 `broken` 開頭時照舊模擬失敗。
- [x] 以子行程測試上述行為；匯入用的假 LibreOffice 路徑（轉 PDF）的既有測試仍然全綠。
- [x] 下載腳本的測試、主測試套件與既有下載腳本的測試都全綠。

## 實作結果（2026-10-30）

做了什麼：
- `scripts/fetch_taishin.py`：把卡片頁的流程泛化成「類別」（`Category`：列表頁、連結格式、資料夾、副檔名、轉檔函式），卡片與權益共用同一套下載、取主內容區、清單、略過、失敗處理，沒有複製平行的邏輯。新增權益類別：從 `/TSB/personal/credit/intro/rights/` 取出 `rights/<群組>/<頁名>/` 子頁連結（去重），取主內容區後用 PATH 上的 `libreoffice`、`soffice`（依序）轉成 `.docx`，放在 `DIR/rights/`，本地檔名 `rights_<群組>_<頁名>`（例如 `rights_insurance_right0201`、`rights_notice_-00001`）。
- 列表頁失敗不再中止整個腳本：那一類沒有網址並記下是哪個列表，其他類別照常處理，最後以非零碼結束（spec 的「那一類找不到任何網址」）。權益頁的子頁數不是 46 時印出實際數量，不中止。
- `tests/fake_libreoffice.py`：接受 `--convert-to "docx:MS Word 2007 XML"`，輸出 `PK` 檔頭加收到的 HTML；轉 PDF 的行為、參數嚴格檢查與 `broken` 開頭模擬失敗不變。
- `scripts/test_fetch_taishin.py`：新增 24 個測試（47 個全部），並更新 5 個既有測試的請求清單與數量（每次執行多請求一個權益頁）。
- 用本機一個小 HTML 檔（不含官網內容）對真的 LibreOffice 執行腳本裡的同一組參數：產出 5,685 bytes 的 `.docx`，document.xml 含該檔的標題與內文。沒有對官網發請求。

發現：真的 LibreOffice 對 HTML 輸入，`--convert-to docx` 回報 `Error: no export filter for ... docx found`（結束碼 1，沒有輸出）；要寫 `docx:MS Word 2007 XML` 才能轉。腳本用完整濾鏡名稱，假 LibreOffice 對只寫 `docx` 的呼叫回非零碼，所以改回去測試會變紅。

紅燈時的輸出：
- 假 LibreOffice：`FakeLibreOfficeFixtureTests` 5 個，1 個失敗：`fake libreoffice: unexpected arguments: ['--headless', '--convert-to', 'docx:MS Word 2007 XML', ...]`（其餘 4 個是拒絕與既有行為的測試，寫完就通過）。
- 權益子頁（腳本尚未實作）：`RightsPageTests` `Ran 5 tests`、`FAILED (failures=5)`。
- 實作權益類別後，既有測試出現 5 個失敗，都是因為腳本現在多請求權益頁（請求清單與數量差 1），預期中的行為改變，測試的期望值已更新。
- 其餘測試（失敗處理、清單、略過、LibreOffice 輸入內容）在實作後才寫，寫完就通過。為了確認它們會變紅，暫時做了兩個變異：目標改成 `docx` → `RightsPageTests`、`LibreOfficeInputTests` 8 個中 7 個失敗；`OFFICE_COMMANDS` 順序對調 → `RightsFailureTests` 1 個失敗（libreoffice 優先於 soffice）。都已還原。

最後一次測試輸出：
- `scripts/test_fetch_taishin.py`：`Ran 47 tests in 32.324s`，`OK`
- 主測試套件：`Ran 116 tests in 386.761s`，`OK`
- `scripts/test_fetch_documents.py` 與 `scripts/test_fetch_papers.py`：`Ran 25 tests in 12.860s`，`OK`

沒做到或有疑慮：
- 沒有對真的台新官網驗證；權益頁的連結抽取與主內容區只用依筆記做的假頁面測試。真實 46 個子頁的轉檔留給 ticket 06。
- 轉出的 `.docx` 字數（spec 的 11,367 → 11,309）沒有在這張驗證。

ASSUMPTION：
- 子頁連結格式只收 `rights/<群組>/<頁名>/` 兩層（筆記第 3 節的 46 個全部符合，含 `notice/-00001/`）；不收更深或更淺的路徑，也不收權益頁自己的選單連結。
- 找不到 LibreOffice 時，每個要轉檔的權益子頁各自記為失敗（訊息列出 `libreoffice`、`soffice`）；已存在的文件仍然略過，不需要 LibreOffice。
- 不指定 LibreOffice 的使用者設定檔（沿用 RAG-Anything 的呼叫方式）。已開著 LibreOffice 視窗時 headless 轉檔的行為沒有驗證。
- 清單的 `format` 欄位寫 `DOCX`（卡片是 `PDF`）。
