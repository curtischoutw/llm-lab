# 03: 匯入 Office 文件（PPT、Word、Excel，含舊格式）

**What to build:** 使用者可以用 `ingest` 匯入 .ppt .pptx .doc .docx .xls .xlsx。RAG-Anything 會呼叫 LibreOffice 轉成 PDF 再交給 MinerU 解析，匯入後問得到內容。沒裝 LibreOffice 時，使用者看得到是 LibreOffice 缺少，以及怎麼安裝。資料夾裡一份 Office 文件轉檔失敗時，其他文件照常匯入。這張全部用假 LibreOffice 驗證，不需要安裝真的 LibreOffice。

**Blocked by:** 02

**Status:** resolved

- [x] 新增測試夾具「假 LibreOffice」，同時提供 `libreoffice` 和 `soffice` 兩個名稱，放在測試的 PATH 最前面（RAG-Anything 會先找 `libreoffice`；只放 `soffice` 的話，機器上裝了真的 LibreOffice 時測試會用到真的）。它收到 `--headless --convert-to pdf --outdir <dir> <檔案>` 時，在 `<dir>` 寫出 `<主檔名>.pdf`；主檔名以 `broken` 開頭時以非零碼結束。
- [x] 支援的格式清單加入 6 種 Office 副檔名；6 種都能從 CLI 匯入，匯入後問得到內容。
- [x] 匯入報告的解析階段標籤改成「解析（含 Office 轉 PDF）」，不另外計算轉檔時間。
- [x] 沒有 LibreOffice 時（測試的 PATH 只放假 mineru，不放假 LibreOffice）：那份文件匯入失敗，錯誤訊息包含「LibreOffice」與安裝方式，結束碼不為 0。RAG-Anything 的原始訊息做不到時，由專案補上說明，但不吞掉原本的錯誤。
- [x] 資料夾裡一份 Office 文件轉檔失敗時，其他文件照常匯入，失敗的列出名稱與原因，結束碼不為 0。
- [x] 重複匯入同一份 Office 文件時略過，不呼叫模型。
- [x] 確認轉出來的 PDF 寫在 parser 輸出資料夾，不會留在來源資料夾，下次匯入資料夾時不會被當成新文件（用測試驗證）。
- [x] Python API 縫：`Session.ingest` 接受 Office 文件。
- [x] 先紅後綠：每個新行為先寫出失敗的測試並貼出失敗輸出，再實作。
- [x] README：安裝 LibreOffice（`brew install --cask libreoffice`）、`LIBREOFFICE_CONVERT_TIMEOUT`（預設 600 秒）、已知限制（Excel 轉成 PDF 頁面後可能遺失多工作表、公式、合併儲存格的結構，寬表格會被切頁；PPT 轉檔可能要好幾分鐘）。架構文件同步更新，包含假 LibreOffice 夾具。
- [x] 主測試套件與下載腳本的測試全綠，貼出實際輸出。

## 實作結果（2026-10-28）

- 程式改動只有三處：
  - `rag_lab/formats.py`：`FORMATS` 加 `"PPT": (".ppt", ".pptx")`、`"Word": (".doc", ".docx")`、`"Excel": (".xls", ".xlsx")`，順序在 PDF 之後、圖片之前。
  - `rag_lab/__main__.py`：解析階段那一行改成 `解析（含 Office 轉 PDF）：<秒> s（MinerU backend=pipeline）`。所有文件共用這一行，PDF 與圖片也是這個標籤（沒有依格式分開）。
  - `rag_lab/pipeline.py`：只改 `IngestReport.parse_seconds` 的 docstring。
- 新增測試夾具 `tests/fake_libreoffice.py`：收到 `--headless --convert-to pdf --outdir <dir> <檔案>` 時在 `<dir>` 寫出 `<主檔名>.pdf`（內容是檔頭加填充，共 217 bytes；RAG-Anything 把小於 100 bytes 的轉檔結果當成空檔）；引數形式不符時以結束碼 2 結束；主檔名以 `broken` 開頭時以結束碼 1 結束。`PipelineCase.setUp` 把它以 `libreoffice`、`soffice` 兩個名稱放在 `office_bin/`，PATH 最前面（`office_bin`、`bin_dir`（假 mineru）、原本的 PATH）。所有繼承 `PipelineCase` 的測試都用假的，不論機器上有沒有真的 LibreOffice。
- Office 測試檔（`write_office`）的內容是一行文字，不是真的 Office 檔：假 LibreOffice 與假 mineru 都不讀內容，只看副檔名與主檔名。真的 Office 檔能不能轉、轉出什麼，留給 ticket 05／06 用真的 LibreOffice 驗證。
- RAG-Anything 沒有 LibreOffice 時的原始訊息（`raganything/parser.py` 的 `convert_office_to_pdf`）已含「LibreOffice」與各平台安裝方式，專案沒有加工，也沒有改寫。CLI 在 stderr 印出的原文：

  ```
  匯入失敗：slides.pptx：RuntimeError: LibreOffice conversion failed for slides.pptx. Please ensure LibreOffice is installed:
  - Windows: Download from https://www.libreoffice.org/download/download/
  - macOS: brew install --cask libreoffice
  - Ubuntu/Debian: sudo apt-get install libreoffice
  - CentOS/RHEL: sudo yum install libreoffice
  Alternatively, convert the document to PDF manually.
  1/1 篇匯入失敗；其餘已匯入的資料保留，重新執行會重試失敗的篇
  ```

  結束碼 1。RAG-Anything 對「找不到命令」與「命令以非零碼結束」拋同一則訊息（只有逾時另有訊息，指出 `LIBREOFFICE_CONVERT_TIMEOUT`），所以轉檔失敗時使用者看到的也是「請確認已安裝 LibreOffice」；訊息沒有帶 LibreOffice 自己的 stderr（只進 RAG-Anything 的 log 的 WARNING）。
- 先紅後綠（CLI 縫，`tests.test_pipeline.IngestOfficeTest`；Python API 縫，`tests.test_python_api.IngestOfficeTest`）。先在沒有對應實作時執行：
  - `test_ingests_a_pptx_and_its_parsed_content_reaches_the_answer_prompt`：`AssertionError: 2 != 0 : 輸入錯誤：不支援的格式：slides.pptx（支援的格式：.pdf .png .jpg .jpeg .bmp .tiff .tif .gif .webp）`。`FORMATS` 先只加 `.pptx` 後通過；通過的條件包含 naive 查詢時回答用的 prompt 含假 mineru 的文字 `A Study of Fake Entities in slides`，證明假 LibreOffice 轉出的 PDF 確實交給了 mineru。
  - `test_every_office_format_can_be_ingested_and_its_extension_is_case_insensitive`（`old.ppt old.doc new.docx old.xls new.xlsx UPPER.DOCX` 6 個 subTest 失敗，`new.pptx` 已通過）：`AssertionError: 2 != 0 : 輸入錯誤：不支援的格式：old.ppt（支援的格式：.pdf .pptx .png ...）`。同時 `IngestTest.test_rejects_a_single_file_in_an_unsupported_format_and_lists_the_supported_formats` 因測試裡的 `SUPPORTED_EXTENSIONS` 更新而失敗：`AssertionError: '.doc' not found in '輸入錯誤：不支援的格式：notes.txt（支援的格式：.pdf .pptx .png ...）'`。補齊 `FORMATS` 後通過。
  - `test_report_labels_the_parse_stage_as_including_the_office_to_pdf_conversion`：`AssertionError: Regex didn't match: '解析（含 Office 轉 PDF）：\d+\.\d s' not found in '[1/1] slides.pptx：耗時 0.8 s\n  MinerU 解析：0.3 s（backend=pipeline）\n ...'`。改標籤後通過。
- 沒有獨立紅燈的測試（寫完後第一次執行就通過），原因與驗證方式：
  - `test_without_libreoffice_the_document_fails_and_the_error_says_how_to_install_it`：RAG-Anything 的原始訊息已滿足需求（見上），專案不必改。驗證測試分得出有無 LibreOffice：暫時把測試的 PATH 覆蓋拿掉（PATH 含假 LibreOffice）後這個測試失敗。
  - `test_a_failed_office_conversion_is_named_and_the_other_documents_in_the_folder_are_kept`、`test_reingesting_the_same_office_document_skips_it_and_calls_no_model`（.pptx、.doc）、`test_the_converted_pdf_is_written_to_the_parser_output_folder_not_next_to_the_source`、Python API 的兩個測試：單篇失敗隔離、略過、輸出資料夾，都是 `pipeline._ingest` 與 RAG-Anything 對所有文件共用的行為，放寬格式清單之後就成立。驗證測試分得出行為：暫時讓假 LibreOffice 對 `broken*` 也成功後，資料夾轉檔失敗的測試與 Python API 的轉檔失敗測試失敗（結束碼 0，沒有「匯入失敗」）。重複匯入略過與輸出資料夾兩個測試，沒有對應的暫時改動能讓它們紅（行為在 RAG-Anything 內），只靠反向檢查（下一項）證明它們依賴 Office 格式被放行。
  - Python API 縫（`Session.ingest`、模組函式 `ingest`）不檢查副檔名，Office 文件本來就能匯入；這兩個測試證明沒有被拒絕、報告欄位是 `document`、轉檔失敗記在該份報告的 `error`（`RuntimeError: LibreOffice conversion failed ...`）、重複匯入略過。
- 反向檢查：暫時從 `FORMATS` 拿掉 PPT、Word、Excel 三項，執行 `IngestOfficeTest`（CLI，7 個測試）、Python API 的 `IngestOfficeTest`（2 個）與「不支援格式的錯誤訊息」測試：10 個測試中 15 個失敗項目（`test_every_office_format_...` 7 個 subTest、重複匯入 2 個 subTest、其餘 6 個測試各 1 個）；CLI 的 `IngestOfficeTest` 7 個測試全部失敗；Python API 的 2 個仍通過（原因同上，沒有副檔名檢查）。還原後全部通過。
- 新增的測試（9 個）：
  - `tests.test_pipeline.IngestOfficeTest`：`test_ingests_a_pptx_and_its_parsed_content_reaches_the_answer_prompt`、`test_every_office_format_can_be_ingested_and_its_extension_is_case_insensitive`、`test_report_labels_the_parse_stage_as_including_the_office_to_pdf_conversion`、`test_without_libreoffice_the_document_fails_and_the_error_says_how_to_install_it`、`test_a_failed_office_conversion_is_named_and_the_other_documents_in_the_folder_are_kept`、`test_reingesting_the_same_office_document_skips_it_and_calls_no_model`、`test_the_converted_pdf_is_written_to_the_parser_output_folder_not_next_to_the_source`
  - `tests.test_python_api.IngestOfficeTest`：`test_module_function_ingests_office_documents_and_reports_the_document`、`test_session_ingests_office_documents_skips_a_repeated_one_and_reports_a_failed_conversion`
- 既有測試的改動：`tests/test_pipeline.py` 的 `SUPPORTED_EXTENSIONS` 補上 6 種 Office 副檔名（ticket 02 的 ASSUMPTION 4）；`PipelineCase` 的 PATH 加上假 LibreOffice 資料夾。沒有改任何既有斷言。
- 文件：README 第 1 節新增安裝 LibreOffice 與 `LIBREOFFICE_CONVERT_TIMEOUT`，第 4 節新增 3 種 Office 格式、沒有 LibreOffice 的錯誤、已知限制，第 7 節說明假 LibreOffice；`docs/architecture.md` 更新流程說明、`formats.py`、`fake_libreoffice.py`、`test_pipeline.py`、`test_python_api.py`、`fake_mineru.py` 的說明。
- 測試結果：
  - 基線（ticket 02）：主套件 101 個。
  - 主套件：`Ran 110 tests in 385.715s`，OK（101 加 CLI 7 個、Python API 2 個）。
  - 下載腳本：`python -m unittest scripts/test_fetch_papers.py scripts/test_fetch_documents.py`，`Ran 23 tests in 12.037s`，OK。
- ASSUMPTION：
  - 解析標籤「解析（含 Office 轉 PDF）」套用在所有文件，不只 Office 文件；PDF 與圖片的報告也印同一個標籤（ticket 與 spec 沒有說只用在 Office）。標籤後面的括號改成 `（MinerU backend=pipeline）`，保留原本印出的後端名稱。
  - 專案沒有改寫 RAG-Anything 的 LibreOffice 錯誤訊息（見上）；「轉檔失敗」與「沒裝」使用者看到相同的安裝說明，沒有補上 LibreOffice 的 stderr。若 ticket 05／06 實機發現這會誤導，再補。
  - 「沒有 LibreOffice」的測試靠 `PATH=<只有假 mineru 的資料夾>`，假 mineru 的 wrapper 用絕對路徑呼叫 python 與 `#!/bin/sh`，所以不依賴 PATH 上有其他東西。
  - 假 LibreOffice 對引數形式嚴格檢查（6 個引數，順序固定），RAG-Anything 改了呼叫方式測試會變紅；這是比 ticket 敘述更嚴格的假設。
  - Office 測試檔不是真的 Office 檔（見上）。
