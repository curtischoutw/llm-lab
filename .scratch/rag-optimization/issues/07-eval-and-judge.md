# 07: 重匯後的 eval、雙判讀與歸因

**What to build:** 在新知識庫上跑 28 題 eval（只跑 mix），兩位判讀者各自判讀並用程式比對，和基準比較；再跑 probe 歸因（spec：「驗收」；grill-notes 決定 1、11）。

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] eval：`eval eval/questions.taishin.jsonl --modes mix`，跑 1 次，開 watchdog。記錄總時間（和基準約 21 分鐘比較，看 4B embedding 讓查詢慢多少）。
- [ ] 檢查每格答案有沒有被長度截斷（rag_lab 不會擋，見 grill-notes「範圍外發現」），有的話算 ✗ 並寫出來。
- [ ] 判讀：照 `output/answer_prompt_01/judge_brief.md` 的判準，兩位判讀者（sonnet）各自判讀，不給基準分數。判讀檔放在 `output/rag_opt/judging/reingest_judge_{A,B}.md`，用 `python3 output/rag_opt/compare_judges.py reingest` 比對。
- [ ] 驗收：內容 ✓ ≥20、最終 ✓ ≥12，兩位判讀者都同意的變好題數減變差題數 ≥4，原本 ✓ 的題目沒有變錯（以兩位判讀者都同意變差的題目計）。列出所有變差的題目，含只有一位判讀者判變差的。
- [ ] probe：`output/rag_opt/probe28.py` 的 `SOURCE_OVERRIDES` 改成新檔名，對新知識庫重跑，列出 a／b_rank／b_trunc／c 的分布，和基準（c 6、a 5、b_trunc 1）對照。
- [ ] 沒達標時不回滾，結果寫進下方，由使用者決定下一步。
- [ ] 結果寫進下方，並更新記憶。

## 結果（2026-11-23）

受測知識庫：06 重匯 → 刪 LINE／FB 圖示圖 → 解析修補增量合併（chunk 3,324、實體 11,658、關係 31,073）。
eval：`output/rag_opt/eval_runs/t07/eval_20261123-121716.md`，28 格全成功，21 分鐘（基準約 21 分鐘，4B embedding 沒讓查詢變慢），沒有答案被長度截斷，wired 峰值 24 GB。

判讀：兩位 sonnet 判讀者各自判讀（`judging/reingest_judge_{A,B}.md`），程式比對只有 cross-02 分歧（A △、B ✗），主對話裁定 ✗：三張卡只答對 Richart 一張，另兩張答「未列出」，歐洲實體商店部分拿簽帳金融卡的規則回答，主要事實缺漏或錯（基準也是 ✗）。兩位判讀者都把答案引用區的檔名（含「信用卡」字樣）算作有卡別；若不算，switch-02 最終 ✓ 改 △。

| 驗收條件 | 結果 | 達標 |
|---|---|---|
| 內容 ✓ ≥20 | 18（基準 16） | ✗ |
| 最終 ✓ ≥12 | 12（基準 8） | ✓ |
| 兩人都同意的變好 − 變差 ≥4 | 內容 +5 −3 = +2；最終 +6 −1 = +5 | 內容 ✗／最終 ✓ |
| 原本 ✓ 沒有變差（兩人都同意） | 內容 ✓→△ 3 題（switch-03、benefit-01、offer-03）；最終 ✓→△ 1 題（offer-03） | ✗ |

變差的題目（兩人一致，沒有只有一人判變差的）：
- switch-03（內容 ✓→△）：結論對，但中間寫高鐵「屬於該方案下的指定交易」，和 reference 矛盾。
- benefit-01（內容 ✓→△）：沒寫到事先登錄車號的方式（行遍天下專線／線上）。
- offer-03（內容 ✓→△、最終 ✓→△）：回饋時間答成請款入帳期限，沒答「預計 2027/4/30 前統一回饋」。

變好的題目（內容）：benefit-02 ✗→✓、benefit-03 △→✓、offer-01 △→✓、debit-negate-01 ✗→✓、debit-wrongcard-02 △→✓；最終另有 switch-02、debit-negate-02、debit-wrongcard-01 △→✓（卡別規則不再觸發）。金融卡 8 題內容與最終全 ✓。

probe（`output/rag_opt/probe07/`）：28 題 a 9／b_rank 0／b_trunc 0／c 19（重匯前 a 9／b_trunc 1／c 18）。內容非 ✓ 的 10 題：c 6（switch-01、switch-03、switch-04、benefit-01、offer-03、cross-01）、a 4（rule-01、rule-02、terms-02、cross-02）；基準 c 6、a 5、b_trunc 1。

**Status:** ready-for-human（部分驗收沒達標；照本票規定不回滾，由使用者決定下一步）

## 後續實驗（2026-11-23，使用者同意）

**查詢上限 16k／20k**（`output/rag_opt/run_ctx_limits.sh`，判讀 `judging/ctx{16000,20000}_judge_{A,B}.md`）：內容 ✓ 15／17、最終 ✓ 11／11（12k 是 18／12）；耗時 24.7／25.8 分鐘；wired 峰值都是 24 GB。變差的題目是生成錯誤（benefit-02 保額寫錯、rule-03 日期推算錯），不是撈不到。維持 12k。

**回答附加指示第二版**（`rag_lab/pipeline.py` ANSWER_INSTRUCTIONS：第 3 點改成段首「【卡別｜卡名】」、新增第 5 點子問題逐一回答、第 6 點數字照原文；`output/rag_opt/run_prompt2.sh`，判讀 `judging/prompt2_judge_{A,B}.md`）：內容 ✓ 18（持平）、**最終 ✓ 16**（12k 是 12）。分歧 3 題：benefit-03 兩人最終都 △；rule-01、cross-02 主對話裁定 ✗（rule-01 把 LINE Pay 說成可拿 3.8%、實體卡說有 0.3%，兩種付款方式答錯）。兩人一致的變化：最終 △→✓ 5 題（switch-03、benefit-02、fee-03、offer-01、offer-02），✓→△ 1 題（rule-03 日期又推算錯）；加上裁決 rule-01 △→✗。第 5、6 點看不出效果。採用。

成效網頁：`docs/rag-optimization-eval.html`（產生程式 `output/rag_opt/report/make_report.py`）。
