# 01: 清理舊知識庫並合併分支

**What to build:** 先把多格式擴充的成果留在 main，再清掉 RAG 論文的知識庫與它的資料，讓新的台新信用卡知識庫從乾淨的狀態開始。文件把舊的實測數據標成「前一版知識庫的量測」，讀者不會把它們當成目前的數字。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] `integration/multi-format-documents` 以 `--no-ff` 合併到 main，不 push。從 main 開新的 integration 分支，供本 spec 使用。
- [x] 刪除前，在對話中列出每個要刪除的路徑與大小，等使用者確認後才刪。刪除範圍：主知識庫、ticket 06 建立的備份、舊的論文與文件下載資料、論文 symlink 資料夾、MinerU 的解析資料夾與 Office 轉檔 PDF。
- [x] 量測紀錄資料夾、`eval_results/`、所有程式碼、測試、舊的下載腳本與舊題目檔都保留。
- [x] README：舊的實測數據標成「前一版知識庫的量測」。「目前的知識庫」改成「台新信用卡知識庫，內容在後續 ticket 建立」。
- [x] 架構文件：目錄表裡舊的下載資料與知識庫備份，改寫成「前一版知識庫用，已刪除，可用腳本重新下載」。
- [x] `GLOSSARY.md`（grilling 時已更新）與 spec 一起 commit 到新的 integration 分支。
- [x] 主測試套件與兩支既有下載腳本的測試，在新的 integration 分支上全綠。
- [x] 文字符合使用者的寫作規則。

## 實作結果（2026-10-30）

- `integration/multi-format-documents` 以 `--no-ff` 合併到 main，merge commit 是 dbce484，沒有 push。新的 integration 分支 `integration/taishin-credit-card-kb` 從 dbce484 開出。
- 刪除前在對話中列出路徑與大小，使用者回答「確認刪除」後才刪除。刪除的項目：
  - `rag_storage/` 與 `rag_storage.before-formats/`；
  - `data/papers/`、`data/documents/`、`data/format_check/`、`data/corpus/`；
  - `output/` 底下 9 個 MinerU 解析資料夾與 4 個 Office 轉檔 PDF。
- 保留的項目：`output/` 底下的量測紀錄資料夾（例如 `ticket04/`、`ticket05_papers/`、`formats_*_run/`）、`eval_results/`、程式碼、測試、舊的下載腳本與舊題目檔。
- README：
  - 開頭改成「目前的知識庫是台新信用卡知識庫，內容在 `.scratch/taishin-credit-card-kb/` 的後續 ticket 建立」。
  - §2、§4、§5 的舊數據標成前一版知識庫的量測，並寫明那批資料在 2026-10-30 刪除。
- 架構文件：
  - 流程圖的來源改成「data/ 底下的文件（PDF、Office 文件、圖片）」。
  - `data/*` 與 `rag_storage.before-formats/` 改寫成前一版知識庫用，已刪除，可以用腳本重新下載。
  - 新增 `.scratch/taishin-credit-card-kb/` 一列。
- 測試輸出：
  - 主測試套件：`Ran 116 tests in 392.249s`，`OK`。
  - `scripts/test_fetch_documents.py` 與 `scripts/test_fetch_papers.py`：`Ran 25 tests in 12.970s`，`OK`。
