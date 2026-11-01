# 11: 下載權益子頁連到的條款 PDF

**What to build:** 下載腳本另外收權益說明子頁裡連到的 PDF，放進新的「權益附件」資料夾。這樣聯名卡、雙幣卡、企業卡的條款也會進入知識庫。使用者在 2026-10-31 決定：只收台新官網網域上的 PDF，icash.com.tw 的條款不收。實作後掃描真實資料，符合規則的 PDF 是 18 份，不是原先估計的 7 份；使用者在 2026-10-31 決定 18 份全收，不限縮到約定條款子頁。

**Blocked by:** None（下載腳本的 02–05 與 code-review 修正都已合併）

**Status:** resolved

- [x] 從每個權益子頁的原始 HTML 取出 `.pdf` 連結。本次已下載的權益子頁，以及「已存在略過」的權益子頁都要處理；後者讀 `_meta/html/` 裡存下的原始 HTML，不重新請求子頁。
- [x] 只收和 `www` 前綴同網域的 PDF，前綴可以用環境變數替換。其他網域的連結記在清單裡，結果是「外部網域略過」。
- [x] 已經在文件下載區收過的同一個網址，不重複下載，在清單裡記為重複略過，並指出它在下載區的檔名。2026-10-30 的資料裡，right0701 連到的 `_115_001final.pdf` 就是這種情況。
- [x] PDF 原樣存檔，存檔前確認內容以 `%PDF-` 開頭。檔名加類別前綴，整批唯一。沿用既有的清單、略過、失敗處理與請求間隔。
- [x] 2026-10-30 的資料預期收到 7 份（實際 18 份，見實作結果；使用者決定全收）：
  - 聯名卡 4 份：`cg037/easrcard.pdf`、`icash-11312.pdf`、`ipass-11312.pdf`、`TSCC-11312.pdf`；
  - 雙幣卡 2 份：`dual-card_01.pdf`、`dual-card_02.pdf`；
  - 企業卡 1 份：`corporate-Member-Agreement-Terms-202405.pdf`。
  
  數量不同時印出實際數量，但不中止。
- [x] 以子行程測試：子頁內的 PDF 被收進來、外部網域略過、和下載區重複時略過、已存在時略過、讀存下的 HTML 時不重新請求子頁。
- [x] 下載腳本的測試與既有下載腳本的測試全綠。
- [x] README 第 2 節的類別表加上這一類。

## 實作結果（2026-10-31）

做了什麼：
- `scripts/fetch_taishin.py` 新增「權益附件」類別（`ATTACHMENTS`，`save_attachment`、`collect_attachments`），沿用 `Category` 的 `collect`／`produce`、`fetch_document` 的清單與略過、`save_pdf`（`%PDF-` 檢查、暫時檔換名）與 `Fetcher` 的請求間隔，沒有複製平行的邏輯。類別排在「下載」之後，因為要用下載區找到的網址判斷重複。
- `collect_attachments` 讀權益子頁存在 `_meta/html/` 的原始 HTML（本次下載、已存在略過、轉檔失敗但 HTML 已存檔的子頁都讀，不重新請求子頁），取整頁 `<a href>` 中路徑以 `.pdf` 結尾（不分大小寫）的連結，以子頁網址解析、去重。
- `save_attachment`：網域不是 www 前綴的網域時不請求，結果「外部網域略過」，原因寫網域；網址在下載區找到的清單裡時不請求，結果「重複略過」，原因寫下載區檔名；其餘交給 `save_pdf`。
- README 第 2 節的類別表加上這一類，結果種類加上兩個新值。
- 測試：`scripts/test_fetch_taishin.py` 新增 4 個類別、18 個測試（子頁內的 PDF 被收進來、外部網域略過、和下載區重複略過、已存在略過、讀存下的 HTML 時不重新請求子頁、轉檔失敗的子頁仍收它的連結、多個子頁連到同一個 PDF 只下載一次、檔名撞名、相對連結與大小寫、非 PDF 連結、%PDF- 檢查、HTTP 錯誤、子頁失敗、權益頁列表失敗、清單欄位、請求間隔與 User-Agent）。既有測試沒有改動：既有的假子頁沒有 PDF 連結，不會多出請求。

真實樣本掃描（只讀，腳本 `/Users/curtis/.claude/jobs/db9cfed9/tmp/t11/scan_rights.py`，用腳本裡的 `_AnchorCollector`、`resolve_href`、`ATTACHMENTS.link_pattern`、`request_url` 掃主 repo `_meta/html/rights_*.html` 的 45 個檔，不發請求）：候選 20 個網址，收 18、外部網域略過 1（`https://www.icash.com.tw/pdf/icash2_contract.pdf`）、和下載區重複 1（`_115_001final.pdf`，下載區檔名 `download__115_001final.pdf`）。
- 收的 18 份中，right0702、right0704、right0705 的 7 份和 ticket 預期的清單完全一致：`TSCC-11312.pdf`、`easrcard.pdf`、`icash-11312.pdf`、`ipass-11312.pdf`、`dual-card_01.pdf`、`dual-card_02.pdf`、`corporate-Member-Agreement-Terms-202405.pdf`。
- 另外 11 份不在 ticket 的預期裡：保險 4 份（`SKinsurance_20260626.pdf`、`2027SKinsurance_20260930.pdf`、`IS_APPLY_NC_20260626.pdf`、`IS_APPLY1_20260626.pdf`）、道路救援 4 份（`SPECIAL_2026.pdf`、`bigcar2FOR_2026.pdf`、`2026normal_charge_20260102_2.pdf`、`2026BENZ_charge_20260102.pdf`）、機場接送 `2026airport_V3.pdf`、洗車 `washcar_2026.pdf`、優惠 `_202003.pdf`。探索筆記第 134 行已記錄保險的 3 個 PDF 不在下載區。

紅燈時的輸出：
- 第 1 個測試（子頁內的 PDF 被收進來，類別尚未存在）：`AssertionError: Lists differ: [] != ['rights_attachments/attachment_TSCC-11312.pdf', ...]`，`FAILED (failures=1)`。實作 `collect_attachments` 與 `save_pdf` 後通過。
- 外部網域（只做收集時）：`returncode 1`，stdout 顯示 `失敗 權益附件 attachment_icash2_contract.pdf`，原因 `URLError ... nodename nor servname provided`（腳本照外部網址發了請求）。加上網域檢查後通過。
- 和下載區重複：`AssertionError: 2 != 1`（`DUAL_PDF` 被請求 2 次）。加上重複檢查後通過。
- 其餘測試在實作後才寫，寫完就通過（只有請求間隔測試第一次失敗，原因是我把請求數寫成 16，實際是 15：總覽 1、權益頁 1、子頁 1、下載頁 1、PDF 2、刷卡優惠 9，修正的是測試的算術）。為了確認它們會變紅，暫時做了 5 個變異，都已還原：拿掉外部網域檢查（2 個失敗）、拿掉重複檢查（2 個失敗）、收集時要求 docx 也存在（1 個失敗）、連結樣式不分大小寫改成分大小寫（1 個失敗）、拿掉 `%PDF-` 檢查（1 個失敗）。

最後一次測試輸出：
- `scripts/test_fetch_taishin.py`：`Ran 134 tests in 182.247s`，`OK`
- `scripts/test_fetch_documents.py` 與 `scripts/test_fetch_papers.py`：`Ran 25 tests in 12.662s`，`OK`
- `rag_lab/` 沒有改動，沒有跑主測試套件。

沒做到或有疑慮：
- 沒有對真的官網下載：18 份 PDF 的實際內容、是否都以 `%PDF-` 開頭沒有驗證；`_202003.pdf`（`/TSB/personal/.categories/download/credit/rights/` 路徑）是否能直接下載也沒有驗證。
- 掃描結果是 18 份，不是 ticket 預期的 7 份：ticket 的規則（每個權益子頁的 `.pdf` 連結、同網域）會收到另外 11 份。這是 ticket 規則與預期數量的差異，照規則實作；若只要約定條款，要加限縮條件（例如只讀 `rights_right_*` 子頁），需要使用者決定。
- ticket 要求「數量不同時印出實際數量」：腳本印出「權益子頁找到 N 個 PDF 連結」，N 含外部網域與重複的（目前真實資料是 20），不設預期值，因為預期的 7 與真實資料不符。
- 全量匯入的規模會增加：多 18 份 PDF，ticket 06 的耗時估計沒有算進去。

ASSUMPTION：
- 資料夾 `rights_attachments`、檔名前綴 `attachment`（`scripts/fetch_taishin.py:1521`、`scripts/fetch_taishin.py:1531`）；ticket 只指定類別名「權益附件」。前綴不用 `rights_`，避免和權益類別的 `rights_<群組>_<頁名>` 撞名。
- 整頁的連結都看，不限主內容區（2026-10-30 的 45 個樣本中，整頁與主內容區的 PDF 連結完全相同）；`scripts/fetch_taishin.py:1351`。
- 轉檔失敗但原始 HTML 已存檔的子頁也讀；原始 HTML 不存在（子頁下載失敗）的子頁沒有連結可讀。
- 下載區列表失敗時沒有下載區的網址，無法判斷重複，這些 PDF 會下載進權益附件資料夾；`scripts/fetch_taishin.py:1344`。
- 清單新增兩個結果值「外部網域略過」「重複略過」（`scripts/fetch_taishin.py:222`、`scripts/fetch_taishin.py:223`）；外部網域與重複的紀錄，檔名欄是假如下載時會用的本地檔名，沒有對應的檔案，`sha256` 為空字串（和「格式不支援略過」的做法相同）。
- 判斷「同網域」比較 netloc（含連接埠），www 前綴被環境變數替換時以替換值為準；`scripts/fetch_taishin.py:1341`。

## 實機下載（2026-10-31）

合併到 integration（2ff90ff）後，對真的官網跑一次。主 repo 的 `data/` 正在被全量匯入讀取，所以先把 `data/taishin_credit_card/` 複製到 job 暫存資料夾，再對副本執行 `scripts/fetch_taishin.py --out <副本>`。結束碼 1，因為有下面 4 個失敗。

- 權益子頁找到 20 個 PDF 連結：
  - 已下載 17 份，全部以 `%PDF-` 開頭，大小 187 KB 到 588 KB；
  - 外部網域略過 1 份（`icash2_contract.pdf`）；
  - 重複略過 1 份（`_115_001final.pdf`）；
  - 失敗 1 份：`_202003.pdf`（right0503 連到的 `/TSB/personal/.categories/download/credit/rights/_202003.pdf`）回 HTTP 404。這是官網上已失效的連結，不是腳本的問題。
- 其他類別：
  - 卡片 16、權益 43、下載 19、活動圖片 8 都是已存在略過；
  - 權益仍是 Visa、Mastercard、JCB 3 頁轉址到外部網域而失敗，與 ticket 06 相同。
- 範圍外：刷卡優惠列表在 2026-10-31 找到 209 個活動頁，比 2026-10-30 多 8 個。副本裡新下載了這 8 個活動，主 repo 的 `data/` 沒有。

權益附件要等全量匯入（ticket 08）結束後，再對主 repo 的 `data/` 執行下載與匯入。

## 匯入（2026-10-31）

ticket 08 結束後，對主 repo 的 `data/` 重跑下載，結果與副本那次相同：權益附件 17 份、新活動 8 份。匯入的 log 都在 `output/taishin_full/`。

- 第一次匯入權益附件時，`SPECIAL_2026` 的大表格讓 LLM server 記憶體不足而停掉，所以先做了 ticket 12，再繼續匯入。
- 第二次匯入權益附件（`ingest_rights_attachments2.log`）：
  - 17 份裡，8 份已完成而略過；`TSCC-11312` 上次被中斷，這次清掉舊紀錄後重匯；另外 8 份是新的。
  - 48:59，failed=0。VLM 呼叫 12 次，全部成功。
- 新活動 8 份逐份匯入（`ingest_new_offers.log`）：22:29 到 22:51，每份 108–324 s，全部成功。
- 匯入後的知識庫：
  - 文件 311 份，全部 processed，每份都有 `multimodal_processed=True`；
  - 實體 15,747，關係 31,239，其中 belongs_to 邊 11,352。
- 從 server 重開到結束，LLM server 收到的最大 prompt 是 4,293 token，wired 記憶體最高 16 GB。
