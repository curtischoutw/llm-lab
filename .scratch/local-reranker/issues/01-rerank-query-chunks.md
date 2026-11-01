# 01: 查詢時用 reranker 重新排序候選 chunk

**What to build:** 使用者在 `.env` 設定 reranker 的位址、模型與 API key 之後，所有查詢（CLI 的 `query`、`eval`、`query --vlm-enhanced`，Python API 的 `pipeline.query`／`pipeline.evaluate`／`Session.query`／`Session.evaluate`）都先把 LightRAG 的候選 chunk 送到 rerank endpoint 重新排序，再依 token 上限截斷成 context。匯入流程不受影響。規格見 `.scratch/local-reranker/spec.md`。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 新增 `RERANK_BASE_URL`、`RERANK_MODEL`、`RERANK_API_KEY` 三個必填欄位，驗證規則與現有的 `*_BASE_URL`／`*_MODEL`／`*_API_KEY` 相同；缺漏或格式錯誤時 CLI 在啟動時中止，結束碼與既有設定錯誤相同。
- [ ] rerank 函式在建立 LightRAG 實例時傳入（初始化之後才設定，mix 等圖譜模式不會用到），所有查詢都開 enable_rerank；程式說明文字裡寫著「不開 rerank」的地方一併更新。
- [ ] 請求帶設定的模型名稱與 API key，documents 是候選 chunk 的內容；回傳的順序反映在答案請求的 prompt 裡（見 spec 的「要驗的行為」第 2 項）。
- [ ] 上一項以 CLI 子行程縫（`query` 的 mix、`query --vlm-enhanced`、`eval`）與 Python API 縫（四個函式）測試；假 OpenAI server 新增 `/v1/rerank`，記錄請求並依測試指定的規則回傳順序。
- [ ] 匯入不呼叫 rerank endpoint（測試驗證）。
- [ ] eval 對照表的「固定查詢設定」加上 `RERANK_MODEL` 的值（測試驗證）。
- [ ] `.env.example` 加上三個欄位與建議值（`RERANK_BASE_URL` 指向 VLM／embedding server，`RERANK_MODEL=BAAI/bge-reranker-v2-m3`）；CLI 測試裡的設定欄位字面清單加上三個欄位，既有的 `.env.example` 一致性測試通過。
- [ ] README：設定說明加上三個欄位；8081 server 的啟動指令加上 `--reranker-model BAAI/bge-reranker-v2-m3`。架構文件：查詢流程補上 rerank 這一步。
- [ ] 每個新測試都先在改程式前看過紅燈；主測試套件 `python -m unittest`（repo 根目錄、專案 venv）全綠。
- [ ] 不對 127.0.0.1:8080／8081 發請求，不讀 `.env`；實機驗證是 ticket 03。
