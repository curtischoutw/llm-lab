# 05: 多篇匯入與五種檢索模式

**What to build:** `ingest` 可以處理整個資料夾，把 3–5 篇論文全部匯入同一個知識庫；`query` 可指定 naive、local、global、hybrid、mix 五種模式。

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `ingest <資料夾>` 逐篇處理資料夾內的 PDF，並印出每篇的耗時；某一篇失敗時指出是哪一篇，其餘已匯入的資料保留，整體以非零碼結束。
- [ ] 資料夾內非 PDF 檔案被略過並在輸出中說明，不當作錯誤。
- [ ] `query --mode` 接受 naive、local、global、hybrid、mix；其他值在 CLI 層被拒絕並列出合法值（下層對非法值只回 `None`，不會報錯）。
- [ ] `query --vlm-enhanced` 開啟 VLM 增強（預設關閉，與 spec「查詢行為」一致）；開啟時查詢端需要 VLM 端點，不可達時錯誤訊息指出 VLM 與其位址。
- [ ] 每種模式實測一次，確認 local／global／hybrid／mix 的關鍵字抽取在 4B 模型下都成功；失敗的模式回報實際錯誤。
- [ ] 3–5 篇論文全部匯入。每種模式各問至少 1 題並得到非空答案；貼出各模式的問題與答案。
- [ ] 至少有 1 題圖表相關問題，答案內容來自 VLM 產生的描述。
- [ ] 快速測試（對假 server）涵蓋非法模式、資料夾中的非 PDF、單篇失敗的結束碼，並通過；貼出實際輸出。
