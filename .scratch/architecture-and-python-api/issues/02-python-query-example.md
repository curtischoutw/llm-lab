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
