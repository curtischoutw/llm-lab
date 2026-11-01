# 02: rerank 失敗時讓查詢失敗

**What to build:** rerank 沒有正常完成時，使用者會看到查詢失敗與原因，不會拿到一個沒有經過 rerank 的答案。LightRAG 在 rerank 發生例外、回傳空結果、回傳 index 超出範圍時，都會改用原本的排序並讓查詢成功；rag_lab 要把這些情況改成查詢失敗。規格見 `.scratch/local-reranker/spec.md` 的「失敗處理」。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 以下情況都記成 rerank 失敗：請求例外、HTTP 錯誤（含候選 chunk 為空白時 mlx-vlm 回的 400）、回傳空結果、回傳的 index 超出範圍。
- [ ] 有失敗的那次查詢以查詢失敗結束：`query` 用既有的查詢失敗結束碼，Python API 拋出既有的查詢失敗例外，`eval` 把該格記成失敗格。訊息包含 endpoint 回報的錯誤，不含 API key。
- [ ] 失敗只算在發生當下的那一次查詢：`eval` 某一格失敗後，下一格 rerank 正常時照常成功（測試驗證）。
- [ ] 以 CLI 子行程縫與 Python API 縫測試；假 server 的 `/v1/rerank` 能被指定回 500、回空結果、回超出範圍的 index。
- [ ] 做法比照 ticket 12（台新知識庫）處理 RAG-Anything 吞掉寫入失敗的方式：在 rag_lab 這一層記錄、在結果層判定。
- [ ] 架構文件的查詢流程補上 rerank 的失敗處理。
- [ ] 每個新測試都先在改程式前看過紅燈；主測試套件 `python -m unittest` 全綠。
- [ ] 不對 127.0.0.1:8080／8081 發請求，不讀 `.env`。
