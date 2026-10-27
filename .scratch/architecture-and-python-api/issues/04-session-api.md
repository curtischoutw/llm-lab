# 04: Session API

**What to build:** 使用者在 Python 程式裡用 `with Session() as s:` 開一個 session，在裡面依序 `ingest`、`query`、`evaluate` 任意多次，知識庫只初始化一次。每次 ingest 的統計只算那一次；記憶體不隨呼叫次數增加。用錯時會得到專案自己的明確錯誤：同時開第二個 session、關閉後還在用、在別的執行緒或已有 running loop 的環境裡用。忘了關閉時，process 結束前仍會收尾並印出警告。既有的 `ingest`／`query`／`evaluate` 模組函式改成「開 session、呼叫一次、關閉」，CLI 行為不變。

介面與實作決策見 spec 的「修訂：Session API」。

**Blocked by:** 01

**Status:** resolved

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

## 實作結果（2026-10-28）

- 先紅後綠（Python API 縫，`tests.test_python_api`）：
  - 模組函式連續 ingest `a.pdf`、`b.pdf`：修正前第二份報告是 `stats b.pdf vlm_ok=2 ...`（預期 1），每次 ingest 開始時呼叫 `models.reset_stats()` 原地清零後通過。
  - 同一個 Session 在 vision 失敗下連續 ingest 兩份：第一版 Session 仍在每次 ingest 包計數，第二份報告是 `description_failed=2`（預期 1）；改成在 Session 初始化後只包一次後通過。
- 新增的測試都做了反向檢查，確認測試分辨得出好壞：
  - 用模組函式問 3 題，初始化次數是 3（同一個 Session 是 1）。
  - 暫時拿掉 `atexit.unregister(rag.close)` 時，關閉後的實例數是 1，測試轉紅。
  - 暫時拿掉 Session 自己的 atexit 收尾時，「忘了 close」的測試轉紅（stderr 沒有警告）。
- C1：同一個 Session 依序執行 ingest → query → evaluate → query，結果與分開執行相同。
- C2：同一個 Session 問 3 題，假 mineru 的 `--version` 只被呼叫 1 次；RAGAnything 實例數在 Session 開著時為 1，關閉後為 0。
- C5：同時開第二個 Session 拋 `SessionError`，關閉後再呼叫拋 `SessionClosedError`，從其他執行緒呼叫拋 `SessionError`，在 `asyncio.run` 內建構拋 `SessionError`（訊息含 `asyncio.to_thread` 的替代寫法）；之後用模組函式查詢照常成功。
- 開 Session 失敗（WORKING_DIR 是檔案）：拋錯、不留鎖；刪掉檔案後，同一個 process 可以照常 ingest 和 query。
- 忘了 close：結束碼 0，stderr 有「Session 沒有呼叫 close()」警告；之後用 CLI 問同一題時，假 server 沒有再收到 chat 請求，代表 LLM 快取已寫回。
- C3：`__main__.py`、`test_cli`、`test_pipeline`、`test_eval`、`test_examples` 都沒有修改；ticket 01 的 4 個模組函式測試的斷言也沒有修改。
- 完整測試：主套件 91 個 OK（296.6 s），下載腳本 6 個 OK。
- 測試夾具的變更：假 mineru 在環境變數 `FAKE_MINERU_VERSION_LOG` 有設定時，每次 `--version` 會在該檔附加一行，用來計算初始化次數。
