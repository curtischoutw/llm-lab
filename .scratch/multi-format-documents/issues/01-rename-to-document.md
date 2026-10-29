# 01: 用語改名，匯入的單位改叫「文件」

**What to build:** 依 `GLOSSARY.md`，把程式、CLI 說明、CLI 輸出、匯入報告、Python API 與測試名稱裡指「匯入單位」的「PDF」改成「文件」（document）。這張不改任何行為：仍然只接受 PDF，只有名稱和文字改變。之後的 tickets 才能在統一的用語上加新格式，不會把改名和新功能混在同一個 diff 裡。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] Python API：`Session.ingest`、模組函式 `ingest` 的參數改名為 `documents`；匯入報告的欄位 `pdf` 改名為 `document`。不保留舊名稱，也不加相容層。
- [x] CLI 的說明文字與輸出裡，指匯入單位的「PDF」改成「文件」。「只接受 PDF」這類描述格式的句子維持原意，等 ticket 02 改行為時再改。
- [x] 程式與測試裡指匯入單位的變數名、函式名、測試名稱一併改名；只指 PDF 這一種格式的地方保留「PDF」。
- [x] 既有測試只改用語，不改斷言的意思；主測試套件與下載腳本的測試全綠，貼出實際輸出。
- [x] README、架構文件、範例裡出現的 Python API 名稱（例如 `ingest(pdfs)`、`report.pdf`）跟著改。
- [x] 文字符合使用者的寫作規則。

## 實作結果（2026-10-28）

- 這張是純改名，沒有紅燈。不變式是既有測試的斷言意義不變、全綠。
- 基線（改名前，base `da40be6`）：主套件 93 個 OK（326.1 s），下載腳本 6 個 OK（3.8 s）。
- 改名後：主套件 93 個 OK（327.0 s），下載腳本 6 個 OK（3.8 s）。
- Python API：`Session.ingest`、模組函式 `ingest` 的參數 `pdfs` 改為 `documents`；`IngestReport.pdf` 改為 `IngestReport.document`。沒有保留舊名稱，沒有相容層。`_ingest`、`_ingest_one` 的參數與迴圈變數、`rag_lab/__main__.py` 的 `_collect_pdfs`（改名 `_collect_documents`）與 `_run_ingest` 的變數同步改名。
- CLI：`ingest` 的說明文字「匯入單一 PDF 或整個資料夾」改為「匯入單一文件或整個資料夾」，路徑參數說明改為「文件或資料夾路徑」；ingest 完成後的提示「對該 PDF 重新執行 ingest 會重試」改為「對該文件」。
- 測試：`self.pdf`、driver 內的 `pdf` 變數改為 `document`；8 個以 pdf 當匯入單位命名的測試改名（例如 `test_ingests_one_document_and_reports_stage_timings`）；docstring 與註解裡指匯入單位的「PDF」改為「文件」。斷言沒有改動。
- README 與 `docs/architecture.md`：`ingest(pdfs)`、`ingest(pdfs: list[Path])` 改為 `documents`；README 的「匯入 PDF」「匯入單篇 PDF」改為「文件」。`examples/` 沒有出現舊名稱，沒有修改。
- 保留「PDF」的地方（都指 PDF 這一種格式）：
  - `rag_lab/__main__.py` 的格式判斷與訊息：`.suffix == ".pdf"`、「略過非 PDF」「不是 PDF 檔」「資料夾內沒有 PDF」，變數 `non_pdfs`，以及模組 docstring 與 `_collect_documents` docstring 裡「只處理 PDF」「非 PDF 檔」。ticket 02 改行為時再改。
  - 測試的檔名（`a.pdf`、`paper.pdf` 等）、`%PDF-1.4` 內容、`略過非 PDF` 的正規式、`test_non_pdf_files_in_a_folder_are_skipped_...`、`test_rejects_missing_or_non_pdf_paths`、`tests/test_pipeline.py` 檔頭的「PDF 內容不重要」。
  - `tests/fake_mineru.py`：模擬 MinerU 的 PDF 解析，docstring 的 `<pdf>`、「PDF 檔名」「不讀 PDF 內容」未動。
  - README 的 `.pdf` 路徑與「資料夾內的非 PDF 會略過」；`docs/architecture.md` 的 `data/papers/*.pdf` 與「5 篇 arXiv PDF」。
- ASSUMPTION：
  - 「篇」這個量詞（「3 篇匯入失敗」「1 篇文件停在 handling」）不是「PDF」字樣，沒有改。
  - `tests/fake_mineru.py` 與 `tests/test_pipeline.py` 檔頭的「PDF」當作指假 mineru 的 PDF 輸入格式，保留。
  - README 與 architecture 裡「論文」「篇」的用法指學術論文內容，沒有改。
