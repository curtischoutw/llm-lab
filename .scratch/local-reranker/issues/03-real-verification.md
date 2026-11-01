# 03: 實機驗收

**What to build:** 用真的 bge reranker 對台新知識庫驗證 rerank 的效果、記憶體與查詢時間，並把結果寫進 README。由主對話做，implementer 不執行。標準見 `.scratch/local-reranker/spec.md` 的「實機驗收」。

**Blocked by:** 01, 02

**Status:** ready-for-human

- [ ] 使用者在 `.env` 加上三個 `RERANK_*` 欄位，並用帶 `--reranker-model BAAI/bge-reranker-v2-m3` 的指令重啟 8081 server。主對話只用布林或計數方式確認欄位存在，不讀 `.env` 的內容。
- [ ] probe（只跑檢索）：11 題（rule-01／02／03、terms-01／02、cross-01／02、switch-02／03、fee-03、offer-01）的關鍵字句不少於 23/33。
- [ ] 清掉 LLM 快取的 `:query:` 項目（先備份）後跑完整 eval（20 題 × 5 模式），兩位判讀者獨立判讀：mix 的 ✓ 不少於 7 題；和第二次 eval 比較，原本 ✓ 而這次不是的題目逐題說明。未達標時停下來回報使用者，不放寬標準。
- [ ] eval 期間 GPU wired 記憶體峰值低於 22 GB（watchdog 的 sampler log）；超過時停下來回報。
- [ ] 記錄每題查詢時間，和第二次 eval 比較。
- [ ] README 記錄實測結果（效果、記憶體峰值、查詢時間）。
- [ ] 回到台新知識庫的 ticket 09 更新評估結果；不要求它的驗收通過。
