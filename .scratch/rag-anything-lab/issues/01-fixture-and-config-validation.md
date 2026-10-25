# 01: 測試夾具與設定驗證

**What to build:** 一個可執行的 CLI 入口，啟動時驗證 `.env` 設定；以及一個假的 OpenAI 相容 server 測試夾具，讓後續所有 ticket 的快速測試不需要啟動真實 MLX 模型。這是其他 ticket 的前置整理。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] CLI 在設定缺漏、URL 格式不合法、`EMBED_DIM` 等整數欄位非正整數時，以非零碼結束，錯誤訊息指出是哪個欄位，不印出任何金鑰值。
- [x] 有 `.env.example`，列出全部欄位並附用途說明，欄位名稱與現有冒煙測試使用的環境變數一致。
- [x] `.gitignore` 排除 `.venv`、`.env`、下載的論文、索引資料、解析輸出、`eval` 結果。
- [x] 有鎖定 `raganything==1.4.3` 的相依清單，用現有的 Python 3.12.12 venv 可重現安裝。
- [x] 有假的 OpenAI 相容 server 夾具，提供 chat、vision（接受 base64 data URI 圖片）、embeddings（維度與設定一致，預期 1024）三個端點，測試可啟停它。
- [x] 快速測試只從 CLI 進入（單一測試縫），涵蓋上述設定驗證行為並通過；貼出實際測試輸出。
- [x] 沒有新增 `raganything` 帶入套件以外的第三方依賴；若測試需要額外依賴，先回報再決定。
