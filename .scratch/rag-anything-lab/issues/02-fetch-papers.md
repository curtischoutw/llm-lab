# 02: 論文下載

**What to build:** 一個指令，把 3–5 篇 RAG 主題的 arXiv 論文下載到不進版本控管的本地資料夾，讓語料可以重現。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 候選清單：RAG（2005.11401）、GraphRAG（2404.16130）、LightRAG（2410.05779）、Self-RAG（2310.11511）、RAG-Anything（ID 需查證）。下載前逐一以 arXiv 官方來源確認 ID 與標題相符，不符就中止並回報，不下載。
- [x] 最終清單 3–5 篇，內容含圖或表，各篇主題相關（以便之後有跨論文的問題）。
- [x] arXiv ID 格式不合法或下載失敗時，以非零碼結束並指出是哪一個 ID；不略過後繼續。
- [x] 重複執行時不重複下載已存在且完整的檔案。
- [x] 下載的 PDF 不進版本控管。（`.gitignore` 排除 `/data/`；已用 `git check-ignore` 確認 `data/papers/*.pdf` 被忽略）
- [x] 貼出實際執行輸出，列出最終下載的論文標題與頁數。
