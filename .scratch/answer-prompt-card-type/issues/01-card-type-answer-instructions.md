# 01: 回答時要求分清楚信用卡與金融卡

**What to build:** 每次查詢產生答案時，在 LightRAG 的回答提示詞裡加上「先分清楚卡別」的附加指示（`QueryParam.user_prompt`，LightRAG `rag_response` 的第 6 點 Additional Instructions），所有查詢入口一律套用；eval 結果檔表頭記下這段指示。用 Gemma 4 重跑 28 題，和 gemma4-switch ticket 02 的結果比較。

依據：`docs/gemma4-vs-qwen-eval.html` 的結論與建議第 1 步；金融卡題的錯誤多半是模型接受問題裡錯的卡別、拿另一種卡的資料回答，或兩種卡的數字合成一個。

**Blocked by:** 無

**Status:** ready-for-agent

## 使用者決定（2026-11-12）

- 套用範圍：`query`、`query --vlm-enhanced`、`eval`、Python API 一律套用，沒有開關（和 rerank 相同）。
- 指示寫在程式裡（不放 `.env`）；eval 結果檔表頭記下全文，之後改版本可以比較。
- 不另寫 spec，一張 ticket，開 branch 用 TDD 做。

## 驗收

- [ ] 所有查詢入口送出的答案請求都含這段指示（測試：CLI `query` 各模式、`--vlm-enhanced`、`eval`、Python API 的 query 與 evaluate）。
- [ ] eval 結果檔表頭有「回答附加指示」一行，內容是指示全文（換行改成空格，不破壞 Markdown）。
- [ ] 現有測試全綠。
- [ ] README 說明這段指示、套用範圍，以及 LightRAG 答案快取的 key 含 `user_prompt`（改指示後不會命中舊答案）。
- [ ] 實機：Gemma 4 跑 `eval eval/questions.taishin.jsonl --modes mix`，兩位判讀者各自判讀、主對話裁決，和 gemma4-switch ticket 02（內容 ✓ 14：信用卡 10、金融卡 4；最終 ✓ 6）逐題比較。
- [ ] 通過標準：金融卡 8 題的內容 ✓ 比 4 多，且信用卡 20 題的內容 ✓ 最多比 10 少 1 題。沒通過時寫明差多少，由使用者決定要不要保留。

## 結果

（待填）
