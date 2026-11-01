# 01: 調查大表格 chunk 擋住後面所有 chunk 的問題

**What to build:** 這張是調查票。要回答：查詢時 LightRAG 截斷 chunk 遇到第一個放不下的就停，大表格 chunk 因此擋住排在後面、和問題更相關的 chunk。兩種修法各能救回多少題、會不會讓其他題目變差。用實測結果決定要不要開實作票、開哪一種。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 量影響範圍：對 eval 的 20 題（mix，含 rerank），記錄每題 rerank 後的 chunk 順序、各自的 token 數、截斷停在第幾名、沒用到的 token 數，以及被擋掉的 chunk 裡有沒有參考答案的關鍵字句。
- [ ] 修法 1「放不下就跳過、繼續放後面的」：實驗腳本裡換掉截斷的行為（不改 rag_lab），用 probe 數 terms-02 與其他題的關鍵字句覆蓋。
- [ ] 修法 2「大表格 chunk 重匯成小表」：用 ticket 12 的切表規則，在知識庫的副本上重匯含超過 2,000 token chunk 的文件，再用 probe 比較。
- [ ] 兩種修法中，覆蓋有增加的，對受影響的題目跑 mix 生成答案，兩位判讀者各自判讀；列出變對與變錯的題目。
- [ ] 結果寫在這張票的「調查結果」段落：事實和推測分開寫，每個結論附出處（log 路徑或檔案:行號），最後寫建議與理由。

## 已知的事實（2026-11-02）

診斷在 `output/taishin_eval2/terms02_diagnosis.md`，log 在同一個資料夾的 `probe_terms02.log`、`terms02_rerank_scores.log`。

- terms-02 需要的「165通報」「詐欺犯罪危害防制條例」有在 rerank 前的候選池（27 個 chunk）裡。rerank 之後，含這兩句的 chunk 排第 10 名，分數 0.6484。
- 實際進 context 的只有前 5 名，共 4,600 token。第 6 名是 5,417 token 的表格分析 chunk（`download_CreditCard_113001changev1.pdf`），累計 10,017 超過上限，所以截斷停在這裡。
- LightRAG 1.4.16 的 `truncate_list_by_token_size`（`lightrag/utils.py` 第 1431–1445 行）依序累加，第一次超過上限就回傳前面的部分。`process_chunks_unified`（同檔第 2840 行）用它截斷 chunk。
- 知識庫 2,065 個 chunk 中，有 32 個超過 2,000 token，全是表格分析 chunk（download 18、attachment 6、card 5、rights 3），最大 6,312 token。
- 推測，還沒驗證：用修法 1，第 10 名能不能放進去，取決於可用的 token 數，可能剛好放不下（前 5 名 4,600，加第 7、8 名到 8,614，再加第 10 名到 9,814）。

## Comments
