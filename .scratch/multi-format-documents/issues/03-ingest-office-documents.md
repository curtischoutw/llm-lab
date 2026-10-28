# 03: 匯入 Office 文件（PPT、Word、Excel，含舊格式）

**What to build:** 使用者可以用 `ingest` 匯入 .ppt .pptx .doc .docx .xls .xlsx。RAG-Anything 會呼叫 LibreOffice 轉成 PDF 再交給 MinerU 解析，匯入後問得到內容。沒裝 LibreOffice 時，使用者看得到是 LibreOffice 缺少，以及怎麼安裝。資料夾裡一份 Office 文件轉檔失敗時，其他文件照常匯入。這張全部用假 LibreOffice 驗證，不需要安裝真的 LibreOffice。

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] 新增測試夾具「假 LibreOffice」，同時提供 `libreoffice` 和 `soffice` 兩個名稱，放在測試的 PATH 最前面（RAG-Anything 會先找 `libreoffice`；只放 `soffice` 的話，機器上裝了真的 LibreOffice 時測試會用到真的）。它收到 `--headless --convert-to pdf --outdir <dir> <檔案>` 時，在 `<dir>` 寫出 `<主檔名>.pdf`；主檔名以 `broken` 開頭時以非零碼結束。
- [ ] 支援的格式清單加入 6 種 Office 副檔名；6 種都能從 CLI 匯入，匯入後問得到內容。
- [ ] 匯入報告的解析階段標籤改成「解析（含 Office 轉 PDF）」，不另外計算轉檔時間。
- [ ] 沒有 LibreOffice 時（測試的 PATH 只放假 mineru，不放假 LibreOffice）：那份文件匯入失敗，錯誤訊息包含「LibreOffice」與安裝方式，結束碼不為 0。RAG-Anything 的原始訊息做不到時，由專案補上說明，但不吞掉原本的錯誤。
- [ ] 資料夾裡一份 Office 文件轉檔失敗時，其他文件照常匯入，失敗的列出名稱與原因，結束碼不為 0。
- [ ] 重複匯入同一份 Office 文件時略過，不呼叫模型。
- [ ] 確認轉出來的 PDF 寫在 parser 輸出資料夾，不會留在來源資料夾，下次匯入資料夾時不會被當成新文件（用測試驗證）。
- [ ] Python API 縫：`Session.ingest` 接受 Office 文件。
- [ ] 先紅後綠：每個新行為先寫出失敗的測試並貼出失敗輸出，再實作。
- [ ] README：安裝 LibreOffice（`brew install --cask libreoffice`）、`LIBREOFFICE_CONVERT_TIMEOUT`（預設 600 秒）、已知限制（Excel 轉成 PDF 頁面後可能遺失多工作表、公式、合併儲存格的結構，寬表格會被切頁；PPT 轉檔可能要好幾分鐘）。架構文件同步更新，包含假 LibreOffice 夾具。
- [ ] 主測試套件與下載腳本的測試全綠，貼出實際輸出。
