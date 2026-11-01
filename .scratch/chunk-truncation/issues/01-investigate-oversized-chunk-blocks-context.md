# 01: 調查大表格 chunk 擋住後面所有 chunk 的問題

**What to build:** 這張是調查票。要回答：查詢時 LightRAG 截斷 chunk 遇到第一個放不下的就停，大表格 chunk 因此擋住排在後面、和問題更相關的 chunk。這些大表格 chunk 來自 ticket 12（大表格切成小表）之前匯入的 22 份文件；用現在的程式重匯這 22 份，能救回多少題、會不會讓其他題目變差。用實測結果決定要不要在正式知識庫上重匯。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 量影響範圍：對 eval 的 20 題（mix，含 rerank），記錄每題 rerank 後的 chunk 順序、各自的 token 數、截斷停在第幾名、沒用到的 token 數，以及被擋掉的 chunk 裡有沒有參考答案的關鍵字句。
- [ ] 修法 2（先做）「重匯成小表」：在知識庫的副本上刪掉下面 22 份文件，用現在的程式（含 ticket 12 的切表）重新匯入，記錄每份的耗時與 GPU 記憶體峰值。重匯後再量一次上一條，比較 terms-02 與其他題的關鍵字句覆蓋。
- [ ] 覆蓋有增加時，對受影響的題目跑 mix 生成答案，兩位判讀者各自判讀；列出變對與變錯的題目。
- [ ] 修法 1（備案）「放不下就跳過、繼續放後面的」：只有重匯之後仍有題目被大 chunk 擋住時才做。在實驗腳本裡換掉截斷的行為（不改 rag_lab），用 probe 比較。
- [ ] 結果寫在這張票的「調查結果」段落：事實和推測分開寫，每個結論附出處（log 路徑或檔案:行號），最後寫建議與理由。建議要在正式知識庫重匯時，刪除前先把文件清單列給使用者確認。

## 已知的事實（2026-11-02）

診斷在 `output/taishin_eval2/terms02_diagnosis.md`，log 在同一個資料夾的 `probe_terms02.log`、`terms02_rerank_scores.log`。

- terms-02 需要的「165通報」「詐欺犯罪危害防制條例」有在 rerank 前的候選池（27 個 chunk）裡。rerank 之後，含這兩句的 chunk 排第 10 名，分數 0.6484。
- 實際進 context 的只有前 5 名，共 4,600 token。第 6 名是 5,417 token 的表格分析 chunk（`download_CreditCard_113001changev1.pdf`），累計 10,017 超過上限，所以截斷停在這裡。
- LightRAG 1.4.16 的 `truncate_list_by_token_size`（`lightrag/utils.py` 第 1431–1445 行）依序累加，第一次超過上限就回傳前面的部分。`process_chunks_unified`（同檔第 2840 行）用它截斷 chunk。
- 知識庫 2,065 個 chunk 中，有 32 個超過 2,000 token，全是表格分析 chunk（download 18、attachment 6、card 5、rights 3），最大 6,312 token。
- 這 32 個 chunk 分布在 22 份文件，文件狀態的建立時間（`created_at`）都在 2026-10-29 23:27～10-31 09:01，早於 ticket 12 合併（51bba3e，2026-10-31 18:27 +0800）；已完整匯入的文件重新匯入時會略過，所以沒有切表。31 個 chunk 的表格超過 800 token（用 LightRAG 的 tokenizer 量 chunk 裡 `<table` 到 `</table>` 的字串，含 HTML 標籤，是 `table_body` 的近似值），推測重匯時會被 ticket 12 切開。`card_cg003_card001.pdf` 的表格只有 365 token，chunk 其餘 1,657 token 不是表格；`rag_lab/tables.py` 只切 `table_body` 超過 800 token 的表格，推測重匯後這個 chunk 大小不變。
- 22 份文件：card_cg047、card_cg003、card_cg039、card_cg045（`card_*_card001.pdf`）；rights_insurance_right0202、rights_notice_right0907、rights_oversea_right0106（`.docx`）；download_01_11502、download_02_11502、download_115001、download_121_1150A、download_12_1150A、download_2、download_CreditCard_113001changev1、download_TSBmember20250801、download_eTag-form_20251217、download_word_CR04131_1150B（`.pdf`）；attachment_2026BENZ_charge_20260102、attachment_2026airport_V3、attachment_2026normal_charge_20260102_2、attachment_IS_APPLY1_20260626、attachment_IS_APPLY_NC_20260626（`.pdf`）。
- 推測，還沒驗證：如果只用修法 1，第 10 名能不能放進去，取決於可用的 token 數，可能剛好放不下（前 5 名 4,600，加第 7、8 名到 8,614，再加第 10 名到 9,814）。

## Comments

- 2026-11-02 使用者決定：先做修法 2（重匯），修法 1 留作備案。由主對話執行（要長時間開 server），開工時間等使用者通知；同一次開 server 先跑 `.scratch/keyword-extraction-json/issues/01`。
- 同一次開 server 時另外實測一件範圍外的事：用 `data/taishin_pilot/` 的一個 symlink 檔案對同一個知識庫副本匯入兩次，看第二次有沒有重跑 MinerU（舊紀錄說 symlink 路徑的解析快取不會命中，但沒有驗證過）。結果寫進 README 的已知限制或刪掉這條紀錄。
