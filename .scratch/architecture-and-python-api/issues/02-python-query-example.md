# 02: Python 問答範例

**What to build:** 使用者在 repo 根目錄用 `python -m examples.query_from_python` 執行一支範例。範例對已建好的知識庫以 mix 模式逐題提問 2 題，每題印出 `Q: <問題>`、`A: <答案>`。範例的位置、執行方式、內容範圍見 spec 的 Implementation Decisions：
- 範例放在 repo 最上層的 `examples` 目錄，不放 `__init__.py`。
- 只示範問答，不攔例外。
- 設定全部來自 `.env`。

README 的「使用」一節結尾，加上「在 Python 裡呼叫」的 3 行程式碼與一句指引。

`docs/architecture-and-example` 分支上已經有範例、範例縫測試、README 段落的草稿（尚未 commit），從那裡接著做，不要重寫。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 範例縫的測試：先 ingest 一份假 PDF，再以子行程在 repo 根目錄執行範例。斷言：
  - 結束碼為 0；
  - 恰有 2 行 `Q: `、2 行 `A: `；
  - 答案等於假 server 的固定回應。
- [ ] 範例檔頭的 docstring 說明執行方式、為什麼要用 `python -m`，以及已知極限：每次呼叫都重新載入知識庫，不適合當常駐服務。
- [ ] README 的「在 Python 裡呼叫」段落裡的指令與程式碼，都實際執行過。
- [ ] 真實 server 驗證：照 README 第 3 節啟動兩個 MLX server，同時以 zsh 執行記憶體 watchdog（門檻 22 GB）。在 repo 根目錄執行範例一次，記錄結束碼、兩題的輸出、總耗時，以及 watchdog 的 wired 記憶體峰值，寫在本 ticket 的回報段落。驗證完關掉 server 與 watchdog。這一步不與其他使用 GPU 的工作平行執行。
- [ ] 主測試套件全綠，貼出實際輸出。

## 實測結果（2026-10-27）

- 範例縫測試（`tests.test_examples`）：通過。修正 01 之前，第 2 題因 `Lock ... is bound to a different event loop` 失敗；修正之後通過。
- 真實 server：照 README 第 3 節啟動兩個 MLX server，同時以 zsh 執行 watchdog（門檻 22 GB，間隔 5 秒）。smoke test 三項 PASS。在 repo 根目錄執行 `.venv/bin/python -m examples.query_from_python`：
  - 結束碼 0；2 題都印出 `Q:`／`A:`。
  - 總耗時 56 秒，含兩次初始化。
  - 第 1 題命中 LightRAG 的 LLM 快取（stderr：`Query cache hit`），因為 rag-anything-lab 的 ticket 期間問過同一題；只有第 2 題走完關鍵字抽取與答案生成。LLM server 共收到 3 個 chat 請求：smoke test 1 個，第 2 題 2 個。
  - wired 記憶體峰值 13 GB。
  - 第 1 題答案：LightRAG 採 dual-level retrieval，分成 low-level（具體實體與關係）與 high-level（主題與概念）；引用 2410.05779、2510.12323。
  - 第 2 題答案：RAG-Anything 是統一處理文字、圖片、表格、公式的多模態 RAG 框架，以雙圖（文字語意圖、跨模態關係圖）建構；引用 2510.12323。
  - 輸出與 log 存在 `output/example_run/`（不進版控）。驗證完已關閉 server 與 watchdog。
- README「在 Python 裡呼叫」的 3 行程式碼：`query("What are the two retrieval levels in LightRAG?", mode="mix")` 與範例第 1 題是同一個呼叫，已隨上面的範例執行過；這 3 行本身沒有單獨執行。
