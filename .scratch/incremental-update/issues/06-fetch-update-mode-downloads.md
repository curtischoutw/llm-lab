# 06: 下載腳本的更新模式骨架：下載區 PDF 只換內容真的變了的

**What to build:** 使用者用更新模式執行下載腳本時，下載區的 PDF 會重新下載到暫存位置並比對雜湊：內容不同才換掉原檔，相同就不碰原檔（修改時間不變，下次匯入走解析快取）。下載清單與結束時的統計多了「內容變更」「未變」兩種結果。不開更新模式時，行為與現在完全相同（spec「下載腳本：更新模式」）。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 開工第一步，實測並把結果與指令寫進這張 ticket 的 Comments（grill Q28）：用 2026-10-30 存下的 `DIR/_meta/html/`（主 checkout 的 `data/taishin_credit_card/_meta/html/`，worktree 裡沒有；只讀不寫），卡片頁、權益子頁、活動頁各取 2 頁，和現在的頁面比對原始 HTML，列出差異出現在哪些區塊。對官網的請求遵守現有的請求間隔。主內容區以外出現差異時（不論主內容區內有沒有差異）回報，由使用者決定是否改成只比主內容區（07 依這個結果實作）。實測結果不影響這張其他驗收條件：這張照常完成；發現主內容區以外的差異時，把 07 的 Status 改成 needs-info，等使用者決定。
- [x] 新增開啟更新模式的命令列選項；不開時既有測試全綠。
- [x] 下載區 PDF 內容沒變：原檔的位元組與修改時間不變，清單記「未變」。
- [x] 內容變了：原檔換成新內容，清單記「內容變更」。新出現的 PDF 沿用「已下載」。
- [x] 下載失敗：原檔不動，清單記失敗。
- [x] 更新模式的請求之間仍遵守請求間隔（用假 HTTP server 記錄請求時間驗證）。
- [x] 結束時印出各類別、各結果的數量。
- [x] 測試沿用下載腳本子行程＋假 HTTP server 的縫。
- [x] 下載腳本的模組說明與 README 第 2 節改寫：更新模式的用法與目前涵蓋的類別，拿掉「要更新內容時刪除資料夾後重新下載」的說法（或改成不用更新模式時的做法）。

## Comments

### 實測：網頁類原始 HTML 的差異出現在哪些區塊（grill Q28，2026-11-02）

做法：從主 checkout 的 `data/taishin_credit_card/_meta/html/`（2026-10-30 存下，只讀）取卡片頁、權益子頁、活動頁各 2 頁，向官網重新取得，和存檔比對。請求只有這 6 個，相隔 2 秒（腳本現有的請求間隔），User-Agent 與腳本相同。重新取得的 HTML 存在新的空資料夾，比對腳本放在別處，用 `python3 -I` 執行，路徑用參數傳。

比對的頁面與結果（區塊的認定同 `scripts/fetch_taishin.py`：卡片與權益子頁是 `id="centercontainer"`，活動頁是 class 含 `page-content` 的第一個元素）：

| 頁面 | 位元組完全相同 | 差異出現的區塊 |
|---|---|---|
| 卡片 `card_cg047_card001` | 是 | 無 |
| 卡片 `card_cg010_card001` | 否 | 只在主內容區（6 個差異：回饋 5%→6%、活動期間與辦法、贈點數與名額、活動連結、新增 MyJapan+ 區塊）；主內容區以外沒有差異 |
| 權益子頁 `rights_oversea_right0101` | 是 | 無 |
| 權益子頁 `rights_oversea_right0102` | 是 | 無 |
| 活動 `offer_WM_20260903141803056` | 否 | 只在主內容區以外：`<head>` 裡的 `<meta id="_csrf" name="_csrf" content="…">`（CSRF token）；主內容區取出後完全相同 |
| 活動 `offer_WM_20260824114903981` | 否 | 同上，只有 `_csrf` token |

結論：

- 主內容區以外出現差異：兩個活動頁的 `<head>` 裡的 `_csrf` token 和 2026-10-30 存的不同。存檔與新取得的兩份之間隔了 2 天；每次請求都換新 token 是推測（沒有對同一頁連續請求兩次驗證，因為請求數限定為這 6 頁）。若整份 HTML 逐位元組比對，活動頁會被誤判為每次執行都「內容變更」，所以 07 的比對範圍需要使用者決定：建議改成只比主內容區（這 6 頁中，主內容區的比對對 5 頁的判斷與實際內容一致，另 1 頁（cg010）確實有內容變更）。
- 主內容區內有差異：1 頁（cg010 的全聯等活動文字是真實內容更新，應該重新轉檔）。
- 因為有主內容區以外的差異，07 的 Status 已改成 needs-info。這張（06）不受影響，下載區 PDF 部分照常完成。

重現指令（腳本在 `~/.claude/jobs/db9cfed9/tmp/inc06-tools/`，不進 repo；`DATA` 是主 checkout 的 `data/taishin_credit_card`）：

```
mkdir NEW_DIR   # 必須是新的空資料夾
python3 -I refetch.py NEW_DIR \
  card_cg047_card001=https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg047/card001/ \
  card_cg010_card001=https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg010/card001/ \
  rights_oversea_right0101=https://www.taishinbank.com.tw/TSB/personal/credit/intro/rights/oversea/right0101/ \
  rights_oversea_right0102=https://www.taishinbank.com.tw/TSB/personal/credit/intro/rights/oversea/right0102/ \
  offer_WM_20260903141803056=https://mkp.taishinbank.com.tw/tscccms/promotion/detail/WM_20260903141803056 \
  offer_WM_20260824114903981=https://mkp.taishinbank.com.tw/tscccms/promotion/detail/WM_20260824114903981
PYTHONDONTWRITEBYTECODE=1 python3 -I compare.py REPO_ROOT DATA/_meta/html NEW_DIR
```

`refetch.py` 逐一 GET（間隔 2 秒），`compare.py` 用 difflib 逐行比對，並用 `scripts/fetch_taishin.py` 的主內容區認定（`_MainContentFinder`）標出每個差異落在 head、主內容區之前、主內容區、主內容區之後哪一段。

### 實作結果（2026-11-02）

- `scripts/fetch_taishin.py`：新增 `--update`；`Run.update`；`Category.refresh`（只有文件下載區設了 `refresh_pdf`，其他類別是 None，更新模式下行為與不加 `--update` 相同）；新結果值「內容變更」「未變」；`download_pdf`／`write_pdf` 從 `save_pdf` 拆出共用；更新模式結束時印「各類別統計」。模組說明與 README 第 2 節改寫（更新模式的用法與目前涵蓋的類別；不加 `--update` 時刪除資料夾重新下載的說法保留並註明）。
- `scripts/test_fetch_taishin.py`：`UpdateModeDownloadAreaTests`（6 個：沒變、內容變更、新出現、下載失敗三種、請求間隔、統計）與 `WithoutUpdateModeTests`（1 個）；`run_script` 加 `extra_args`、新增 `run_update`。縫沿用下載腳本子行程＋假 HTTP server。

ASSUMPTION：

- 選項名稱 `--update`，統計格式 `  <類別>：<結果> <數量>、…`，沒有紀錄的類別印「沒有文件」；只在更新模式印（不加 `--update` 的輸出與現在完全相同）。
- 更新模式下，沒有 `refresh` 的類別（卡片、權益、權益附件、活動、活動圖片）維持「已存在就略過」；等 07–10。
- 「未變」的清單紀錄，下載日期取原檔的修改日期（和「已存在略過」一致）；「內容變更」取這次執行的下載當天。
- 比對時整份 PDF 讀進記憶體（現有下載本來就是這樣），內容不同才寫暫時檔再換掉原檔。
- 下載失敗時，結束碼 1，與其他失敗相同。

範圍外發現：

- 實測的活動頁 `_csrf` token 差異，見上；07 已改成 needs-info。
