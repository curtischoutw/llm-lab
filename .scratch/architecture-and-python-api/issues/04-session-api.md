# 04: Session API

**What to build:** 使用者在 Python 程式裡用 `with Session() as s:` 開一個 session，在裡面依序 `ingest`、`query`、`evaluate` 任意多次，知識庫只初始化一次。每次 ingest 的統計只算那一次；記憶體不隨呼叫次數增加。用錯時會得到專案自己的明確錯誤：同時開第二個 session、關閉後還在用、在別的執行緒或已有 running loop 的環境裡用。忘了關閉時，process 結束前仍會收尾並印出警告。既有的 `ingest`／`query`／`evaluate` 模組函式改成「開 session、呼叫一次、關閉」，CLI 行為不變。

介面與實作決策見 spec 的「修訂：Session API」。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 先紅後綠：在 Python API 縫加入 session 步驟，先寫出下面兩個測試，確認在修正前失敗，並貼出失敗輸出：
  - 同一個 session（或同一個 process）依序 ingest 兩份不同的 PDF，兩份報告的 VLM 統計都等於單獨 ingest 的值；
  - vision 失敗的設定下，兩份各自報 1 次描述失敗（防止計數累加，也防止包兩層而重複計數）。
- [ ] C1：同一個 session 依序 ingest → query → evaluate → query，每一步的結果等於各自獨立執行。
- [ ] C2：同一個 session 問 3 題，假 mineru 的 `--version` 只被呼叫 1 次；`gc` 後 RAGAnything 實例數，session 開著時為 1，關閉後為 0。
- [ ] C5：以下情況各拋預期的例外類別，之後再開新 session 問一題要成功：
  - 同時開第二個 session（`SessionError`）；
  - 關閉後呼叫（`SessionClosedError`）；
  - 其他執行緒呼叫（`SessionError`）；
  - 在 `asyncio.run` 內建構（`SessionError`，訊息含替代寫法）。
- [ ] 忘了 close：driver 開 session、問一題、不關閉就結束。結束碼為 0、stderr 有警告；接著用 CLI 問同一題，命中 LLM 快取（假 server 不再收到答案生成的請求）。
- [ ] 初始化失敗：讓 WORKING_DIR 無法建立，`Session()` 拋錯、不留鎖；修好後再開 session 可以問答。
- [ ] C3：既有 CLI 測試、ticket 01 的 4 個模組函式測試、範例測試都不修改，全綠。
- [ ] pipeline 與 models 的模組 docstring 更新：寫入 session 的設計決策、已知極限（session 讀的是開啟當下的索引），並移除「CLI 一次只跑一個命令，所以不需要重置」這類已經不成立的敘述。
- [ ] 新增的函式、方法都有 Args／Returns docstring。
- [ ] 主測試套件與下載腳本的測試全綠，貼出實際輸出。
