# 07: 重匯後的 eval、雙判讀與歸因

**What to build:** 在新知識庫上跑 28 題 eval（只跑 mix），兩位判讀者各自判讀並用程式比對，和基準比較；再跑 probe 歸因（spec：「驗收」；grill-notes 決定 1、11）。

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] eval：`eval eval/questions.taishin.jsonl --modes mix`，跑 1 次，開 watchdog。記錄總時間（和基準約 21 分鐘比較，看 4B embedding 讓查詢慢多少）。
- [ ] 檢查每格答案有沒有被長度截斷（rag_lab 不會擋，見 grill-notes「範圍外發現」），有的話算 ✗ 並寫出來。
- [ ] 判讀：照 `output/answer_prompt_01/judge_brief.md` 的判準，兩位判讀者（sonnet）各自判讀，不給基準分數。判讀檔放在 `output/rag_opt/judging/reingest_judge_{A,B}.md`，用 `python3 output/rag_opt/compare_judges.py reingest` 比對。
- [ ] 驗收：內容 ✓ ≥20、最終 ✓ ≥12，兩位判讀者都同意的變好題數減變差題數 ≥4。列出原本 ✓ 但變差的題目。
- [ ] probe：`output/rag_opt/probe28.py` 的 `SOURCE_OVERRIDES` 改成新檔名，對新知識庫重跑，列出 a／b_rank／b_trunc／c 的分布，和基準（c 6、a 5、b_trunc 1）對照。
- [ ] 沒達標時不回滾，結果寫進下方，由使用者決定下一步。
- [ ] 結果寫進下方，並更新記憶。
