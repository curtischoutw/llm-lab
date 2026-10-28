# rag-anything-lab

用 [RAG-Anything](https://github.com/HKUDS/RAG-Anything) 1.4.3（底層 LightRAG）做的本地 RAG 實驗環境。四個指令：`ingest` 匯入 PDF、`query` 提問、`eval` 用題目檔批次比較五種檢索模式、`graph` 抽樣檢視知識圖譜。

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

匯入單篇 PDF：

```sh
.venv/bin/python -m rag_lab ingest data/papers/2410.05779.pdf
```

匯入整個資料夾（逐篇處理，資料夾內的非 PDF 會略過；已完整匯入的論文會略過）。目前的知識庫是下面這 3 篇。資料夾裡放的是指向 `data/papers/` 的 symlink：RAG-Anything 的文件 ID 是解析內容（文字、表格、公式與圖片路徑）的雜湊，而圖片所在的解析輸出資料夾名稱取自 symlink 解析後的原檔路徑，所以同一篇論文不會因為放在不同資料夾而被當成新文件。

```sh
mkdir -p data/corpus
ln -sf ../papers/2410.05779.pdf ../papers/2404.16130.pdf ../papers/2510.12323.pdf data/corpus/
.venv/bin/python -m rag_lab ingest data/corpus
```

另外 2 篇（2005.11401 RAG、2310.11511 Self-RAG）已下載但沒有匯入；每篇匯入耗時可參考第 5 節。

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
- MinerU 後端比較（LightRAG 論文、server 關閉時）：pipeline 51 s、hybrid-engine 140 s、vlm-engine 711 s（transformers 推論）。pipeline 與 hybrid-engine 抽出的圖、表、公式數量相同。

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

快速測試對假的 OpenAI 相容 server 與假的 `mineru` 執行，不需要模型 server：

```sh
.venv/bin/python -m unittest
```
