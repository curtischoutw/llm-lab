# 10: 更新模式：權益附件跟著子頁上的連結走

**What to build:** 更新模式下，所有權益子頁都不再連到的附件，搬到 `DIR/_meta/removed/<日期>/`，清單記「下架」；權益列表或任何一個權益子頁沒有成功取得時，這次不判斷附件下架，報告寫明原因（spec「下載腳本：更新模式」的下架判斷）。

**Blocked by:** 07、08

**Status:** resolved

- [x] 所有子頁都不再連到：附件搬到 `DIR/_meta/removed/<日期>/`，清單記「下架」。
- [x] 同一份附件被多個子頁連到時，只要還有一頁連到就不算下架。
- [x] 附件的候選與下架判斷讀權益子頁存檔的原始 HTML。權益列表失敗，或有任何子頁請求失敗或轉檔失敗（存檔沒換）：這次不判斷附件下架，報告寫明原因。
- [x] 附件內容變了：照 06 的規則比對雜湊後換掉。
- [x] 測試沿用假 HTTP server；現有測試全綠。

## Comments

### 實作結果（2026-11-02）

更新模式下，權益附件重新下載並比對 SHA-256（內容不同才換掉，記「內容變更」；相同記「未變」，位元組與修改時間不動）；本地附件的檔名不在「這次所有權益子頁存檔的原始 HTML 連到的 PDF」算出的檔名之內時，搬到 `DIR/_meta/removed/<日期>/rights_attachments/`，清單記「下架」。

- `scripts/fetch_taishin.py`：`ATTACHMENTS.refresh` 改用 `refresh_pdf`（沿用 06 的比對）；新增 `attachment_removal_blocker`、`remove_unlinked_attachments`（重用 08 的 `remove_missing`／`move_removed`）；`main` 在附件類別處理完後多一個 `elif` 分支；模組說明、`--update` 說明與 README 第 2 節同步。
- `scripts/test_fetch_taishin.py`：`UpdateModeAttachmentTests`（10 個）。縫沿用下載腳本子行程＋假 HTTP server、假 Chrome、假 LibreOffice。涵蓋：不再連到 → 下架；內容不變／變了；下載失敗原檔不動；多個子頁連到時只要一頁還連到就不下架；子頁離開權益列表時它的附件下架；子頁請求失敗、轉檔失敗、權益列表失敗 → 不判斷並寫明原因（轉檔失敗的下次成功後才判斷）；不加 `--update` 不搬；請求間隔。

ASSUMPTION：

- 不判斷的條件：權益列表失敗（含解析出 0 筆而本地有權益文件），或這次權益類別有任何一筆紀錄是「失敗」（請求、轉檔、搬移都算）。原因寫在 stderr（「權益附件這次不判斷下架」），不另外改結束碼，因為原因本身已讓結束碼是 1。
- 權益子頁都成功、但連到的 PDF 一個也沒有時，本地的附件全部算下架（規格只對列表頁定了 0 筆的防護）。
- 附件的檔名由候選網址算出（含同名時的網址雜湊後綴），所以候選集合改變導致後綴改變時，舊檔名會被當成下架、新檔名當成新增（同 08）。
- 下架紀錄的網址是空字串（同 08）。
- 本地已有的附件在更新模式下不再套用「外部網域」「重複」的略過檢查：這兩種結果沒有本地檔，所以不會走到比對。
- 紅燈說明：第一個測試先紅後綠（下架），再加比對的三個測試先紅（`refresh` 還是 None）後綠；其餘 6 個測試在實作後才寫，第一次就綠。事後把 `attachment_removal_blocker` 改成永遠回 None 做變異檢查，三個「不判斷」測試轉紅，還原後全綠。

範圍外發現：

- 無。

### code-review 修正 1：轉址到外部網域的子頁不阻擋附件下架（2026-11-02）

真實官網的 Visa、Mastercard、JCB 權益子頁每次都記「失敗：轉址到外部網域…，不跟隨」（主 checkout 的 `data/taishin_credit_card/_meta/manifest.jsonl`），原本會讓 `attachment_removal_blocker` 永遠回傳原因，附件下架因此永遠不會執行。

- `attachment_removal_blocker` 不再把失敗原因是「轉址到外部網域」的權益子頁算進去：這類子頁從來沒有內容，也不提供附件連結。請求失敗、轉檔失敗、搬移失敗照樣阻擋。失敗原因開頭的字串抽成常數 `EXTERNAL_REDIRECT`，轉址處理與判斷共用。
- 測試：`test_subpage_that_always_redirects_to_another_domain_does_not_block_the_removal_judgement`（先紅：stderr 出現「權益附件這次不判斷下架」；修後綠）。

範圍外發現：這三個子頁讓每次執行的結束碼都是 1，是既有行為，沒有改。

### code-review 修正 5：更新模式的附件也做「和下載區重複」檢查（2026-11-02）

更新模式原本對已存在的附件走 `refresh_pdf`，跳過了 `save_attachment` 的重複檢查（上面「實作結果」ASSUMPTION 的最後一條）。

- 新增 `download_area_duplicate`（`save_attachment` 與新的 `refresh_attachment` 共用）；`ATTACHMENTS.refresh` 改用 `refresh_attachment`：網址現在也在文件下載區時不請求，`fetch_document` 把它當成下架搬到 `_meta/removed/<日期>/rights_attachments/`，清單記「重複略過」，網址是附件網址，原因寫出它在下載區的檔名。
- ASSUMPTION（使用者指定）：它的內容已由下載區那一份匯入，不搬的話同一份 PDF 會在知識庫裡兩次。
- 外部網域的略過不加進更新模式：外部網域的附件從來沒有本地檔。
- 測試：`test_existing_attachment_that_is_now_in_the_download_area_is_recorded_as_duplicate_and_moved_away`（先紅：附件還在附件資料夾；修後綠）。

### code-review 修正 6：解析到 0 個附件連結而本地有附件時不判斷下架（2026-11-02，使用者同意改掉上面的 ASSUMPTION）

原本的 ASSUMPTION「權益子頁都成功取得、但連到的 PDF 一個也沒有時，本地的附件全部算下架」作廢。改成：權益子頁都成功、但解析到的附件連結是 0 個，而本地 `rights_attachments/` 有附件時，當成沒有成功取得，不搬任何附件，stderr 寫「權益附件這次不判斷下架」與原因（做法同列表頁「解析出 0 筆」的保護）；本地沒有附件時，0 個不算失敗。

- `remove_unlinked_attachments` 在 `attachment_removal_blocker` 之後多一個 0 個連結的檢查；並把附件類別名稱加進 `failed_lists`。
- ASSUMPTION：結束碼比照列表頁的 0 筆保護是 1（使用者只說「做法和列表頁相同」，沒有明講結束碼）。
- 測試：`test_removal_is_not_judged_when_all_subpages_succeed_but_no_attachment_link_is_parsed_while_local_has_attachments`（先紅：2 份附件被搬走）、`test_zero_attachment_links_is_fine_when_there_are_no_local_attachments`（本來就綠，守住「本地沒有附件不算失敗」）。
