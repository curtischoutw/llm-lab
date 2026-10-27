# 05: 範例與文件改為示範 Session

**What to build:** 使用者照著範例、README、架構文件，看到的是 session 的用法：開一個 session、問很多題、離開 `with` 時關閉。文件正確寫出 session 的規則與已知極限，並修掉 tickets 01–03 之後 review 與 read-back 找到的文件錯誤。

**Blocked by:** 04

**Status:** ready-for-agent

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
