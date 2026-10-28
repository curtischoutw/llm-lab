# 05: 格式驗證知識庫的實機驗證（Excel 與舊格式）

**What to build:** 在真的 LibreOffice、MinerU 和 MLX server 上，確認 Excel（.xlsx）和舊格式（.ppt .doc .xls）能完整匯入，而且問得到內容。用暫時的 `WORKING_DIR` 建一個格式驗證知識庫，主知識庫不受影響。驗證完留下紀錄，刪除這個知識庫。這張排在主知識庫擴充之前，先在用完就丟的知識庫上確認 Office 路徑真的能用。

**Blocked by:** 03, 04

**Status:** ready-for-agent

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
