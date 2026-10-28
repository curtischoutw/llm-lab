# 03: 專案架構文件

**What to build:** 使用者打開 `docs` 下的架構文件，就能看懂下面這些內容：
- 整體資料流；
- repo 裡每個目錄的用途、是否進版控、由什麼產生、能不能刪；
- 知識庫內每個檔案的用途；
- 每個程式檔的職責與主要公開介面，以及模組依賴圖；
- 知識庫建好之後的三種使用入口：CLI、Python API、範例。

README 最上方有一行連到這份文件。內容範圍與深度見 spec 的 Solution 與 Implementation Decisions。

`docs/architecture-and-example` 分支上已經有草稿（尚未 commit），從那裡接著做，不要重寫。

**Blocked by:** 01, 02

**Status:** resolved

- [ ] 修正第一次 read-back 找到的 6 處（見 spec 的 Further Notes）：
  - 測試表補上測試套件的 `__init__`；
  - 「每張 ticket 都有量測結果」改成只有 03–07 有；
  - 假 server 契約測試的描述改成「只對假 server 執行，與真 server 一致是以 smoke test 曾對真 server 通過為前提」；
  - `ingest`、`evaluate` 的失敗欄補上「初始化失敗拋 `PipelineError`」；
  - config 補上 `EMBED_QUERY_PREFIX` 是選填欄位；
  - 範例程式碼區塊標明是節錄。
- [ ] 把 01 新增的 Python API 測試檔寫進測試表，並說明 Python API 的三個公開函式現在可以在同一個程式裡重複呼叫。
- [ ] 文件裡的數字（匯入耗時、每題秒數）都能對應到 rag-anything-lab 的 ticket 03、05 實測，或 02 的真實 server 驗證。
- [ ] README 最上方的連結指向這份文件。
- [ ] 文字符合使用者的寫作規則：用描述不用比喻、不誇飾、絕對化的斷言要能自圓其說。
- [ ] 01、02 merge 之後，派一個沒參與撰寫的 agent 對照實際 repo 做 read-back，逐條核對路徑、版控狀態、函式簽章、import、CLI 參數、README 章節號碼。結果不能有任何不符；無法確認的項目要列出理由。

## 結案說明（2026-10-28）

- 第一次 read-back 的 6 處已修正。第二次 read-back 仍找到 2 處小錯（`docs/agents/` 漏列 `domain.md`、`requirements.txt` 不是全部鎖版本），並指出「任意順序、任意次數」沒有測試支持；code review 另指出 `query()` 的例外寫錯。改做 session API 後第 4.2 節要整段重寫，所以這些修正與最後一次 read-back 移到 ticket 05。本 ticket「read-back 無不符」這一條未達成，由 05 承接。
