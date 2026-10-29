# 06: 主知識庫擴充與驗收

**What to build:** 把 `data/documents/` 的 6 份 RAG 主題文件（PPT 2、Word 2、圖片 2）匯入主知識庫，並用新的題目檔確認每份文件的內容都問得到，而且新文件的實體和既有的論文圖譜連得起來。匯入前先備份主知識庫，作為比較與回復的基準。

**Blocked by:** 05（不是程式上的依賴：真的 LibreOffice 在 05 安裝，而且兩次實機匯入都要佔用同一台機器的 GPU 記憶體，不能同時跑）

**Status:** resolved

- [x] 寫 `eval/questions.formats.jsonl`（納入版本控管），欄位沿用現有題目檔，`source` 填文件名稱：每份文件 1–2 題，答案只能從那份文件找到，不能從已匯入的 3 篇論文答出；另加 2 題跨格式的題目。參考答案根據文件原文撰寫。
- [x] 匯入前，把 `rag_storage` 複製成 `rag_storage.before-formats/`，確認它在 gitignore 底下。
- [x] 照 README 啟動兩個 MLX server，同時以 zsh 執行 watchdog（門檻 22 GB）；smoke test 三項 PASS。
- [x] 執行 `ingest data/documents`：6 份都匯入成功。記錄每份的耗時、轉檔時間（從 log 讀出）、wired 記憶體峰值，以及圖譜在匯入前後的實體與關係數。
- [ ] 用 `eval` 跑 `eval/questions.formats.jsonl`：mix 模式下每份新文件至少答對 1 題。答對與否由實作者對照參考答案判斷，並列出判斷理由，讓使用者抽查。也記錄其他 4 種模式的結果。（**未達成**：6 份中 3 份未通過，使用者決定接受，見實作結果）
- [x] 確認既有能力沒有退步：用 `eval/questions.example.jsonl` 跑一次，結果與擴充前一樣能答出。
- [x] 驗證完關掉 server 與 watchdog；輸出與 log 存到 `output/` 底下。
- [x] README：新格式的實測數據（耗時、記憶體、圖譜增加量、問答結果），目前的知識庫內容改成 3 篇論文加 6 份文件。
- [x] 派一個沒參與實作的 agent，對照 repo 對 README、架構文件、`GLOSSARY.md` 做 read-back，結果不能有任何不符；無法確認的項目要列出理由。
- [x] 任何文件驗收失敗時，記下事實、已排除的假設、卡點，回報使用者決定，不放寬驗收標準。
- [x] 文字符合使用者的寫作規則。

## 實作結果（2026-10-29，mix 驗收 3／6 份未通過，使用者決定接受並另開 spec）

在主 repo 工作目錄執行（integration 分支 ef8f7d0），理由同 ticket 05。紀錄存在 `output/formats_main_run/`。

- **題目檔**：`eval/questions.formats.jsonl`，10 題（每份文件 1–3 題，另有 2 題跨格式）。參考答案依文件原文撰寫。
- **備份**：`rag_storage` 複製成 `rag_storage.before-formats/`，`.gitignore` 加上 `/rag_storage.before-formats/`，`git check-ignore` 確認被忽略，`diff -rq` 確認內容相同。
- **實機匯入**：沿用 ticket 05 啟動的 server 與 watchdog（zsh，門檻 22 GB），smoke test 三項 PASS。`ingest data/documents` 從 00:42:52 跑到 01:23:53（2461 s），6 份都匯入成功，文件狀態 processed=9（3 篇論文加 6 份文件）、failed=0，VLM 呼叫 29 次全部成功。
  - 每份耗時：Experimentations docx 747 s、LLM_Comparisons docx 584 s、RAGHack pptx 910 s（其中 Office 轉 PDF 11 s）、docling_arch pptx 66 s、auto-tune png 62 s、unified-search png 87 s。
  - wired 記憶體峰值：匯入期間 19 GB，之後的 eval 期間 20 GB，watchdog 沒有觸發。
  - 圖譜：實體 1358 → 1838，關係 1835 → 2873。
- **eval**：`eval_results/eval_20261029-012408.md`，50 格，失敗 0 格，沒有 query cache 命中。逐格判讀與理由在 `output/formats_main_run/judgement.md`。各模式答對題數：naive 4、local 3、global 3、hybrid 2、mix 4。
- **驗收：未通過。** mix 模式下 6 份文件有 3 份至少答對 1 題（docling_arch pptx、Experimentations docx、LLM_Comparisons docx），3 份沒有：
  - RAGHack pptx：pptx-01 部分對，pptx-02 答錯；
  - auto-tune png：png-01 答錯；
  - unified-search png：png-02 回答「無法確定」，cross-02 部分對。
- **事實與原因**（探測方式與數據見 `judgement.md`）：參考答案的原文都在知識庫裡，答錯是因為這些切塊沒有送進 LLM，或送進去的內容不完整：
  1. mix 在 `QUERY_MAX_TOTAL_TOKENS=12000` 下只放得進 5–6 個切塊；png-02、cross-02 的切塊向量名次 7、10，被截掉，改成 LightRAG 預設的 30000 時會被送進 LLM。
  2. pptx-02 的切塊向量名次在 100 名外，png-01 排第 26，30000 token 也拿不到。
  3. pptx-01 依賴的表格打勾欄位在解析時遺失，該欄全部是空的。
- **已排除的假設**：內容沒有匯入、query cache 回傳舊答案、擴充造成既有能力退步。
- **既有能力**：直接重跑 `eval/questions.example.jsonl` 時 10 格全部是 query cache 命中，不能當作驗證。改用拿掉 `:query:` cache 的知識庫副本重跑（`eval_results/eval_20261029-020848.md`），10 格都答對，0 次 cache 命中。副本已刪除。
- **卡點**：要讓這 3 份文件通過，需要改變查詢設定或檢索方式，例如提高 `QUERY_MAX_TOTAL_TOKENS`（ticket 03 因 GPU 記憶體不足才降到 12000）、啟用 rerank、或調整切塊方式。這些都超出本 ticket 範圍，而且改題目或放寬判讀標準違反本 ticket 的規定，所以停在這裡回報使用者。
- **使用者決定**（2026-10-29）：接受現況，把 3 份文件沒通過的原因記成已知限制，本 ticket 結案；改善檢索另開 spec。
- **收尾**：server 已關閉，watchdog 隨之結束。read-back 由沒參與撰寫的 agent 執行，查出 4 處不符（論文切塊長度範圍、匯入總時間的計算方式、題目檔尚未進版控、formats 題目檔的描述），都已修正；無法確認的項目是過去的量測數字（repo 內沒有紀錄）與未執行的測試指令。README 第 4 節（圖片已知限制、目前的知識庫內容、LLM 快取的限制）與第 5 節（本次實測表格與問答結果）已更新；`docs/architecture.md` 的目錄表補上新的題目檔、`.scratch/multi-format-documents/`、`GLOSSARY.md`、`rag_storage.before-formats/` 與轉檔 PDF。
