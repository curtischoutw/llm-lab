Status: ready-for-agent

# Spec：知識庫擴充到 PPT、Word、Excel 與圖片

## Problem Statement

知識庫目前只有 3 篇 arXiv 論文，全部是 PDF。RAG-Anything 本身支援 Office 文件與圖片，但這個專案只能匯入 PDF：

- `ingest` 指定單一檔案時，非 PDF 會被拒絕；指定資料夾時，非 PDF 會被略過。Python API 的參數也叫 `pdfs`。
- 這台機器沒有安裝 LibreOffice，而 RAG-Anything 要靠它把 Office 文件轉成 PDF，所以就算放寬過濾，PPT／Word／Excel 也匯入不了。
- 沒有任何 PPT、Word、Excel 或圖片可以匯入，也沒有可重現的取得方式。arXiv 論文有 `fetch_papers.py`，其他格式沒有。
- 沒有題目能確認新格式的內容真的進了知識庫。現有的題目檔只有 2 題，都出自論文。

使用者希望知識庫的來源涵蓋 PPT、Word、Excel 與圖片，而且每種格式都要能確認「匯入之後問得到」。

## Solution

- `ingest` 接受 PDF、PPT、Word、Excel 與 8 種圖片格式。匯入資料夾時，挑出所有支援的格式，不支援的檔案列出檔名後略過。Python API 同樣接受這些格式，參數名稱改為 `documents`。
- Office 文件由 RAG-Anything 呼叫 LibreOffice 轉成 PDF，再交給 MinerU 解析。圖片直接交給 MinerU，不是 png／jpg 的先由 RAG-Anything 轉成 png。
- 新增下載腳本，用一個指令下載 11 份公開文件，核對雜湊後分成兩個資料夾：
  - 6 份 RAG 主題的文件，要加進主知識庫：PPT 2、Word 2、圖片 2。
  - 5 份只用來確認格式能用的文件：Excel 2，舊格式 .ppt、.doc、.xls 各 1。
- 新增一份題目檔，每份新文件出 1–2 題只能從那份文件找到答案的題目，另加 2 題跨格式的題目。
- 實機驗證分兩部分：
  - 主知識庫：先備份，再匯入 6 份文件，用 `eval` 跑題目檔確認問得到。
  - 格式驗證知識庫：用暫時的 `WORKING_DIR` 匯入那 5 份文件，問表格數字確認格式可用，留下紀錄後刪除這個知識庫。

## User Stories

### 匯入

1. 身為使用者，我想用 `ingest` 匯入一份 .pptx，這樣投影片的內容就會進入知識庫。
2. 身為使用者，我想用 `ingest` 匯入一份 .docx，這樣 Word 文件的內容就會進入知識庫。
3. 身為使用者，我想用 `ingest` 匯入一份 .xlsx，這樣表格的內容就會進入知識庫。
4. 身為使用者，我想匯入舊格式的 .ppt、.doc、.xls，這樣手上的舊檔案不必先自己轉檔。
5. 身為使用者，我想匯入 .png 或 .jpg 圖片，這樣架構圖和截圖裡的文字與內容就會進入知識庫。
6. 身為使用者，我想匯入 .bmp、.tiff、.tif、.gif、.webp 圖片，不必先自己轉成 png。
7. 身為使用者，我想用 `ingest <資料夾>` 一次匯入資料夾裡所有支援格式的文件，不必一份一份下指令。
8. 身為使用者，匯入資料夾時，我想在輸出裡看到哪些檔案因為格式不支援而被略過，這樣才不會誤以為檔案匯入了卻問不到。
9. 身為使用者，指定單一檔案而且格式不支援時，我想看到清楚的錯誤訊息，列出支援的格式。
10. 身為使用者，資料夾裡沒有任何支援的格式時，我想看到清楚的錯誤訊息，而不是「匯入 0 份」的成功結果。
11. 身為使用者，我想看到每份文件的匯入報告（各階段耗時、圖譜統計），而且報告寫的是「文件」，不是「PDF」。
12. 身為使用者，匯入 Office 文件時，我想讓報告的解析時間標成「解析（含 Office 轉 PDF）」，這樣看到 PPT 解析時間特別長時，知道裡面包含了轉檔。
13. 身為使用者，沒有安裝 LibreOffice 卻匯入 Office 文件時，我想看到指出是 LibreOffice 缺少的錯誤，並且知道怎麼安裝。
14. 身為使用者，資料夾裡有一份 Office 文件轉檔失敗時，我想讓其他文件照常匯入，失敗的那份列出名稱與原因，結束碼不為 0。這和現有「一篇 PDF 失敗」的行為一致。
15. 身為使用者，我想讓重複匯入同一份 PPT、Word、Excel 或圖片時直接略過，不重新呼叫模型。這和 PDF 的行為一致。
16. 身為使用者，我想讓匯入中斷後重新執行時，未完成的 Office 文件或圖片會重試，而且不會在知識庫裡留下重複紀錄。
17. 身為使用者，我想讓投影片、Word 文件裡的內嵌圖片也經過 VLM 描述，就像 PDF 裡的圖片一樣。

### Python API

18. 身為在 Python 裡呼叫的開發者，我想用 `Session.ingest(documents)` 匯入任何支援格式的文件。
19. 身為在 Python 裡呼叫的開發者，我想讓模組函式 `ingest(documents)` 同樣接受新格式。
20. 身為在 Python 裡呼叫的開發者，我想讓匯入報告的欄位名稱是 `document`，和 CLI 用語一致。

### 取得文件

21. 身為使用者，我想用一個指令下載這次選定的 11 份公開文件，在任何機器上都能重建同一批文件。
22. 身為使用者，我想讓下載腳本把主知識庫要用的文件放進 `data/documents/`，格式驗證用的文件放進 `data/format_check/`，這樣用資料夾匯入時不會混在一起。
23. 身為使用者，我想讓下載腳本核對每份文件的 SHA-256，來源檔案被更換時就中止並指出是哪一份，這樣重建時拿到的一定是同一份內容。
24. 身為使用者，我想讓已經下載而且雜湊正確的文件被略過，重新執行腳本時不必重新下載。
25. 身為使用者，下載中斷時，我想讓殘缺的檔案不會被當成完整檔案；下次執行時會重新下載。
26. 身為使用者，我想只下載其中一組（只要主知識庫的，或只要格式驗證的），不必每次都下載 11 份。
27. 身為使用者，我想看到每份文件的授權與出處，這樣知道這些檔案只適合在本地研究使用。
28. 身為使用者，網路或 HTTP 失敗時，我想讓腳本以非零碼結束並指出是哪一份文件，不默默略過。

### 驗證

29. 身為使用者，我想要一份題目檔，針對每份新文件出只能從那份文件找到答案的題目，這樣能確認內容真的進了知識庫，而不是從論文答出來的。
30. 身為使用者，我想要跨格式的題目（例如投影片和論文講的是同一件事），確認新文件的實體和既有的圖譜連得起來。
31. 身為使用者，我想用現有的 `eval` 跑這份題目檔，比較五種檢索模式的結果。
32. 身為使用者，我想在匯入新文件前保留一份主知識庫的備份，這樣可以比較擴充前後的差異，或在新文件弄亂圖譜時回復。
33. 身為使用者，我想用暫時的 `WORKING_DIR` 匯入 Excel 和舊格式文件，確認這些格式能用，但不讓無關的內容進入主知識庫。
34. 身為使用者，我想知道實機匯入每份新文件花了多久、PPT 轉檔佔了多久、記憶體峰值多少，這樣下次擴充可以估計時間。
35. 身為使用者，我想知道 Excel 轉成 PDF 之後遺失了什麼（多個工作表、寬表格被切頁等），這樣決定之後要不要另外寫直接讀儲存格的路徑。

### 文件

36. 身為使用者，我想在 README 看到怎麼安裝 LibreOffice、怎麼下載新文件、支援哪些格式。
37. 身為使用者，我想在 README 看到各格式的已知限制（Excel 轉 PDF 的損失、PPT 轉檔耗時、沒有文字的圖片能抽出的內容很少）。
38. 身為使用者，我想在架構文件看到新的資料夾（`data/documents/`、`data/format_check/`）、新腳本、新測試夾具的說明。
39. 身為使用者，我想讓 README 的實測數據加上新格式的匯入耗時與問答結果。
40. 身為維護者，我想讓所有文件、程式、測試名稱都用 glossary 的「文件」「格式」「知識庫」「格式驗證知識庫」，不再把匯入的單位叫做 PDF。

## Implementation Decisions

### 用語

- 依 `GLOSSARY.md`：匯入的單位叫**文件**，檔案類型叫**格式**；「PDF」只指 PDF 這一種格式。
- 程式裡指匯入單位的名稱全部改名，不保留舊名稱或相容層：`pdfs` → `documents`、`IngestReport.pdf` → `IngestReport.document`、CLI 說明與輸出裡的「PDF」→「文件」。

### 支援的格式

- 支援的格式以副檔名判定，大小寫不分：
  - PDF：.pdf
  - PPT：.ppt、.pptx
  - Word：.doc、.docx
  - Excel：.xls、.xlsx
  - 圖片：.png、.jpg、.jpeg、.bmp、.tiff、.tif、.gif、.webp
- 這份清單在專案裡只定義一次，CLI 的過濾、錯誤訊息和文件都從這裡取值。
- 不支援 txt／md，雖然 RAG-Anything 支援。這次不在範圍內。
- 每種格式怎麼解析都交給 RAG-Anything 1.4.3 的 `parse_document` 依副檔名分派，專案不自己判斷：
  - Office 文件：LibreOffice 轉成 PDF，再交給 MinerU。
  - 圖片：直接交給 MinerU；不是 png／jpg 的，先用 Pillow 轉成 png。
- parser 維持 MinerU，不引入 Docling。

### CLI `ingest`

- 單一檔案：格式不支援就以非零碼結束，訊息列出支援的格式。
- 資料夾：不遞迴，挑出所有支援格式的文件，依檔名排序；不支援的檔案逐一印出「略過不支援的格式：<檔名>」；沒有任何支援的文件就以非零碼結束。
- 匯入報告的解析階段標籤改成「解析（含 Office 轉 PDF）」，不另外計算轉檔時間。轉檔是在 RAG-Anything 的解析呼叫裡面進行的，要拆開計時就得侵入它的內部。
- 其他行為不變：一份失敗時其他照常匯入、失敗的列出名稱、結束碼不為 0；重複匯入時略過；中斷後重試。

### LibreOffice

- 依賴：LibreOffice（`brew install --cask libreoffice`）。用途是把 Office 文件轉成 PDF。MinerU 2.0 之後拿掉了 Office 轉檔，RAG-Anything 指定用 LibreOffice。使用者已在 grilling Q2 同意安裝。
- RAG-Anything 依序嘗試 PATH 上的 `libreoffice` 和 `soffice`，轉檔逾時由環境變數 `LIBREOFFICE_CONVERT_TIMEOUT` 控制（預設 600 秒）。專案不改這兩點，只在文件寫明。
- 轉出來的 PDF 寫在 parser 輸出資料夾（`PARSER_OUTPUT_DIR`）底下，不會留在來源資料夾，所以下次匯入資料夾時不會被當成新文件。
- 沒裝 LibreOffice 時，RAG-Anything 拋出的錯誤會成為那份文件的匯入失敗原因。驗收要確認使用者看得到「LibreOffice」和安裝方式。如果 RAG-Anything 的原始訊息做不到，就由專案補上說明，但不吞掉原本的錯誤。

### 下載腳本

- 新增一支和 `fetch_papers.py` 同類的下載腳本，只用標準函式庫。
- 腳本裡寫死一份清單，每筆包含：URL、預期的 SHA-256、檔名、格式、授權與出處、目標資料夾（`data/documents/` 或 `data/format_check/`）。
- 先驗證參數，再發出網路請求。可以只下載其中一組。
- 下載先寫成 `.part`，核對 SHA-256 後才改名。雜湊不符時中止並指出是哪一份文件，`.part` 不會被改名成正式檔案。
- 已存在而且雜湊正確的檔案略過。已存在但雜湊不符時以非零碼結束並指出檔名，不自動覆蓋。
- 任何失敗（網路、HTTP、雜湊）都以非零碼結束，並指出是哪一份文件。
- 帶可辨識的 User-Agent。可以用環境變數改寫下載位址的前綴，只給測試指向本機假 server 用（比照 `FETCH_PAPERS_ARXIV_BASE`）。
- SHA-256 在實作時從實際下載的檔案算出來，寫進清單。

### 題目檔

- 新增 `eval/questions.formats.jsonl`，納入版本控管。欄位沿用現有題目檔（`id`、`question`、`reference`、`type`、`source`），`source` 填文件名稱。
- 主知識庫的每份新文件出 1–2 題，答案只能從那份文件找到，不能從已匯入的 3 篇論文答出。另加 2 題跨格式的題目。
- 格式驗證知識庫的題目另外放一份題目檔，例如問表格裡的數字。它和主知識庫的題目檔分開，因為兩者要對不同的 `WORKING_DIR` 跑。
- 參考答案根據文件原文撰寫。

### 實機驗證流程

1. 安裝 LibreOffice，下載 11 份文件。
2. 把 `rag_storage` 複製成 `rag_storage.before-formats/`，同樣不進版本控管。
3. 啟動兩個 MLX server，同時以 zsh 執行 watchdog（門檻 22 GB），比照過去的實機驗證。
4. 主知識庫：`ingest data/documents`，記錄每份文件的耗時、從 log 時間戳記讀出的轉檔時間、wired 記憶體峰值、圖譜增加的實體與關係數。接著用 `eval` 跑主知識庫的題目檔。
5. 格式驗證知識庫：設定 `WORKING_DIR=<暫存路徑>`，執行 `ingest data/format_check`，再用 `eval` 跑格式驗證的題目檔，並記錄 Excel 多工作表的解析結果。紀錄存到 `output/` 底下之後，刪除這個暫存的 `WORKING_DIR`。
6. 驗證完關掉 server 與 watchdog。

- 驗收標準：
  - 主知識庫：mix 模式下，每份新文件至少答對 1 題。
  - 格式驗證知識庫：每種格式（Excel、舊 PPT、舊 Word、舊 Excel）都匯入成功，而且至少有 1 題問得到該文件的內容。
  - 答對與否由實作者對照參考答案判斷，使用者再抽查。

### 文件更新

- README：
  - 支援的格式；
  - 安裝 LibreOffice；
  - 下載新文件；
  - 匯入新文件；
  - 各格式的已知限制；
  - 新格式的實測數據。
- 架構文件：新資料夾、新腳本、新的測試夾具、用語變更。
- `GLOSSARY.md` 已在 grilling 期間建立，內容包含文件、格式、知識庫、格式驗證知識庫。

## Testing Decisions

- 好的測試只從外部行為驗證：子行程的結束碼、stdout／stderr、知識庫查得到的內容、假 server 收到的請求。不 import 內部函式，也不檢查私有狀態。這和現有測試的原則相同。
- 測試縫（已與使用者確認，沒有新增測試縫）：
  1. **CLI 子行程**，比照 `tests/test_pipeline`：
     - 每種格式（PPT、Word、Excel、圖片，含需要轉 png 的圖片格式）都能從 CLI 匯入，匯入後問得到內容；
     - 資料夾匯入時挑出支援的格式，並列出略過的檔案；
     - 單一檔案格式不支援時的錯誤；資料夾裡沒有支援格式時的錯誤；
     - 報告標籤；
     - 沒有 LibreOffice 時的錯誤訊息：PATH 只放假 mineru、不放假 soffice；
     - Office 文件轉檔失敗時，其他文件照常匯入；
     - 重複匯入 Office 文件或圖片時略過，不呼叫模型。
  2. **Python API 縫**，比照 `tests/test_python_api` 的 driver：`Session.ingest` 和模組函式 `ingest` 接受新格式，報告欄位是 `document`。
  3. **下載腳本子行程**，比照 `scripts/test_fetch_papers`，對本機假 HTTP server：
     - 雜湊核對；
     - `.part` 改名；
     - 略過已存在的檔案；
     - 雜湊不符時中止，`.part` 沒有被改名；
     - 已存在但雜湊不符時報錯；
     - 檔案放進正確的資料夾；
     - 只下載一組；
     - HTTP 失敗時指出是哪一份文件。
- 新增測試夾具：假 LibreOffice，同時提供 `libreoffice` 和 `soffice` 兩個名稱，放在測試的 PATH 最前面。如果只放 `soffice`，機器上裝了真的 LibreOffice 時，RAG-Anything 會先找到真的 `libreoffice`。
  - 假 LibreOffice 收到 `--headless --convert-to pdf --outdir <dir> <檔案>` 時，在 `<dir>` 寫出 `<主檔名>.pdf`。
  - 主檔名以 `broken` 開頭時以非零碼結束，模擬轉檔失敗，比照假 mineru 的慣例。
- 假 mineru 不讀檔案內容，對圖片和轉出來的 PDF 都輸出固定的 content list。驗證的重點是流程與分派，不是解析品質。
- 解析品質、問答正確性、轉檔耗時，只靠實機驗證，不放進快速測試。
- 修改既有測試時，只改用語（例如 `pdfs` → `documents`），不改斷言的意思。「單一非 PDF 檔被拒絕」這類行為已經被這次的需求推翻，相關測試改寫成新行為（支援的格式接受、不支援的拒絕），並在 ticket 裡說明理由。

## Out of Scope

- txt／md 格式。
- 換掉 4B LLM，或用更強的模型重建圖譜。圖譜品質問題（參考文獻作者被當成論文作者等）不在這次範圍。
- Excel 直接讀儲存格的解析路徑。等實機結果不夠好時，再開新的 spec。
- Docling 或其他 parser。
- 遞迴匯入子資料夾。
- 把下載的文件或知識庫推上 GitHub。`data/` 和 `WORKING_DIR` 照舊不進版本控管。
- README 的「切塊與檢索設定」說明。使用者另外提出，等使用者提供 `/btw` 的原始問題後另外處理。

## Further Notes

### 選定的文件（grilling Q17–Q23；URL 與授權在 2026-10-28 由 agent 查證，每個 URL 都回 HEAD 200）

主知識庫，放進 `data/documents/`：

| 格式 | 文件 | URL | 授權（所在 repo） |
|---|---|---|---|
| PPT | RAG Hack「Evaluating a RAG chat app」（25 張） | https://raw.githubusercontent.com/microsoft/RAG_Hack/main/slides/RAGHack-EvaluatingAChatApp.pptx | MIT（microsoft/RAG_Hack） |
| PPT | Docling 架構圖（1 張，純文字方塊） | https://raw.githubusercontent.com/docling-project/docling/main/docs/assets/docling_arch.pptx | MIT（docling-project/docling） |
| Word | Experimentations for KG creation | https://raw.githubusercontent.com/neo4j-labs/llm-graph-builder/main/experiments/Experimentations%20for%20Kg%20creation.docx | Apache-2.0（neo4j-labs/llm-graph-builder） |
| Word | LLM Comparisons with one pdf | https://raw.githubusercontent.com/neo4j-labs/llm-graph-builder/main/experiments/LLM%20Comparisons%20with%20one%20pdf.docx | Apache-2.0（同上） |
| 圖片 | GraphRAG Prompt Tuning 流程圖 | https://raw.githubusercontent.com/microsoft/graphrag/main/docs/img/auto-tune-diagram.png | MIT（microsoft/graphrag） |
| 圖片 | GraphRAG 統一搜尋 App 截圖（Local／Global／DRIFT／basic） | https://raw.githubusercontent.com/microsoft/graphrag/main/unified-search-app/images/image-1.png | MIT（同上） |

格式驗證知識庫，放進 `data/format_check/`：

| 格式 | 文件 | URL | 授權（所在 repo） |
|---|---|---|---|
| Excel | Nestlé 2023 上半年分部分析（5 個工作表） | https://raw.githubusercontent.com/Unstructured-IO/unstructured/main/example-docs/2023-half-year-analyses-by-segment.xlsx | Apache-2.0（Unstructured-IO/unstructured） |
| Excel | xlsx_01.xlsx（4 個工作表） | https://raw.githubusercontent.com/docling-project/docling/main/tests/data/xlsx/sources/xlsx_01.xlsx | MIT（docling-project/docling） |
| PPT（舊格式） | legacy_sample.ppt | https://raw.githubusercontent.com/docling-project/docling/main/tests/data/ppt/sources/legacy_sample.ppt | MIT（同上） |
| Word（舊格式） | legacy_sample.doc | https://raw.githubusercontent.com/docling-project/docling/main/tests/data/doc/sources/legacy_sample.doc | MIT（同上） |
| Excel（舊格式） | legacy_sample.xls | https://raw.githubusercontent.com/docling-project/docling/main/tests/data/xls/sources/legacy_sample.xls | MIT（同上） |

- 授權欄是文件所在 repo 的 LICENSE。文件內的第三方素材（例如 RAG Hack 投影片裡的 Microsoft 商標、Nestlé 的財報數字）沒有查證，依 grilling Q9 只在本地研究使用。
- 選文件的原則：主知識庫的文件要和 RAG 主題相關，而且內容不能和已匯入的論文重複，否則問得到答案時分不出是來自哪一份文件。所以沒選 LightRAG Figure 1、RAG-Anything 框架圖。
- 找不到 RAG 主題的 Excel：搜過 GitHub code search、Hugging Face 183 個 dataset，以及約 30 個 repo 的檔案樹。所以 Excel 只在格式驗證知識庫驗證。
- 時間推估：每篇論文匯入 25–45 分鐘。PPT 轉檔依 RAG-Anything 原始碼的註解，7.4 MB 的 PPTX 要 4 分鐘。6 份主知識庫的文件加 5 份格式驗證的文件，粗估合計 3–5 小時，沒有實測。
- grilling 的決策紀錄（Q1–Q24）在 2026-10-28 的對話裡；這份 spec 的每一節都已經寫入對應的決策。
