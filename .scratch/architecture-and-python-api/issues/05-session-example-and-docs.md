# 05: 範例與文件改為示範 Session

**What to build:** 使用者照著範例、README、架構文件，看到的是 session 的用法：開一個 session、問很多題、離開 `with` 時關閉。文件正確寫出 session 的規則與已知極限，並修掉 tickets 01–03 之後 review 與 read-back 找到的文件錯誤。

**Blocked by:** 04

**Status:** resolved

- [ ] 範例改成在一個 session 裡逐題提問：主體不超過 15 行，不出現 asyncio；檔頭 docstring 的「已知極限」改寫，不再說每題重新載入。範例測試照舊通過（輸出格式不變）。
- [ ] README「在 Python 裡呼叫」改成 session 的寫法，並保留一句「只問一題可以直接呼叫 `query()`」。
- [ ] 架構文件第 4.2 節改寫：
  - session 的介面；
  - 規則：同一時間只能開一個 session，只能在建立它的執行緒使用，不能在 Jupyter 或 async 程式裡直接用（附替代寫法），忘了關閉會在結束時收尾並警告；
  - 三個模組函式等於「開 session、呼叫一次、關閉」；
  - 已知極限：session 讀的是開啟當下的索引。
  - 移除「任意順序、任意次數」的說法。
- [ ] 修正 code review 與第二次 read-back 找到的文件錯誤：
  - `query()` 在查詢途中 LLM 失敗時拋 `PipelineError`，不是 `EndpointError`；
  - `docs/agents/` 漏列 `domain.md`；
  - `requirements.txt` 只有 raganything 精確鎖版本，lightrag 與 mineru 只限上限；
  - 測試表寫入 ticket 04 新增的 session 測試。
- [ ] 真實 server 驗證：照 README 第 3 節啟動兩個 MLX server，同時以 zsh 執行 watchdog（門檻 22 GB）。執行範例一次，記錄結束碼、輸出、總耗時、wired 記憶體峰值，以及兩題是否各自命中快取。驗證完關掉 server 與 watchdog。
- [ ] 派一個沒參與撰寫的 agent 對照 repo 做 read-back，結果不能有任何不符；無法確認的項目要列出理由。
- [ ] 文字符合使用者的寫作規則。

## 實作結果（2026-10-28）

- 範例改成在一個 `Session` 裡逐題提問（主體 6 行，沒有 asyncio）；範例測試照舊通過。
- README「在 Python 裡呼叫」改成 `Session` 的寫法，並說明只問一題可以直接呼叫 `query()`。
- 架構文件第 4.2 節依 `Session` 重寫，內容包括：
  - 方法表、開 `Session` 時的檢查、四條規則與各自的例外類別；
  - `SessionError` 不繼承 `PipelineError`；
  - 模組函式等於「開 `Session`、呼叫一次、關閉」；
  - 已知極限。

  另外修正 review 與 read-back 找到的錯誤：`query` 的例外、`docs/agents/` 漏列 `domain.md`、`requirements.txt` 的版本限制、`.scratch` 目錄列、測試的進入方式（`python -c` driver），以及 `WORKING_DIR` 改寫成以 `.env.example` 的預設值描述。
- 真實 server 驗證：照 README 第 3 節啟動兩個 MLX server，同時以 zsh 執行 watchdog（門檻 22 GB）。smoke test 三項 PASS。執行 `.venv/bin/python -m examples.query_from_python`：
  - 結束碼 0，2 題都印出 `Q:`／`A:`，總耗時 4 秒；
  - 2 題都命中 LLM 快取（stderr 有 2 次 `Query cache hit`），LLM server 只收到 smoke test 的 1 個 chat 請求；
  - 整個執行只初始化 1 次（`Parser 'mineru' installation verified` 出現 1 次）；
  - wired 記憶體峰值 8 GB；
  - 輸出與 log 存在 `output/example_run_session/`。驗證完已關閉 server 與 watchdog。這次沒有測到未命中快取的生成耗時，ticket 02 量過第 2 題完整生成約 56 秒（含 2 次初始化）。
- 第二次 code review（對 tickets 04、05）找到 10 項，處理如下：
  - Session 的 4 項正確性問題都已修正：
    - 關 event loop 時被中斷也會釋放 process 層級的鎖；
    - 不合法的 mode（例如 LightRAG 的 `bypass`）拋 `ValueError`，不送出任何 LLM 請求；
    - 先自己建立 WORKING_DIR，讓建立失敗發生在建構 RAGAnything 之前，避免留下已註冊 atexit 的半成品；
    - 建構失敗時收尾的錯誤附在原例外的 note，不蓋掉原例外。
  - 端點檢查不再重複：模組函式只在開 `Session` 前補檢查 VLM。
  - 建立 `Session` 的執行緒結束後，其他執行緒可以 `close()`。
  - 補齊 docstring。
  - 修正文件 2 處。
  - 新增 2 個測試（不合法 mode、執行緒結束後關閉），修正前都是紅燈：`bad_mode ok`、`orphan close SessionError`。
- 最後一次 read-back（修正前的 HEAD dd7bd8e）：2 處不符、1 處無法確認。本 ticket 範圍內的兩處（`.scratch` 目錄列、`WORKING_DIR` 的描述）已經修正。修正後沒有再派 agent read-back 一次。
- 範圍外、未修改（記錄給使用者決定）：
  - README 第 4 節說「RAG-Anything 以 symlink 解析後的原檔路徑計算文件 ID」：實際上文件 ID 是解析內容的雜湊，路徑只進入輸出資料夾名稱與圖片路徑；結論（同一篇不會被當成新文件）仍成立。
  - README 第 6 節「context 至少 32K token（建議 64K）」：LightRAG 1.4.16 的 METADATA 寫的是「32KB／64KB」，沒有寫 token。
- 完整測試：主套件 93 個 OK，下載腳本 6 個 OK。
