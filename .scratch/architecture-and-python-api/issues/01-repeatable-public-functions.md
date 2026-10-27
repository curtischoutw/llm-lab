# 01: 公開函式可在同一個程式裡重複呼叫

**What to build:** 使用者在同一個 Python 程式裡呼叫 `rag_lab.pipeline` 的 `ingest`、`query`、`evaluate`，可以用任意順序、任意次數，不會因為 LightRAG 的共用鎖綁在上一個 event loop 上而失敗。根因與修法見 spec 的 Problem Statement 與 Implementation Decisions（收尾流程最後呼叫 LightRAG 的 `finalize_share_data()`）。新增 spec 的「縫 3」Python API 測試，作為這個 bug 的回歸保護。

`docs/architecture-and-example` 分支上已經有這個修正的草稿（尚未 commit），從那裡接著做，不要重寫。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 新增 Python API 縫的測試：以子行程執行一段在同一個 process 裡呼叫公開函式的程式，對假 OpenAI server 與假 mineru 執行。至少覆蓋四種順序：
  - `ingest` 後 `query`；
  - `query` 連續兩次；
  - `evaluate` 後 `query`；
  - `ingest` 同一份 PDF 兩次，第二次要回報略過。

  斷言結束碼，以及 stdout 上每一步的結果。
- [ ] 先紅後綠的證據：暫時拿掉修正時，新測試要失敗，而且失敗原因是 event loop 錯誤（貼出錯誤訊息）；恢復修正後通過。
- [ ] 收尾時重置共用鎖這一步，在儲存寫回或限流 worker 關閉失敗時也要執行。
- [ ] pipeline 模組 docstring 的關鍵設計決策要寫上這一條與原因。
- [ ] 主測試套件與下載腳本的測試全綠，貼出實際輸出。
- [ ] CLI 行為不變：既有的 CLI 測試不做任何修改就通過。
