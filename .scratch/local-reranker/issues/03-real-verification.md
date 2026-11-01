# 03: 實機驗收

**What to build:** 用真的 bge reranker 對台新知識庫驗證 rerank 的效果、記憶體與查詢時間，並把結果寫進 README。由主對話做，implementer 不執行。標準見 `.scratch/local-reranker/spec.md` 的「實機驗收」。

**Blocked by:** 01, 02

**Status:** resolved

- [x] 使用者在 `.env` 加上三個 `RERANK_*` 欄位，並用帶 `--reranker-model BAAI/bge-reranker-v2-m3` 的指令重啟 8081 server。主對話只用布林或計數方式確認欄位存在，不讀 `.env` 的內容。
- [x] probe（只跑檢索）：11 題（rule-01／02／03、terms-01／02、cross-01／02、switch-02／03、fee-03、offer-01）的關鍵字句不少於 23/33。
- [x] 清掉 LLM 快取的 `:query:` 項目（先備份）後跑完整 eval（20 題 × 5 模式），兩位判讀者獨立判讀：mix 的 ✓ 不少於 7 題；和第二次 eval 比較，原本 ✓ 而這次不是的題目逐題說明。未達標時停下來回報使用者，不放寬標準。
- [x] eval 期間 GPU wired 記憶體峰值低於 22 GB（watchdog 的 sampler log）；超過時停下來回報。
- [x] 記錄每題查詢時間，和第二次 eval 比較。
- [x] README 記錄實測結果（效果、記憶體峰值、查詢時間）。
- [x] 回到台新知識庫的 ticket 09 更新評估結果；不要求它的驗收通過。

## 實機驗收結果（2026-11-01，主對話）

- `.env` 的三個 `RERANK_*` 欄位以 `grep -c` 確認各 1 行，`get_settings` 讀到的位址與模型名稱和 `.env.example` 相同（只看布林值）。8081 以 `--reranker-model BAAI/bge-reranker-v2-m3` 重啟（`output/taishin_full/vlm_server4.log`），`/v1/rerank` 帶 `top_n` 正常回傳。
- probe（rag_lab 自己的 rerank 路徑，mix）：11 題關鍵字句 24/33，標準 23/33，通過。rerank 11 次全成功（`output/reranker_verify/probe_mix.log`）。
- 完整 eval：`eval_results/eval_20261101-205632.md`，100 格失敗 0 格，耗時 1:44:20，rerank 100 次全成功。判讀在 `output/reranker_verify/judgement.md`（兩位判讀者 96/100 格一致，分歧都不在 mix）。
  - mix ✓ 9 題（標準 7 題），通過。和第二次 eval 比：多了 benefit-01、fee-01、fee-02；benefit-03 從 ✓ 變 △，原因是答案把「每次達標可使用 2 次」寫成全年上限 2 次（reference 是 12 次）。
  - 各模式 ✓：naive 8→10、local 2→2、global 4→4、hybrid 1→1、mix 7→9。
- GPU wired 峰值 16 GB（21:41:36），低於 22 GB，通過。
- 查詢時間：平均每格 62.6 秒，第二次 eval 是 56.7 秒（都是總時間除以 100 格）。
- README 第 5 節新增「台新信用卡知識庫：eval 與 reranker」。
- 台新知識庫 ticket 09：mix 仍是 5/7 類通過（約定條款、跨卡比較未通過），已更新該 ticket；spec 不要求它通過。
