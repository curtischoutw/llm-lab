"""下載台新銀行信用卡的官網內容到本地資料夾，作為知識庫的來源文件。

為什麼存在：知識庫要用台新信用卡的卡片頁、權益說明、文件下載區與刷卡優惠活動頁（約 140 份）。
這些內容不進版本控管，所以用這支腳本讓任何機器都能用一個指令重建同一批內容。

用法：
    python3 scripts/fetch_taishin.py [--out DIR] [--update]
    預設輸出到 repo 根目錄下的 data/taishin_credit_card。
    不加 --update 時，本地已有的文件一律略過；加上 --update 是更新模式（見下面「更新模式」）。

目前涵蓋的類別：
- 卡片：總覽頁列出的卡片頁，列印成 PDF，放在 DIR/cards/。
- 權益：權益頁列出的權益說明子頁，用 LibreOffice 轉成 .docx，放在 DIR/rights/。
- 下載：文件下載區每一頁列出的 PDF（約定條款、費用表、申請書等），不轉檔、原樣存檔，放在 DIR/downloads/。
- 權益附件：權益子頁連到的 PDF（聯名卡、雙幣卡、企業卡的約定條款等），不轉檔、原樣存檔，放在 DIR/rights_attachments/。
- 活動：刷卡優惠列表（分類 A–I）列出、下載當天還沒結束的活動頁，取主內容區後列印成 PDF，放在 DIR/offers/。
- 活動圖片：依發現順序，前 IMAGE_LIMIT（8）個有主視覺的活動頁的主視覺，原樣存檔，放在 DIR/offer_images/。

輸出結構：
- DIR/<類別資料夾>/：匯入知識庫的文件，每個類別一個資料夾（ingest 不遞迴，一次匯入一個資料夾）。
- DIR/_meta/html/：每一個網頁（卡片頁、權益子頁、活動頁）的原始 HTML，過期的活動頁也有；PDF 與圖片不是網頁，沒有。
- DIR/_meta/print/：取出主內容區後交給 Chrome 或 LibreOffice 的本機 HTML。
- DIR/_meta/manifest.jsonl：下載清單，一行一份文件。_meta 不會被匯入。欄位 period 是活動的活動期間
  （YYYY-MM-DD~YYYY-MM-DD，讀不出來是「期間不明」），其他類別為空字串。result 除了已下載、已存在略過、失敗，
  還有「過期略過」（活動）、「格式不支援略過」（活動圖片）、「外部網域略過」與「重複略過」（權益附件）。
  更新模式另有「內容變更」、「未變」、「下架」與「過期移除」（見下面「更新模式」）。

更新模式（--update，增量更新 spec 的下載端；目前涵蓋文件下載區 PDF 與網頁類的比對，卡片、權益、下載、活動四個列表類別的下架，
權益附件的比對與下架，活動的過期判斷與活動圖片跟著活動走）：
- 文件下載區的 PDF：本地已有的檔案重新下載一次並比對 SHA-256。內容不同才換掉原檔，清單記「內容變更」；相同就不碰原檔
  （位元組與修改時間都不變，清單記「未變」），這樣之後匯入時沒變的文件可以走 RAG-Anything 的解析快取（快取鍵含修改時間與內容雜湊）。
  新出現的 PDF 沿用「已下載」。下載失敗（HTTP、網路、內容不是 PDF）時原檔不動，清單記「失敗」，結束碼 1。
- 網頁類（卡片頁、權益子頁、活動頁）：重新取得原始 HTML，和 DIR/_meta/html/ 存的上一份比對主內容區（轉檔實際用的那一塊：
  卡片頁與權益子頁是 id="centercontainer"，活動頁是 class 含 page-content 的第一個元素，取出後拿掉會執行的部分；grill Q29）。
  主內容區相同就不轉檔、不碰文件、列印用 HTML 與存檔的原始 HTML（位元組與修改時間不變，清單記「未變」），
  主內容區以外的差異（例如活動頁 <head> 的 _csrf token，2026-11-02 實測 2 頁都和 10-30 存的不同）不算變更。
  例外：活動頁的主視覺（div.banner-image，在主內容區外面）網址變了也算變更（grill Q30），照下面的主內容區不同處理（重新轉檔、換存檔）。
  主內容區不同才重新轉檔，轉檔成功後依序換掉文件、列印用 HTML、原始 HTML（原始 HTML 是下次比對的基準，最後換，中途中斷時
  下次還會比對到差異），清單記「內容變更」。下載、轉檔失敗或找不到主內容區時三者都不動，清單記「失敗」，結束碼 1，下次執行會再比對到差異並重試。
  文件不存在（存檔的原始 HTML 在，第一次下載時轉檔失敗留下的狀態）時不比對，照新增處理：用這次取得的原始 HTML 轉檔，成功記「已下載」；
  活動的存檔 HTML 讀出的期間已過期時除外，不請求、不轉檔，記「過期略過」。
  文件在但存檔的原始 HTML 不在（無法比對）時視為變更（ASSUMPTION）。
- 下架（卡片、權益、下載、活動；權益附件的下架另見下一項，活動圖片的去留見下面「活動過期與活動圖片」）：這次官網列表裡沒有、本地類別資料夾（第一層）裡有的文件，
  連同它在 DIR/_meta/html/、DIR/_meta/print/ 的檔案（有才搬），搬到 DIR/_meta/removed/<下載當天>/，底下保留原本的相對路徑：
  文件到 <類別資料夾>/<檔名>，原始 HTML 到 html/<名稱>.html，列印用 HTML 到 print/<名稱>.html。清單記「下架」。
  _meta 在資料根目錄，不在類別資料夾底下，所以匯入時不會挑到搬走的檔案。這樣之後匯入端才看得到這份文件已經不在。
  - 目的地已有同名檔時，在檔名後加時間（_HHMMSS 加微秒），不覆寫（ASSUMPTION，見增量更新 spec）。
  - 下架清單紀錄的網址是空字串：本地只有檔案，沒有它的網址，不去翻上一次的清單（ASSUMPTION）。
  - 搬移時的檔案系統錯誤，那一份記「失敗」並寫出原因（結束碼 1），其餘文件照常處理。
  - 本地清單不含不是文件的檔案（`.` 開頭的隱藏檔如 .DS_Store、`~$` 開頭的鎖定檔，規則同 rag_lab/formats.py 的 NOT_A_DOCUMENT_PREFIXES）：
    它們不會被搬走，「解析出 0 筆」的保護也只算真正的文件。
  - 不設下架數量的比例門檻：列表有 1 筆以上時，其餘本地文件全部算下架。
  - 某個類別的列表頁沒有成功取得（請求失敗、逾時、翻頁失敗），那個類別這次不搬任何檔案，stderr 寫明列表與原因，結束碼 1，其他類別照常。
    列表頁回應成功、卻解析出 0 筆，而本地這個類別資料夾有文件時，也當成列表頁沒有成功取得（官網改版讓解析失效的可能高於整類下架），
    不搬任何檔案，stderr 寫明，結束碼 1；本地沒有文件時，0 筆不算失敗。
  - 判斷只看類別資料夾裡的檔名是否在這次列表算出的檔名之內（檔名規則見下面「本地檔名」）。同一類別兩個網址組出同一個檔名而加了網址雜湊後綴的
    情況，列表增減會改變後綴，舊檔名會被當成下架、新檔名當成新增。
- 權益附件跟著權益子頁上的連結走：
  - 比對：本地已有的附件重新下載並比對 SHA-256，和下載區 PDF 相同的規則（內容不同才換掉，記「內容變更」；相同記「未變」、
    位元組與修改時間不動；下載失敗時原檔不動，記「失敗」）。
    本地已有的附件，網址現在也在文件下載區時（和不加 --update 的「重複略過」同一條規則）不請求：清單記「重複略過」並把它當成下架搬走
    （搬法同下架）。ASSUMPTION：它的內容已由下載區那一份匯入，不搬的話同一份 PDF 會在知識庫裡兩次。
  - 下架：附件的候選是這次所有權益子頁（權益列表裡的）存檔的原始 HTML 連到的 PDF（讀存檔，和不加 --update 時相同；子頁在這次執行裡
    已先換成最新的存檔）。本地 DIR/rights_attachments/ 裡的檔名不在候選算出的檔名之內，才算下架：同一份附件被多個子頁連到時，
    只要還有一頁連到就不算；子頁本身下架（搬走、不在權益列表）時，它不再貢獻候選。搬移方式與上面的下架相同，清單記「下架」。
  - 權益列表沒有成功取得，或任何一個權益子頁處理失敗（請求失敗，或內容變了但轉檔失敗而存檔沒換）時，這次不判斷附件下架，
    不搬任何附件，stderr 寫「權益附件這次不判斷下架」與原因；原因本身已讓結束碼是 1，下次子頁都成功時再判斷。
    例外：失敗原因是「轉址到外部網域」的子頁不算（真實官網的 Visa、Mastercard、JCB 子頁每次都是）：它從來沒有內容，
    也不會提供附件連結。其他失敗（請求、轉檔、搬移）照樣阻擋。
  - 權益子頁都成功取得、但解析到的附件連結是 0 個，而本地有附件時，也當成沒有成功取得（官網改版讓解析失效的可能高於所有附件同時下架，
    做法同列表頁解析出 0 筆）：不搬任何附件，stderr 寫「權益附件這次不判斷下架」與原因。ASSUMPTION：結束碼比照列表頁的 0 筆保護是 1。
    本地沒有附件時，0 個不算失敗。
  - 附件下架紀錄的網址是空字串，沿用列表類別下架的做法。
- 活動過期與活動圖片（更新模式；活動列表沒有成功取得時，這次不判斷活動過期，也不判斷活動圖片，見上面的列表失敗規則）：
  - 過期：每個已有活動文件的活動重新取得詳情頁，期間的結束日早於下載當天就算過期（現有規則，結束日等於當天仍有效），
    不比對、不轉檔，文件連同 _meta/html、_meta/print 的檔案搬到 DIR/_meta/removed/<下載當天>/（搬法同下架），清單記「過期移除」，
    網址是活動詳情頁網址、period 是這次讀到的期間。同一次既內容變更又過期的，也記「過期移除」，搬走的是舊版本的存檔
    （這次取得的新頁面不存檔；下次執行時這個活動沒有文件也沒有存檔，照一般流程記「過期略過」並存下原始 HTML）。
    取得頁面失敗的活動（清單記「失敗」）原封不動，不用存檔的期間判斷（ASSUMPTION）。
    只有原始 HTML、沒有活動文件的活動，行為不變：存檔的期間已過期記「過期略過」，不請求；否則當成新增轉檔。
  - 圖片的去留在所有活動處理完之後算：圖片資料夾裡，沒有任何「活動文件仍在」（活動 PDF 與存檔的原始 HTML 都在）的活動
    指向的圖片，搬到 DIR/_meta/removed/<下載當天>/offer_images/，清單記「下架」、網址是空字串。共用同一張圖的活動都不在了才搬；
    活動改版換了主視覺網址時，舊圖搬走。新舊網址只有資料夾或 query 不同、檔名相同時，本地檔名一樣，那個檔案是舊圖：
    先把它搬走（清單記「下架」），新圖再下載換上（記「已下載」），不會當成「已存在」略過。
  - 名額：「活動文件仍在」的活動的主視覺網址去除重複後，圖片檔在本地的或副檔名不支援的各佔一個（下載失敗沒有留檔的不佔）。
    少於 IMAGE_LIMIT（8）個時才補，從「活動文件確實存在、有主視覺、主視覺網址還沒有佔名額」的活動補：這次重新取得之前存檔的
    主視覺網址和現在不同的排最前面，其餘依活動被找到的順序。補不滿 8 個時印出「活動圖片名額 N/8，沒有更多候選」。
    新出現在前面的活動不擠掉現有的圖片。仍有效、主視覺網址沒變、已有圖片的活動不重新請求圖片，圖片與修改時間不變，清單記「已存在略過」。
- 結束時多印一段「各類別統計」：每個類別每種結果的數量。不加 --update 時不印。
- 請求間隔、網域限制與轉址規則和不加 --update 時相同。

關鍵設計決策：
- 直接列印原網址會漏掉收合區與彈窗：2026-10-30 實測 Richart 卡片頁的 PDF 只有 2 頁、1,074 字，
  原始 HTML 的可見文字是 36,767 字，「23:59」與「天天刷」都是 0 次。官網 CSS 讓預設收合的區塊與彈窗在列印時不顯示。
  所以先從原始 HTML 取出主內容區（卡片頁是 id="centercontainer"），拿掉其中會執行或載入外部內容的部分，
  包成只帶固定列印用 CSS 與 <base href>（指回原網址）的本機 HTML，再交給 Chrome。
  這樣列印出的版面是純 HTML 的排版，不像官網。
- 拿掉的部分（strip_active_content，用 HTMLParser 重新輸出，不用正規表示式）：<script>、<style>、<iframe> 連同內容，
  <link rel="stylesheet">，名稱以 on 開頭的事件屬性（onclick、onerror、onload…），值是 javascript: 網址的 href／src 等屬性
  （只拿掉屬性，文字留著），以及註解。headless Chrome 開著 JS，所以 Chrome 的暫時 profile 另外把 JavaScript 設成封鎖。
  封鎖用 profile 的 Preferences（`profile.default_content_setting_values.javascript` = 2），不是命令列參數：
  2026-10-30 用真的 Chrome 對本機 HTML 實測，`--disable-javascript` 沒有效果（inline script 與 onload 照常寫入文字），
  `--blink-settings=scriptEnabled=false` 讓 `--print-to-pdf` 結束碼 0 但沒有產出 PDF；只有 Preferences 讓 PDF 沒有 JS 寫入的文字。
- 找不到主內容區的頁面記為失敗，原因寫「找不到主內容區」，不退回列印整頁。
- 權益子頁和卡片頁共用同一套流程（下載、取主內容區、轉檔、清單、略過、失敗處理），只有轉檔的外部命令不同：
  `<libreoffice 或 soffice> --headless --convert-to "docx:MS Word 2007 XML" --outdir <資料夾> <HTML 檔>`。
  目標一定要寫完整的濾鏡名稱：2026-10-30 實測，LibreOffice 把 HTML 當成 Writer/Web 文件開啟，
  目標只寫 docx 會回報 "no export filter"。LibreOffice 沿用 RAG-Anything 的找法，在 PATH 上依序找
  libreoffice、soffice；找不到時，每一個權益子頁各自記為失敗。轉檔不受官網 CSS 影響，取主內容區是為了去掉導覽選單。
  每次轉檔加上 `-env:UserInstallation=file://<暫時資料夾>/profile` 使用暫時的 user profile（轉檔後移除）：
  不指定時，使用者開著 LibreOffice，headless 轉檔會結束碼 0 但沒有產出。
- 本地檔名由網址路徑組成並加類別前綴（卡片 card_cg047_card001，權益 rights_insurance_right0201，
  下載 download_word_CR04131_1150B），整批唯一。前綴也讓以 - 開頭的 PDF 檔名（真實有 -_11407.pdf）不會變成以 - 開頭。
  檔名中字母、數字、底線、. 與 - 以外的字元換成底線；同一類別裡兩個網址組出同一個檔名時（不分大小寫），兩者都加上完整網址的
  SHA-256 前 8 碼，所以檔名只取決於這一批網址。
- 文件下載區：從第 1 頁起用 `?nav1=credit&nav2=file-download&page=N` 往後翻，直到某一頁沒有新的 PDF 連結為止。
  官網超過最後一頁時回 200 並重複最後一頁（2026-10-30 調查：page=3 與 page=99 都等於 page=2），不是空清單，
  所以「沒有新連結」會在最後一頁的下一頁停下來（目前 2 頁，發 3 個請求）。
  PDF 的 href 是只有路徑的相對網址，補上列表頁的網域；只收和列表頁同一個網域、路徑以 .pdf 結尾的連結，網址去除重複。
  送出請求前，路徑與 query 中 ASCII 以外的字元做百分比編碼（request_url）；card 與權益子頁的網址去掉 fragment 再去重複
  （`card001/` 與 `card001/#tab2` 是同一頁）。列表頁裡格式錯誤的 href（例如 `http://[bad`）略過，不讓那一類失敗。
  PDF 是不可信資料：存檔前確認內容以 `%PDF-` 開頭，不是的話（例如錯誤頁的 HTML）那一份記為失敗，不存檔。
- 刷卡優惠列表（mkpcard）：分類 A–I 各自從 `/tscccms/promotion/offerList/<字母>?page=N` 的第 1 頁往後翻（GET，不是 POST），
  直到某一頁沒有新連結為止。官網超過最後一頁時回 200、清單為空、內容是「查無資料」（和下載區的重複最後一頁不同），
  所以沿用同一個停止條件「沒有新連結」，與下載區共用 walk_pages。每個分類的上限 OFFER_MAX_PAGES。
  只收 class 含 card-holder 的 <a>，且路徑是 `/tscccms/promotion/detail/WM_<數字>`：<script> 裡的 JS 字串樣板不會被當成連結。
  連結可能是相對路徑（解析到 mkpcard）或指向 mkp 的絕對網址；兩者都只取路徑，接在 mkp 的前綴後面，
  所以活動詳情頁一律向 mkp 請求。任何一個分類的任何一頁失敗，整個「刷卡優惠」列表失敗（訊息指出分類與頁碼）。
- 活動期間：詳情頁 `<h5 class="subtitle">活動期間</h5>` 後面緊接的 `<p>`，格式 `YYYY-MM-DD~YYYY-MM-DD`。
  正文裡的其他寫法（「活動期間：2026/9/22-10/31」等自由文字）不當期間。結束日早於下載當天（本機日期）略過，
  結果記為「過期略過」，不轉檔；結束日等於下載當天仍下載。讀不出期間（沒有這個區塊、格式不同、日期不存在）
  時照樣下載，period 記為「期間不明」。過期與期間不明的活動，原始 HTML 都照樣存檔。
  「下載當天」一次執行只取一次（Run.today），過期判斷與清單的下載日期共用，執行跨過午夜時前後一致。
  再次執行時，活動沒有 PDF 但 `_meta/html` 已有原始 HTML 且讀出的期間已過期，直接記為過期略過，不再請求詳情頁。
- 活動頁的主內容區是 class 含 page-content 的元素（第一個），其餘處理和卡片頁相同（web_page_producer）。
- 活動圖片：主視覺是詳情頁 `div.banner-image` 裡的第一個 `<img>`，沒有這個 div 就視為沒有主視覺。
  內容區的第一張 `<img>` 是分享圖示（round-default.png），不是主視覺。2026-10-30 的 5 個樣本中有 2 頁沒有主視覺。
  挑選：依活動的發現順序，只算活動 PDF 確實存在的活動（本次下載，或已存在而略過），取前 8 個有主視覺的。
  過期的活動與 PDF 失敗（下載、列印失敗）的活動沒有 PDF，不算；已存在的活動不論現在是否過期都算，所以再次執行時挑出同一批。
  讀存下來的原始 HTML 挑選，不重新請求。副檔名不支援的主視覺照樣佔名額，記為「格式不支援略過」。
  支援的副檔名取自 rag_lab/formats.py 的 FORMATS["圖片"]（專案裡唯一的一份），腳本啟動時把 repo 根目錄放進 sys.path 來 import。
  主視覺網址若是指向官網 mkp 網域的絕對網址，和活動詳情頁連結一樣換成 TAISHIN_MKP_BASE 的前綴（Run.to_mkp），所以用本機
  server 測試時真實格式的主視覺也會向本機請求。
  活動圖片的本地檔名一律用「活動文件仍在的活動的全部主視覺網址」算（banner_universe），下載（只下載其中前 8 個或名額內補的）、名額判斷、
  孤兒圖片判斷都用同一組：兩個主視覺網址的檔名相同（只有資料夾或 query 不同）時，兩個都加雜湊後綴，檔名在三處一致。
  圖片是不可信資料：只向 mkp 網域請求（其他網域的主視覺記為失敗，訊息列出該網域與 mkp 網域），存檔前檢查檔頭（magic bytes）和副檔名一致
  （png、jpg／jpeg、bmp、gif、tif／tiff、webp 各有檢查），不符的記為失敗、不存檔。副檔名取自網址，轉成小寫。
- 權益附件（ASSUMPTION：類別名「權益附件」、資料夾 rights_attachments、檔名前綴 attachment，ticket 11 只指定類別名，
  資料夾與前綴是這次自己訂的）：讀權益子頁存在 DIR/_meta/html/ 的原始 HTML，不重新請求子頁，所以本次下載與已存在而略過的子頁
  處理方式相同；子頁的轉檔失敗但原始 HTML 已存檔時，也讀它。整頁的 <a href> 都看，連結以子頁網址解析，路徑以 .pdf 結尾（不分大小寫）的
  是候選，同一個網址連在很多頁只算一次，檔名規則與下載區相同（前綴 attachment，例如 attachment_dual-card_01.pdf）。
  這個類別排在文件下載之後，因為要用下載區找到的網址判斷重複。每個候選的處理：
  只收和 www 前綴同網域的（環境變數 TAISHIN_WWW_BASE 替換後以替換值為準），其他網域不請求，清單的結果是「外部網域略過」，
  原因寫出網域（使用者 2026-10-31 決定：icash.com.tw 的條款不收）；網址和文件下載區找到的相同時不請求，結果是「重複略過」，
  原因寫出它在下載區的檔名（例如 right0701 連到的 _115_001final.pdf，下載區的 download__115_001final.pdf）；
  其餘照 save_pdf：確認以 %PDF- 開頭後原樣存檔、再次執行時已存在就略過、失敗只記那一份。
  下載區的列表失敗（沒有下載區的網址）時，無法判斷重複，這些 PDF 照常下載到權益附件資料夾。
- 單頁失敗（HTTP、網路、轉址到外部網域、網址無法送出請求、轉檔、檔案系統）時記下原因，其他頁照常處理；最後列出所有失敗的頁面並以非零碼結束。
  列表頁（總覽頁、權益頁、文件下載頁與刷卡優惠列表的任何一頁）本身失敗時，那一類沒有任何網址，指出是哪一個列表；
  其他類別照常處理，最後以非零碼結束。
- 轉址：腳本自己發出的請求只跟隨原請求網域內的轉址。轉址到其他網域時不跟隨，那一頁記為失敗，原因是
  「轉址到外部網域 <網域>」。2026-10-30 實測，權益頁的 Visa、Mastercard、JCB 子頁會轉址到國際組織的網站。
  「原請求的網域」是環境變數替換後實際請求的網域，所以本機 server 的測試也適用。
- 再次執行時（不加 --update），本地檔案已存在就略過（不發請求）並記入清單，內容不會更新；要用這種方式更新內容，
  刪除資料夾後重新下載。加 --update 時文件下載區的 PDF 與網頁類會重新取得並比對，見「更新模式」。
- 請求間隔：腳本自己發出的每個 HTTP 請求之間至少 TAISHIN_REQUEST_INTERVAL_SEC 秒（預設 2）。
  這個環境變數只給測試調小。
- 三個網域的前綴各用一個環境變數取代，只給測試指向本機假 server 用：TAISHIN_WWW_BASE 取代
  https://www.taishinbank.com.tw，TAISHIN_MKPCARD_BASE 取代 https://mkpcard.taishinbank.com.tw（刷卡優惠列表），
  TAISHIN_MKP_BASE 取代 https://mkp.taishinbank.com.tw（活動詳情頁與主視覺）。列表裡指向 mkp 的絕對網址
  會被換成 TAISHIN_MKP_BASE 的前綴，所以測試只要設這三個變數，不會有請求送到真的官網。
  TAISHIN_CHROME 指定 Chrome 執行檔，預設是 macOS 上 Google Chrome 的標準安裝路徑。
- Chrome 列印時使用暫時的使用者資料夾（含封鎖 JavaScript 的 Preferences），不用使用者自己的 Chrome profile。
- 下載的內容是不可信資料：腳本不執行它們；外部命令用參數列表呼叫。

已知極限：
- Chrome 與 LibreOffice 透過 <base href> 自行載入圖片，這些請求不受腳本的間隔控制。
- 刷卡優惠列表頁頂的輪播（a.btn-slide，絕對網址）不收：2026-10-30 的樣本中，A 的輪播有一個活動不在 A 的任何列表頁裡，
  所以這類活動不會被下載（範圍外，ticket 05）。
- 權益附件收的是子頁上所有同網域的 PDF 連結，不只約定條款：2026-10-30 存下原始 HTML 的 45 個子頁（含保險、道路救援、停車、
  機場接送、優惠方案等）一共連到 18 個同網域 PDF，其中聯名卡、雙幣卡、企業卡的條款 7 份（right0702、right0704、right0705）。
  ticket 11 預期 7 份，只對應 right07xx；其餘 11 份（SKinsurance_20260626.pdf 等）依同一條規則也會收，使用者 2026-10-31 決定 18 份全收、不限縮。
  數量沒有預期值，只印出找到的連結數（含外部網域與重複的）。
- 官網改版時，列表頁的連結格式、id="centercontainer" 或 class page-content 可能失效；總覽頁找到的卡片數不是 16、
  權益頁找到的子頁數不是 46、下載區找到的 PDF 數不是 19 時，腳本會印出實際數量提醒，但不中止。
- 翻頁上限 DOWNLOAD_MAX_PAGES（ASSUMPTION：20，目前實際只有 2 頁）。翻滿上限仍有新的 PDF 時，
  視為下載頁失敗（官網改版或不再重複最後一頁的徵兆），而不是無限翻頁。
- 只確認 PDF 以 `%PDF-` 開頭，不檢查檔案是否完整、能不能開啟（ASSUMPTION）。
- 刷卡優惠每個分類的翻頁上限 OFFER_MAX_PAGES（ASSUMPTION：20，2026-10-30 實測 A=5、B=4、I=2 頁，C–H 未實測）。
  翻滿上限仍有新連結時，視為刷卡優惠列表失敗。
- 圖片只檢查檔頭和副檔名一致，不檢查圖片是否完整、能不能解碼。沒有大小上限（ASSUMPTION）。
- 活動已存在而再次執行時，不加 --update 不重新判斷是否過期：已下載的活動 PDF 與圖片留著，清單記為已存在略過。
  加 --update 時每個已有文件的活動會重新判斷（見「更新模式」的活動過期與活動圖片）。
- 已過期的活動，不加 --update 再次執行時依上次存下的原始 HTML 判斷，不再請求；官網之後延長該活動的期間，要刪除 `_meta/html`
  裡那個檔案才會重新下載。加 --update 時，沒有文件但有存檔 HTML 的活動，存檔的期間已過期同樣不請求（記過期略過）；
  已經搬到 `_meta/removed/` 的過期活動，之後在活動列表又出現且沒過期，視為新增，重新下載。
- 更新模式的 PDF 比對把整份回應讀進記憶體再算雜湊（ASSUMPTION：2026-10-30 下載區最大的 PDF 約 6.7 MB，不另外做串流；現有的下載本來就是整份讀進記憶體）。
- 行內 `style="display:none"` 沒有處理：2026-10-30 實測轉出率 0.93–1.01，沒有因此漏字。
- 列印前拿掉註解與 <iframe>、樣式表連結，所以 iframe 裡的內容與外部樣式表不會出現在 PDF／.docx；<object>、<embed> 沒有處理
  （Chrome 的 JavaScript 已封鎖，LibreOffice 不執行腳本）。

Dependencies: 標準函式庫；rag_lab.formats（專案內，只用標準函式庫，取圖片副檔名清單與「不是文件」的檔名開頭）；
列印需要 Google Chrome，轉 .docx 需要 LibreOffice。
"""

import argparse
import hashlib
import html
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import IO
from urllib.parse import ParseResult, quote, unquote, urljoin, urlparse, urlunparse

# 圖片格式的清單沿用專案唯一的一份（rag_lab/formats.py，只用標準函式庫）；腳本在 scripts/ 底下，
# 要先把 repo 根目錄放進 sys.path 才找得到 rag_lab
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag_lab.formats import FORMATS, NOT_A_DOCUMENT_PREFIXES  # noqa: E402

# ==============================
# 設定
# ==============================

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "taishin_credit_card"
USER_AGENT = "llm-lab-fetch-taishin/1.0 (personal RAG knowledge base)"
TIMEOUT_SEC = 60
CHROME_TIMEOUT_SEC = 180

WWW_PREFIX = "https://www.taishinbank.com.tw"
MKPCARD_PREFIX = "https://mkpcard.taishinbank.com.tw"
MKP_PREFIX = "https://mkp.taishinbank.com.tw"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_INTERVAL_SEC = 2.0

OFFICE_COMMANDS = ("libreoffice", "soffice")
OFFICE_TIMEOUT_SEC = 180
# 目標要寫完整的濾鏡名稱：HTML 是 Writer/Web 文件，只寫 docx 會回報 "no export filter"
DOCX_TARGET = "docx:MS Word 2007 XML"

FORMAT_PDF = "PDF"
FORMAT_DOCX = "DOCX"
FORMAT_IMAGE = "圖片"

# 文件下載區：翻頁上限（ASSUMPTION，目前實際 2 頁）與 PDF 檔頭
DOWNLOAD_MAX_PAGES = 20
PDF_MAGIC = b"%PDF-"

# 刷卡優惠：分類 A–I 各自翻頁，每類的翻頁上限（ASSUMPTION：20，2026-10-30 實測 A=5、B=4、I=2 頁）
OFFER_CATEGORIES = "ABCDEFGHI"
OFFER_MAX_PAGES = 20

# 活動圖片：依發現順序，只取前幾個有主視覺的活動；只收 RAG-Anything 支援的圖片副檔名
IMAGE_LIMIT = 8
SUPPORTED_IMAGE_EXTENSIONS = FORMATS["圖片"]

# 網路失敗的例外：連線／逾時／重設／HTTP 狀態錯誤（OSError，HTTPError 與 URLError 都是其子類）與讀 body
# 到一半斷線的 http.client.IncompleteRead 等（HTTPException，不是 OSError）
NETWORK_ERRORS = (OSError, http.client.HTTPException)

CHROME_ENV = "TAISHIN_CHROME"
INTERVAL_ENV = "TAISHIN_REQUEST_INTERVAL_SEC"
WWW_BASE_ENV = "TAISHIN_WWW_BASE"
MKPCARD_BASE_ENV = "TAISHIN_MKPCARD_BASE"
MKP_BASE_ENV = "TAISHIN_MKP_BASE"

# request_url 編碼 query 時保持原樣的字元：query 的分隔符號與已經編碼的 %
QUERY_SAFE = "=&%+/?:;,@$!*'()~"

# Chrome profile 的 Preferences：封鎖所有網頁的 JavaScript（content setting 2 = block）。
# 2026-10-30 用真的 Chrome 對本機 HTML 實測：--disable-javascript 沒有效果，--blink-settings=scriptEnabled=false
# 會讓 --print-to-pdf 結束碼 0 但沒有產出 PDF，只有這個設定讓 inline script 與 onload 都不執行
CHROME_PREFERENCES = {"profile": {"default_content_setting_values": {"javascript": 2}}}

# 固定的列印用 CSS：圖片不超出頁寬，表格有框線
PRINT_CSS = "img{max-width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #999;padding:2px}"

# 轉址到外部網域的失敗原因開頭（_SameDomainRedirectHandler 寫入；attachment_removal_blocker 靠它辨認這類失敗）
EXTERNAL_REDIRECT = "轉址到外部網域"

RESULT_DOWNLOADED = "已下載"
RESULT_SKIPPED = "已存在略過"
RESULT_FAILED = "失敗"
RESULT_EXPIRED = "過期略過"
RESULT_UNSUPPORTED = "格式不支援略過"
RESULT_EXTERNAL = "外部網域略過"
RESULT_DUPLICATE = "重複略過"
RESULT_CHANGED = "內容變更"
RESULT_UNCHANGED = "未變"
RESULT_REMOVED = "下架"
RESULT_EXPIRED_REMOVED = "過期移除"
# 結束時統計的顯示順序
RESULT_ORDER = (
    RESULT_DOWNLOADED,
    RESULT_CHANGED,
    RESULT_UNCHANGED,
    RESULT_SKIPPED,
    RESULT_REMOVED,
    RESULT_EXPIRED_REMOVED,
    RESULT_EXPIRED,
    RESULT_UNSUPPORTED,
    RESULT_EXTERNAL,
    RESULT_DUPLICATE,
    RESULT_FAILED,
)


class FetchError(Exception):
    """某一頁無法完成下載或轉檔；訊息是寫進清單的失敗原因。"""


class SkipDocument(Exception):
    """這份文件依規則不下載（不是失敗）；result 是寫進清單的結果，訊息是寫進清單的原因。"""

    def __init__(self, result: str, detail: str) -> None:
        """SkipDocument 的建構。

        Args:
            result: 寫進清單的結果（RESULT_EXPIRED 或 RESULT_UNSUPPORTED）。
            detail: 寫進清單的原因。
        """
        super().__init__(detail)
        self.result = result


@dataclass
class Record:
    """下載清單的一行：一份文件的來源、本地檔案與結果。"""

    url: str
    category: str
    filename: str
    format: str
    downloaded_at: str
    sha256: str
    html_sha256: str
    result: str
    detail: str
    period: str = ""


# ==============================
# HTTP
# ==============================


class _SameDomainRedirectHandler(urllib.request.HTTPRedirectHandler):
    """只跟隨同一個網域內的轉址；轉址到其他網域時拋出 FetchError，不發出那個請求。"""

    def __init__(self, domain: str) -> None:
        """_SameDomainRedirectHandler 的建構。

        Args:
            domain: 原請求的網域（netloc，小寫）。
        """
        self.domain = domain

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """urllib 要跟隨轉址時呼叫。

        Args:
            req: 被轉址的請求。
            fp: 轉址回應。
            code: 轉址的 HTTP 狀態碼。
            msg: 狀態文字。
            headers: 回應標頭。
            newurl: 轉址目標的完整網址。

        Returns:
            跟隨轉址用的新請求；目標網域與原請求相同時才會有。

        Raises:
            FetchError: 目標網域和原請求不同。
        """
        target = urlparse(newurl).netloc
        if target.lower() != self.domain:
            fp.close()
            raise FetchError(f"{EXTERNAL_REDIRECT} {target}，不跟隨")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    """腳本自己發出的 HTTP 請求：帶 User-Agent，每個請求之間至少間隔 interval 秒；轉址只跟隨原請求的網域內。"""

    def __init__(self, interval: float) -> None:
        """Fetcher 的建構。

        Args:
            interval: 兩個請求之間至少間隔的秒數。
        """
        self.interval = interval
        self._last_end = float("-inf")

    def get(self, url: str) -> bytes:
        """GET url。

        Args:
            url: 完整網址。

        Returns:
            回應 body。網路失敗、HTTP 狀態錯誤、轉址到原請求以外的網域，或網址本身無法送出請求
            （例如路徑含 ASCII 以外的字元）時拋出 FetchError。
        """
        wait = self._last_end + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        opener = urllib.request.build_opener(_SameDomainRedirectHandler(urlparse(url).netloc.lower()))
        try:
            with opener.open(req, timeout=TIMEOUT_SEC) as resp:
                return resp.read()
        except NETWORK_ERRORS as exc:
            raise FetchError(f"下載失敗（{type(exc).__name__}: {exc}）") from exc
        except ValueError as exc:
            raise FetchError(f"網址無法送出請求（{type(exc).__name__}: {exc}）") from exc
        finally:
            self._last_end = time.monotonic()


# ==============================
# HTML 解析：連結與主內容區
# ==============================


def _has_class(attrs: list[tuple[str, str | None]], css_class: str) -> bool:
    """attrs 的 class 屬性是否含有 css_class 這個完整的 class 名稱。

    Args:
        attrs: 標籤的屬性清單。
        css_class: class 名稱。

    Returns:
        class 屬性（以空白分隔）含有 css_class 時為 True。
    """
    return css_class in (dict(attrs).get("class") or "").split()


class _AnchorCollector(HTMLParser):
    """收集 <a href>（script 與 style 的內容由 HTMLParser 當成文字，不會被解析成標籤）。

    required_class 不是 None 時，只收 class 含這個名稱的 <a>。
    """

    def __init__(self, required_class: str | None = None) -> None:
        """_AnchorCollector 的建構。

        Args:
            required_class: 只收 class 含這個名稱的 <a>；None 表示全收。
        """
        super().__init__(convert_charrefs=True)
        self.required_class = required_class
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """遇到開始標籤時記下符合條件的 <a> 的 href。

        Args:
            tag: 標籤名稱（小寫）。
            attrs: 屬性（名稱小寫，值已還原字元參照；沒有值的屬性是 None）。
        """
        if tag == "a" and (self.required_class is None or _has_class(attrs, self.required_class)):
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def resolve_href(base_url: str, href: str) -> ParseResult | None:
    """把列表頁裡的 href 解析成完整網址。

    Args:
        base_url: 列表頁網址，用來解析相對路徑。
        href: <a> 的 href 屬性。

    Returns:
        解析後的網址；href 格式錯誤（例如 `http://[bad`）時為 None，呼叫端略過這個連結，不讓整個列表失敗。
    """
    try:
        return urlparse(urljoin(base_url, href))
    except ValueError:
        return None


def find_page_links(list_html: str, list_url: str, link_pattern: re.Pattern[str]) -> list[str]:
    """從列表頁取出子頁的網址。

    Args:
        list_html: 列表頁 HTML。
        list_url: 列表頁網址，用來解析相對路徑。
        link_pattern: 子頁連結的路徑格式；選單、PDF 等其他連結不符合就不收。

    Returns:
        去除重複、保留出現順序的子頁完整網址（不含 query 與 fragment；只差 fragment 的連結是同一頁）。
        格式錯誤的 href 略過。
    """
    collector = _AnchorCollector()
    collector.feed(list_html)
    seen: dict[str, None] = {}
    for href in collector.hrefs:
        parsed = resolve_href(list_url, href)
        if parsed is not None and link_pattern.match(parsed.path) and not parsed.query:
            seen[parsed._replace(fragment="").geturl()] = None
    return list(seen)


class _MainContentFinder(HTMLParser):
    """找出第一個符合條件的元素（id 等於某值，或 class 含某個名稱），記下它的起訖位置。

    只數同名標籤的開始與結束（例如 div），所以內容裡未關閉的 <p>、<li> 不影響配對。
    """

    def __init__(self, attr: str, value: str) -> None:
        """_MainContentFinder 的建構。

        Args:
            attr: 用哪個屬性找：id 或 class。
            value: 屬性值（class 時是 class 名稱）。
        """
        super().__init__(convert_charrefs=False)
        self.attr = attr
        self.value = value
        self.tag: str | None = None
        self.depth = 0
        self.start: tuple[int, int] | None = None
        self.end: tuple[int, int] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """找到符合條件的元素就記下起點；之後數同名標籤的深度。

        Args:
            tag: 標籤名稱（小寫）。
            attrs: 屬性（名稱小寫，值已還原字元參照；沒有值的屬性是 None）。
        """
        if self.end is not None:
            return
        if self.start is None:
            if self._matches(attrs):
                self.tag, self.depth, self.start = tag, 1, self.getpos()
        elif tag == self.tag:
            self.depth += 1

    def _matches(self, attrs: list[tuple[str, str | None]]) -> bool:
        """屬性是否符合要找的主內容區。

        Args:
            attrs: 標籤的屬性清單。

        Returns:
            符合時為 True。
        """
        if self.attr == "class":
            return _has_class(attrs, self.value)
        return dict(attrs).get(self.attr) == self.value

    def handle_endtag(self, tag: str) -> None:
        """遇到結束標籤時，深度歸零就記下終點。

        Args:
            tag: 標籤名稱（小寫）。
        """
        if self.start is None or self.end is not None or tag != self.tag:
            return
        self.depth -= 1
        if self.depth == 0:
            self.end = self.getpos()


# 值是網址的屬性：值以 javascript: 開頭時整個屬性拿掉
URL_ATTRIBUTES = frozenset({"href", "src", "action", "formaction", "xlink:href", "data", "poster", "background"})
# 連同內容整個拿掉的元素
REMOVED_ELEMENTS = frozenset({"script", "style", "iframe"})


def _is_javascript_url(value: str) -> bool:
    """網址是不是 javascript: 開頭（瀏覽器解析網址時會忽略空白與控制字元，大小寫不分）。

    Args:
        value: 屬性值。

    Returns:
        移除空白與控制字元後以 javascript: 開頭（不分大小寫）時為 True。
    """
    return re.sub(r"[\x00-\x20]+", "", value).lower().startswith("javascript:")


class _ActiveContentStripper(HTMLParser):
    """把 HTML 重新輸出，拿掉會執行或載入外部內容的部分：

    - <script>、<style>、<iframe> 連同內容；
    - <link rel="stylesheet">；
    - 事件屬性（名稱以 on 開頭，例如 onclick、onerror、onload）；
    - 值是 javascript: 網址的 href、src 等屬性（只拿掉屬性，標籤與文字留著）。

    註解不輸出；其餘標籤、屬性與文字（含字元參照）照原樣輸出，所以未關閉的 <p>、<li> 不受影響。
    """

    def __init__(self) -> None:
        """_ActiveContentStripper 的建構。"""
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.removing: str | None = None
        self.removing_depth = 0

    def _open_tag(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        """輸出一個開始標籤（需要拿掉的除外）。

        Args:
            tag: 標籤名稱（小寫）。
            attrs: 屬性（名稱小寫，值已還原字元參照）。
            self_closing: 原文是不是 `<tag ... />` 的寫法。
        """
        if self.removing is not None:
            if tag == self.removing and not self_closing:
                self.removing_depth += 1
            return
        if tag in REMOVED_ELEMENTS:
            if not self_closing:
                self.removing, self.removing_depth = tag, 1
            return
        if tag == "link" and "stylesheet" in (dict(attrs).get("rel") or "").lower().split():
            return
        kept = []
        for name, value in attrs:
            if name.startswith("on") or (name in URL_ATTRIBUTES and value is not None and _is_javascript_url(value)):
                continue
            kept.append(name if value is None else f'{name}="{html.escape(value, quote=True)}"')
        self.parts.append(f"<{' '.join([tag, *kept])}{' /' if self_closing else ''}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """輸出開始標籤（需要拿掉的除外）。

        Args:
            tag: 標籤名稱（小寫）。
            attrs: 屬性（名稱小寫，值已還原字元參照；沒有值的屬性是 None）。
        """
        self._open_tag(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """輸出 `<tag ... />` 形式的標籤（需要拿掉的除外）。

        Args:
            tag: 標籤名稱（小寫）。
            attrs: 屬性（名稱小寫，值已還原字元參照；沒有值的屬性是 None）。
        """
        self._open_tag(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        """輸出結束標籤；正在拿掉的元素則依深度判斷是否結束。

        Args:
            tag: 標籤名稱（小寫）。
        """
        if self.removing is not None:
            if tag == self.removing:
                self.removing_depth -= 1
                if self.removing_depth == 0:
                    self.removing = None
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        """輸出文字（正在拿掉的元素內除外）。

        Args:
            data: 文字。
        """
        if self.removing is None:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        """輸出具名字元參照，例如 &amp;。

        Args:
            name: 參照名稱（不含 & 與 ;）。
        """
        if self.removing is None:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        """輸出數字字元參照，例如 &#169;。

        Args:
            name: 參照內容（不含 &# 與 ;）。
        """
        if self.removing is None:
            self.parts.append(f"&#{name};")


def strip_active_content(fragment: str) -> str:
    """拿掉 HTML 片段裡會執行或載入外部內容的部分（細節見 _ActiveContentStripper）。

    Args:
        fragment: HTML 片段。

    Returns:
        處理後的 HTML 片段。
    """
    stripper = _ActiveContentStripper()
    stripper.feed(fragment)
    stripper.close()
    return "".join(stripper.parts)


def extract_main_content(page_html: str, attr: str, value: str) -> str | None:
    """取出第一個符合條件的元素（含自身），並拿掉會執行或載入外部內容的部分（strip_active_content）。

    Args:
        page_html: 原始 HTML。
        attr: 主內容區用哪個屬性找：id（屬性值等於 value）或 class（class 含 value 這個名稱）。
        value: 屬性值或 class 名稱。

    Returns:
        主內容區的 HTML（不含 <script>、<style>、<iframe>、樣式表連結、事件屬性與 javascript: 網址）；
        找不到、或元素沒有結束標籤時為 None。
    """
    finder = _MainContentFinder(attr, value)
    finder.feed(page_html)
    finder.close()
    if finder.start is None or finder.end is None:
        return None
    offsets = [0]
    for line in page_html.split("\n"):
        offsets.append(offsets[-1] + len(line) + 1)
    begin = offsets[finder.start[0] - 1] + finder.start[1]
    close = offsets[finder.end[0] - 1] + finder.end[1]
    stop = page_html.index(">", close) + 1
    return strip_active_content(page_html[begin:stop])


def build_print_html(main_content: str, base_url: str) -> str:
    """把主內容區包成可列印的本機 HTML。

    Args:
        main_content: 主內容區的 HTML。
        base_url: 原網址，寫進 <base href> 讓相對路徑的圖片可以載入。

    Returns:
        完整的 HTML 文件。
    """
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<base href="{html.escape(base_url, quote=True)}">'
        f"<style>{PRINT_CSS}</style></head><body>{main_content}</body></html>"
    )


# ==============================
# 活動詳情頁：活動期間與主視覺
# ==============================

PERIOD_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})")
PERIOD_HEADING = "活動期間"
PERIOD_UNKNOWN = "期間不明"


class _PeriodFinder(HTMLParser):
    """找 <h5 class="subtitle">活動期間</h5> 後面緊接的 <p> 的文字；正文裡的其他寫法不是期間。"""

    def __init__(self) -> None:
        """_PeriodFinder 的建構。"""
        super().__init__(convert_charrefs=True)
        self.state = "idle"  # idle → in_heading → after_heading → in_period → done
        self.heading = ""
        self.text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """找 h5.subtitle，或「活動期間」標題後面緊接的 <p>。

        Args:
            tag: 標籤名稱（小寫）。
            attrs: 屬性（名稱小寫，值已還原字元參照；沒有值的屬性是 None）。
        """
        if self.state == "idle" and tag == "h5" and _has_class(attrs, "subtitle"):
            self.state, self.heading = "in_heading", ""
        elif self.state == "after_heading":
            self.state = "in_period" if tag == "p" else "idle"

    def handle_endtag(self, tag: str) -> None:
        """標題結束時確認是不是「活動期間」；<p> 結束時完成。

        Args:
            tag: 標籤名稱（小寫）。
        """
        if self.state == "in_heading" and tag == "h5":
            self.state = "after_heading" if self.heading.strip() == PERIOD_HEADING else "idle"
        elif self.state == "in_period" and tag == "p":
            self.state = "done"

    def handle_data(self, data: str) -> None:
        """收集標題或期間 <p> 的文字。

        Args:
            data: 文字。
        """
        if self.state == "in_heading":
            self.heading += data
        elif self.state == "in_period":
            self.text += data


def read_offer_period(page_html: str) -> tuple[date, date] | None:
    """從活動詳情頁讀出活動期間。

    Args:
        page_html: 活動詳情頁的 HTML。

    Returns:
        (開始日, 結束日)；找不到「活動期間」標題後的 <p>、格式不是 YYYY-MM-DD~YYYY-MM-DD 或日期不存在時為 None。
    """
    finder = _PeriodFinder()
    finder.feed(page_html)
    finder.close()
    match = PERIOD_PATTERN.fullmatch(finder.text.strip())
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))
    except ValueError:
        return None


class _BannerFinder(HTMLParser):
    """找 div.banner-image 裡的第一個 <img> 的 src；沒有這個 div 就沒有主視覺（內容區第一張圖是分享圖示）。"""

    def __init__(self) -> None:
        """_BannerFinder 的建構。"""
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.src: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """進入 div.banner-image 後記下第一個 <img> 的 src。

        Args:
            tag: 標籤名稱（小寫）。
            attrs: 屬性（名稱小寫，值已還原字元參照；沒有值的屬性是 None）。
        """
        if self.src is not None:
            return
        if self.depth == 0:
            if tag == "div" and _has_class(attrs, "banner-image"):
                self.depth = 1
        elif tag == "div":
            self.depth += 1
        elif tag == "img":
            self.src = (dict(attrs).get("src") or "").strip() or None

    def handle_endtag(self, tag: str) -> None:
        """離開 div 時減少深度。

        Args:
            tag: 標籤名稱（小寫）。
        """
        if self.depth > 0 and tag == "div":
            self.depth -= 1


def find_banner_src(page_html: str) -> str | None:
    """取出活動詳情頁主視覺（div.banner-image 裡的 <img>）的 src。

    Args:
        page_html: 活動詳情頁的 HTML。

    Returns:
        src 屬性（可能是相對路徑）；沒有 div.banner-image、裡面沒有 <img> 或 src 為空時為 None。
    """
    finder = _BannerFinder()
    finder.feed(page_html)
    finder.close()
    return finder.src


def period_label(period: tuple[date, date] | None) -> str:
    """清單的活動期間欄：讀得出來是 YYYY-MM-DD~YYYY-MM-DD，讀不出來是 PERIOD_UNKNOWN。

    Args:
        period: read_offer_period 的結果。

    Returns:
        清單的 period 欄的值。
    """
    return PERIOD_UNKNOWN if period is None else f"{period[0].isoformat()}~{period[1].isoformat()}"


# ==============================
# 轉檔
# ==============================


def print_to_pdf(chrome: str, html_path: Path, pdf_path: Path, work_dir: Path) -> None:
    """用 headless Chrome 把本機 HTML 檔列印成 PDF，使用暫時的使用者資料夾，資料夾的設定封鎖 JavaScript。

    Args:
        chrome: Chrome 執行檔路徑。
        html_path: 要列印的本機 HTML 檔。
        pdf_path: 最終 PDF 路徑；列印成功才會出現。
        work_dir: 放暫時資料夾的位置（與 pdf_path 同一個檔案系統）。

    Raises:
        FetchError: Chrome 不存在、列印失敗、逾時或沒有產出 PDF。
    """
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        tmp_pdf = Path(tmp) / "page.pdf"
        profile = Path(tmp) / "profile"
        (profile / "Default").mkdir(parents=True)
        (profile / "Default" / "Preferences").write_text(json.dumps(CHROME_PREFERENCES), encoding="utf-8")
        command = [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={tmp_pdf}",
            html_path.resolve().as_uri(),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=CHROME_TIMEOUT_SEC)
        except subprocess.TimeoutExpired as exc:
            raise FetchError(f"Chrome 列印逾時（{CHROME_TIMEOUT_SEC} 秒）") from exc
        except OSError as exc:
            raise FetchError(
                f"無法執行 Chrome（{chrome}）：{exc}；用環境變數 {CHROME_ENV} 指定 Chrome 執行檔的路徑"
            ) from exc
        if completed.returncode != 0:
            raise FetchError(f"Chrome 列印失敗（結束碼 {completed.returncode}）：{completed.stderr.strip()[-300:]}")
        if not tmp_pdf.is_file() or tmp_pdf.stat().st_size == 0:
            raise FetchError("Chrome 結束碼為 0，但沒有產出 PDF")
        tmp_pdf.replace(pdf_path)


def find_office() -> str | None:
    """在 PATH 上依序找 libreoffice、soffice（沿用 RAG-Anything 的找法）。

    Returns:
        第一個找到的命令路徑；都找不到時為 None。
    """
    for name in OFFICE_COMMANDS:
        found = shutil.which(name)
        if found:
            return found
    return None


def convert_to_docx(office: str | None, html_path: Path, docx_path: Path, work_dir: Path) -> None:
    """用 LibreOffice 把本機 HTML 檔轉成 .docx，使用暫時的 user profile。

    不指定 profile 時，使用者開著 LibreOffice 的話，headless 轉檔會結束碼 0 但沒有產出。

    Args:
        office: LibreOffice 命令路徑；None 表示 PATH 上找不到。
        html_path: 要轉檔的本機 HTML 檔；LibreOffice 輸出的檔名由它的主檔名決定。
        docx_path: 最終 .docx 路徑（主檔名必須和 html_path 相同）；轉檔成功才會出現。
        work_dir: 放暫時資料夾的位置（與 docx_path 同一個檔案系統）。

    Raises:
        FetchError: 找不到 LibreOffice、轉檔失敗、逾時或沒有產出 .docx。
    """
    if office is None:
        raise FetchError(f"找不到 LibreOffice（PATH 上沒有 {' 或 '.join(OFFICE_COMMANDS)}）")
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        profile = (Path(tmp) / "profile").resolve().as_uri()
        command = [
            office,
            f"-env:UserInstallation={profile}",
            "--headless",
            "--convert-to",
            DOCX_TARGET,
            "--outdir",
            tmp,
            str(html_path.resolve()),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=OFFICE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired as exc:
            raise FetchError(f"LibreOffice 轉檔逾時（{OFFICE_TIMEOUT_SEC} 秒）") from exc
        except OSError as exc:
            raise FetchError(f"無法執行 LibreOffice（{office}）：{exc}") from exc
        if completed.returncode != 0:
            raise FetchError(
                f"LibreOffice 轉檔失敗（結束碼 {completed.returncode}）：{completed.stderr.strip()[-300:]}"
            )
        tmp_docx = Path(tmp) / docx_path.name
        if not tmp_docx.is_file() or tmp_docx.stat().st_size == 0:
            raise FetchError("LibreOffice 結束碼為 0，但沒有產出 .docx")
        tmp_docx.replace(docx_path)


# ==============================
# 一次執行共用的東西與類別
# ==============================


@dataclass(frozen=True)
class Tools:
    """轉檔用的外部命令：Chrome 的路徑，以及 PATH 上找到的 LibreOffice（找不到為 None）。"""

    chrome: str
    office: str | None


@dataclass(frozen=True)
class Run:
    """一次執行共用的設定：資料根目錄、三個官網網域的前綴、發請求的物件、轉檔工具、下載當天，以及各類別找到的網址。

    today 在一次執行開始時取一次（本機日期），活動是否過期、清單的下載日期都用它，所以執行跨過午夜時前後一致。

    update 是更新模式（--update）：已存在而且類別有 refresh 的文件，重新下載後比對內容，不同才換掉。

    found 是類別名稱對網址清單，main 在每個類別的 collect 之後填入，讓後面的類別（活動圖片）
    能用前面類別（活動）找到的網址。

    previous_banners 只在更新模式用：活動詳情頁網址對「這次重新取得之前，存檔的原始 HTML 裡的主視覺網址」
    （沒有主視覺為 None），fetch_document 在比對每個已有文件的活動之前填入，讓活動圖片找出主視覺網址變了的活動。
    """

    out: Path
    www: str
    mkpcard: str
    mkp: str
    fetcher: Fetcher
    tools: Tools
    today: date
    update: bool
    found: dict[str, list[str]] = field(default_factory=dict)
    previous_banners: dict[str, str | None] = field(default_factory=dict)

    def base(self, site: str) -> str:
        """網域代號對應的網址前綴。

        Args:
            site: 網域代號：www、mkpcard 或 mkp。

        Returns:
            該網域這次執行用的前綴（預設是官網，環境變數替換後是替換值）。
        """
        return {"www": self.www, "mkpcard": self.mkpcard, "mkp": self.mkp}[site]

    def to_mkp(self, absolute: str) -> str:
        """指向官網 mkp 網域的網址，換成這次執行的 mkp 前綴（和活動詳情頁連結的處理一樣）；其他網域原樣回傳。

        Args:
            absolute: 完整網址。

        Returns:
            網域是官網 mkp（MKP_PREFIX）時，換成 self.mkp 加上原本的路徑與 query；否則是 absolute 本身。
        """
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != urlparse(MKP_PREFIX).netloc:
            return absolute
        return self.mkp + urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))


@dataclass(frozen=True)
class Category:
    """一個類別：從哪個列表頁找文件、文件怎麼取得、放在哪個資料夾。

    list_site 是列表頁所在的網域代號（www 或 mkpcard），list_path 接在該網域的前綴後面。

    collect 的參數是 (執行設定, 類別)，回傳文件的完整網址（去除重複、保留順序），列表頁失敗時拋出 FetchError。
    produce 的參數是 (執行設定, 類別, 網址, 本地名稱, 最終檔案, 清單紀錄)，把文件寫到最終檔案、
    補上紀錄的 html_sha256（有原始 HTML 的類別），失敗時拋出 FetchError。
    refresh 只在更新模式下用在本地已有的文件，參數同 produce，回傳 True 表示內容變了、最終檔案已換成新內容，
    False 表示沒變、最終檔案原封不動；失敗時拋出 FetchError，而且最終檔案不動。活動頁的 refresh 在期間已過期時拋出
    SkipDocument（檔案不動），權益附件的 refresh 在網址已在文件下載區時拋出 SkipDocument（重複），由 fetch_document 把文件搬走。None 表示這個類別的更新模式不比對內容（活動圖片：已存在就略過，去留由 remove_unreferenced_images 判斷）。
    local_name 由 name_prefix 和 link_pattern 的各個群組以底線接起來，例如卡片 card_cg047_card001。
    extension 是 None 時，副檔名取自文件網址路徑的最後一個副檔名（小寫），活動圖片是這樣。
    """

    name: str
    list_label: str
    list_name: str
    list_site: str
    list_path: str
    link_pattern: re.Pattern[str]
    expected_count: int | None
    unit: str
    name_prefix: str
    folder: str
    extension: str | None
    fmt: str
    keeps_html: bool
    reads_period: bool
    collect: Callable[["Run", "Category"], list[str]]
    produce: Callable[["Run", "Category", str, str, Path, "Record"], None]
    refresh: Callable[["Run", "Category", str, str, Path, "Record"], bool] | None

    def local_name(self, url: str) -> str:
        """由文件網址組出本地檔名（不含副檔名）。

        路徑先做百分比解碼，字母、數字、底線、. 與 - 以外的字元換成底線。

        Args:
            url: 文件完整網址；路徑必須符合 link_pattern。

        Returns:
            name_prefix 和 link_pattern 的各個群組以底線接起來的名稱，例如 card_cg047_card001。
        """
        match = self.link_pattern.match(unquote(urlparse(url).path))
        assert match is not None, url
        parts = (re.sub(r"[^\w.-]", "_", group) for group in match.groups())
        return "_".join((self.name_prefix, *parts))

    def extension_of(self, url: str) -> str:
        """文件的副檔名（不含點、小寫）。

        Args:
            url: 文件完整網址。

        Returns:
            類別固定一種格式時是 extension；否則取自網址路徑的最後一個副檔名，字母、數字、底線、- 以外的字元換成底線。
        """
        if self.extension is not None:
            return self.extension
        return re.sub(r"[^\w-]", "_", Path(unquote(urlparse(url).path)).suffix.removeprefix(".").lower())

    def local_names(self, urls: list[str]) -> dict[str, str]:
        """為一批網址組出本地檔名；檔名相同（不分大小寫）的網址都加上完整網址的 SHA-256 前 8 碼。

        Args:
            urls: 這個類別的文件網址。

        Returns:
            網址對本地檔名（不含副檔名）；值在整批中不重複。
        """
        names = {url: self.local_name(url) for url in urls}
        counts = Counter(name.lower() for name in names.values())
        return {
            url: name if counts[name.lower()] == 1 else f"{name}_{hashlib.sha256(url.encode()).hexdigest()[:8]}"
            for url, name in names.items()
        }


# ==============================
# 列表頁與取得文件
# ==============================


def decode_page(raw: bytes) -> str:
    """把頁面的位元組解成 UTF-8 文字。

    Args:
        raw: 回應 body。

    Returns:
        頁面文字。不是 UTF-8 時拋出 FetchError。
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError(f"頁面不是 UTF-8（{exc}）") from exc


def sha256_of(path: Path) -> str:
    """檔案內容的 SHA-256。

    Args:
        path: 檔案路徑。

    Returns:
        十六進位字串。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saved_html(path: Path) -> str:
    """讀本腳本存下來的原始 HTML。

    Args:
        path: _meta/html/ 底下的檔案。

    Returns:
        檔案內容；不是 UTF-8 的位元組以替代字元顯示，不拋出錯誤（存檔前 decode_page 已確認是 UTF-8）。
    """
    return path.read_bytes().decode("utf-8", errors="replace")


def collect_from_one_page(run: Run, category: Category) -> list[str]:
    """從單一列表頁取出子頁網址（卡片、權益）。

    Args:
        run: 一次執行共用的設定。
        category: 要找文件的類別。

    Returns:
        子頁完整網址。列表頁失敗時拋出 FetchError。
    """
    list_url = run.base(category.list_site) + category.list_path
    return find_page_links(decode_page(run.fetcher.get(list_url)), list_url, category.link_pattern)


def request_url(absolute: str) -> str:
    """把完整網址整理成可以送出請求的形式。

    Args:
        absolute: 完整網址。

    Returns:
        路徑與 query 中 ASCII 以外的字元已做百分比編碼（已編碼的 % 與 query 的分隔符號保持原樣）、去掉 fragment 的網址。
    """
    parsed = urlparse(absolute)
    return urlunparse(
        parsed._replace(path=quote(parsed.path, safe="/%"), query=quote(parsed.query, safe=QUERY_SAFE), fragment="")
    )


def find_pdf_links(list_html: str, list_url: str, link_pattern: re.Pattern[str]) -> list[str]:
    """從文件下載頁取出 PDF 的網址。

    Args:
        list_html: 下載頁 HTML。
        list_url: 下載頁網址，用來解析相對路徑，也限定只收同一個網域。
        link_pattern: PDF 連結的路徑格式。

    Returns:
        去除重複、保留出現順序的 PDF 完整網址；路徑與 query 中 ASCII 以外的字元已做百分比編碼，網址才能送出請求。
        格式錯誤的 href 略過。
    """
    collector = _AnchorCollector()
    collector.feed(list_html)
    host = urlparse(list_url).netloc
    seen: dict[str, None] = {}
    for href in collector.hrefs:
        parsed = resolve_href(list_url, href)
        if parsed is not None and parsed.netloc == host and link_pattern.match(parsed.path):
            seen[request_url(parsed.geturl())] = None
    return list(seen)


def walk_pages(
    fetcher: Fetcher,
    page_url: Callable[[int], str],
    find_links: Callable[[str, str], list[str]],
    max_pages: int,
    what: str,
) -> list[str]:
    """從第 1 頁往後翻，直到某一頁沒有新連結為止（文件下載區與刷卡優惠列表共用）。

    停止條件是「沒有新連結」：文件下載區超過最後一頁時重複最後一頁，刷卡優惠列表則回空清單，兩者都適用。

    Args:
        fetcher: 發請求的物件。
        page_url: 頁碼（從 1 起）對網址。
        find_links: (頁面 HTML, 頁面網址) 對這一頁的連結清單。
        max_pages: 翻頁上限。
        what: 連結的名稱，只用在翻滿上限的錯誤訊息。

    Returns:
        所有頁面的連結（去除重複、保留出現順序）。任何一頁失敗，或翻滿 max_pages 頁仍有新連結時拋出 FetchError。
    """
    found: dict[str, None] = {}
    for number in range(1, max_pages + 1):
        url = page_url(number)
        try:
            page_links = find_links(decode_page(fetcher.get(url)), url)
        except FetchError as exc:
            raise FetchError(f"第 {number} 頁（{url}）：{exc}") from exc
        new = [link for link in page_links if link not in found]
        if not new:
            return list(found)
        found.update(dict.fromkeys(new))
    raise FetchError(f"翻到上限 {max_pages} 頁仍有新的{what}，停止翻頁")


def collect_from_paged_downloads(run: Run, category: Category) -> list[str]:
    """從文件下載頁的第 1 頁往後翻，直到某一頁沒有新的 PDF 連結為止。

    Args:
        run: 一次執行共用的設定。
        category: 文件下載類別；list_path 含 query，翻頁時在後面加 &page=N。

    Returns:
        所有頁面的 PDF 完整網址（去除重複）。任何一頁失敗，或翻滿 DOWNLOAD_MAX_PAGES 頁仍有新的 PDF 時拋出 FetchError。
    """
    list_url = run.base(category.list_site) + category.list_path
    return walk_pages(
        run.fetcher,
        lambda number: f"{list_url}&page={number}",
        lambda page, url: find_pdf_links(page, url, category.link_pattern),
        DOWNLOAD_MAX_PAGES,
        " PDF 連結",
    )


def find_offer_links(list_html: str, list_url: str, link_pattern: re.Pattern[str], mkp: str) -> list[str]:
    """從刷卡優惠列表的一頁取出活動詳情頁的網址。

    只收 class 含 card-holder 的 <a>（頁頂輪播的 a.btn-slide 不收，見已知極限）。連結可能是相對路徑
    （解析到 mkpcard），也可能是指向 mkp 的絕對網址；兩者都只取路徑，接在 mkp 的前綴後面。

    Args:
        list_html: 列表頁 HTML。
        list_url: 列表頁網址，用來解析相對路徑。
        link_pattern: 活動詳情頁的路徑格式。
        mkp: mkp 網域的前綴。

    Returns:
        去除重複、保留出現順序的活動詳情頁完整網址（mkp 上，不含 query）。格式錯誤的 href 略過。
    """
    collector = _AnchorCollector("card-holder")
    collector.feed(list_html)
    seen: dict[str, None] = {}
    for href in collector.hrefs:
        parsed = resolve_href(list_url, href)
        if parsed is not None and link_pattern.match(parsed.path) and not parsed.query:
            seen[mkp + parsed.path] = None
    return list(seen)


def collect_offers(run: Run, category: Category) -> list[str]:
    """翻完刷卡優惠的分類 A–I，每類都從第 1 頁往後翻到沒有新連結為止（GET ?page=N）。

    Args:
        run: 一次執行共用的設定。
        category: 活動類別；list_path 是分類頁網址去掉分類字母的部分。

    Returns:
        所有分類的活動詳情頁網址（去除重複、保留發現順序）。任何一頁失敗，或某分類翻滿 OFFER_MAX_PAGES 頁
        仍有新連結時拋出 FetchError，訊息指出是哪個分類。
    """
    found: dict[str, None] = {}
    for letter in OFFER_CATEGORIES:
        list_url = f"{run.base(category.list_site)}{category.list_path}{letter}"
        try:
            links = walk_pages(
                run.fetcher,
                lambda number: f"{list_url}?page={number}",
                lambda page, url: find_offer_links(page, url, category.link_pattern, run.mkp),
                OFFER_MAX_PAGES,
                "活動連結",
            )
        except FetchError as exc:
            raise FetchError(f"分類 {letter}：{exc}") from exc
        found.update(dict.fromkeys(links))
    return list(found)


def web_page_producer(
    convert: Callable[[Tools, Path, Path, Path], None],
    main_content: tuple[str, str] = ("id", "centercontainer"),
    inspect: Callable[[Record, str], None] | None = None,
) -> Callable[[Run, Category, str, str, Path, Record], None]:
    """產生「下載網頁、取出主內容區、轉檔」的 produce 函式。

    Args:
        convert: 轉檔函式，參數是 (工具, 本機 HTML, 最終檔案, 暫時資料夾的位置)，失敗時拋出 FetchError。
        main_content: 主內容區怎麼找，(屬性, 值)，傳給 extract_main_content；預設是 id="centercontainer"。
        inspect: 原始 HTML 存檔後、取主內容區前呼叫，參數是 (清單紀錄, 頁面文字)；可以補紀錄，
            或拋出 SkipDocument 讓這一頁不轉檔。

    Returns:
        可放進 Category.produce 的函式。
    """

    def produce(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> None:
        """下載網頁、存原始 HTML、取出主內容區、轉檔成 target。

        Args:
            run: 一次執行共用的設定。
            category: 這個網頁所屬的類別（未使用，為了符合 Category.produce 的參數）。
            url: 網頁完整網址。
            name: 本地名稱（不含副檔名）。
            target: 最終檔案路徑。
            record: 清單紀錄；補上 html_sha256，inspect 也可能補其他欄位。

        Raises:
            FetchError: 下載失敗、頁面不是 UTF-8、找不到主內容區或轉檔失敗。
            SkipDocument: inspect 判斷這一頁不下載。
        """
        raw_path = run.out / "_meta" / "html" / f"{name}.html"
        print_path = run.out / "_meta" / "print" / f"{name}.html"
        for folder in (raw_path.parent, print_path.parent):
            folder.mkdir(parents=True, exist_ok=True)
        raw = run.fetcher.get(url)
        raw_path.write_bytes(raw)
        record.html_sha256 = hashlib.sha256(raw).hexdigest()
        page = decode_page(raw)
        if inspect is not None:
            inspect(record, page)
        content = extract_main_content(page, *main_content)
        if content is None:
            raise FetchError("找不到主內容區")
        print_path.write_text(build_print_html(content, url), encoding="utf-8")
        convert(run.tools, print_path, target, run.out / "_meta")

    return produce


def web_page_refresher(
    convert: Callable[[Tools, Path, Path, Path], None],
    main_content: tuple[str, str] = ("id", "centercontainer"),
    inspect: Callable[[Record, str], None] | None = None,
    also_compare: Callable[[Run, str, str], object] | None = None,
) -> Callable[[Run, Category, str, str, Path, Record], bool]:
    """產生更新模式的 refresh 函式：重新取得網頁，主內容區和存檔的上一份不同才重新轉檔。

    Args:
        convert: 轉檔函式，同 web_page_producer。
        main_content: 主內容區怎麼找，必須和同一個類別的 web_page_producer 相同，比對的就是轉檔實際用的那一塊。
        also_compare: 主內容區以外還要比對的東西，參數是 (執行設定, 網頁網址, 頁面文字)，回傳可比較相等的值；
            新舊頁面的值不同也算變更（活動頁用它比主視覺網址，主視覺在主內容區外面；grill Q30）。
        inspect: 取得頁面、比對前呼叫，參數是 (清單紀錄, 頁面文字)；可以補紀錄，或拋出 SkipDocument 讓這一頁不比對、不轉檔
            （活動頁用它補活動期間並判斷過期，同 web_page_producer 的 inspect）。

    Returns:
        可放進 Category.refresh 的函式。
    """

    def refresh(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> bool:
        """重新取得網頁並比對主內容區；不同才轉檔，轉檔成功後才換掉文件、列印用 HTML 與存檔的原始 HTML。

        比對的是 extract_main_content 的結果（轉檔實際用的那一塊）加上 also_compare 指定的東西，所以其餘的差異
        （例如 <head> 的 _csrf token）不算變更，存檔的原始 HTML 也不換。存檔的原始 HTML 不存在（無法比對）時視為變更。
        換檔的順序是文件、列印用 HTML、原始 HTML：原始 HTML 是下次比對的基準，最後換，中途中斷時下次還會比對到差異並重試。

        Args:
            run: 一次執行共用的設定。
            category: 這個網頁所屬的類別（未使用，為了符合 Category.refresh 的參數）。
            url: 網頁完整網址。
            name: 本地名稱（不含副檔名）。
            target: 文件路徑（已存在）。
            record: 清單紀錄；補上 html_sha256，inspect 也可能補其他欄位（活動頁的 period）。

        Returns:
            主內容區變了、文件已換成新內容時為 True；沒變、三個檔案都原封不動時為 False。

        Raises:
            FetchError: 下載失敗、頁面不是 UTF-8、找不到主內容區或轉檔失敗；三個檔案都不動。
            SkipDocument: inspect 判斷這一頁不處理；三個檔案都不動。
        """
        raw_path = run.out / "_meta" / "html" / f"{name}.html"
        print_path = run.out / "_meta" / "print" / f"{name}.html"
        raw = run.fetcher.get(url)
        page = decode_page(raw)
        if inspect is not None:
            inspect(record, page)
        content = extract_main_content(page, *main_content)
        if content is None:
            raise FetchError("找不到主內容區")
        if raw_path.is_file():
            saved = saved_html(raw_path)
            if extract_main_content(saved, *main_content) == content and (
                also_compare is None or also_compare(run, url, saved) == also_compare(run, url, page)
            ):
                record.html_sha256 = sha256_of(raw_path)
                return False
        for folder in (raw_path.parent, print_path.parent):
            folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=run.out / "_meta") as tmp:
            new_raw = Path(tmp) / "raw.html"
            # 暫時的列印用 HTML 與文件要和最終檔案同名：LibreOffice 輸出的檔名由 HTML 的主檔名決定
            new_print = Path(tmp) / print_path.name
            new_target = Path(tmp) / target.name
            new_raw.write_bytes(raw)
            new_print.write_text(build_print_html(content, url), encoding="utf-8")
            convert(run.tools, new_print, new_target, run.out / "_meta")
            new_target.replace(target)
            new_print.replace(print_path)
            new_raw.replace(raw_path)
        record.html_sha256 = hashlib.sha256(raw).hexdigest()
        return True

    return refresh


def download_pdf(run: Run, url: str) -> bytes:
    """下載 PDF，確認檔頭是 %PDF-。

    Args:
        run: 一次執行共用的設定。
        url: PDF 完整網址。

    Returns:
        PDF 的位元組。

    Raises:
        FetchError: 下載失敗，或內容不是以 %PDF- 開頭（例如伺服器回了錯誤頁的 HTML）。
    """
    data = run.fetcher.get(url)
    if not data.startswith(PDF_MAGIC):
        raise FetchError(f"下載的內容不是 PDF（開頭不是 {PDF_MAGIC.decode()}，共 {len(data)} bytes）")
    return data


def write_pdf(run: Run, data: bytes, target: Path) -> None:
    """先寫暫時檔，成功才換成最終檔案。

    Args:
        run: 一次執行共用的設定（暫時檔放在 _meta 底下，與最終檔案同一個檔案系統）。
        data: PDF 的位元組。
        target: 最終檔案路徑。
    """
    with tempfile.TemporaryDirectory(dir=run.out / "_meta") as tmp:
        tmp_pdf = Path(tmp) / "download.pdf"
        tmp_pdf.write_bytes(data)
        tmp_pdf.replace(target)


def save_pdf(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> None:
    """下載 PDF，確認檔頭是 %PDF- 後原樣存檔（先寫暫時檔，成功才換成最終檔案）。

    Args:
        run: 一次執行共用的設定。
        category: PDF 所屬的類別（未使用，為了符合 Category.produce 的參數）。
        url: PDF 完整網址。
        name: 本地名稱（未使用，為了符合 Category.produce 的參數）。
        target: 最終檔案路徑。
        record: 清單紀錄（PDF 沒有原始 HTML，不改它）。

    Raises:
        FetchError: 下載失敗，或內容不是以 %PDF- 開頭（例如伺服器回了錯誤頁的 HTML）。
    """
    write_pdf(run, download_pdf(run, url), target)


def refresh_pdf(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> bool:
    """更新模式：重新下載 PDF 並比對 SHA-256，內容不同才換掉原檔；相同時不碰原檔（修改時間不變）。

    Args:
        run: 一次執行共用的設定。
        category: PDF 所屬的類別（未使用，為了符合 Category.refresh 的參數）。
        url: PDF 完整網址。
        name: 本地名稱（未使用，為了符合 Category.refresh 的參數）。
        target: 原檔路徑（已存在）。
        record: 清單紀錄（PDF 沒有原始 HTML，不改它）。

    Returns:
        內容變了、原檔已換成新內容時為 True；沒變時為 False。

    Raises:
        FetchError: 下載失敗，或內容不是以 %PDF- 開頭；原檔不動。
    """
    data = download_pdf(run, url)
    if hashlib.sha256(data).hexdigest() == sha256_of(target):
        return False
    write_pdf(run, data, target)
    return True


def download_area_duplicate(run: Run, url: str) -> SkipDocument | None:
    """附件的網址若和文件下載區找到的相同，回傳「重複略過」。

    Args:
        run: 一次執行共用的設定（found 裡要有文件下載區找到的網址；下載區的列表失敗時沒有，無法判斷重複）。
        url: 附件 PDF 的完整網址。

    Returns:
        重複時是 result 為 RESULT_DUPLICATE、訊息寫出它在下載區的檔名的 SkipDocument（交給呼叫端拋出）；否則為 None。
    """
    downloads = run.found.get(DOWNLOADS.name, [])
    if url not in downloads:
        return None
    in_downloads = f"{DOWNLOADS.local_names(downloads)[url]}.{DOWNLOADS.extension_of(url)}"
    return SkipDocument(RESULT_DUPLICATE, f"同一個網址已在文件下載區，檔名 {in_downloads}")


def refresh_attachment(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> bool:
    """更新模式的權益附件：和文件下載區重複就略過，否則同 refresh_pdf（重新下載並比對 SHA-256）。

    ASSUMPTION：已存在的附件若網址現在也在文件下載區，它的內容已由下載區那一份匯入，不搬走的話同一份 PDF 會在知識庫裡兩次，
    所以由 fetch_document 記「重複略過」並把它當成下架搬走（不請求）。

    Args:
        run: 一次執行共用的設定。
        category: 權益附件類別。
        url: PDF 完整網址。
        name: 本地名稱。
        target: 原檔路徑（已存在）。
        record: 清單紀錄。

    Returns:
        內容變了、原檔已換成新內容時為 True；沒變時為 False。

    Raises:
        SkipDocument: 和文件下載區找到的網址相同（不請求，檔案不動）。
        FetchError: 下載失敗，或內容不是以 %PDF- 開頭；原檔不動。
    """
    duplicate = download_area_duplicate(run, url)
    if duplicate is not None:
        raise duplicate
    return refresh_pdf(run, category, url, name, target, record)


def save_attachment(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> None:
    """權益子頁連到的 PDF：只收官網（www）網域的，其他網域略過；文件下載區已有的同一個網址也略過；
    通過後和下載區的 PDF 一樣原樣存檔（save_pdf）。

    Args:
        run: 一次執行共用的設定。
        category: 權益附件類別。
        url: PDF 完整網址。
        name: 本地名稱。
        target: 最終檔案路徑。
        record: 清單紀錄。

    Raises:
        SkipDocument: 網址不在官網網域，或和文件下載區找到的網址相同（都不請求）。
        FetchError: save_pdf 的失敗：下載失敗，或內容不是以 %PDF- 開頭。
    """
    host, www_host = urlparse(url).netloc.lower(), urlparse(run.www).netloc.lower()
    if host != www_host:
        raise SkipDocument(RESULT_EXTERNAL, f"外部網域 {host}（官網網域是 {www_host}），不下載")
    duplicate = download_area_duplicate(run, url)
    if duplicate is not None:
        raise duplicate
    save_pdf(run, category, url, name, target, record)


def collect_attachments(run: Run, category: Category) -> list[str]:
    """從權益子頁存下來的原始 HTML 取出 PDF 連結（不重新請求子頁）。

    本次下載的子頁與已存在而略過的子頁都處理：只要 _meta/html 有那一頁的原始 HTML 就讀。
    整頁的連結都看，不只主內容區（2026-10-30 的樣本中兩者的 PDF 連結完全相同）。
    連結以子頁網址解析，路徑以 .pdf 結尾（不分大小寫）的才收；同一個網址連在很多頁只算一次。

    Args:
        run: 一次執行共用的設定（found 裡要有權益類別找到的網址）。
        category: 權益附件類別。

    Returns:
        PDF 的完整網址（去除重複、保留發現順序），包含外部網域與下載區已有的網址，由 produce 決定略過。
        權益頁列表失敗時為空：那個失敗已經回報過。
    """
    page_urls = run.found.get(RIGHTS.name, [])
    names = RIGHTS.local_names(page_urls)
    found: dict[str, None] = {}
    for page_url in page_urls:
        raw_path = run.out / "_meta" / "html" / f"{names[page_url]}.html"
        if not raw_path.is_file():
            continue
        collector = _AnchorCollector()
        collector.feed(saved_html(raw_path))
        for href in collector.hrefs:
            parsed = resolve_href(page_url, href)
            if parsed is not None and category.link_pattern.match(parsed.path):
                found[request_url(parsed.geturl())] = None
    return list(found)


# 圖片檔頭（magic bytes）：副檔名對檢查函式。清單內每個副檔名都要有檢查，沒有的當成失敗，不放行
IMAGE_SIGNATURES: dict[str, Callable[[bytes], bool]] = {
    ".png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda data: data.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    ".bmp": lambda data: data.startswith(b"BM"),
    ".gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
    ".tiff": lambda data: data.startswith((b"II*\x00", b"MM\x00*")),
    ".tif": lambda data: data.startswith((b"II*\x00", b"MM\x00*")),
    ".webp": lambda data: data[:4] == b"RIFF" and data[8:12] == b"WEBP",
}


def banner_of(run: Run, activity_url: str, page_html: str) -> str | None:
    """活動詳情頁的主視覺網址。

    Args:
        run: 一次執行共用的設定。
        activity_url: 活動詳情頁的完整網址（主視覺是相對路徑時的基準）。
        page_html: 活動詳情頁的 HTML。

    Returns:
        主視覺的完整網址（指向官網 mkp 網域的換成這次執行的 mkp 前綴）；頁面沒有主視覺為 None。
    """
    src = find_banner_src(page_html)
    return None if src is None else request_url(run.to_mkp(urljoin(activity_url, src)))


def live_banners(run: Run) -> dict[str, str | None]:
    """活動文件仍在的活動，各自的主視覺網址。

    讀的是本地現況：活動 PDF 與存下來的原始 HTML 都在才算（原始 HTML 是主視覺網址的來源）。
    指向官網 mkp 網域的絕對網址，換成這次執行的 mkp 前綴（Run.to_mkp）。

    Args:
        run: 一次執行共用的設定（found 裡要有活動類別找到的網址）。

    Returns:
        活動詳情頁網址對主視覺的完整網址（頁面沒有主視覺時為 None），依活動被找到的順序。
        活動列表失敗時為空：那個失敗已經回報過。
    """
    activity_urls = run.found.get(ACTIVITIES.name, [])
    names = ACTIVITIES.local_names(activity_urls)
    live: dict[str, str | None] = {}
    for url in activity_urls:
        pdf_path = run.out / ACTIVITIES.folder / f"{names[url]}.{ACTIVITIES.extension_of(url)}"
        raw_path = run.out / "_meta" / "html" / f"{names[url]}.html"
        if not (pdf_path.is_file() and raw_path.is_file()):
            continue
        live[url] = banner_of(run, url, saved_html(raw_path))
    return live


def banner_universe(run: Run) -> list[str]:
    """活動文件仍在的活動的主視覺網址（去除重複，依活動被找到的順序）；活動圖片的本地檔名都以這一組網址算。

    檔名取決於整批網址（兩個網址的檔名相同時都加雜湊後綴），所以下載、名額判斷與孤兒圖片判斷必須用同一組網址，
    不能一個用全部、一個只用這次要下載的子集合，否則同一張圖在不同地方的檔名不同。

    Args:
        run: 一次執行共用的設定（found 裡要有活動類別找到的網址）。

    Returns:
        主視覺的完整網址；活動列表失敗時為空。
    """
    return list(dict.fromkeys(banner for banner in live_banners(run).values() if banner is not None))


def local_names_for(run: Run, category: Category, urls: list[str]) -> dict[str, str]:
    """這次要處理的網址的本地檔名；活動圖片用 banner_universe 算，其他類別用 urls 本身。

    Args:
        run: 一次執行共用的設定。
        category: 要處理的類別。
        urls: 這次要處理的網址（活動圖片時是 banner_universe 的子集合）。

    Returns:
        網址對本地檔名（不含副檔名）。
    """
    if category is IMAGES:
        return IMAGES.local_names(banner_universe(run))
    return category.local_names(urls)


def replaced_banners(run: Run, live: dict[str, str | None]) -> set[str]:
    """主視覺網址變了、而且新網址的本地檔名和舊網址的一樣的主視覺網址。

    只有資料夾或 query 不同、檔名相同的新舊網址，衍生出的本地檔名一樣：本地那個檔案是舊圖，不是新圖，
    不能因為「檔案已存在」就略過。舊網址的檔名以它單獨存在時的檔名算（舊網址不在現在的主視覺網址裡了）；
    它若和別的主視覺網址同名，新網址會因此加雜湊後綴，檔名就不一樣，不在這裡。

    Args:
        run: 一次執行共用的設定（previous_banners 是重新取得之前存檔的主視覺網址）。
        live: live_banners 的結果。

    Returns:
        新的主視覺網址的集合；沒有主視覺網址變動的活動時為空。
    """
    names = IMAGES.local_names(banner_universe(run))
    replaced: set[str] = set()
    for activity, banner in live.items():
        previous = run.previous_banners.get(activity)
        if banner is None or previous is None or previous == banner:
            continue
        if document_filename(IMAGES, banner, names[banner]) == document_filename(
            IMAGES, previous, IMAGES.local_name(previous)
        ):
            replaced.add(banner)
    return replaced


def remove_replaced_images(run: Run, urls: list[str]) -> list[Record]:
    """更新模式：主視覺網址變了、但新舊網址的本地檔名相同的活動，把本地的舊圖搬到 DIR/_meta/removed/<日期>/offer_images/。

    搬走之後，新圖在下載時才不會被當成「已存在」略過。只處理這次要下載的網址（urls）。

    Args:
        run: 一次執行共用的設定（found 裡要有活動類別找到的網址）。
        urls: 這次要處理的主視覺網址（collect_banners_to_fill 的結果）。

    Returns:
        每一張搬走（或搬移失敗）舊圖的清單紀錄。
    """
    replaced = replaced_banners(run, live_banners(run))
    names = IMAGES.local_names(banner_universe(run))
    filenames = [document_filename(IMAGES, url, names[url]) for url in urls if url in replaced]
    return [
        move_removed(run, IMAGES, filename, reason="活動換了主視覺網址，舊圖搬走")
        for filename in filenames
        if (run.out / IMAGES.folder / filename).is_file()
    ]


def collect_banners_to_fill(run: Run) -> list[str]:
    """更新模式：現有的圖片照舊，名額少於 IMAGE_LIMIT 個時才補。

    名額的算法：「活動文件仍在」的活動的主視覺網址去除重複後，圖片檔在本地存在的，或副檔名不支援的（現行規則照樣佔名額），
    各佔一個；下載失敗、沒有留檔的不佔。名額不到 IMAGE_LIMIT 個時，從「活動文件確實存在、有主視覺、主視覺網址還沒有佔名額」
    的活動補：主視覺網址變了的（和這次重新取得之前存檔的 HTML 不同）排在最前面，其餘依活動被找到的順序。
    所以新出現在前面的活動不會擠掉現有的圖片。

    Args:
        run: 一次執行共用的設定（found 裡要有活動類別找到的網址）。

    Returns:
        已佔名額的主視覺網址（依活動被找到的順序），接著是補上的網址；現有的圖片因此記為已存在略過，不重新請求。
        候選不足 IMAGE_LIMIT 個時，印出名額數寫進報告。活動列表失敗時為空：那個失敗已經回報過。
    """
    live = live_banners(run)
    banners = banner_universe(run)
    names = IMAGES.local_names(banners)
    replaced = replaced_banners(run, live)
    occupied = [
        banner
        for banner in banners
        if (
            (run.out / IMAGES.folder / document_filename(IMAGES, banner, names[banner])).is_file()
            and banner not in replaced
        )
        or f".{IMAGES.extension_of(banner)}" not in SUPPORTED_IMAGE_EXTENSIONS
    ]
    changed = {
        banner
        for activity, banner in live.items()
        if banner is not None and activity in run.previous_banners and run.previous_banners[activity] != banner
    }
    candidates = sorted((b for b in banners if b not in occupied), key=lambda banner: banner not in changed)
    filled = candidates[: max(IMAGE_LIMIT - len(occupied), 0)]
    if ACTIVITIES.name in run.found and len(occupied) + len(filled) < IMAGE_LIMIT:
        print(f"活動圖片名額 {len(occupied) + len(filled)}/{IMAGE_LIMIT}，沒有更多候選")
    return [*occupied, *filled]


def collect_banners(run: Run, category: Category) -> list[str]:
    """依活動的發現順序，取前 IMAGE_LIMIT 個有主視覺的活動，回傳它們的主視覺網址。

    更新模式（run.update）改用 collect_banners_to_fill：現有的圖片照舊，名額少於 IMAGE_LIMIT 個時才補。

    讀的是活動類別存下來的原始 HTML（不另外請求）。只算活動 PDF 確實存在的活動（本次下載，或已存在而略過）：
    過期的活動、下載或列印失敗的活動沒有 PDF，不算，名額由下一個有主視覺的活動補上；已存在的活動不論現在是否過期都算，
    所以再次執行時挑出同一批。指向官網 mkp 網域的絕對網址，換成這次執行的 mkp 前綴（Run.to_mkp）。
    副檔名不支援的主視覺照樣佔名額，下載時記為略過。

    Args:
        run: 一次執行共用的設定（found 裡要有活動類別找到的網址）。
        category: 活動圖片類別（未使用，為了符合 Category.collect 的參數）。

    Returns:
        主視覺的完整網址（去除重複、保留順序，最多 IMAGE_LIMIT 個）。活動列表失敗時為空：那個失敗已經回報過。
    """
    if run.update:
        return collect_banners_to_fill(run)
    return banner_universe(run)[:IMAGE_LIMIT]


def save_image(run: Run, category: Category, url: str, name: str, target: Path, record: Record) -> None:
    """下載活動主視覺，確認檔頭和副檔名一致後原樣存檔（先寫暫時檔，成功才換成最終檔案）。

    Args:
        run: 一次執行共用的設定。
        category: 圖片所屬的類別。
        url: 圖片完整網址。
        name: 本地名稱（未使用，為了符合 Category.produce 的參數）。
        target: 最終檔案路徑。
        record: 清單紀錄（圖片沒有原始 HTML，不改它）。

    Raises:
        SkipDocument: 副檔名不是 RAG-Anything 支援的圖片格式（不請求圖片）。
        FetchError: 網址不在 mkp 網域、下載失敗，或內容的檔頭和副檔名不符（例如伺服器回了錯誤頁的 HTML）。
    """
    extension = f".{category.extension_of(url)}"
    if extension not in SUPPORTED_IMAGE_EXTENSIONS:
        raise SkipDocument(RESULT_UNSUPPORTED, f"不支援的圖片格式（副檔名 {extension}）")
    if urlparse(url).netloc != urlparse(run.mkp).netloc:
        raise FetchError(
            f"主視覺網址不在 mkp 網域（{urlparse(url).netloc}，mkp 網域是 {urlparse(run.mkp).netloc}），不下載"
        )
    is_valid = IMAGE_SIGNATURES.get(extension)
    if is_valid is None:
        raise FetchError(f"沒有 {extension} 的檔頭檢查，不下載")
    data = run.fetcher.get(url)
    if not is_valid(data):
        raise FetchError(f"下載的內容檔頭和副檔名 {extension} 不符（共 {len(data)} bytes），不存檔")
    with tempfile.TemporaryDirectory(dir=run.out / "_meta") as tmp:
        tmp_image = Path(tmp) / f"download{extension}"
        tmp_image.write_bytes(data)
        tmp_image.replace(target)


def print_with_chrome(tools: Tools, html_path: Path, target: Path, work_dir: Path) -> None:
    """網頁類的轉檔函式（卡片頁、活動頁）：用 Chrome 列印成 PDF。

    Args:
        tools: 轉檔用的外部命令，取其中的 Chrome 路徑。
        html_path: 要列印的本機 HTML 檔。
        target: 最終 PDF 路徑；列印成功才會出現。
        work_dir: 放暫時資料夾的位置（與 target 同一個檔案系統）。

    Raises:
        FetchError: Chrome 不存在、列印失敗、逾時或沒有產出 PDF（見 print_to_pdf）。
    """
    print_to_pdf(tools.chrome, html_path, target, work_dir)


def convert_with_office(tools: Tools, html_path: Path, target: Path, work_dir: Path) -> None:
    """網頁類的轉檔函式（權益子頁）：用 LibreOffice 轉成 .docx。

    Args:
        tools: 轉檔用的外部命令，取其中的 LibreOffice 命令（找不到時為 None）。
        html_path: 要轉檔的本機 HTML 檔；LibreOffice 輸出的檔名由它的主檔名決定。
        target: 最終 .docx 路徑（主檔名必須和 html_path 相同）；轉檔成功才會出現。
        work_dir: 放暫時資料夾的位置（與 target 同一個檔案系統）。

    Raises:
        FetchError: 找不到 LibreOffice、轉檔失敗、逾時或沒有產出 .docx（見 convert_to_docx）。
    """
    convert_to_docx(tools.office, html_path, target, work_dir)


CARDS = Category(
    name="卡片",
    list_label="總覽頁",
    list_name="信用卡總覽",
    list_site="www",
    list_path="/TSB/personal/credit/intro/overview/",
    link_pattern=re.compile(r"^/TSB/personal/credit/intro/overview/(cg\d+)/(card\d+)/$"),
    expected_count=16,
    unit="張卡片頁",
    name_prefix="card",
    folder="cards",
    extension="pdf",
    fmt=FORMAT_PDF,
    keeps_html=True,
    reads_period=False,
    collect=collect_from_one_page,
    produce=web_page_producer(print_with_chrome),
    refresh=web_page_refresher(print_with_chrome),
)
RIGHTS = Category(
    name="權益",
    list_label="權益頁",
    list_name="信用卡權益",
    list_site="www",
    list_path="/TSB/personal/credit/intro/rights/",
    # 子頁是權益頁底下 <群組>/<頁名>/ 兩層；選單只連到權益頁自己，不符合這個格式。頁名可以是 -00001 這種怪名字
    link_pattern=re.compile(r"^/TSB/personal/credit/intro/rights/([^/]+)/([^/]+)/$"),
    expected_count=46,
    unit="個權益子頁",
    name_prefix="rights",
    folder="rights",
    extension="docx",
    fmt=FORMAT_DOCX,
    keeps_html=True,
    reads_period=False,
    collect=collect_from_one_page,
    produce=web_page_producer(convert_with_office),
    refresh=web_page_refresher(convert_with_office),
)
DOWNLOADS = Category(
    name="下載",
    list_label="下載頁",
    list_name="文件下載",
    list_site="www",
    list_path="/TSB/personal/common/download/index.html?nav1=credit&nav2=file-download",
    # PDF 在 /TSB/export/sites/TSB/ 底下有三種前綴；任何以 .pdf 結尾的路徑都收，檔名（含 - 或 _ 開頭的）取最後一段
    link_pattern=re.compile(r"^/(?:.*/)?([^/]+)\.pdf$", re.IGNORECASE),
    expected_count=19,
    unit="個 PDF",
    name_prefix="download",
    folder="downloads",
    extension="pdf",
    fmt=FORMAT_PDF,
    keeps_html=False,
    reads_period=False,
    collect=collect_from_paged_downloads,
    produce=save_pdf,
    refresh=refresh_pdf,
)

ATTACHMENTS = Category(
    name="權益附件",
    list_label="權益子頁",
    list_name="權益附件",
    list_site="www",
    list_path="",
    # 路徑以 .pdf 結尾的連結都是候選；名稱取最後一段的主檔名，和下載區相同
    link_pattern=re.compile(r"^/(?:.*/)?([^/]+)\.pdf$", re.IGNORECASE),
    expected_count=None,
    unit="個 PDF 連結",
    name_prefix="attachment",
    folder="rights_attachments",
    extension="pdf",
    fmt=FORMAT_PDF,
    keeps_html=False,
    reads_period=False,
    collect=collect_attachments,
    produce=save_attachment,
    refresh=refresh_attachment,
)


def check_offer_period(record: Record, page: str) -> None:
    """讀出活動詳情頁的活動期間寫進清單紀錄；結束日早於下載當天的活動不下載。

    下載當天是 record.downloaded_at，新下載的紀錄由 fetch_document 設成 Run.today。

    讀不出期間時照樣下載，清單的活動期間欄是「期間不明」。

    Args:
        record: 這份活動的清單紀錄（downloaded_at 是下載當天）。
        page: 活動詳情頁的 HTML。

    Raises:
        SkipDocument: 結束日早於下載當天。
    """
    period = read_offer_period(page)
    record.period = period_label(period)
    if period is not None and period[1] < date.fromisoformat(record.downloaded_at):
        raise SkipDocument(RESULT_EXPIRED, f"活動結束日 {period[1].isoformat()} 早於下載當天 {record.downloaded_at}")


ACTIVITIES = Category(
    name="活動",
    list_label="刷卡優惠列表",
    list_name="刷卡優惠",
    list_site="mkpcard",
    list_path="/tscccms/promotion/offerList/",
    link_pattern=re.compile(r"^/tscccms/promotion/detail/(WM_\d+)$"),
    expected_count=None,
    unit="個活動頁",
    name_prefix="offer",
    folder="offers",
    extension="pdf",
    fmt=FORMAT_PDF,
    keeps_html=True,
    reads_period=True,
    collect=collect_offers,
    produce=web_page_producer(
        print_with_chrome,
        main_content=("class", "page-content"),
        inspect=check_offer_period,
    ),
    refresh=web_page_refresher(
        print_with_chrome, main_content=("class", "page-content"), inspect=check_offer_period, also_compare=banner_of
    ),
)
IMAGES = Category(
    name="活動圖片",
    list_label="活動頁",
    list_name="活動圖片",
    list_site="mkp",
    list_path="",
    # 不論路徑是什麼都收：名稱取最後一段的主檔名（官網是 WM_<編號>_banner_image），副檔名由 extension_of 取
    link_pattern=re.compile(r"^(?:.*/)?([^/]*?)(?:\.[^/.]*)?$"),
    expected_count=None,
    unit="張主視覺",
    name_prefix="offer_image",
    folder="offer_images",
    extension=None,
    fmt=FORMAT_IMAGE,
    keeps_html=False,
    reads_period=False,
    collect=collect_banners,
    produce=save_image,
    refresh=None,
)
CATEGORIES = (CARDS, RIGHTS, DOWNLOADS, ATTACHMENTS, ACTIVITIES, IMAGES)
# 更新模式下，列表裡沒有的文件會被搬走的類別（權益附件與活動圖片的下架判斷不依列表，另外處理）
REMOVAL_CATEGORIES = (CARDS, RIGHTS, DOWNLOADS, ACTIVITIES)


def document_filename(category: Category, url: str, name: str) -> str:
    """文件在類別資料夾裡的檔名。

    Args:
        category: 文件所屬的類別。
        url: 文件完整網址。
        name: 本地名稱（不含副檔名）。

    Returns:
        name 加上副檔名；沒有副檔名時就是 name。
    """
    extension = category.extension_of(url)
    return f"{name}.{extension}" if extension else name


def fetch_document(run: Run, category: Category, url: str, name: str) -> Record:
    """取得一份文件：已存在就略過，否則呼叫類別的 produce。

    Args:
        run: 一次執行共用的設定。
        category: 這份文件所屬的類別。
        url: 文件完整網址。
        name: 本地名稱（不含副檔名）。

    Returns:
        下載清單的一筆紀錄；失敗時 result 是「失敗」，detail 是原因。
    """
    filename = document_filename(category, url, name)
    record = Record(url, category.name, filename, category.fmt, run.today.isoformat(), "", "", RESULT_FAILED, "")
    target = run.out / category.folder / filename
    raw_path = run.out / "_meta" / "html" / f"{name}.html"
    try:
        if target.is_file() and run.update and category.refresh is not None:
            if category.reads_period and raw_path.is_file():
                # 活動頁：重新取得之前先記下存檔的主視覺網址，活動圖片用它找出主視覺網址變了的活動
                run.previous_banners[url] = banner_of(run, url, saved_html(raw_path))
            try:
                changed = category.refresh(run, category, url, name, target, record)
            except SkipDocument as exc:
                # refresh 拋的略過都要把已存在的文件搬走：活動頁重新判斷的結果是已過期（過期移除），
                # 權益附件的網址現在也在文件下載區（重複略過）
                moved_result = {RESULT_EXPIRED: RESULT_EXPIRED_REMOVED, RESULT_DUPLICATE: RESULT_DUPLICATE}[exc.result]
                moved = move_removed(run, category, filename, moved_result, str(exc))
                moved.url, moved.period = url, record.period
                return moved
            if not changed:
                record.downloaded_at = date.fromtimestamp(target.stat().st_mtime).isoformat()
            record.sha256 = sha256_of(target)
            record.result = RESULT_CHANGED if changed else RESULT_UNCHANGED
            return record
        if target.is_file():
            record.downloaded_at = date.fromtimestamp(target.stat().st_mtime).isoformat()
            record.sha256 = sha256_of(target)
            record.html_sha256 = sha256_of(raw_path) if category.keeps_html and raw_path.is_file() else ""
            if category.reads_period and raw_path.is_file():
                record.period = period_label(read_offer_period(saved_html(raw_path)))
            record.result = RESULT_SKIPPED
            return record
        if category.reads_period and raw_path.is_file():
            # 上次存下的原始 HTML 顯示已過期：不再請求詳情頁
            record.html_sha256 = sha256_of(raw_path)
            check_offer_period(record, saved_html(raw_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        (run.out / "_meta").mkdir(parents=True, exist_ok=True)
        category.produce(run, category, url, name, target, record)
        record.sha256 = sha256_of(target)
        record.result = RESULT_DOWNLOADED
    except SkipDocument as exc:
        record.result, record.detail = exc.result, str(exc)
    except FetchError as exc:
        record.detail = str(exc)
    except OSError as exc:
        record.detail = f"檔案系統錯誤（{type(exc).__name__}: {exc}）"
    return record


# ==============================
# 更新模式：官網列表已沒有的文件
# ==============================


def local_documents(run: Run, category: Category) -> list[str]:
    """類別資料夾裡現有的文件檔名（ingest 不遞迴，所以只看資料夾第一層的檔案）。

    不是文件的檔案（.DS_Store 等 `.` 開頭的隱藏檔、`~$` 開頭的 Office 鎖定檔，規則同 rag_lab.formats.NOT_A_DOCUMENT_PREFIXES，
    ingest 也不會匯入它們）不列，所以不會被當成下架搬走，「解析出 0 筆」的保護也不把它們算進本地文件。

    Args:
        run: 一次執行共用的設定。
        category: 要看哪個類別的資料夾。

    Returns:
        排序後的檔名；資料夾不存在時為空。
    """
    folder = run.out / category.folder
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(NOT_A_DOCUMENT_PREFIXES))


def free_destination(destination: Path) -> Path:
    """目的地已有同名檔時，在檔名後加時間（ASSUMPTION：時分秒加微秒，不覆寫）。

    Args:
        destination: 想搬到的路徑。

    Returns:
        沒有檔案佔用的路徑：destination 本身，或副檔名前加上 _<HHMMSSffffff> 的路徑。
    """
    if not destination.exists():
        return destination
    stamp = datetime.now().strftime("%H%M%S%f")
    return destination.with_name(f"{destination.stem}_{stamp}{destination.suffix}")


def move_removed(
    run: Run,
    category: Category,
    filename: str,
    result: str = RESULT_REMOVED,
    reason: str = "官網列表已沒有",
) -> Record:
    """把一份文件，連同它的原始 HTML 與列印用 HTML，搬到 DIR/_meta/removed/<日期>/。

    底下保留原本的相對路徑：文件到 <類別資料夾>/<檔名>，原始 HTML 到 html/<名稱>.html，列印用 HTML 到 print/<名稱>.html。
    清單紀錄的網址是空字串（ASSUMPTION：本地只有檔案，沒有它的網址；不去翻上一次的清單），呼叫端知道網址時自己補上。

    Args:
        run: 一次執行共用的設定。
        category: 文件所屬的類別。
        filename: 文件在類別資料夾裡的檔名。
        result: 搬成功時寫進清單的結果：下架或過期移除。
        reason: 寫進清單原因的前半段，後面接搬到哪裡。

    Returns:
        結果是 result 的清單紀錄；搬移時發生檔案系統錯誤則是「失敗」，detail 寫出原因。
    """
    name = Path(filename).stem
    meta = run.out / "_meta"
    destination_root = meta / "removed" / run.today.isoformat()
    document = run.out / category.folder / filename
    raw_html = meta / "html" / f"{name}.html"
    print_html = meta / "print" / f"{name}.html"
    record = Record(
        "",
        category.name,
        filename,
        category.fmt,
        date.fromtimestamp(document.stat().st_mtime).isoformat(),
        sha256_of(document),
        sha256_of(raw_html) if category.keeps_html and raw_html.is_file() else "",
        RESULT_FAILED,
        "",
    )
    if category.reads_period and raw_html.is_file():
        record.period = period_label(read_offer_period(saved_html(raw_html)))
    moves = [
        (document, destination_root / category.folder / filename),
        *(
            (source, destination_root / source.parent.name / source.name)
            for source in (raw_html, print_html)
            if source.is_file()
        ),
    ]
    try:
        for source, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(free_destination(destination))
    except OSError as exc:
        record.detail = f"搬移失敗（{type(exc).__name__}: {exc}）"
        return record
    record.result = result
    record.detail = f"{reason}，搬到 _meta/removed/{run.today.isoformat()}/"
    return record


def remove_unreferenced_images(run: Run) -> list[Record]:
    """圖片資料夾裡，沒有任何「活動文件仍在」的活動指向的圖片，搬到 DIR/_meta/removed/<日期>/offer_images/。

    活動的過期、下架與內容變更都處理完之後才呼叫。兩個活動共用同一張圖時，兩個都不在了才搬；
    活動改版換了主視覺網址時，舊圖搬走（轉檔失敗時存檔的 HTML 不換，舊圖留到下次）。
    活動列表沒有成功取得時（run.found 裡沒有活動），不判斷。

    Args:
        run: 一次執行共用的設定。

    Returns:
        每一張搬走（或搬移失敗）圖片的清單紀錄；活動列表失敗時為空。
    """
    if ACTIVITIES.name not in run.found:
        return []
    referenced = banner_universe(run)
    names = IMAGES.local_names(referenced)
    kept = {document_filename(IMAGES, url, names[url]) for url in referenced}
    return [
        move_removed(run, IMAGES, filename, reason="沒有任何仍在的活動使用這張圖片")
        for filename in local_documents(run, IMAGES)
        if filename not in kept
    ]


def remove_missing(run: Run, category: Category, filenames: set[str]) -> list[Record]:
    """本地有、這次官網列表沒有的文件算下架，逐份搬走。

    Args:
        run: 一次執行共用的設定。
        category: 要判斷的類別；它的列表這次必須成功取得。
        filenames: 這次列表裡所有文件的檔名。

    Returns:
        每一份下架（或搬移失敗）文件的清單紀錄。
    """
    return [move_removed(run, category, name) for name in local_documents(run, category) if name not in filenames]


def attachment_removal_blocker(records: list[Record], failed_lists: list[str]) -> str | None:
    """權益附件這次能不能判斷下架：權益列表與每個權益子頁都要成功取得。

    子頁內容變了但轉檔失敗時存檔的原始 HTML 不換，附件的候選讀的是舊的連結，所以請求失敗與轉檔失敗都算沒有成功取得。
    例外：失敗原因是轉址到外部網域的子頁（真實官網的 Visa、Mastercard、JCB 權益子頁每次都是）不算：它從來沒有內容，
    也不會提供附件連結，不影響附件候選。

    Args:
        records: 目前為止這次執行的紀錄（權益類別已處理完）。
        failed_lists: 目前為止沒有成功取得的列表名稱。

    Returns:
        不能判斷的原因；可以判斷時為 None。
    """
    if RIGHTS.list_name in failed_lists:
        return f"權益列表「{RIGHTS.list_name}」沒有成功取得"
    failed = [
        r.filename
        for r in records
        if r.category == RIGHTS.name and r.result == RESULT_FAILED and not r.detail.startswith(EXTERNAL_REDIRECT)
    ]
    if failed:
        return f"{len(failed)} 個權益子頁請求、轉檔或搬移失敗（{'、'.join(failed)}）"
    return None


def remove_unlinked_attachments(
    run: Run, category: Category, urls: list[str], records: list[Record], failed_lists: list[str]
) -> list[Record]:
    """所有權益子頁都不再連到的附件算下架，搬到 DIR/_meta/removed/<日期>/。

    附件的候選（urls）讀的是權益子頁存檔的原始 HTML；同一份附件被多個子頁連到時，只要還有一頁連到就在候選裡，不算下架。
    權益列表或任何一個權益子頁沒有成功取得時，這次不判斷，stderr 寫明原因（原因本身已讓結束碼是 1）。
    權益子頁都成功、但解析到的附件連結是 0 個，而本地有附件時，也當成沒有成功取得（官網改版讓解析失效的可能高於所有附件同時下架，
    做法同列表頁解析出 0 筆）：不搬任何附件，stderr 寫明原因，結束碼 1（ASSUMPTION：結束碼比照列表頁的 0 筆保護）；本地沒有附件時不算失敗。

    Args:
        run: 一次執行共用的設定。
        category: 權益附件類別。
        urls: 這次所有權益子頁連到的附件網址（含外部網域與下載區已有的網址，它們沒有本地檔，不影響判斷）。
        records: 目前為止這次執行的紀錄。
        failed_lists: 目前為止沒有成功取得的列表名稱；解析到 0 個連結而本地有附件時，這裡會加上附件類別的名稱（結束碼因此是 1）。

    Returns:
        每一份下架（或搬移失敗）附件的清單紀錄；不判斷時為空。
    """
    blocker = attachment_removal_blocker(records, failed_lists)
    if blocker is not None:
        print(f"ERROR 權益附件這次不判斷下架：{blocker}", file=sys.stderr)
        return []
    local = local_documents(run, category)
    if not urls and local:
        print(
            f"ERROR 權益附件這次不判斷下架：權益子頁都成功取得，但解析到的附件連結是 0 個，"
            f"本地 {category.folder}/ 有 {len(local)} 份附件；當成沒有成功取得，不搬任何附件",
            file=sys.stderr,
        )
        failed_lists.append(category.list_name)
        return []
    names = category.local_names(urls)
    return remove_missing(run, category, {document_filename(category, url, names[url]) for url in urls})


# ==============================
# 主程式
# ==============================


def write_manifest(out: Path, records: list[Record]) -> None:
    """把這次執行的紀錄寫成下載清單（JSON Lines，一行一份文件）。

    Args:
        out: 資料根目錄。
        records: 紀錄清單。
    """
    manifest = out / "_meta" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def print_summary(records: list[Record]) -> None:
    """印出各類別、各結果的數量（更新模式結束時用）。

    Args:
        records: 這次執行的紀錄。沒有任何紀錄的類別（例如列表頁失敗）印「沒有文件」。
    """
    print("各類別統計：")
    for category in CATEGORIES:
        counts = Counter(r.result for r in records if r.category == category.name)
        order = [*RESULT_ORDER, *(result for result in counts if result not in RESULT_ORDER)]
        detail = "、".join(f"{result} {counts[result]}" for result in order if counts[result]) or "沒有文件"
        print(f"  {category.name}：{detail}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令列參數。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        含 out（Path）與 update（bool）的 Namespace。
    """
    parser = argparse.ArgumentParser(description="下載台新銀行信用卡官網的內容，作為知識庫的來源文件。")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"輸出資料夾（預設 {DEFAULT_OUT}）")
    parser.add_argument(
        "--update",
        action="store_true",
        help="更新模式：已存在的下載區 PDF、權益附件與網頁類重新取得並比對內容，不同才換掉；官網列表已沒有的文件、已過期的活動、所有權益子頁都不再連到的附件搬到 _meta/removed/<日期>/，活動圖片跟著活動走；結束時印出各類別、各結果的數量",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """下載總覽頁列出的卡片頁、權益頁列出的權益子頁、文件下載區的 PDF、權益子頁連到的 PDF、刷卡優惠的活動頁與前 8 個主視覺。

    Args:
        argv: 不含程式名稱的參數清單。

    Returns:
        0 全部成功；1 有任何一頁或列表失敗（stderr 指出是哪一個）；2 命令列或環境變數設定錯誤。
    """
    args = parse_args(argv)
    www = os.environ.get(WWW_BASE_ENV, WWW_PREFIX).rstrip("/")
    mkpcard = os.environ.get(MKPCARD_BASE_ENV, MKPCARD_PREFIX).rstrip("/")
    mkp = os.environ.get(MKP_BASE_ENV, MKP_PREFIX).rstrip("/")
    chrome = os.environ.get(CHROME_ENV, DEFAULT_CHROME)
    try:
        interval = float(os.environ.get(INTERVAL_ENV, DEFAULT_INTERVAL_SEC))
    except ValueError:
        print(f"ERROR 環境變數 {INTERVAL_ENV} 必須是數字（秒）", file=sys.stderr)
        return 2
    if interval < 0:
        print(f"ERROR 環境變數 {INTERVAL_ENV} 不可以是負數", file=sys.stderr)
        return 2
    if args.out.exists() and not args.out.is_dir():
        print(f"ERROR --out {args.out} 已存在但不是資料夾", file=sys.stderr)
        return 2
    run = Run(args.out, www, mkpcard, mkp, Fetcher(interval), Tools(chrome, find_office()), date.today(), args.update)

    records: list[Record] = []
    failed_lists: list[str] = []
    for category in CATEGORIES:
        list_url = run.base(category.list_site) + category.list_path
        removable = run.update and category in REMOVAL_CATEGORIES
        try:
            urls = category.collect(run, category)
        except FetchError as exc:
            note = "；這個類別這次不搬任何檔案" if removable else ""
            print(f"ERROR 列表「{category.list_name}」（{list_url}）失敗：{exc}{note}", file=sys.stderr)
            failed_lists.append(category.list_name)
            continue
        if removable and not urls and local_documents(run, category):
            # 回應成功卻解析出 0 筆，而本地有文件：官網改版讓解析失效的可能高於整類下架，當成列表沒有取得
            print(
                f"ERROR 列表「{category.list_name}」（{list_url}）回應成功但解析出 0 筆，"
                f"本地 {category.folder}/ 有 {len(local_documents(run, category))} 份文件；"
                "當成列表沒有成功取得，這個類別這次不搬任何檔案",
                file=sys.stderr,
            )
            failed_lists.append(category.list_name)
            continue
        run.found[category.name] = urls
        expected = "" if category.expected_count is None else f"（預期 {category.expected_count}）"
        print(f"{category.list_label}找到 {len(urls)} {category.unit}{expected}")
        names = local_names_for(run, category, urls)
        if run.update and category is IMAGES:
            records.extend(remove_replaced_images(run, urls))
        records.extend(fetch_document(run, category, url, names[url]) for url in urls)
        if removable:
            listed = {document_filename(category, url, names[url]) for url in urls}
            records.extend(remove_missing(run, category, listed))
        elif run.update and category is ATTACHMENTS:
            records.extend(remove_unlinked_attachments(run, category, urls, records, failed_lists))
    if run.update:
        records.extend(remove_unreferenced_images(run))

    write_manifest(args.out, records)
    for r in records:
        print(f"{r.result} {r.category} {r.filename}")
    failed = [r for r in records if r.result == RESULT_FAILED]
    for r in failed:
        print(f"FAILED {r.url}（{r.filename}）：{r.detail}", file=sys.stderr)
    if args.update:
        print_summary(records)
    return 1 if failed or failed_lists else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
