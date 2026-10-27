# 07: README 與搬機器說明

**What to build:** 一份 README，讓一個月後的使用者能照著重建環境、啟動本地模型 server、跑三個指令，並知道搬到別台機器時要改 `.env` 的哪些項目。

**Blocked by:** 06

**Status:** resolved

- [x] 說明如何啟動 LLM server（含 `--max-tokens 4096` 與原因）與 VLM 加 embedding 的 server。
- [x] 說明如何建立 Python 3.12.12 venv 並安裝鎖定的相依套件。
- [x] 說明 `ingest`、`query`、`eval` 的用法，各附一個可執行的範例指令。
- [x] 說明搬機器：哪些 `.env` 欄位要改（三組端點、模型名稱、並行數、輸出長度）、哪個欄位不能改（embedding 模型與維度；更換需要重建索引）。
- [x] 說明換成更大的 LLM 時，只改 LLM 的 base URL 與模型名稱。
- [x] 記錄第 03、04 張實測得到的耗時與圖譜品質觀察，標明是哪個模型組合下量到的。
- [x] README 中的每個指令都在寫完後實際執行過一次；沒執行過的不寫入。

## 實測結果（2026-10-27）

README 中的每個指令都在 2026-10-27 執行過，結果全部 rc=0，紀錄在 `output/ticket07_run/`（gitignore）：
- 不需要 server：`pyenv install --skip-existing 3.12.12`、`fetch_papers.py`（含 `--ids`）、`pipx install mlx-lm==0.32.0`／`mlx-vlm==0.7.10`（已安裝，不修改）、`cp .env.example .env`（在臨時資料夾）、`graph`。
- 環境重建：在臨時資料夾以 pyenv 的 3.12.12 建 venv 並 `pip install -r requirements.txt`，rc=0，79 s（pip 快取命中），版本 raganything 1.4.3、lightrag-hku 1.4.16、mineru 3.4.5；驗證後刪除。
- 需要 server：以 README 的指令啟動兩個 server，再依序執行 `smoke_test.py`、`ingest` 單篇、`mkdir`／`ln -sf`／`ingest data/corpus`、兩個 `query`、`eval`。
- `unittest`：Ran 69 tests OK。

由 fresh-context agent 核對 README 與紀錄後，修正了 4 處：漏列 `graph` 子命令、重複實體漏寫「後綴」、耗時未說明量測條件，以及 LLM 建議規格寫錯（LightRAG 1.4.16 文件建議至少 32B 參數、context 至少 32K，不是「本地下限 Qwen3-30B-A3B」）。
