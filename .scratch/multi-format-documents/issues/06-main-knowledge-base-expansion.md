# 06: 主知識庫擴充與驗收

**What to build:** 把 `data/documents/` 的 6 份 RAG 主題文件（PPT 2、Word 2、圖片 2）匯入主知識庫，並用新的題目檔確認每份文件的內容都問得到，而且新文件的實體和既有的論文圖譜連得起來。匯入前先備份主知識庫，作為比較與回復的基準。

**Blocked by:** 05（不是程式上的依賴：真的 LibreOffice 在 05 安裝，而且兩次實機匯入都要佔用同一台機器的 GPU 記憶體，不能同時跑）

**Status:** ready-for-agent

- [ ] 寫 `eval/questions.formats.jsonl`（納入版本控管），欄位沿用現有題目檔，`source` 填文件名稱：每份文件 1–2 題，答案只能從那份文件找到，不能從已匯入的 3 篇論文答出；另加 2 題跨格式的題目。參考答案根據文件原文撰寫。
- [ ] 匯入前，把 `rag_storage` 複製成 `rag_storage.before-formats/`，確認它在 gitignore 底下。
- [ ] 照 README 啟動兩個 MLX server，同時以 zsh 執行 watchdog（門檻 22 GB）；smoke test 三項 PASS。
- [ ] 執行 `ingest data/documents`：6 份都匯入成功。記錄每份的耗時、轉檔時間（從 log 讀出）、wired 記憶體峰值，以及圖譜在匯入前後的實體與關係數。
- [ ] 用 `eval` 跑 `eval/questions.formats.jsonl`：mix 模式下每份新文件至少答對 1 題。答對與否由實作者對照參考答案判斷，並列出判斷理由，讓使用者抽查。也記錄其他 4 種模式的結果。
- [ ] 確認既有能力沒有退步：用 `eval/questions.example.jsonl` 跑一次，結果與擴充前一樣能答出。
- [ ] 驗證完關掉 server 與 watchdog；輸出與 log 存到 `output/` 底下。
- [ ] README：新格式的實測數據（耗時、記憶體、圖譜增加量、問答結果），目前的知識庫內容改成 3 篇論文加 6 份文件。
- [ ] 派一個沒參與實作的 agent，對照 repo 對 README、架構文件、`GLOSSARY.md` 做 read-back，結果不能有任何不符；無法確認的項目要列出理由。
- [ ] 任何文件驗收失敗時，記下事實、已排除的假設、卡點，回報使用者決定，不放寬驗收標準。
- [ ] 文字符合使用者的寫作規則。
