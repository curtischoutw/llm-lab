# 05: 下載刷卡優惠活動與主視覺圖片

**What to build:** 下載腳本也會翻完刷卡優惠的每個分類與分頁，把下載當天還沒結束的活動頁列印成 PDF，放進活動資料夾。前 8 個有主視覺的活動，另外把主視覺存成圖片文件。已過期與期間不明的活動都記在下載清單裡。

**Blocked by:** 04

**Status:** resolved

- [x] 在 `mkpcard` 的刷卡優惠列表翻完分類 A–I 的每一頁，直到沒有新連結為止，取出 `mkp` 上的活動詳情頁連結並去除重複。這兩個網域的網址前綴都可以用環境變數替換。
- [x] 從活動詳情頁讀出活動期間。結束日早於下載當天就略過，記為過期；讀不出期間時照樣下載，記為期間不明。清單記錄活動期間。
- [x] 活動頁照 02 的方式處理：原始 HTML 另存，取出主內容區（class 含 `page-content` 的元素）後用 headless Chrome 列印成 PDF。
- [x] 依發現順序，取前 8 個有主視覺的活動頁，把主視覺存成圖片文件；只收支援的圖片格式，其他略過並記入清單。主視覺是 `div.banner-image` 裡的圖片，沒有這個元素就視為沒有主視覺（內容區第一張圖片是分享圖示）。判斷方式寫進 docstring。
- [x] 單頁失敗時其他頁照常完成；列表頁失敗時以非零碼結束並指出是哪一個列表。
- [x] 以子行程測試分類與翻頁、過期與期間不明、圖片數量上限與不支援格式的略過。
- [x] 下載腳本的測試、主測試套件與既有下載腳本的測試都全綠。

## 實作結果（2026-10-30）

做了什麼：
- `scripts/fetch_taishin.py` 新增「活動」與「活動圖片」兩個類別，沿用 `Category` 的 `collect`／`produce`、清單、略過、失敗處理與請求間隔。
  - 活動：分類 A–I 各自用 GET `/tscccms/promotion/offerList/<字母>?page=N` 從第 1 頁往後翻到沒有新連結為止（上限 `OFFER_MAX_PAGES`），只收 `a.card-holder`，詳情頁網址一律接在 mkp 前綴後面（絕對網址只取路徑）。詳情頁取 class 含 `page-content` 的主內容區，用 `web_page_producer` 列印成 PDF，放在 `DIR/offers/`。
  - 活動期間：讀 `<h5 class="subtitle">活動期間</h5>` 後面緊接的 `<p>`，格式 `YYYY-MM-DD~YYYY-MM-DD`。結束日早於下載當天記為「過期略過」（不轉檔）；讀不出來照樣下載，清單的 `period` 記為「期間不明」。清單新增 `period` 欄位，其他類別為空字串。
  - 活動圖片：`div.banner-image` 裡的 `<img>` 是主視覺，沒有這個 div 就沒有主視覺（不取內容區第一張圖，那是分享圖示）。依發現順序取前 8 個，存到 `DIR/offer_images/`。支援的副檔名取自 `rag_lab/formats.py` 的 `FORMATS["圖片"]`；不支援的記為「格式不支援略過」。存檔前檢查檔頭和副檔名一致（8 種副檔名各有檢查），不符記為失敗、不存檔。
- 重構（不複製平行的邏輯）：文件下載區的翻頁迴圈抽成 `walk_pages`，下載區與刷卡優惠共用；`extract_main_content` 改成可用 id 或 class 找；`web_page_producer` 多兩個參數（主內容區怎麼找、存檔後的檢查）；`Category` 多 `list_site`、`reads_period`，`extension` 可為 None（取自網址）；新增 `SkipDocument` 表示「依規則不下載」。
- 環境變數 `TAISHIN_MKPCARD_BASE`、`TAISHIN_MKP_BASE`，用法寫在腳本的 docstring。
- `scripts/test_fetch_taishin.py` 從 61 個增加到 93 個。測試用兩個假 server：www 與 mkpcard 指到同一個，mkp 另一個，所以能看出詳情頁與主視覺是向 mkp 請求。列表裡的絕對網址用 `.invalid` 網域，腳本若照絕對網址發請求會失敗。更新了 8 個既有測試的請求清單與數量（每次執行多 9 個刷卡優惠列表請求）。
- 沒有改 `tests/fake_chrome.py`。沒有對官網發請求。

紅燈時的輸出：
- 第 1 輪（列表翻頁、PDF、交給 Chrome 的 HTML、清單欄位；腳本尚未支援）：7 個新測試 `FAILED (failures=3, errors=4)`；例：`AssertionError: Lists differ: [] != ['/tscccms/promotion/offerList/A?page=1', ...]`。實作後 7 個通過，既有測試出現 8 個失敗，都是請求清單與數量差 9 個列表請求（預期中的行為改變），期望值已更新。
- 第 2 輪（過期與期間不明）：6 個測試中 2 個失敗：`AssertionError: '已下載' != '過期略過'`、`Lists differ: ['offer_WM_...001.pdf', 'offer_WM_...002.pdf'] != ['offer_WM_...002.pdf']`；其餘 4 個（期間不明、結束日等於當天、再次執行）在第 1 輪實作後就通過。
- 第 3 輪（活動圖片）：11 個測試中 10 個失敗（`failures=7, errors=3`）；唯一通過的是「活動列表失敗時沒有圖片」（沒有圖片類別時本來就沒有）。實作後 1 個測試的期望值寫錯（8 種副檔名加 1 個大寫 JPG 共 9 個，超過名額 8），改測試，不是改實作。
- 第 4 輪（失敗處理、翻頁上限、請求策略）：寫完就通過。為了確認它們會變紅，暫時做了 6 個變異，都已還原：主視覺改成任何 `<img>`（2 個失敗）、拿掉檔頭檢查（1 個）、不限 `card-holder`（3 個）、過期判斷改成 `<=`（1 個）、過期活動佔主視覺名額（1 個）、不支援的副檔名不略過（1 個）。

最後一次測試輸出：
- `scripts/test_fetch_taishin.py`：`Ran 93 tests in 123.105s`，`OK`
- 主測試套件：`Ran 116 tests in 383.467s`，`OK`
- `scripts/test_fetch_documents.py` 與 `scripts/test_fetch_papers.py`：`Ran 25 tests in 13.318s`，`OK`

沒做到或有疑慮：
- 沒有對真的台新官網驗證。列表、詳情頁與主視覺只依官網結構筆記做的假頁面測試；C–H 分類的 `?page=N` 沒有實測（筆記只實測 A、B、I），真實下載留給 ticket 06。
- 列表頁頂輪播（`a.btn-slide`）的活動不收（筆記 0 節 K，範圍外）：A 的輪播有一個活動不在 A 的任何列表頁，這種活動不會被下載。測試用一個輪播連結確認它不被收。
- 腳本 import `rag_lab.formats` 來取圖片副檔名清單，需要先把 repo 根目錄放進 `sys.path`（`fetch_taishin.py` 第 119 行）。這讓腳本依賴它在 repo 內的位置；`fetch_documents.py`、`fetch_papers.py` 沒有這個依賴。

ASSUMPTION：
- 刷卡優惠每個分類的翻頁上限 `OFFER_MAX_PAGES = 20`（`scripts/fetch_taishin.py:152`；實測 A=5、B=4、I=2）。翻滿仍有新連結視為整個刷卡優惠列表失敗，訊息指出分類。
- 任何分類的任何一頁失敗，整個刷卡優惠列表失敗，已翻過的分類不下載（沿用 04；`collect_offers`，`scripts/fetch_taishin.py:801`）。
- 前 8 個有主視覺的活動不含過期的活動與下載失敗的活動（沒有原始 HTML）；過期活動的 PDF 沒下載，它的圖片也不收（`collect_banners`，`scripts/fetch_taishin.py:902`）。ticket 沒有明說。
- 副檔名不支援的主視覺照樣佔 8 個名額（`scripts/fetch_taishin.py:902`）。ticket 的「取前 8 個有主視覺的活動頁……只收支援的圖片格式」可以讀成先挑 8 個再過濾，也可以讀成先過濾再挑；這裡採前者。
- 主視覺挑選讀 `_meta/html/` 裡存下來的原始 HTML，不重新請求，所以再次執行時挑出同一批；但活動在兩次執行之間過期時，挑選會跳過它並多取一個活動的主視覺（已下載的圖片不會被刪除）。
- 主視覺只向 mkp 網域請求，其他網域記為失敗（`scripts/fetch_taishin.py:954`）；ticket 沒有要求，是對不可信 HTML 的防護。
- 圖片只檢查檔頭，不檢查是否能解碼、沒有大小上限；magic bytes 對照表是自己寫的（`IMAGE_SIGNATURES`，`scripts/fetch_taishin.py:890`），只有副檔名清單共用 `rag_lab/formats.py`。
- 清單的活動期間欄叫 `period`，「期間不明」是欄位值，結果仍是「已下載」；過期與格式不支援另有結果值「過期略過」「格式不支援略過」。
- 過期的活動照樣存原始 HTML（頁面已經取回），但沒有 print HTML 與 PDF。
- 資料夾名 `offers`、`offer_images`，檔名前綴 `offer`、`offer_image`；圖片檔名 `offer_image_WM_<編號>_banner_image.<小寫副檔名>`。
- 結束日等於下載當天仍下載；「下載當天」用執行腳本機器的本機日期。
- 活動頁數量沒有預期值，只印出實際數量（卡片 16、權益 46、下載 19 才有）。
