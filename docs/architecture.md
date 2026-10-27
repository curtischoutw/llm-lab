# 專案架構

這份文件說明 repo 裡每個目錄放什麼、每支程式負責什麼，以及知識庫建好之後怎麼使用。怎麼安裝、怎麼啟動 server、實測數據，見 [README](../README.md)。

## 1. 整體流程

```
data/papers/*.pdf
      │  python -m rag_lab ingest
      ▼
MinerU 解析（文字、圖、表、公式） ──► output/<論文>_<雜湊>/   解析結果與切出的圖片
      │
      ▼
LightRAG 建圖：LLM 抽實體與關係，embedding 建向量
VLM／LLM 描述圖、表、公式，併入同一張圖
      │
      ▼
rag_storage/   知識圖譜＋向量庫＋快取（＝知識庫本體）
      │  python -m rag_lab query／eval，或從 Python 用 rag_lab.pipeline.Session
      ▼
檢索（naive／local／global／hybrid／mix） → LLM 依檢索結果產生答案
```

三個模型都經由 OpenAI 相容的 HTTP 端點呼叫，端點寫在 `.env`：

| 用途 | 本機的 server | 什麼時候會呼叫 |
|---|---|---|
| LLM | `mlx_lm.server`（port 8080） | 建圖時抽實體、描述表格與公式；查詢時抽關鍵字、產生答案 |
| VLM | `scripts/vlm_server.py`（port 8081） | 建圖時描述圖片；`query --vlm-enhanced` 時看檢索到的圖片 |
| embedding | 同上（port 8081） | 建圖時把 chunk、實體、關係轉成向量；查詢時把問題轉成向量 |

## 2. 目錄

「進版控」為否的路徑不會被 git 追蹤，只存在你的機器上。

| 路徑 | 放什麼 | 進版控 | 怎麼產生 | 能不能刪 |
|---|---|---|---|---|
| `rag_lab/` | 主程式（Python 套件），見第 3 節 | 是 | — | 不能 |
| `examples/` | 從 Python 呼叫 `rag_lab` 的範例 | 是 | — | 不能 |
| `scripts/` | 維運工具：下載論文、啟動 VLM server、檢查端點 | 是 | — | 不能 |
| `tests/` | 自動測試與測試用的假 server、假 MinerU | 是 | — | 不能 |
| `eval/` | `eval` 指令的題目檔（JSONL）；目前只有範例 `questions.example.jsonl` | 是 | 手寫 | 範例檔被測試引用，不能刪 |
| `docs/` | 這份架構文件；`docs/agents/` 是給 Claude Code 技能讀的設定（issue tracker 位置、triage 標籤、domain 文件的讀法） | 是 | 手寫 | 不能 |
| `.scratch/rag-anything-lab/` | 主程式的規格 `spec.md` 與 7 張 ticket（`issues/`）。ticket 03–07 末尾有實測結果段落，README 的數據出自這裡 | 是 | 手寫 | 不建議：設計決策與實測結果記錄在這裡 |
| `.scratch/architecture-and-python-api/` | 這份架構文件、Python 範例、公開函式重複呼叫修正的規格與 3 張 ticket | 是 | 手寫 | 不建議，理由同上 |
| `.env.example` | 所有設定欄位與註解，預設值對應本機 MLX server | 是 | — | 不能 |
| `requirements.txt` | 專案 venv 的相依套件：`raganything==1.4.3` 鎖定版本，`lightrag-hku<1.5` 與 `mineru[core]<4` 只限制上限，其餘由 raganything 帶入 | 是 | — | 不能 |
| `CLAUDE.md` | 給 Claude Code 的專案說明 | 是 | — | 不能 |
| `.env` | 實際使用的設定（含 API 金鑰欄位） | 否 | 從 `.env.example` 複製後修改 | 刪了所有指令都會因缺設定而失敗 |
| `.venv/` | 專案的 Python 3.12 虛擬環境 | 否 | `python -m venv` ＋ `pip install -r requirements.txt` | 可以，照 README 第 1 節重建 |
| `data/papers/` | 下載的 5 篇 arXiv PDF | 否 | `scripts/fetch_papers.py` | 可以，重新下載即可 |
| `data/corpus/` | 指向 `data/papers/` 其中 3 篇的 symlink，是目前知識庫匯入的資料夾 | 否 | README 第 4 節的 `ln -sf` | 可以，不影響已建好的知識庫 |
| `rag_storage/` | **知識庫本體**：知識圖譜、向量庫、文件狀態、LLM 快取（路徑由 `.env` 的 `WORKING_DIR` 決定） | 否 | `ingest` | 刪了就要重新 `ingest`（3 篇約 1.7 小時） |
| `output/<論文>_<雜湊>/` | MinerU 的解析結果：Markdown、content list、切出來的圖片（路徑由 `PARSER_OUTPUT_DIR` 決定） | 否 | `ingest` | 不建議：知識庫記錄的是這裡圖片的絕對路徑，`--vlm-enhanced` 查詢要讀這些圖片 |
| `output/` 其他子目錄 | 開發過程的量測紀錄與 log（`ticket03_run/`、`ticket05_run/`、`crash_repro/`、`backend_bench/` 等），ticket 的實測段落引用它們當證據；`crash_repro/tools/watchdog.sh` 是記憶體監控腳本 | 否 | 開發時手動產生 | 可以，但會失去原始證據 |
| `eval_results/` | `eval` 產生的 Markdown 對照表，檔名 `eval_<時間戳記>.md` | 否 | `eval` | 可以 |
| `.claude/` | Claude Code 的本機設定與 subagent 用的 worktree | 否 | Claude Code | 不影響專案的程式 |

`rag_storage/` 裡的檔案（LightRAG 與 RAG-Anything 的格式，不要手動編輯）：

| 檔案 | 內容 |
|---|---|
| `graph_chunk_entity_relation.graphml` | 知識圖譜：實體（節點）與關係（邊）。`graph` 指令讀這個檔 |
| `vdb_chunks.json`、`vdb_entities.json`、`vdb_relationships.json` | 向量庫：chunk、實體、關係各自的 embedding |
| `kv_store_full_docs.json`、`kv_store_text_chunks.json` | 原文與切好的 chunk |
| `kv_store_full_entities.json`、`kv_store_full_relations.json`、`kv_store_entity_chunks.json`、`kv_store_relation_chunks.json` | 每份文件抽出的實體與關係，以及它們出自哪些 chunk |
| `kv_store_doc_status.json` | 每份文件的處理狀態；`ingest` 依它判斷哪篇已完成、可以略過 |
| `kv_store_llm_response_cache.json` | LLM 回應快取；同一個問題再問一次會直接命中，不呼叫 LLM |
| `kv_store_parse_cache.json` | RAG-Anything 的解析快取，重複匯入同一個檔案時不重跑 MinerU |

## 3. 程式碼

每個檔案開頭的 docstring 有完整的設計決策與已知極限，這裡只列職責與主要介面。

### 3.1 `rag_lab/`：主程式

模組之間的依賴（箭頭指向被 import 的一方）：

```
__main__ ──► config
   │  ├────► evaluation
   │  ├────► pipeline ──► models ──► config
   │  │         ├───────► config
   │  │         └───────► evaluation
   │  └────► graph_report
```

`__main__` 只在執行對應子命令時才 import `pipeline`、`graph_report`，所以設定錯誤、題目檔格式錯誤能在載入 LightRAG／torch 之前就回報。

| 檔案 | 職責 | 主要介面 |
|---|---|---|
| `__init__.py` | 套件根，刻意不 import 任何子模組 | — |
| `__main__.py` | CLI 入口：解析參數、驗證輸入、呼叫 `pipeline`／`graph_report`、格式化輸出、決定結束碼（0 成功、1 執行失敗、2 用法或輸入錯誤、3 設定錯誤） | `main(argv)`；子命令 `ingest`、`query`、`graph`、`eval` |
| `config.py` | 從 `.env` 與環境變數讀設定並驗證；必填欄位缺漏或格式錯就拋錯，不給預設值（只有 `EMBED_QUERY_PREFIX` 是選填，預設空字串） | `get_settings() -> Settings`、`ConfigError` |
| `models.py` | 把三個 OpenAI 相容端點包成 RAG-Anything 需要的模型函式；失敗包成帶端點名稱與位址的錯誤；計數圖、表、公式描述的失敗（RAG-Anything 自己會吞掉） | `llm_model_func`、`vision_model_func`、`build_embedding_func()`、`check_reachable(...)`、`EndpointError` |
| `pipeline.py` | 核心流程：建立 RAGAnything 實例、匯入（解析、建圖、多模態描述）、查詢、批次比較；把 LightRAG 會吞掉的錯誤轉成可偵測的失敗；`Session` 讓同一個 process 只初始化一次、依序呼叫 | `Session`（`ingest`、`query`、`evaluate`、`close`）、模組函式 `ingest(pdfs) -> IngestSummary`、`query(question, mode, vlm_enhanced=False) -> str`、`evaluate(questions) -> list[list[Cell]]`、`PipelineError`、`SessionError`、`SessionClosedError` |
| `evaluation.py` | `eval` 的題目檔讀取驗證與 Markdown 對照表排版，不需要任何模型 | `load_questions(path)`、`render_report(...)`、`RETRIEVAL_MODES`、`QuestionFileError` |
| `graph_report.py` | 直接讀 `rag_storage/` 的 graphml，抽樣列出實體與關係，不需要模型 server | `load_graph(working_dir)`、`format_report(graph, sample_size, seed)` |

### 3.2 `scripts/`：維運工具

都是獨立腳本，不屬於 `rag_lab` 套件。

| 檔案 | 用途 | 用哪個 Python 執行 |
|---|---|---|
| `fetch_papers.py` | 下載 5 篇 RAG 論文到 `data/papers/`，先比對 arXiv 標題，已存在的完整檔案會略過 | 專案 venv 或系統 python3（只用標準函式庫） |
| `vlm_server.py` | 啟動 VLM＋embedding 的 `mlx_vlm.server`，先把 MLX 的 GPU cache 上限設為 1 GB，避免 ingest 時記憶體不足 | pipx 安裝的 mlx-vlm 的 python |
| `smoke_test.py` | 確認三個端點都能用：chat、看 base64 圖片、embedding 維度 | 專案 venv |
| `test_fetch_papers.py` | `fetch_papers.py` 的離線測試（對本機假 arXiv server） | `python -m unittest scripts.test_fetch_papers` |

### 3.3 `tests/`：自動測試

測試只從子行程進入（`python -m rag_lab ...`、`python -m examples...`），只看結束碼、輸出和產生的檔案，不 import `rag_lab` 內部。模型與 MinerU 都用假的，不需要開 server，`python -m unittest` 一次跑完。

| 檔案 | 內容 |
|---|---|
| `__init__.py` | 測試套件的說明：測試只從子行程進入、模型用假 server |
| `fake_openai_server.py` | 假的 OpenAI 相容 server：chat、vision、embedding 都回固定且合法的內容，並記錄收到的請求 |
| `fake_mineru.py` | 假的 `mineru` 指令：依檔名寫出固定的解析結果（文字、一張圖、一個表、一條公式）；設了 `FAKE_MINERU_VERSION_LOG` 時記錄每次 `--version`，用來計算初始化次數 |
| `test_cli.py` | 設定驗證、子命令註冊、結束碼；提供其他測試共用的 `run_cli`、`valid_env` |
| `test_fake_server.py` | 以 `scripts/smoke_test.py` 當客戶端對假 server 執行，確認假 server 符合同一份介面（smoke test 曾對真 server 通過，所以把它當作介面的定義）；不連真 server |
| `test_pipeline.py` | `ingest`、`query` 的完整流程（含重複匯入、失敗重試、端點不可達、查詢 token 上限）；提供共用的 `PipelineCase` |
| `test_graph.py` | `graph` 指令的抽樣與可重現性 |
| `test_eval.py` | `eval` 指令的題目檔驗證與結果表 |
| `test_python_api.py` | 在同一個 process 裡依序呼叫 `rag_lab.pipeline` 的模組函式與 `Session`：連續呼叫、每次 ingest 的統計獨立、同一個 `Session` 只初始化一次並在關閉後釋放實例、誤用時的 `SessionError`、開 `Session` 失敗後不留狀態、忘了 `close()` 時的收尾 |
| `test_examples.py` | 實際執行 `examples/` 的範例，確認在一個 `Session` 裡連續提問能跑完 |

### 3.4 `examples/`：範例

| 檔案 | 內容 |
|---|---|
| `query_from_python.py` | 開一個 `Session`，對已建好的知識庫逐題提問並印出問答，見第 4.2 節 |

## 4. 知識庫建好之後怎麼使用

以下都要在 repo 根目錄執行，並先開好兩個模型 server（README 第 3 節）。只有 `graph` 不需要 server。

### 4.1 命令列

```sh
.venv/bin/python -m rag_lab query "What are the two retrieval levels in LightRAG?"   # 問一題，預設 mix 模式
.venv/bin/python -m rag_lab query --mode naive "..."                                # 指定檢索模式
.venv/bin/python -m rag_lab eval eval/questions.example.jsonl                       # 題目檔 × 五種模式，寫出對照表
.venv/bin/python -m rag_lab graph                                                   # 抽樣看知識圖譜
.venv/bin/python -m rag_lab ingest data/papers/2005.11401.pdf                       # 再加一篇論文進知識庫
```

五種檢索模式的差別：

| 模式 | 檢索什麼 |
|---|---|
| `naive` | 只用向量搜尋找相似的 chunk，不用知識圖譜 |
| `local` | 用 LLM 從問題抽出的低層關鍵字（具體名詞）找相關實體，再帶出這些實體的關係與出處 chunk |
| `global` | 用高層關鍵字（主題、概念）找相關關係，再帶出關係兩端的實體與出處 chunk |
| `hybrid` | `local` ＋ `global` |
| `mix` | `hybrid` 再加上 `naive` 的向量 chunk；預設模式 |

### 4.2 在自己的 Python 程式裡呼叫

`rag_lab.pipeline` 提供同步的 `Session` 與三個模組函式，CLI 也是呼叫這三個函式。設定一律讀 `.env`，不用另外傳。

**Session**：在同一個 `Session` 裡依序呼叫，知識庫只在開 `Session` 時載入一次。

```python
from pathlib import Path

from rag_lab.pipeline import Session

with Session() as session:
    summary = session.ingest([Path("data/papers/2310.11511.pdf")])  # Self-RAG 論文
    answer = session.query("What is Self-RAG?", mode="mix")
```

| 方法 | 回傳 | 失敗時 |
|---|---|---|
| `query(question, mode, vlm_enhanced=False)` | 答案字串 | 開始前端點不可達拋 `EndpointError`；查詢失敗（含查詢途中 LLM 失敗）或沒有答案拋 `PipelineError`；`vlm_enhanced=True` 時 VLM 呼叫失敗拋 `EndpointError` |
| `ingest(pdfs: list[Path])` | `IngestSummary`：每篇的耗時與錯誤、圖譜統計、這一次的 VLM 與描述統計 | 單篇失敗記在該篇的 `error`、圖表公式描述失敗記在 `description_error`，都不拋例外；開始前端點不可達拋 `EndpointError` |
| `evaluate(questions: list[Question])` | `cells[i][j]`：第 i 題在第 j 種模式的答案或錯誤 | 單格失敗記在該格的 `error`，不拋例外；開始前 LLM 或 embedding 端點不可達拋 `EndpointError` |
| `close()` | — | 離開 `with` 時自動呼叫；重複呼叫不做事 |

開 `Session()` 時就會檢查 LLM 與 embedding 端點並初始化知識庫：設定有誤拋 `rag_lab.config.ConfigError`，端點不可達拋 `EndpointError`，初始化失敗拋 `PipelineError`。

`Session` 的規則，違反時拋 `SessionError`（關閉後呼叫拋它的子類 `SessionClosedError`）：
- 同一個 process 同一時間只能開一個 `Session`。LightRAG 的共用狀態是 process 層級的，要先 `close()` 前一個。
- 只能在建立它的執行緒使用。
- 不能在已經有執行中 event loop 的地方使用（Jupyter、async 函式）。替代寫法：把開 `Session` 與所有呼叫寫成一個同步函式，再用 `await asyncio.to_thread(該函式)` 執行。
- 忘了 `close()` 時，process 結束前會自動收尾（寫回快取與索引），並在 stderr 印出警告。

`SessionError` 不繼承 `PipelineError`：它代表程式寫錯，要改程式，不是匯入或查詢失敗。

**模組函式**：`query(...)`、`ingest(...)`、`evaluate(...)` 的參數、回傳與失敗行為跟 `Session` 的同名方法相同，差別是每次呼叫都會開一個 `Session`、呼叫一次、再關閉，等於每次都重新載入知識庫。適合只做一件事的情況（CLI 就是這樣用）。已經開著 `Session` 時呼叫模組函式，會因為「同時只能開一個」而拋 `SessionError`。

完整範例是 [`examples/query_from_python.py`](../examples/query_from_python.py)，下面是節錄（省略 `main()` 與每題之間的空行）：

```python
from rag_lab.pipeline import Session

QUESTIONS = [
    "What are the two retrieval levels in LightRAG?",
    "What is the main idea of RAG-Anything?",
]

with Session() as session:
    for question in QUESTIONS:
        answer = session.query(question, mode="mix")
        print(f"Q: {question}")
        print(f"A: {answer}")
```

執行（在 repo 根目錄）：

```sh
.venv/bin/python -m examples.query_from_python
```

一定要用 `python -m`，從 repo 根目錄執行：
- `import rag_lab` 要靠 repo 根目錄在 `sys.path` 上。直接執行 `python examples/query_from_python.py` 只會把 `examples/` 加進 `sys.path`，會出現 `ModuleNotFoundError`。
- `.env` 裡的 `WORKING_DIR=./rag_storage` 是相對於目前目錄的路徑。

自己寫的程式也一樣：放在 `examples/` 底下，或放在 repo 根目錄的其他資料夾，然後用 `python -m <資料夾>.<檔名>` 執行。

已知極限：
- `Session` 讀的是開啟當下的索引。開著的期間如果另一個 process（例如另一個終端機的 `python -m rag_lab ingest`）匯入新論文，這個 `Session` 看不到，要關掉重開。
- 呼叫途中按 Ctrl-C 中斷後，不保證 `Session` 的狀態一致；中斷後應關閉 `Session` 再開新的。
- 本機 4B LLM 每題 52–66 秒；同一個問題再問一次會命中 LLM 快取，4 秒（README 第 5 節）。

## 5. 設定

所有欄位與註解在 `.env.example`；搬機器、換模型時要改哪些欄位，見 README 第 6 節。改程式之外的東西（端點、模型、路徑、並行數、查詢 token 上限）都只改 `.env`。
