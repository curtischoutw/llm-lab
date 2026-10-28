# 05: 格式驗證知識庫的實機驗證（Excel 與舊格式）

**What to build:** 在真的 LibreOffice、MinerU 和 MLX server 上，確認 Excel（.xlsx）和舊格式（.ppt .doc .xls）能完整匯入，而且問得到內容。用暫時的 `WORKING_DIR` 建一個格式驗證知識庫，主知識庫不受影響。驗證完留下紀錄，刪除這個知識庫。這張排在主知識庫擴充之前，先在用完就丟的知識庫上確認 Office 路徑真的能用。

**Blocked by:** 03, 04

**Status:** resolved

- [ ] 安裝 LibreOffice（`brew install --cask libreoffice`；使用者已在 grilling Q2 同意。執行環境不允許時，請使用者自己執行）。確認 `libreoffice` 或 `soffice` 在 PATH 上，並記錄版本。
- [ ] 寫格式驗證用的題目檔，和主知識庫的題目檔分開：每份文件至少 1 題，問那份文件裡的內容（例如表格裡的數字），參考答案根據文件原文。
- [ ] 照 README 啟動兩個 MLX server，同時以 zsh 執行 watchdog（門檻 22 GB）；smoke test 三項 PASS。
- [ ] 以 `WORKING_DIR=<暫存路徑>` 執行 `ingest data/format_check`：5 份都匯入成功。記錄每份的耗時、從 log 時間戳記讀出的轉檔時間、wired 記憶體峰值、圖譜的實體與關係數。
- [ ] 對同一個 `WORKING_DIR` 用 `eval` 跑格式驗證的題目檔：每種格式（Excel、舊 PPT、舊 Word、舊 Excel）至少 1 題問得到該文件的內容。答對與否由實作者對照參考答案判斷，並列出判斷理由，讓使用者抽查。
- [ ] 記錄 Excel 多工作表的解析結果：每個工作表有沒有被解析、寬表格是否被切頁、表格是否被辨識成 table。
- [ ] 匯入報告、eval 結果、log 存到 `output/` 底下，然後刪除暫存的 `WORKING_DIR`。確認主知識庫（`rag_storage`）的檔案在驗證前後沒有變動（例如比對修改時間或雜湊）。
- [ ] 驗證完關掉 server 與 watchdog。
- [ ] README：Excel 與舊格式的實測數據與已知限制改用實測結果，不再是推測。
- [ ] 任何格式驗證失敗時，記下事實、已排除的假設、卡點，回報使用者決定，不放寬驗收標準。

## 實作結果（2026-10-29）

在主 repo 工作目錄執行（integration 分支 2f01ee0），沒有開 worktree，因為要用 `.env`、`data/` 和主知識庫，這些都不進版本控管。

- **安裝與下載**：`brew install --cask libreoffice` 安裝 LibreOffice 26.8.1.1，`soffice` 在 `/opt/homebrew/bin/soffice`（brew 沒有建立 `libreoffice` 這個名稱）。下載腳本下載 11 份文件，雜湊都相符。裝了真的 LibreOffice 之後重跑 Office 相關的 9 個快速測試，全部 OK（35.7 s），代表測試仍然用假的 LibreOffice。
- **題目檔**：`eval/questions.format_check.jsonl`，6 題。參考答案依 LibreOffice 轉出的 PDF 內容撰寫。
- **實機匯入**：smoke test 三項 PASS。設定 `WORKING_DIR` 與 `PARSER_OUTPUT_DIR` 指向暫存資料夾，執行 `ingest data/format_check`：
  - 5 份都匯入成功，`processed=5`，`failed=0`，總共 1132 s；
  - 每份的耗時與轉檔時間（從 log 時間戳記讀出，每份約 1 s）寫在 README 第 5 節；
  - wired 記憶體峰值 15 GB，watchdog 沒有觸發；
  - 圖譜：實體 237，關係 508。
- **eval**：6 題 × 5 種模式 = 30 格，失敗 0 格，耗時 1176 s。對照表存在 `output/formats_check_run/eval_20261029-001952.md`。以下是逐格判斷（✓ 對，✗ 錯）：

  | 題目 | naive | local | global | hybrid | mix | 判斷理由 |
  |---|---|---|---|---|---|---|
  | fc-xlsx-01（9,373） | ✗ | ✓ | ✗ | ✗ | ✗ | 4 格答 8,589，那是 2022 年同一列的數字 |
  | fc-xlsx-02（2,713） | ✗ | ✗ | ✗ | ✗ | ✗ | 答 12,553（Sales）、2,632（Trading operating profit）或 (81)（Net other trading），都是同一列的其他欄 |
  | fc-xlsx-03（32） | ✗ | ✗ | ✗ | ✗ | ✗ | 答 6 或「6 8」；col-1=8 那一列在解析時已經錯位 |
  | fc-xls-01（170） | ✓ | ✓ | ✓ | ✓ | ✓ | 5 格都答 170 |
  | fc-doc-01（200；Corn、Buckwheat、Barley） | ✓ | ✓ | ✓ | ✓ | ✓ | 5 格都答 200 和三種穀物（naive 把 Buckwheat 譯成「大麥」，英文名稱正確） |
  | fc-ppt-01（長方形文字、清單 With foo／Bar／And baz things） | ✗ | ✓ | ✗ | 半 | ✗ | naive 答成 .doc 的內容；global 說找不到長方形的文字；hybrid 長方形文字對、清單錯；mix 說長方形寫的是「With foo」 |

- **驗收**：每種格式至少 1 題問得到該文件的內容，字面上成立。Excel 靠 local 的 1 格，舊 PPT 靠 local，舊 Word 和舊 Excel 每格都對。但 Excel `.xlsx` 是 15 格答對 1 格，mix 模式 3 題全錯，所以只算勉強達標，已回報使用者決定要不要另開 spec 處理。
- **Excel 解析結果**（內容清單存在 `output/formats_check_run/content_lists/`）：
  - Nestlé 5 個工作表轉成 5 頁，得到 7 個 table、12 個 text，每個工作表都有被解析。旋轉的欄位標題被 OCR 成無法辨識的文字（`Undeng Tedng peong pnyh`）。第 1 頁上方的「January–June 2023／2022」沒有進入任何內容項目，同一頁兩張表的 HTML 裡都沒有年份。頁尾被 LibreOffice 加上「…Nestlé Group 2022」。這三點就是 fc-xlsx-01、02 答錯的原因。
  - `xlsx_01.xlsx` 4 個工作表轉成 5 頁：第 2 個工作表比較寬，被切成第 2、3 頁。得到 5 個 table、3 個 chart。第 1 張表的欄位錯位（「1 5」併在同一格）；第 2 個工作表裡並排的兩張表被合併成一張，col-1=8 那一列錯位，這是 fc-xlsx-03 答錯的原因。最後一個工作表的放射狀圖被辨識成 table。
  - 所有表格都沒有 caption。
- **發現的實作限制**：主檔名相同的 Office 文件，會轉成同一個 `PARSER_OUTPUT_DIR/<主檔名>.pdf`，也解析進同一個資料夾。3 個 `legacy_sample.*` 依序覆蓋了彼此的轉檔 PDF 和內容清單；內容在被覆蓋前已寫入知識庫，圖片以雜湊命名所以沒有遺失。原因是 RAG-Anything 把轉檔 PDF 放在 `output_dir/<主檔名>.pdf`，解析資料夾名稱再取自這個 PDF 路徑的雜湊。這不在 ticket 範圍內，沒有修改程式，只寫進 README 的已知限制並回報使用者。
- **主知識庫**：驗證前後各記錄一次 `rag_storage` 13 個檔案的 SHA-256，`diff` 兩份記錄沒有差異。
- **收尾**：紀錄（ingest log、eval 對照表、內容清單、sampler log、server log）存在 `output/formats_check_run/`，暫存的 `WORKING_DIR` 與 `PARSER_OUTPUT_DIR` 已刪除。
- **偏離 ticket 的地方**：驗證完沒有關掉 server 與 watchdog，因為接著要做 ticket 06 的實機匯入，不必重新載入模型；ticket 06 結束後一起關閉。
- README：第 4 節 Office 文件的已知限制改成實測結果，並加上主檔名相同的限制；第 5 節加上 Excel 與舊格式的實測表格。
