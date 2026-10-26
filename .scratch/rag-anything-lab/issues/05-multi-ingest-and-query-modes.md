# 05: 多篇匯入與五種檢索模式

**What to build:** `ingest` 可以處理整個資料夾，把 3–5 篇論文全部匯入同一個知識庫；`query` 可指定 naive、local、global、hybrid、mix 五種模式。

**Blocked by:** 03

**Status:** resolved

- [x] `ingest <資料夾>` 逐篇處理資料夾內的 PDF，並印出每篇的耗時；某一篇失敗時指出是哪一篇，其餘已匯入的資料保留，整體以非零碼結束。
- [x] 資料夾內非 PDF 檔案被略過並在輸出中說明，不當作錯誤。
- [x] `query --mode` 接受 naive、local、global、hybrid、mix；其他值在 CLI 層被拒絕並列出合法值（下層對非法值只回 `None`，不會報錯）。
- [x] `query --vlm-enhanced` 開啟 VLM 增強（預設關閉，與 spec「查詢行為」一致）；開啟時查詢端需要 VLM 端點，不可達時錯誤訊息指出 VLM 與其位址。
- [x] 每種模式實測一次，確認 local／global／hybrid／mix 的關鍵字抽取在 4B 模型下都成功；失敗的模式回報實際錯誤。
- [x] 3–5 篇論文全部匯入。每種模式各問至少 1 題並得到非空答案；貼出各模式的問題與答案。
- [x] 至少有 1 題圖表相關問題，答案內容來自 VLM 產生的描述。
- [x] 快速測試（對假 server）涵蓋非法模式、資料夾中的非 PDF、單篇失敗的結束碼，並通過；貼出實際輸出。

## 實測結果（2026-10-27）

紀錄在 `output/ticket05_run/`（gitignore）。server 參數與 ticket 03 相同；`.env`：`LLM_MAX_ASYNC=1`、`EMBED_MAX_ASYNC=1`、`QUERY_MAX_TOTAL_TOKENS=12000`。

**語料**：3 篇（使用者決定），以 `output/ticket05_papers/`（3 個 PDF 的 symlink 加 1 個 README.txt）執行 `ingest`。RAG-Anything 以 `Path.resolve()` 後的路徑計算解析輸出資料夾，symlink 與原檔得到同一個文件 ID。

```
略過非 PDF：README.txt
[1/3] 2404.16130.pdf：耗時 2112.6 s
  MinerU 解析：42.1 s（backend=pipeline）
  建圖（文字切塊、實體抽取、向量）：1218.3 s
  多模態（圖／表／公式描述）：852.3 s，13 項
[2/3] 2410.05779.pdf：耗時 37.3 s
  已完整處理過，略過（查快取 37.3 s）
[3/3] 2510.12323.pdf：耗時 2675.9 s
  MinerU 解析：31.3 s（backend=pipeline）
  建圖（文字切塊、實體抽取、向量）：780.2 s
  多模態（圖／表／公式描述）：1864.4 s，27 項
VLM 呼叫：成功 15，失敗 0
圖譜：實體 1358，關係 1835（其中 RAG-Anything 加的 belongs_to 邊 735，其餘 1100）
文件狀態：failed=0，pending=0，preprocessed=0，processed=3，processing=0
```

總耗時 4829 s，rc=0，wired 記憶體最高 18 GB。ingest log 中 LLM 格式警告 9 次（「Complete delimiter can not be found」5 次、「LLM output format error」3 次、「regex fallback for JSON parsing」1 次），都沒有讓匯入失敗。

**五種模式**（各 1 題，全部 rc=0、答案非空；local／global／hybrid／mix 的關鍵字抽取都成功，log 有 `<mode>:keywords` 快取寫入）

| 模式 | 問題 | 耗時 | 答案開頭 |
|---|---|---|---|
| naive | What is the main idea of RAG-Anything? | 52 s | 統一的多模態 RAG 框架，dual-graph construction（text-based 與 cross-modal 兩張圖）、cross-modal hybrid retrieval，在 DocBench 與 MMLongBench 驗證 |
| local | What is community detection used for in GraphRAG? | 59 s | 把知識圖譜分成主題社群（C0–C3 階層，Leiden 演算法），用於 global sensemaking 的 query-focused summarization |
| global | What common themes appear across these papers on graph-based RAG? | 66 s | 以圖譜建索引支援 global sensemaking；圖譜方法在 comprehensiveness 與 diversity 上優於 vector RAG |
| hybrid | How does LightRAG's retrieval differ from GraphRAG's? | 63 s | LightRAG 用 low-level／high-level 雙層檢索；GraphRAG 以社群為單位，社群報告的 token 數多 |
| mix | In the GraphRAG pipeline figure, which stages happen at query time and which at indexing time? | 52 s | 見下方圖表題 |

完整答案在 `output/ticket05_run/query_<mode>.out`。

**圖表題**（GraphRAG Figure 1；原圖以顏色區分：淡紫色為 indexing time，綠色只有 Community Answers 與 Global Answer）

- mix 模式的答案把 Graph Communities、Community Summaries、Community Answers、Global Answer 列為 query time。這個分法與索引中 VLM 描述（`chunk-c2d7f2…`）的「'Indexing Time' on the left and 'Query Time' on the right」逐項一致，答案內容來自 VLM 描述。VLM 描述本身有錯：它同時寫了「light purple boxes for indexing components and light green boxes for query components」，卻把右欄的兩個淡紫色方塊歸到 query time。
- `--vlm-enhanced`（問「哪些是綠色、哪些是紫色」）：rc=0，log 為「Processed 2 images for VLM」。答案中綠色列出 Community Answers、Community Summaries、Global Answer，其中 Community Summaries 在原圖是淡紫色；紫色列出四個方塊，漏掉 Graph Communities 與 Community Summaries。
