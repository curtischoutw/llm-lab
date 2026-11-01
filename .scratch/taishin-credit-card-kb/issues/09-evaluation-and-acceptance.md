# 09: 評估與驗收

**What to build:** 用新的題目檔對知識庫跑五種檢索模式，逐格判讀，確認台新信用卡知識庫在 mix 模式下每一類內容都答得出來，並把實測數據寫進文件，作為之後調整查詢設定時的基準。

**Blocked by:** 07、08

**Status:** ready-for-agent

- [x] 照 README 啟動兩個 MLX server 與 watchdog，用 `eval` 跑題目檔的 20 題 × 5 種模式。查詢設定維持 `QUERY_MAX_TOTAL_TOKENS=12000`、不啟用 rerank。
- [x] 逐格判讀，列出判讀理由，讓使用者抽查。
- [ ] 驗收：mix 模式下 7 個類別（切換、權益、回饋規則、費用、約定條款、優惠活動、跨卡比較）各至少答對 1 題。其他 4 種模式的結果也要記錄。
- [ ] 任何類別驗收失敗時，記下事實、已排除的假設與卡點，回報使用者決定，不放寬標準、不改題目。
- [ ] README：新知識庫的實測數據（匯入耗時、記憶體、圖譜大小、問答結果），以及重建知識庫的完整指令順序。
- [ ] 架構文件：目錄表加入新的資料夾、下載腳本、新題目檔。
- [ ] 派一個沒參與撰寫的 agent，對照 repo 對 README、架構文件、`GLOSSARY.md` 做 read-back，結果不能有任何不符；無法確認的項目要列出理由。
- [ ] 驗證完關閉 server 與 watchdog；輸出與 log 存在 `output/` 底下。
- [ ] 文字符合使用者的寫作規則。

## 評估結果（2026-11-01）

- `eval eval/questions.taishin.jsonl`：100 格，失敗 0 格，耗時 1:41:12。結果在 `eval_results/eval_20261031-225221.md`，log 在 `output/taishin_eval/eval.log`。
- 逐格判讀在 `output/taishin_eval/judgement.md`：兩個判讀者各自獨立判讀，再由主對話裁決分歧。
- 各模式答對（✓）題數：naive 8、local 4、global 8、hybrid 4、mix 4。
- **驗收未通過**：mix 模式下 7 類中 4 類通過，3 類未通過，標準沒有放寬，題目也沒有改。
  - 通過的 4 類：切換（switch-02）、權益（benefit-01）、費用（fee-02）、優惠活動（offer-02）。
  - 未通過的 3 類：回饋規則（rule-01／02／03 都是 △）、約定條款（terms-01 △、terms-02 ✗）、跨卡比較（cross-01、cross-02 都是 ✗）。這 3 類在其他 4 種模式也沒有任何一格 ✓。
- 事實、已排除的假設與未驗證的推測都寫在 `judgement.md`。重點如下：
  - mix 答案引用的 65 份文件中，44 份是活動頁；rule-01、rule-02 完全沒有引用到題目的來源文件。
  - terms-01 混入 iCash 聯名卡條款的規定。
- 已回報使用者，等使用者決定下一步。README、架構文件、read-back 與關閉 server 這 4 項，等決定後再做。

## 第二次評估（2026-11-01，ticket 13 之後）

- 使用者決定先查根本原因，再調 mix 的 token 分配（ticket 13）並加 reranker。
- `eval_results/eval_20261101-095122.md`：entity／relation 上限 500／500，mix 的 ✓ 從 4 題增加到 7 題。判讀在 `output/taishin_eval2/judgement.md`。
- **驗收仍未通過**：7 類中 5 類通過。回饋規則這次通過（rule-03）；約定條款（terms-01 △、terms-02 ✗）、跨卡比較（cross-01、cross-02 ✗）仍未通過。
- 改善提案與實驗結果在 `.scratch/taishin-credit-card-kb/proposal-answer-quality.md`：回答規則（方案 A）沒有效果；拆成單卡子問題（方案 C）讓 cross-01、cross-02 的檢索覆蓋增加，還沒有實作。
- 使用者決定下一步：另開 reranker 的 spec（方案 B）。這張 ticket 等 reranker 之後重新評估。
