# 10: 主檔名相同的 Office 文件不再互相覆蓋

**What to build:** 匯入兩份主檔名相同的 Office 文件時，兩份都能正確進入知識庫。例如同一個資料夾裡的 `a.docx` 與 `a.pptx`，或不同資料夾裡的 `x/a.docx` 與 `y/a.docx`，轉檔 PDF 和解析輸出都不會互相覆蓋。這是多格式擴充 code-review 留下、使用者在 2026-10-31 決定要修的項目。

**Blocked by:** None（但要等 08 的全量匯入結束才合併，見下方）

**Status:** resolved

- [x] 先用測試重現問題。RAG-Anything 1.4.3 的 `convert_office_to_pdf` 把轉出的 PDF 寫到 `<輸出資料夾>/<主檔名>.pdf`，MinerU 的解析資料夾再依這個 PDF 的路徑命名，所以同名的兩份會撞在一起。
- [x] 在 `rag_lab` 修正，不改 RAG-Anything 的安裝檔。限制如下：
  - PDF 與圖片文件的轉檔路徑、解析輸出路徑與解析快取都不能改變。主知識庫正在用目前的路徑全量匯入，改了會讓已經匯入的文件重新解析。
  - 已經匯入的 Office 文件，例如 `rights/` 的 43 份 docx，再匯入一次時要照常被略過，不能重新解析。
- [x] 修法有多種時，選最簡單、而且符合上面限制的一種，在實作結果寫明選了哪一種、理由，以及其他做法為什麼不選。
- [x] 以 `rag_lab` 現有的測試縫（CLI 子行程、Python API）測試：同名的兩份 Office 文件都匯入成功，各自的內容都查得到，或在假 MinerU 的輸出裡可以分辨。
- [x] 主測試套件全綠。
- [x] README 第 4 節有關 Office 文件的說明，如果需要就更新。

## 實作結果（2026-10-31）

**做了什麼**
- `rag_lab/pipeline.py` 新增 `_office_output_dir`，`_ingest_one` 對 Office 文件（`formats.is_office`）在呼叫 `parse_document` 與 `process_document_complete` 時多帶 `output_dir=<PARSER_OUTPUT_DIR>/office/<主檔名>_<原檔絕對路徑 md5 前 8 碼>`。RAG-Anything 因此把轉出的 PDF 寫在這個資料夾，MinerU 的解析資料夾再接在它底下。PDF 與圖片不帶 `output_dir`，路徑沒變。
- 根因（RAG-Anything 1.4.3 `parser.py`）：`convert_office_to_pdf` 寫到 `<output_dir>/<主檔名>.pdf`（317 行起），`parse_pdf` 再用 `_unique_output_dir(output_dir, pdf_path)`（250 行）依這個 PDF 路徑的雜湊命名解析資料夾，所以同主檔名的兩份文件共用同一個 PDF 與同一個解析資料夾。PDF 與圖片用原檔路徑算雜湊，沒有這個問題。
- 解析快取 key（`processor.py` 的 `_generate_cache_key`）由原檔絕對路徑、mtime、檔案內容 SHA-256、parser、parse_method 與解析參數組成，不含 `output_dir`（`output_dir` 是 `parse_document` 的具名參數，不在 `_relevant_parser_kwargs` 的輸入裡）。所以換輸出資料夾不改變 key，已匯入的文件重匯時命中快取、被略過。
- 測試夾具：`tests/fake_libreoffice.py` 轉出的 PDF 多寫一行 `% fake libreoffice source: <輸入檔第一行>`，`tests/fake_mineru.py` 遇到這一行就多輸出一段 `Converted from Office document: <文字>`。原本兩者的輸出只依主檔名，同主檔名的兩份文件內容完全相同，分辨不出來。
- README 第 4 節的 Office 說明更新（轉出的 PDF 位置、同主檔名的行為、舊路徑不搬動）。

**選的修法與理由**：只對 Office 文件另給 `output_dir`（約 10 行）。它只改 Office 文件的輸出路徑，不碰快取 key，也不動 PDF 與圖片。
**不選的做法**
- 把 Office 文件複製或建 symlink 成唯一檔名再匯入：快取 key 含原檔路徑，已匯入的 43 份 docx 會全部重新解析；報告與 doc_status 的檔名也會變。
- 在 `rag_lab` 包裝或替換 RAG-Anything 的 `convert_office_to_pdf`：要改函式庫的行為，升級時容易壞；改安裝檔又不被允許。
- 只在偵測到撞名時才用新路徑：要有地方記錄哪份來源寫了 `<主檔名>.pdf`，要多一份狀態，而且行為依匯入順序而變。
- 對所有格式都加 `output_dir`：會改變 PDF 與圖片的解析輸出路徑，違反限制。

**紅燈時的輸出**（修改前的 `rag_lab/pipeline.py`）
- `tests.test_pipeline.IngestOfficeTest.test_two_documents_with_the_same_stem_in_one_folder_...`：`AssertionError: 1 != 2 : 兩份文件各有自己轉出的 PDF，不共用同一個路徑`
- `tests.test_pipeline.IngestOfficeTest.test_two_documents_with_the_same_name_in_different_folders_...`：`AssertionError: 1 != 2`
- `tests.test_python_api.IngestOfficeTest.test_session_ingests_two_office_documents_with_the_same_stem_...`：`AssertionError: 1 != 2`
- 另外兩個特徵化測試在修改前就是綠燈，目的是證明修改沒有動到下列項目：`test_a_pdf_and_an_image_keep_their_parser_output_path`（PDF、圖片的解析輸出路徑）與 `test_an_office_document_ingested_before_is_skipped_without_parsing_again`（刪掉整個輸出資料夾後重匯，仍略過、不呼叫模型、不重建輸出資料夾）。

**最後一次測試**
- 主套件 `/Users/curtis/GitHub/llm-lab/.venv/bin/python -m unittest`：`Ran 121 tests in 445.517s` / `OK`。
- `scripts/test_fetch_taishin.py`（也用假 LibreOffice）：`Ran 116 tests in 155.846s` / `OK`。
- 一次性驗證（沒進 repo）：用修改前的 `pipeline.py` 匯入 `deck.pptx` 與 `report.docx`（輸出在舊路徑 `<output>/deck.pdf`），換成新的 `pipeline.py` 重匯：兩份都「已完整處理過，略過」，模型請求數不變，輸出資料夾的檔案清單不變。這是「已匯入的 Office 文件不受影響」的直接證據；自動測試裡的 `test_an_office_document_ingested_before_is_skipped_without_parsing_again` 是它在 repo 內可重現的替代（無法在測試裡跑舊程式碼）。

**沒做到或有疑慮**
- `docs/architecture.md` 第 62、131、132 行仍寫 `output/<主檔名>.pdf` 與舊的假命令說明；這個檔案不在這張 ticket 允許修改的範圍，需要另外更新。
- 已匯入的 Office 文件的舊輸出（`<PARSER_OUTPUT_DIR>/<主檔名>.pdf` 與解析資料夾）留在原處。若某份文件的解析快取失效（檔案被修改）而重新解析，新輸出會寫到 `office/` 底下，舊檔不會被清掉。
- 真的 MinerU 與 LibreOffice 沒跑過，只用假命令驗證；`parse_office_doc` 把 `output_dir` 同時給 `convert_office_to_pdf` 與 `parse_pdf` 是讀 1.4.3 原始碼確認的（`parser.py` 的 `parse_office_doc`）。
- ASSUMPTION：子資料夾名稱沿用 RAG-Anything 的 `<主檔名>_<md5 前 8 碼>` 慣例；8 碼雜湊在極少數文件數下碰撞機率可忽略。
- 搬動來源資料夾會改變雜湊，但這時解析快取 key（含原檔路徑）也跟著變，與既有行為一致，不是新問題。
