# 01: 調查大表格 chunk 擋住後面所有 chunk 的問題

**What to build:** 這張是調查票。要回答：查詢時 LightRAG 截斷 chunk 遇到第一個放不下的就停，大表格 chunk 因此擋住排在後面、和問題更相關的 chunk。這些大表格 chunk 來自 ticket 12（大表格切成小表）之前匯入的 22 份文件；用現在的程式重匯這 22 份，能救回多少題、會不會讓其他題目變差。用實測結果決定要不要在正式知識庫上重匯。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 量影響範圍：對 eval 的 20 題（mix，含 rerank），記錄每題 rerank 後的 chunk 順序、各自的 token 數、截斷停在第幾名、沒用到的 token 數，以及被擋掉的 chunk 裡有沒有參考答案的關鍵字句。
- [x] 修法 2（先做）「重匯成小表」：在知識庫的副本上刪掉下面 22 份文件，用現在的程式（含 ticket 12 的切表）重新匯入，記錄每份的耗時與 GPU 記憶體峰值。重匯後再量一次上一條，比較 terms-02 與其他題的關鍵字句覆蓋。
- [x] （條件不成立，沒做：覆蓋沒有增加）覆蓋有增加時，對受影響的題目跑 mix 生成答案，兩位判讀者各自判讀；列出變對與變錯的題目。
- [x] （條件不成立，沒做：重匯後 0 題被大 chunk 擋住）修法 1（備案）「放不下就跳過、繼續放後面的」：只有重匯之後仍有題目被大 chunk 擋住時才做。在實驗腳本裡換掉截斷的行為（不改 rag_lab），用 probe 比較。
- [x] 結果寫在這張票的「調查結果」段落：事實和推測分開寫，每個結論附出處（log 路徑或檔案:行號），最後寫建議與理由。建議要在正式知識庫重匯時，刪除前先把文件清單列給使用者確認。

## 已知的事實（2026-11-02）

診斷在 `output/taishin_eval2/terms02_diagnosis.md`，log 在同一個資料夾的 `probe_terms02.log`、`terms02_rerank_scores.log`。

- terms-02 需要的「165通報」「詐欺犯罪危害防制條例」有在 rerank 前的候選池（27 個 chunk）裡。rerank 之後，含這兩句的 chunk 排第 10 名，分數 0.6484。
- 實際進 context 的只有前 5 名，共 4,600 token。第 6 名是 5,417 token 的表格分析 chunk（`download_CreditCard_113001changev1.pdf`），累計 10,017 超過上限，所以截斷停在這裡。
- LightRAG 1.4.16 的 `truncate_list_by_token_size`（`lightrag/utils.py` 第 1431–1445 行）依序累加，第一次超過上限就回傳前面的部分。`process_chunks_unified`（同檔第 2840 行）用它截斷 chunk。
- 知識庫 2,065 個 chunk 中，有 32 個超過 2,000 token，全是表格分析 chunk（download 18、attachment 6、card 5、rights 3），最大 6,312 token。
- 這 32 個 chunk 分布在 22 份文件，文件狀態的建立時間（`created_at`）都在 2026-10-29 23:27～10-31 09:01，早於 ticket 12 合併（51bba3e，2026-10-31 18:27 +0800）；已完整匯入的文件重新匯入時會略過，所以沒有切表。31 個 chunk 的表格超過 800 token（用 LightRAG 的 tokenizer 量 chunk 裡 `<table` 到 `</table>` 的字串，含 HTML 標籤，是 `table_body` 的近似值），推測重匯時會被 ticket 12 切開。`card_cg003_card001.pdf` 的表格只有 365 token，chunk 其餘 1,657 token 不是表格；`rag_lab/tables.py` 只切 `table_body` 超過 800 token 的表格，推測重匯後這個 chunk 大小不變。
- 22 份文件：card_cg047、card_cg003、card_cg039、card_cg045（`card_*_card001.pdf`）；rights_insurance_right0202、rights_notice_right0907、rights_oversea_right0106（`.docx`）；download_01_11502、download_02_11502、download_115001、download_121_1150A、download_12_1150A、download_2、download_CreditCard_113001changev1、download_TSBmember20250801、download_eTag-form_20251217、download_word_CR04131_1150B（`.pdf`）；attachment_2026BENZ_charge_20260102、attachment_2026airport_V3、attachment_2026normal_charge_20260102_2、attachment_IS_APPLY1_20260626、attachment_IS_APPLY_NC_20260626（`.pdf`）。
- 推測，還沒驗證：如果只用修法 1，第 10 名能不能放進去，取決於可用的 token 數，可能剛好放不下（前 5 名 4,600，加第 7、8 名到 8,614，再加第 10 名到 9,814）。

## 調查結果（2026-11-03）

檔案都在 `output/chunk_trunc/`（gitignore）：probe 腳本 `probe_truncation.py`，結果 `probe_before.json`／`.log`（重匯前）與 `probe_after.json`／`.log`（重匯後）；重匯腳本 `reingest22.py`、log `reingest.log`；chunk 大小比較 `chunk_sizes.py`。知識庫副本在 `kb_copy/`。

### 方法（事實）

- probe：在副本上以 mix（`rag_lab.pipeline.query_param("mix")`，含 rerank，和 eval 相同）只做檢索（`aquery_data`，不生成答案）。替換 `lightrag.utils.truncate_list_by_token_size`，只記錄 `process_chunks_unified` 截斷 chunk 時的輸入（rerank 後的順序）、每個 chunk 的 token 數（和原函式相同的 key 與 tokenizer）、上限與保留筆數，行為不變。
- 關鍵字句：每題 3 句。11 題沿用 `output/taishin_eval/probe_context.py` 的 `KEY_FACTS`（reranker 驗收用），另外 9 題依參考答案補（清單在 `probe_truncation.py`）。「進 context」= 出現在 `aquery_data` 回傳的 chunk、entity、relation 文字裡（去掉空白後比對）。60 句中 59 句在知識庫的 chunk 裡找得到（重匯前後都是）；rule-01 的「完全沒有回饋」在知識庫裡沒有這個字串（2026-11-01 reranker 驗收用同一組關鍵字句，分母也含這句）。
- 重匯：副本上用 `adelete_by_doc_id(delete_llm_cache=False)` 刪掉 22 份（和 rag_lab 替換舊版本相同，22 份都 `success`），再用 `Session.ingest` 重新匯入。解析快取保留，沒有重跑 MinerU。
- 重匯前的 probe 和 2026-11-01 reranker 驗收的結果一致：那 11 題合計 24/33。
- token 數有兩種算法：probe 的 chunk token 數（下面的截斷、上限、累計、5,515 等）用 LightRAG 截斷時的算法，是 chunk 序列化成 JSON 之後的長度；「超過 2,000 token」「最大 6,312」用 chunk 本文（`chunk_sizes.py`）。兩者同一個 chunk 差幾十 token。

### 重匯（事實，`reingest.log`）

- 22 份全部成功，2026-11-03 09:35:24～17:28:45，牆上時間 7 小時 53 分（含刪除 22 份與載入知識庫）；22 份的匯入耗時加總 24,437.8 秒（6 小時 47 分）。每份 157–3,674 秒（最久 `card_cg047_card001.pdf` 3,673.5 秒、`card_cg039_card001.pdf` 3,396.8 秒、`download_word_CR04131_1150B.pdf` 2,675.2 秒）。VLM 呼叫 178 次，失敗 0。文件 311 份全部 processed，failed 0。
- 記憶體：watchdog 取樣（`output/keyword_json/watchdog/sampler.log`，10 秒一次）在重匯期間系統 wired 記憶體最高 19 GB（11:11:24）。只有整段期間的最大值，沒有分每份文件記錄。
- chunk：2,065 → 2,212 個；超過 2,000 token 的 32 → 2 個（`download_CreditCard_113001changev1.pdf` 2,374、`download_word_CR04131_1150B.pdf` 2,090）；最大 6,312 → 2,374 token。實體 15,747 → 16,839，關係 31,239 → 34,218（數 graphml 的 node 與 edge）。

### 截斷與覆蓋（事實，`probe_before.json`、`probe_after.json`）

| 20 題（mix＋rerank） | 重匯前 | 重匯後 |
|---|---|---|
| 關鍵字句進 context | 50/60 | 50/60（每題都沒有得失） |
| 平均放進 context 的 chunk 數 | 6.35 | 8.2 |
| 平均沒用到的 token 數 | 1,379 | 706 |
| context 平均涵蓋的文件數 | 3.55 | 4.8 |
| 截斷停在超過 2,000 token（JSON 序列化後）的 chunk 上的題數 | 4 | 0 |

- terms-02：重匯前含「165通報」「詐欺犯罪危害防制條例」的 chunk 排第 10 名，截斷停在第 6 名（5,515 token 的表格 chunk，上限 10,147，已用 5,010）。重匯後排第 12 名，前 8 名放進去（已用 9,253，上限 10,153），累計到第 12 名要 14,379 token。所以重匯後擋住它的不是大 chunk，是排名：rerank 後排在它前面的 11 個 chunk，10 個在 1,100–1,300 token，第 7 名 534 token。
- 其他沒有拿全的題目，進 context 的關鍵字句也沒變：cross-02 0/3、rule-01 1/3、cross-01 2/3、fee-02 2/3。

### 推測

- 對這 20 題，重匯讓 context 多放約 2 個 chunk、多涵蓋約 1 份文件，但需要的關鍵字句沒有變多；答案會不會變好沒有實測（依本票規則，覆蓋沒增加就不跑生成）。
- terms-02 要救回來，要改的是排名或上限（例如 rerank 的輸入、`chunk_top_k`、總 token 上限），不是截斷方式。修法 1 對重匯後的知識庫沒有作用：沒有題目被超過 2,000 token 的 chunk 擋住；以 terms-02 重匯後的順序模擬「放不下就跳過、繼續放後面的」（上限 10,153），第 12 名的 1,305 token 仍放不進去。

### 建議與決定

- 建議：正式知識庫換成重匯後的副本（不用再花 8 小時），換之前備份。理由：超過 2,000 token 的 chunk 從 32 個降到 2 個，所有文件都經過 ticket 12 的切表；代價是答案沒有實測；金融卡 ticket 05 的新基準 eval 可能量到這個差異。
- 2026-11-03 使用者選擇用副本取代。執行：原本的 `rag_storage/` 搬到 `output/kb_backups/rag_storage-20261103-before-reingest22/`，再把 `kb_copy/` clone 成 `rag_storage/`。換完後 311 份 processed、2,212 個 chunk；答案快取（`cache_type=query`）0 筆，重匯時已清。要還原就把備份搬回 `rag_storage/`。

### symlink 與解析快取（範圍外的實測，`output/chunk_trunc/symlink_test/`）

- RAG-Anything 解析快取的 key 含 `file_path.absolute()`（`raganything/processor.py:110–119`），`absolute()` 不解析 symlink。rag_lab 的 CLI 匯入單一檔案時先 `resolve()`（`rag_lab/__main__.py:155`），匯入資料夾時傳的是資料夾底下的路徑、沒有 resolve（`rag_lab/formats.py` `list_folder` 的說明）。
- 實測（空知識庫，一份指向 `offers/offer_WM_20250716180549852.pdf` 的 symlink，`run.sh`、`run.log`）：
  - a. 匯入含 symlink 的資料夾：跑 MinerU（解析 23.0 秒），存快取。（`run.log` 的 a 列 `cached=1` 是存入快取之後同一次匯入再讀一次，不是命中。）
  - b. 同一個資料夾再匯入一次：快取命中，0.0 秒，對照表記「沒變」。
  - c. 用實體路徑匯入單一檔案：快取沒命中，又跑一次 MinerU（23.0 秒），對照表記「沒變」。
  - d. 用 symlink 路徑匯入單一檔案（CLI 會 resolve 成實體路徑）：命中 c 存的快取，0.0 秒。
- 結論：舊紀錄「經由 symlink 重複 ingest 時，parse cache 不會命中」不正確。同一條路徑重複匯入會命中；同一份文件從資料夾裡的 symlink 換成實體路徑時不命中（實測 a→c；反過來由實體路徑換成 symlink 沒測，依 key 的算法推論也不命中），多跑一次 MinerU，知識庫內容不變。已寫進 README 的已知限制。

## Comments

- 2026-11-02 使用者決定：先做修法 2（重匯），修法 1 留作備案。由主對話執行（要長時間開 server），開工時間等使用者通知；同一次開 server 先跑 `.scratch/keyword-extraction-json/issues/01`。
- 同一次開 server 時另外實測一件範圍外的事：用 `data/taishin_pilot/` 的一個 symlink 檔案對同一個知識庫副本匯入兩次，看第二次有沒有重跑 MinerU（舊紀錄說 symlink 路徑的解析快取不會命中，但沒有驗證過）。結果寫進 README 的已知限制或刪掉這條紀錄。
