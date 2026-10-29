# 02: 匯入圖片

**What to build:** 使用者可以用 `ingest` 匯入單張圖片（.png .jpg .jpeg .bmp .tiff .tif .gif .webp），匯入後問得到圖片的內容；匯入資料夾時，PDF 和圖片都會被挑出來，不支援的檔案列出檔名後略過。Python API 同樣接受圖片。這條路徑不需要 LibreOffice，是第一條端到端打通的新格式。

**Blocked by:** 01

**Status:** resolved

- [x] 支援的格式在專案裡只定義一次，這張先放 PDF 與 8 種圖片格式，副檔名大小寫不分；CLI 的過濾、錯誤訊息、文件都從這份清單取值。
- [x] CLI 匯入單張圖片成功，匯入後用 `query` 問得到假 mineru 輸出的內容。需要轉成 png 的格式（至少一種，例如 .webp 或 .bmp）也能匯入。
- [x] 匯入資料夾時，不遞迴，依檔名排序挑出 PDF 與圖片；不支援的檔案逐一印出「略過不支援的格式：<檔名>」，不算錯誤。
- [x] 單一檔案格式不支援時，以非零碼結束，訊息列出支援的格式。資料夾裡沒有任何支援的文件時，以非零碼結束。
- [x] 重複匯入同一張圖片時略過，不呼叫模型；中斷後重新匯入會重試，不留下重複紀錄。行為和 PDF 相同。
- [x] Python API 縫：`Session.ingest` 與模組函式 `ingest` 接受圖片，報告欄位是 `document`。
- [x] 先紅後綠：每個新行為先寫出失敗的測試並貼出失敗輸出，再實作。「單一非 PDF 檔被拒絕」的既有測試，改寫成「支援的格式接受、不支援的拒絕」，並在本 ticket 的實作結果寫明理由（需求改變）。
- [x] README：支援的格式、圖片的已知限制（沒有文字的圖片能抽出的內容很少；單張圖片的實際效果在 ticket 06 實機驗證）。架構文件同步更新。
- [x] 主測試套件與下載腳本的測試全綠，貼出實際輸出。

## 實作結果（2026-10-28）

- 格式清單：新增 `rag_lab/formats.py`，`FORMATS`（格式名稱 → 副檔名）是專案裡唯一的清單，目前是 PDF 與 8 種圖片副檔名；`is_supported()`、`describe_supported()` 供 CLI 的過濾與錯誤訊息取值。副檔名大小寫不分。ticket 03 在 `FORMATS` 加 Office 格式即可。
- CLI 新訊息：
  - 資料夾內不支援的檔案（stdout，不算錯誤）：`略過不支援的格式：<檔名>`
  - 單一檔案格式不支援（stderr，結束碼 2）：`輸入錯誤：不支援的格式：<檔名>（支援的格式：.pdf .png .jpg .jpeg .bmp .tiff .tif .gif .webp）`
  - 資料夾內沒有支援的文件（stderr，結束碼 2）：`輸入錯誤：資料夾內沒有支援的文件：<路徑>（支援的格式：.pdf .png .jpg .jpeg .bmp .tiff .tif .gif .webp）`
- 先紅後綠（CLI 縫，`tests.test_pipeline`）。每個測試先在沒有對應實作時執行，失敗輸出如下：
  - `IngestImageTest.test_ingests_a_png_and_its_parsed_content_reaches_the_answer_prompt`：`AssertionError: 2 != 0 : 輸入錯誤：不是 PDF 檔：.../diagram.png`。清單先只放 `.pdf` 與 `.png` 後通過；通過的條件包含 naive 查詢時，回答用的 prompt 含假 mineru 的文字 `A Study of Fake Entities in diagram`。
  - `IngestImageTest.test_every_other_image_format_can_be_ingested_...`：`.jpg .jpeg .bmp .tiff .tif .gif .webp` 與 `UPPER_WEBP.WEBP` 共 8 個 subTest 失敗，都是 `2 != 0 : 輸入錯誤：不是 PDF 檔：...`（`UPPER.PNG` 已通過，因為 `.png` 在清單內，比對本來就先轉小寫）。清單補齊 8 種圖片副檔名後通過。
  - `IngestTest.test_a_folder_ingests_supported_formats_in_name_order_and_reports_skipped_files_without_failing`：`'略過不支援的格式：notes.txt' not found in '略過非 PDF：data.csv\n略過非 PDF：notes.txt\n[1/2] a.png：...`。這個測試同時檢查依檔名排序（`a.png` 在 `b.pdf` 前）與不遞迴（`sub/c.pdf` 沒被匯入）。
  - `IngestTest.test_rejects_a_single_file_in_an_unsupported_format_and_lists_the_supported_formats`：`'不支援的格式：notes.txt' not found in '輸入錯誤：不是 PDF 檔：.../notes.txt'`。
  - `IngestTest.test_rejects_a_folder_without_any_supported_document_and_lists_the_supported_formats`（空資料夾、只有 notes.txt 的資料夾兩個 subTest）：`'資料夾內沒有支援的文件' not found in '輸入錯誤：資料夾內沒有 PDF：...'`。
- 沒有獨立紅燈的測試（寫完後第一次執行就通過），原因與驗證方式：
  - `IngestImageTest.test_reingesting_the_same_image_skips_it_and_calls_no_model`（.png 與需要轉檔的 .webp）、`test_retrying_a_failed_image_processes_it_without_a_dup_record`（.webp）：略過與重試的邏輯在 `pipeline._ingest_one`，對所有文件相同；放寬過濾之前這兩個測試被輸入檢查擋下，不是因為略過邏輯。紅燈改用下面的反向檢查證明。
  - Python API 縫（`tests.test_python_api.IngestImageTest`，模組函式與 Session 各一個，涵蓋 `.png`、`.webp`、重複匯入略過、`report.document`）：`Session.ingest` 與模組函式 `ingest` 沒有檢查副檔名，圖片本來就能匯入，所以沒有紅燈。這兩個測試只能證明沒有被拒絕、報告欄位是 `document`；假 mineru 不讀內容，所以也分不出 RAG-Anything 是依圖片還是依 PDF 解析。
- 反向檢查：暫時把 `FORMATS["圖片"]` 改成空元組，執行 `IngestImageTest`（CLI）、`IngestTest`、Python API 的 `IngestImageTest`，28 個測試中有 17 個失敗項目（subTest 分開計）：圖片匯入 13 個（單張 .png 1、其他格式 9、重複匯入 2、重試 1）、資料夾挑選 1 個、不支援格式的錯誤訊息 3 個；Python API 的 2 個測試仍通過，原因如上。還原後全部通過。
- 改寫的既有測試與理由（需求改變：spec 的「支援的格式」「CLI ingest」）：
  - `test_rejects_missing_or_non_pdf_paths`（一個測試、三個 subTest：不存在、.txt、空資料夾）拆成 `test_rejects_a_missing_path`、`test_rejects_a_single_file_in_an_unsupported_format_and_lists_the_supported_formats`、`test_rejects_a_folder_without_any_supported_document_and_lists_the_supported_formats`。「單一非 PDF 檔被拒絕」不再成立（圖片要接受），改成「支援的格式接受、不支援的拒絕」，拒絕時訊息要列出支援的格式。
  - `test_non_pdf_files_in_a_folder_are_skipped_and_reported_without_failing` 改名為 `test_a_folder_ingests_supported_formats_in_name_order_and_reports_skipped_files_without_failing`。原測試把 `figure.png` 當成要被略過的非 PDF 檔，與新需求矛盾。
  - 沒有改寫的斷言：其他既有測試的斷言沒有動。
- 夾具與文字：
  - `tests/test_pipeline.py` 新增 `write_image(path)`，用 Pillow 依副檔名產生 8×8 的小圖（Pillow 是 raganything 的依賴，沒有新增依賴）；`tests/test_python_api.py` 的 driver 新增步驟 `doc:<檔名>`，印出 `report.document.name`、`skipped`、`error`。
  - `tests/fake_mineru.py` 檔頭改為「依主檔名」，註明 PDF 與圖片輸出相同，非 png／jpg 的圖片主檔名會多 `_converted`。
  - ticket 01 留下的「略過非 PDF」「不是 PDF 檔」「資料夾內沒有 PDF」、變數 `non_pdfs` 都已改掉；`grep` 搜尋 `非 PDF|不是 PDF|沒有 PDF|non_pdf` 在 `rag_lab/`、`tests/`、`README.md`、`docs/` 沒有結果。
  - README 第 4 節新增支援的格式表與圖片的已知限制；`docs/architecture.md` 新增 `formats.py` 的說明、依賴圖與測試說明。
- 測試結果：
  - 基線（base `bacf6ad`，ticket 01 的結果）：主套件 93 個。
  - 主套件：`Ran 101 tests in 364.321s`，OK（93 個基線測試加 CLI 圖片 4 個、Python API 圖片 2 個、拆分不支援格式的測試多 2 個）。
  - 下載腳本：`python -m unittest scripts/test_fetch_papers.py scripts/test_fetch_documents.py`，`Ran 23 tests in 11.781s`，OK。
- ASSUMPTION：
  - Python API（`Session.ingest`、模組函式 `ingest`）不檢查副檔名，只有 CLI 檢查；沒有被要求，沒有新增。呼叫端給不支援的副檔名時，RAG-Anything 的 `parse_document` 會嘗試當 PDF 解析。
  - 資料夾裡的子資料夾不列入「略過」訊息（原本就只看檔案）。
  - 資料夾內只有不支援的檔案時，只印「資料夾內沒有支援的文件」錯誤，不逐一列出那些檔案。
  - 測試裡的副檔名清單是獨立寫的字面值（不從 `rag_lab.formats` 取值），ticket 03 新增格式時要同步更新 `tests/test_pipeline.py` 的 `SUPPORTED_EXTENSIONS`。
  - 「圖片解析出的內容會進入回答」只靠假 mineru 的輸出驗證；真實 MinerU 對圖片的解析品質留給 ticket 06。
