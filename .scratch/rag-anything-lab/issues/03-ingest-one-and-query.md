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
- [ ] 使用者不需要先 activate venv：CLI 確保專案 venv 的 bin 目錄在 PATH 上，MinerU 能被找到；以直接呼叫 venv 的 python 執行 `ingest` 驗證。
- [ ] MinerU 的後端在 Mac（無 CUDA）上實測挑選（候選：pipeline），回報各自的解析耗時與選擇理由；模型預先下載與解析耗時分開量測。
- [ ] 以計數或內容檢查驗證「圖片描述確實來自 VLM」（VLM 失敗時匯入不會報錯，描述會變成原始 dict 的 fallback 文字）；貼出 VLM 成功呼叫次數。
- [ ] `query` 使用可回報失敗的查詢介面（`aquery_llm`），失敗時以非零碼結束並印出原例外文字，不得把 `None` 當成空答案。
- [ ] 重複匯入的處理避開「failed 重複紀錄」與「卡在 handling」問題（先解析取得文件 ID，已完整處理就不再匯入）；重複匯入後 `get_status_counts()` 不拋錯。
- [ ] 對真實 server 驗證 mix 模式的關鍵字抽取不會因 4B 輸出不是乾淨 JSON 而失敗；若失敗，回報實際錯誤並停下來，不自行加 workaround。
- [ ] 驗證真實 embedding server 接受 LightRAG 預設的 `encoding_format=base64`；不接受時回報，由使用者決定是否改設定。
- [ ] 快速測試（對假 server）涵蓋重複匯入與端點不可達的訊息，並通過；貼出實際輸出。
- [ ] 回報實測的解析耗時、建圖耗時、LLM 並行數，供之後調整參考。
