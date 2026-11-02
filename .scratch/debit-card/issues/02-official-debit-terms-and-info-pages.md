# 02: 官網金融卡的條款與說明頁

**What to build:** 下載腳本也會下載官網金融卡的約定條款、費用與常見問題，以及存款專區的晶片金融卡說明，讓「金融卡跨行提款手續費多少」「晶片金融卡有沒有回饋」這類問題有資料可答。分成兩個類別（spec「下載腳本」的類別表）：「金融卡約定條款 PDF」從約定條款頁收集同網域的 PDF 連結，照原檔存到 `debit_terms/`；「金融卡說明頁」是寫死的 7 個網址（費用、常見問題 2 頁、Richart 摘要頁、存款專區晶片金融卡 3 頁），照 01 的方式轉檔存到 `debit_info/`。

**Blocked by:** 01

**Status:** resolved

- [x] 約定條款 PDF 存到 `debit_terms/`，名稱 `debit_term_<PDF 主檔名>`；約定條款頁上指向悠遊卡公司（外部網域）的連結略過。約定條款頁本身不存成文件。
- [x] 說明頁 7 個網址取 `#centercontainer` 後轉成文件，存到 `debit_info/`，名稱 `debit_info_<網址最後一段>`；沒有主內容區或請求失敗時記失敗，其他照常。
- [x] 名稱不和現有文件撞名；下載清單照現有欄位記錄。
- [x] 更新模式：PDF 內容沒變不重寫、說明頁主內容區變了才重新轉檔；約定條款頁上消失的 PDF 搬到 `_meta/removed/<日期>/`，約定條款頁失敗或解析出 0 份而本地有檔案時不判斷；說明頁沒有下架判斷，取不到時本地檔案不動。
- [x] 測試沿用下載腳本子行程＋假 HTTP server、假 Chrome 的縫；現有測試全綠。
- [x] 模組說明與 README 第 2 節同步。

## 實作結果（2026-11-03）

**做了什麼**

- `scripts/fetch_taishin.py`：新增兩個類別，排在 `CATEGORIES` 的金融卡卡片頁之後。
  - `DEBIT_TERMS`（金融卡約定條款 PDF）：資料夾 `debit_terms/`，本地名稱 `debit_term_<PDF 主檔名>`，沿用下載區的 `save_pdf`／`refresh_pdf`（原樣存檔、SHA-256 比對）。新增 `collect_pdfs_from_one_page`：請求約定條款頁（`payment/notice/TSBankGridPage-000003/`），用既有的 `find_pdf_links` 收同網域的 PDF 連結，其他網域的連結略過（不請求、不記入清單）。約定條款頁本身不存成文件。加進 `REMOVAL_CATEGORIES`，所以頁面失敗或解析出 0 份而本地有 PDF 時，沿用 `main` 既有的保護（不搬任何檔案、結束碼 1）。
  - `DEBIT_INFO`（金融卡說明頁）：資料夾 `debit_info/`，本地名稱 `debit_info_<網址最後一段>`，格式 PDF，沿用卡片頁的 `web_page_producer`／`web_page_refresher`（取 `#centercontainer`、Chrome 列印）。新增 `DEBIT_INFO_PATHS`（寫死的 7 個路徑）與 `collect_fixed_info_pages`（不請求任何列表）。不在 `REMOVAL_CATEGORIES`，所以沒有下架判斷；取不到、沒有主內容區或轉檔失敗時記失敗，本地文件與存檔不動（`web_page_refresher` 既有行為）。
- `scripts/test_fetch_taishin.py`：新增 25 個測試（`DebitTermsTests` 8、`DebitTermsUpdateModeTests` 6、`DebitInfoTests` 6、`DebitInfoUpdateModeTests` 5）。`setUp` 預設登記約定條款頁（沒有 PDF）與 7 個說明頁，所以每個案例多出 8 個請求與 7 份說明頁文件。42 個既有測試的預期值因此調整：請求清單與數量 +8（重跑時只 +1，因為說明頁已存在而略過）、檔案清單加 `DEBIT_INFO_FILES`、清單紀錄改成只看自己的類別。沒有放寬任何判斷條件。另外 `test_redirect_target_outside_the_same_group_…` 原本拿約定條款頁當「不是卡片頁的目標」，現在腳本會請求它，改用不存在的 `TSBankGridPage-000999`，仍是「目標不請求」的檢查。`test_missing_chrome_names_the_environment_variable` 的預期改成卡片頁加 7 個說明頁都失敗（說明頁也要用 Chrome）。
- `README.md` 第 2 節與 `scripts/fetch_taishin.py`、`scripts/test_fetch_taishin.py` 的模組說明同步。

**紅燈輸出**

- 約定條款：第一個測試在腳本沒有該類別時 `FileNotFoundError: ... taishin/debit_terms`（`Ran 1 test ... FAILED (errors=1)`）。其餘 13 個約定條款測試沿用既有機制，寫完直接綠燈，沒有逐個先看紅燈。
- 說明頁：11 個測試一起寫，實作前 `Ran 11 tests ... FAILED (failures=5, errors=6)`。
- 補驗證（破壞腳本後確認測試變紅）：

| 破壞 | 變紅的測試 |
|---|---|
| 約定條款不在 `REMOVAL_CATEGORIES` | `DebitTermsUpdateModeTests` 3 個（下架、頁面失敗、0 份） |
| 說明頁加進 `REMOVAL_CATEGORIES` | `…local_files_that_are_not_one_of_the_seven_pages_are_not_judged_as_removed`（1 個） |
| 說明頁 `refresh=None` | `DebitInfoUpdateModeTests` 4 個（未變、內容變更、取不到、沒有主內容區） |

**最後一次測試輸出**

- 下載腳本三個測試檔（`scripts/test_fetch_papers.py scripts/test_fetch_documents.py scripts/test_fetch_taishin.py`，merge integration 之後，integration 沒有新提交）：`Ran 266 tests in 546.453s`，`OK`（ticket 01 的 241 個加 25 個新測試）。
- 主套件沒跑：這張沒有動 `rag_lab`。
- 第一次跑 `test_fetch_taishin.py` 有 46 個失敗（42 個測試，其中一個有 5 組子案例），都是預設多出的請求與檔案；改預期值後第二次剩 1 個，再改一處後全綠。

**沒做到或有疑慮**

- 沒有對真的官網請求。真實約定條款頁的 PDF 連結用盤點存的 HTML 檢查過：4 個 `.pdf` 連結都是相對路徑（`/TSB/export/sites/TSB/...`），外部連結是 `easycard.com.tw/term`；整頁沒有其他 `.pdf`。
- 約定條款頁的 PDF 連結取整頁，不限主內容區（和權益附件的做法一致）。
- 外部網域的連結略過，不在下載清單留紀錄（ticket 寫「略過」）；權益附件類別則有「外部網域略過」紀錄，兩者不一致。
- 不加 `--update` 時，7 個說明頁已存在就不請求；約定條款頁每次都請求（要靠它列出 PDF）。
- 說明頁類別沒有主內容區的真實樣本可驗證 `deposit/debit-card/` 首頁（盤點沒抓過）。

**ASSUMPTION**

- 說明頁本地名稱的路徑格式 `^/TSB/personal/(?:.+/)?([^/]+)/$`：取最後一段，`deposit/debit-card/` 首頁的名稱是 `debit_info_debit-card`。
- 約定條款 PDF 的 `link_pattern` 與下載區相同（任何 `.pdf` 結尾的路徑，不分大小寫）；同主檔名的 PDF 靠既有的網址雜湊後綴區分。
- 約定條款 PDF 的 `expected_count` 是 4、說明頁是 7，只用於 stdout 的「預期」提示。
