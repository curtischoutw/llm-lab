# 03: 匯入 1 篇論文並問答

**What to build:** 第一條完整路徑：用 `ingest` 把一篇 PDF 匯入（MinerU 解析、圖片由 VLM 描述、LLM 抽取實體與關係、embedding 建向量），再用 `query` 以 mix 模式回答問題。對真實本地 MLX server 驗證。

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] 第一次真實執行前，先重跑現有冒煙測試，三個端點全過；任一項失敗就停下來回報錯誤輸出與可行選項，不換框架、不寫 workaround。
- [ ] 啟動 LLM server 時帶 `--max-tokens 4096`；VLM 與 embedding 在同一個 server 啟動。
- [ ] `ingest <單一 PDF>` 印出 MinerU 解析耗時與建圖耗時；MinerU 第一次執行的模型下載時間單獨標示。
- [ ] 圖片、表格、公式有被處理；至少有一張圖的描述來自 VLM，貼出該描述並判斷與原圖相符。
- [ ] 重複 `ingest` 同一篇不會重複建立資料。
- [ ] `query "<問題>"` 預設 mix 模式，印出答案；查詢端 embedding 帶可設定的 instruction 前綴，文件端不帶。
- [ ] LLM、VLM、embedding 任一端點不可達時，錯誤訊息指出是哪一個端點與其位址。
- [ ] LLM 並行請求數預設為低值並可由設定調整。
- [ ] 快速測試（對假 server）涵蓋重複匯入與端點不可達的訊息，並通過；貼出實際輸出。
- [ ] 回報實測的解析耗時、建圖耗時、LLM 並行數，供之後調整參考。
