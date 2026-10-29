# rag-anything-lab

用 [RAG-Anything](https://github.com/HKUDS/RAG-Anything) 1.4.3（底層 LightRAG）做的本地 RAG 實驗環境。四個指令：`ingest` 匯入文件、`query` 提問、`eval` 用題目檔批次比較五種檢索模式、`graph` 抽樣檢視知識圖譜。

三個模型（LLM、VLM、embedding）都經由 OpenAI 相容的 HTTP 端點呼叫，端點與模型名稱全部寫在 `.env`。本機用 MLX server 提供；換機器或換模型時只改 `.env`。

規格與實測紀錄在 `.scratch/rag-anything-lab/`（`spec.md` 與 `issues/`）。每個目錄與程式的用途見 [`docs/architecture.md`](docs/architecture.md)。

## 1. 建立環境

需求：Apple Silicon Mac（以下數據在 M2 Pro、32 GB 上量測）、[pyenv](https://github.com/pyenv/pyenv)、[pipx](https://pipx.pypa.io/)。

專案 venv（Python 3.12.12，相依套件鎖在 `requirements.txt`）：

```sh
pyenv install --skip-existing 3.12.12
"$(pyenv root)/versions/3.12.12/bin/python" -m venv .venv
.venv/bin/pip install -r requirements.txt
```

MLX server 用 pipx 另外安裝，不放進專案 venv（避免與 MinerU、torch 的相依衝突）：

```sh
pipx install mlx-lm==0.32.0
pipx install mlx-vlm==0.7.10
```

LibreOffice（只有匯入 PPT、Word、Excel 時需要，PDF 與圖片不需要）。RAG-Anything 先用 LibreOffice 把 Office 文件轉成 PDF，再交給 MinerU：

```sh
brew install --cask libreoffice
```

RAG-Anything 依序嘗試 PATH 上的 `libreoffice`、`soffice`。轉檔逾時由環境變數 `LIBREOFFICE_CONVERT_TIMEOUT` 控制，預設 600 秒；大型文件逾時時，錯誤訊息會指出這個變數。這個專案不改這兩點。

設定檔：

```sh
cp .env.example .env
```

`.env.example` 的預設值對應下一節的本機 server，每個欄位的用途寫在檔案註解裡。`.env` 不進版本控管。

## 2. 下載論文

```sh
.venv/bin/python scripts/fetch_papers.py
```

下載 5 篇 RAG 主題的 arXiv 論文到 `data/papers/`，每篇都會先比對 arXiv 上的標題。已存在的完整檔案會略過。只下載部分論文：`--ids 2410.05779 2510.12323`。

### 下載其他格式的文件

```sh
.venv/bin/python scripts/fetch_documents.py
```

下載 11 份公開文件：6 份 RAG 主題的文件（PPT 2、Word 2、圖片 2）放進 `data/documents/`，5 份只用來確認格式能用的文件（Excel 2，舊格式 .ppt、.doc、.xls 各 1）放進 `data/format_check/`。每份都核對 SHA-256，來源檔案被更換時以非零碼結束並指出是哪一份。已存在而且雜湊正確的檔案會略過；已存在但雜湊不符時不覆蓋，也以非零碼結束。只下載一組：`--group documents` 或 `--group format_check`。`--out` 改下載的根資料夾（預設 `data/`）。

這些文件各自屬於所在的 repo，授權是該 repo 的 LICENSE：

| 組 | 來源 repo | 授權 | 份數 |
|---|---|---|---|
| `data/documents/` | microsoft/RAG_Hack、microsoft/graphrag | MIT | 3 |
| `data/documents/` | docling-project/docling | MIT | 1 |
| `data/documents/` | neo4j-labs/llm-graph-builder | Apache-2.0 | 2 |
| `data/format_check/` | docling-project/docling | MIT | 4 |
| `data/format_check/` | Unstructured-IO/unstructured | Apache-2.0 | 1 |

每份文件的 URL、格式與授權寫在 `scripts/fetch_documents.py` 的 `DOCUMENTS`。文件內的第三方素材（RAG Hack 投影片裡的 Microsoft 商標、Nestlé 財報的數字）沒有逐項查證授權，所以這些文件只在本地研究使用，不要重新散布，也不要推上 GitHub（`data/` 不進版本控管）。URL 指向各 repo 的 `main` 分支，不是固定的 commit。

## 3. 啟動本地模型 server

兩個 server 各開一個終端機，在 repo 根目錄執行。

LLM（port 8080）：

```sh
mlx_lm.server --host 127.0.0.1 --port 8080 \
  --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --max-tokens 4096 --prompt-cache-bytes 4GB
```

- `--max-tokens 4096`：`mlx_lm.server` 預設輸出上限 512 token，會截斷實體抽取的輸出。
- `--prompt-cache-bytes 4GB`：限制 prompt cache 的大小，實測最高用到 3.7 GB。

VLM 與 embedding（同一個 server，port 8081）：

```sh
~/.local/share/pipx/venvs/mlx-vlm/bin/python scripts/vlm_server.py --mlx-cache-limit-gb 1 \
  --host 127.0.0.1 --port 8081 \
  --model mlx-community/Qwen3-VL-4B-Instruct-4bit \
  --embedding-model mlx-community/Qwen3-Embedding-0.6B-8bit
```

`scripts/vlm_server.py` 先把 MLX 保留的 GPU buffer cache 上限設為 1 GB，再啟動 `mlx_vlm.server`。mlx-vlm 0.7.10 的 embedding 路徑不會清 cache，ingest 期間 server 會從 5 GB 增加到 13 GB，與 LLM server 加起來超過 32 GB 機器的 GPU 記憶體。

確認三個端點可用（chat、看 base64 圖片、embedding 維度）：

```sh
.venv/bin/python scripts/smoke_test.py
```

**32 GB 機器的記憶體限制**（ticket 03 實測）：`.env` 的 `LLM_MAX_ASYNC` 要設 1，設 2 時兩個長生成請求同時進行會讓 `mlx_lm.server` GPU 記憶體不足；`QUERY_MAX_TOTAL_TOKENS` 設 12000，LightRAG 預設的 30000 會讓 mix 查詢的 prompt 到 29.7k token，同樣記憶體不足。

## 4. 使用

不需要先 activate venv，直接用 venv 的 python 執行。

**支援的格式**：以副檔名判定，大小寫不分。

| 格式 | 副檔名 |
|---|---|
| PDF | `.pdf` |
| PPT | `.ppt` `.pptx` |
| Word | `.doc` `.docx` |
| Excel | `.xls` `.xlsx` |
| 圖片 | `.png` `.jpg` `.jpeg` `.bmp` `.tiff` `.tif` `.gif` `.webp` |

- 單一檔案的格式不支援時，`ingest` 以結束碼 2 結束，訊息列出支援的格式。
- 匯入資料夾時，只挑出支援格式的檔案，依檔名排序，不遞迴；不支援的檔案逐一印出 `略過不支援的格式：<檔名>`，不算錯誤。資料夾內沒有任何支援的文件時，以結束碼 2 結束。
- 圖片：`.png`、`.jpg`、`.jpeg` 直接交給 MinerU；其他格式先由 RAG-Anything 用 Pillow 轉成 png 再交給 MinerU。轉檔用的暫存檔不會留在來源資料夾。
- 圖片的已知限制：沒有文字的圖片，MinerU 能抽出的內容很少，內容主要來自 VLM 的描述。實測 2 張圖片時（第 5 節），流程圖的 VLM 描述寫出了各節點的名稱，截圖的文字也被 OCR 出來，但兩張圖片各自的題目在 mix 模式都沒有答對，因為這些切塊沒有被選進查詢的 context。
- 重複匯入同一張圖片會略過，不呼叫模型；匯入中斷後重新執行會重試，不會留下重複的紀錄。行為和 PDF 相同。
- Office 文件（PPT、Word、Excel，含舊格式 .ppt .doc .xls）：RAG-Anything 呼叫 LibreOffice 轉成 PDF，再交給 MinerU。轉出的 PDF 寫在 `PARSER_OUTPUT_DIR` 底下，不會留在來源資料夾，所以下次匯入同一個資料夾時不會被當成新文件。需要先安裝 LibreOffice（第 1 節）。匯入報告的解析階段標籤是「解析（含 Office 轉 PDF）」，轉檔時間包含在裡面，沒有另外計時。
- 沒有安裝 LibreOffice 時，那份文件匯入失敗，`stderr` 的訊息是 RAG-Anything 的原始錯誤，包含「LibreOffice」與各平台的安裝方式（macOS：`brew install --cask libreoffice`）；結束碼 1。資料夾裡其他文件照常匯入。Office 文件轉檔失敗（LibreOffice 以非零碼結束）時，訊息相同，因為 RAG-Anything 無法區分兩者；逾時時訊息改為指出 `LIBREOFFICE_CONVERT_TIMEOUT`。
- Office 文件的已知限制（Excel 與舊格式的實測見第 5 節）：
  - Excel 轉成 PDF 頁面後由 MinerU 做表格辨識，不讀儲存格。實測時，旋轉的欄位標題被 OCR 成無法辨識的文字（例如 Underlying Trading operating profit 變成 `Undeng Tedng peong pnyh`）；表格上方的「January–June 2023」這類標題沒有進入任何內容項目，同一頁的兩張表分不出年份；同一個工作表裡並排的兩張表被合併成一張、欄位錯位。所以問表格裡的特定數字時，常常答成同一張表的其他欄或其他年份。每個工作表都有被解析；寬的工作表會被切成多頁。
  - 主檔名相同的 Office 文件（例如同一個資料夾裡的 `report.docx` 與 `report.pptx`，或不同資料夾裡的兩份 `report.docx`）會轉成同一個 `PARSER_OUTPUT_DIR/<主檔名>.pdf`，解析結果也寫進同一個資料夾，後匯入的會覆蓋先匯入的轉檔 PDF 與內容清單。文件是逐份匯入的，每份的內容在被覆蓋前就已寫入知識庫；圖片以雜湊命名，不會被覆蓋。實測 `legacy_sample.ppt`／`.doc`／`.xls` 時發生，三份都問得到。重新解析被覆蓋的文件時會重新轉檔。PDF 與圖片沒有這個問題，它們的解析資料夾名稱含原檔路徑的雜湊。
  - PPT 轉檔可能要好幾分鐘：RAG-Anything 原始碼的註解記錄 7.4 MB 的 PPTX 要 4 分鐘。

匯入單篇文件：

```sh
.venv/bin/python -m rag_lab ingest data/papers/2410.05779.pdf
```

匯入整個資料夾（逐份處理；已完整匯入的文件會略過）。目前的知識庫是下面這 3 篇論文，加上 `data/documents/` 的 6 份文件。論文資料夾裡放的是指向 `data/papers/` 的 symlink：RAG-Anything 的文件 ID 是解析內容（文字、表格、公式與圖片路徑）的雜湊，而圖片所在的解析輸出資料夾名稱取自 symlink 解析後的原檔路徑，所以同一篇論文不會因為放在不同資料夾而被當成新文件。

```sh
mkdir -p data/corpus
ln -sf ../papers/2410.05779.pdf ../papers/2404.16130.pdf ../papers/2510.12323.pdf data/corpus/
.venv/bin/python -m rag_lab ingest data/corpus
.venv/bin/python -m rag_lab ingest data/documents
```

另外 2 篇（2005.11401 RAG、2310.11511 Self-RAG）已下載但沒有匯入；每篇匯入耗時可參考第 5 節。`data/format_check/` 的 5 份文件只在暫時的知識庫驗證過，沒有匯入主知識庫。

提問，預設 mix 模式；`--mode` 可選 naive、local、global、hybrid、mix；`--vlm-enhanced` 讓 VLM 看檢索到的圖片後產生答案（預設關閉）：

```sh
.venv/bin/python -m rag_lab query "What are the two retrieval levels in LightRAG?"
.venv/bin/python -m rag_lab query --mode naive "What is the main idea of RAG-Anything?"
```

抽樣檢視知識圖譜（預設 10 個實體與涉及它們的關係，不需要模型 server）：

```sh
.venv/bin/python -m rag_lab graph
```

批次比較五種檢索模式。題目檔是 JSONL，欄位 `id`、`question`、`reference`、`type`（text／figure／table／cross-paper）、`source`，範例見 `eval/questions.example.jsonl`。結果寫到 `eval_results/eval_<時間戳記>.md`，每題一列、每種模式一欄；有任何一格失敗時以非零碼結束：

```sh
.venv/bin/python -m rag_lab eval eval/questions.example.jsonl
```

在 Python 裡呼叫（設定一樣讀 `.env`）。在同一個 `Session` 裡問多題，知識庫只載入一次：

```python
from rag_lab.pipeline import Session

with Session() as session:
    answer = session.query("What are the two retrieval levels in LightRAG?", mode="mix")
```

只問一題也可以直接呼叫 `rag_lab.pipeline.query(question, mode="mix")`，它等於開一個 `Session`、問一題、關閉。完整範例在 `examples/query_from_python.py`，在 repo 根目錄用 `.venv/bin/python -m examples.query_from_python` 執行；`Session` 的規則與 `ingest`、`evaluate` 的說明見 `docs/architecture.md` 第 4 節。

## 5. 實測數據

模型組合：LLM `Qwen3-4B-Instruct-2507-4bit`、VLM `Qwen3-VL-4B-Instruct-4bit`、embedding `Qwen3-Embedding-0.6B-8bit`；MinerU backend `pipeline`；`LLM_MAX_ASYNC=1`、`EMBED_MAX_ASYNC=1`、`QUERY_MAX_TOTAL_TOKENS=12000`；M2 Pro 32 GB。2410.05779 是 2026-10-26 單篇匯入時量測，另外兩篇是 2026-10-27 以資料夾匯入時量測（紀錄在 `.scratch/rag-anything-lab/issues/03-*.md` 與 `05-*.md`）。

| 論文 | 頁數 | MinerU 解析 | 建圖 | 圖／表／公式描述 | 合計 |
|---|---|---|---|---|---|
| 2410.05779 LightRAG | 16 | 36 s | 644 s | 787 s（14 項） | 1472 s |
| 2404.16130 GraphRAG | 26 | 42 s | 1218 s | 852 s（13 項） | 2113 s |
| 2510.12323 RAG-Anything | 18 | 31 s | 780 s | 1864 s（27 項） | 2676 s |

- 3 篇匯入後的圖譜：實體 1358，關係 1835（其中 735 條是 RAG-Anything 加的 belongs_to 邊）。ingest 期間 wired 記憶體最高 18 GB。
- 查詢（3 篇的知識庫，五種模式各 1 題）每題 52–66 s；`eval` 2 題 × 5 種模式 522 s。同一個問題再問一次會命中 LightRAG 的 LLM 快取，查詢 4 s、同一份題目檔的 `eval` 3 s。
- LLM 快取的 key 由模式與問題文字等查詢參數算出，不包含檢索到的內容。知識庫匯入新文件後，問以前問過的問題，拿到的仍是匯入前的答案（2026-10-29 擴充後重跑 `eval/questions.example.jsonl`，10 格都是快取命中）。要讓舊問題用新的知識庫回答，要先從 `WORKING_DIR` 的 `kv_store_llm_response_cache.json` 刪掉 key 含 `:query:` 的項目。
- MinerU 後端比較（LightRAG 論文、server 關閉時）：pipeline 51 s、hybrid-engine 140 s、vlm-engine 711 s（transformers 推論）。pipeline 與 hybrid-engine 抽出的圖、表、公式數量相同。

Excel 與舊格式（格式驗證知識庫，2026-10-29 量測，LibreOffice 26.8.1.1；紀錄在 `output/formats_check_run/` 與 `.scratch/multi-format-documents/issues/05-*.md`）：

| 文件 | 解析（含 Office 轉 PDF） | 其中 LibreOffice 轉檔 | 建圖 | 圖／表描述 | 合計 |
|---|---|---|---|---|---|
| Nestlé 財報 `.xlsx`（5 個工作表） | 24 s | 約 1 s | 19 s | 487 s（7 項） | 529 s |
| `legacy_sample.doc` | 19 s | 約 1 s | 24 s | 70 s（2 項） | 113 s |
| `legacy_sample.ppt` | 17 s | 約 1 s | 34 s | 58 s（1 項） | 108 s |
| `legacy_sample.xls` | 14 s | 約 1 s | 0 s | 52 s（1 項） | 66 s |
| `xlsx_01.xlsx`（4 個工作表） | 17 s | 不到 1 s | 0 s | 296 s（8 項） | 313 s |

- 轉檔時間是從 log 的時間戳記讀出的（精度 1 秒）。整張表都被辨識成表格的文件，沒有文字切塊，所以建圖是 0 s。匯入期間 wired 記憶體最高 15 GB。
- `eval/questions.format_check.jsonl` 6 題 × 5 種模式（1176 s）。答對的格數：舊 Excel `.xls` 5／5，舊 Word `.doc` 5／5，舊 PPT `.ppt` 只有 local 完全答對、hybrid 答對一半，Excel `.xlsx` 3 題共 15 格只有 1 格答對（local 答出 PetCare 的 9,373）。`.xlsx` 答錯的原因見第 4 節 Office 文件的已知限制。

PPT、Word、圖片（主知識庫，在 3 篇論文之後匯入 `data/documents/`，2026-10-29 量測；紀錄在 `output/formats_main_run/` 與 `.scratch/multi-format-documents/issues/06-*.md`）：

| 文件 | 解析（含 Office 轉 PDF） | 其中 LibreOffice 轉檔 | 建圖 | 圖／表描述 | 合計 |
|---|---|---|---|---|---|
| `Experimentations_for_Kg_creation.docx` | 27 s | 約 1 s | 190 s | 530 s（9 項） | 747 s |
| `LLM_Comparisons_with_one_pdf.docx` | 20 s | 約 2 s | 141 s | 424 s（5 項） | 584 s |
| `RAGHack-EvaluatingAChatApp.pptx` | 65 s | 約 11 s | 144 s | 702 s（21 項） | 910 s |
| `docling_arch.pptx` | 15 s | 約 1 s | 0 s | 52 s（1 項） | 66 s |
| `graphrag-auto-tune-diagram.png` | 13 s | — | 0 s | 49 s（1 項） | 62 s |
| `graphrag-unified-search-app.png` | 15 s | — | 34 s | 38 s（2 項） | 87 s |

- 6 份從開始到結束 2461 s（各份耗時相加 2457 s，差額是初始化與收尾），VLM 呼叫 29 次全部成功。匯入期間 wired 記憶體最高 19 GB，之後的 `eval` 期間最高 20 GB。
- 圖譜從實體 1358、關係 1835 增加到實體 1838、關係 2873（belongs_to 邊從 735 條增加到 1237 條）。
- `eval/questions.formats.jsonl` 10 題 × 5 種模式（2628 s）。各模式完全答對的題數：naive 4、local 3、global 3、hybrid 2、mix 4。mix 模式下，`docling_arch.pptx` 與兩份 `.docx` 都至少答對 1 題；`RAGHack-EvaluatingAChatApp.pptx` 與兩張圖片沒有任何一題完全答對。逐格判讀在 `output/formats_main_run/judgement.md`。
- 沒答對的題目，答案原文都在知識庫裡，但沒有被送進 LLM：`QUERY_MAX_TOTAL_TOKENS=12000` 時，mix 模式在放完圖譜的實體與關係後只剩 5–6 個切塊的空間，被選進來的論文切塊每塊 1,500–6,300 字元，名次在前面時就會用完這個空間。有些切塊的向量名次也太低（RAGHack 投影片「Evaluation approach」那一頁和範例對話在同一個切塊裡，排在 100 名外；auto-tune 流程圖的描述排第 26）。RAGHack 投影片有一張表，「Can run without ground truth?」那一欄的打勾記號在解析時遺失。
- 擴充後的知識庫，用刪掉 `:query:` 快取的副本重跑 `eval/questions.example.jsonl`，10 格都答對，和擴充前相同。

圖譜品質（LightRAG 論文單篇，詳見 `.scratch/rag-anything-lab/issues/04-graph-quality-report.md`）：

- 13 個實體來自 LightRAG 抽取 prompt 的範例（例如 Noah Carter、Nexon Technologies），論文中沒有出現，出自以參考文獻與公式為主的兩個 chunk。
- 名稱只差大小寫、空格或後綴的重複實體 9 組，例如 `LightRAG`／`LIGHTRAG`／`Lightrag`。
- 參考文獻作者被抽成實體，其中 108 個沒有任何關係。
- 33 個實體類型為 UNKNOWN。

## 6. 搬到別台機器

只改 `.env`，程式碼不動。

| 欄位 | 搬機器時 |
|---|---|
| `LLM_BASE_URL`、`VLM_BASE_URL`、`EMBED_BASE_URL` | 改成新機器上的端點（OpenAI 相容，結尾含 `/v1`） |
| `LLM_MODEL`、`VLM_MODEL` | 改成新端點上的模型名稱 |
| `LLM_API_KEY`、`VLM_API_KEY`、`EMBED_API_KEY` | 雲端 API 填真的金鑰；本機 MLX server 填任意非空字串 |
| `LLM_MAX_ASYNC`、`EMBED_MAX_ASYNC` | 記憶體較大的機器或雲端 API 可以調高 |
| `LLM_MAX_TOKENS`、`VLM_MAX_TOKENS` | 依新模型的輸出上限調整 |
| `QUERY_MAX_TOTAL_TOKENS` | 依新 LLM 的 context 長度與記憶體調整 |
| `EMBED_MODEL`、`EMBED_DIM` | **不能改**，除非重建索引 |

- **embedding 模型與維度在建索引後鎖定。** 要換的話，`WORKING_DIR` 也要改到新的資料夾再重新 ingest：LightRAG 預設的向量檔名不含模型名稱或維度，沿用舊資料夾會讓新舊向量混在同一個庫。
- **換成更大的 LLM** 只改 `LLM_BASE_URL` 與 `LLM_MODEL`。已建好的圖譜是舊 LLM 抽取的；要讓圖譜改由新 LLM 抽取，需刪除 `WORKING_DIR` 後重新 ingest。LightRAG 1.4.16 的文件建議 LLM 至少 32B 參數、context length 至少 32KB（建議 64KB；文件原文的單位就是 KB），建圖階段不建議用推理模型；目前的 4B 模型與 `QUERY_MAX_TOTAL_TOKENS=12000` 都低於這個建議。
- **文件 ID 含圖片的絕對路徑**：專案資料夾搬到別的路徑，或 `PARSER_OUTPUT_DIR` 改了，同一篇論文會被當成新文件。搬機器後從空的 `WORKING_DIR` 重新 ingest。

## 7. 測試

快速測試對假的 OpenAI 相容 server、假的 `mineru` 與假的 LibreOffice 執行，不需要模型 server，也不需要安裝 LibreOffice。假 LibreOffice 以 `libreoffice` 與 `soffice` 兩個名稱放在測試 PATH 的最前面，所以機器上裝了真的 LibreOffice 時，測試也不會用到它：

```sh
.venv/bin/python -m unittest
```

下載腳本的測試對本機假 HTTP server 執行，不連網路，不在上面的 `unittest` 範圍內，要另外執行：

```sh
.venv/bin/python -m unittest scripts/test_fetch_papers.py scripts/test_fetch_documents.py
```
