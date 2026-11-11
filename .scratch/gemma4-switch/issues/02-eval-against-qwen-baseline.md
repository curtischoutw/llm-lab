# 02: 28 題 eval 與 Qwen 基準對照

**What to build:** 用 Gemma 4 跑 `eval/questions.taishin.jsonl` 的 28 題（只跑 mix），用跟 2026-11-04 相同的方式判讀，跟 Qwen 基準比較內容 ✓；通過才把 README 和 `.env.example` 的預設模型改成 Gemma 4（spec：`.scratch/gemma4-switch/spec.md`「對照與驗收」「通過之後」，grill Q9–Q12）。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 備份 `WORKING_DIR` 的 `kv_store_llm_response_cache.json`，再刪掉 key 含 `:query:` 的項目，記下刪了幾筆。
- [ ] 照 01 確認過的 server 參數重啟 server，開 watchdog（門檻 22 GB），跑 `eval eval/questions.taishin.jsonl --modes mix`。記錄耗時、wired 峰值、成功格數。
- [ ] 判讀：兩位判讀者各自評分再比對分歧，主對話裁決；判準與卡別規則照 `.scratch/debit-card/spec.md` 和 debit-card ticket 05。判讀者只拿題目、reference、答案和判準，不拿 Qwen 的分數。
- [ ] 對照表：28 題逐題列出 Qwen（`output/debit05/judgement.md`）和 Gemma 的內容分數與最終分數，加上兩邊的 ✓ 總數。
- [ ] 驗收：Gemma 的內容 ✓ > 8（Qwen 基準），且 eval 全程沒有 OOM、沒有觸發 watchdog。最終 ✓ 一起列出，但不拿來判定。
- [ ] 通過：README 第 3 節啟動指令與 `.env.example` 的預設模型改成 Gemma 4，Qwen 的啟動方式留一小段當退路。
- [ ] 沒通過：寫明差多少，README 和 `.env.example` 不改，`.env` 換回 Qwen，由使用者決定下一步。
- [ ] 記錄檔放在 `output/gemma4_02/`（gitignore），結果寫進下方。

## 結果

（待填）
