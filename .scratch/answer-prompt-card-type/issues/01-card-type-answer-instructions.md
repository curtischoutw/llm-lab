# 01: 回答時要求分清楚信用卡與金融卡

**What to build:** 每次查詢產生答案時，在 LightRAG 的回答提示詞裡加上「先分清楚卡別」的附加指示（`QueryParam.user_prompt`，LightRAG `rag_response` 的第 6 點 Additional Instructions），所有查詢入口一律套用；eval 結果檔表頭記下這段指示。用 Gemma 4 重跑 28 題，和 gemma4-switch ticket 02 的結果比較。

依據：`docs/gemma4-vs-qwen-eval.html` 的結論與建議第 1 步；金融卡題的錯誤多半是模型接受問題裡錯的卡別、拿另一種卡的資料回答，或兩種卡的數字合成一個。

**Blocked by:** 無

**Status:** resolved

## 使用者決定（2026-11-12）

- 套用範圍：`query`、`query --vlm-enhanced`、`eval`、Python API 一律套用，沒有開關（和 rerank 相同）。
- 指示寫在程式裡（不放 `.env`）；eval 結果檔表頭記下全文，之後改版本可以比較。
- 不另寫 spec，一張 ticket，開 branch 用 TDD 做。

## 驗收

- [x] 所有查詢入口送出的答案請求都含這段指示（測試：CLI `query` 各模式、`--vlm-enhanced`、`eval`、Python API 的 query 與 evaluate）。
- [x] eval 結果檔表頭有「回答附加指示」一行，內容是指示全文（換行改成空格，不破壞 Markdown）。
- [x] 現有測試全綠。
- [x] README 說明這段指示、套用範圍，以及 LightRAG 答案快取的 key 含 `user_prompt`（改指示後不會命中舊答案）。
- [x] 實機：Gemma 4 跑 `eval eval/questions.taishin.jsonl --modes mix`，兩位判讀者各自判讀、主對話裁決，和 gemma4-switch ticket 02（內容 ✓ 14：信用卡 10、金融卡 4；最終 ✓ 6）逐題比較。
- [x] 通過標準：金融卡 8 題的內容 ✓ 比 4 多，且信用卡 20 題的內容 ✓ 最多比 10 少 1 題。沒通過時寫明差多少，由使用者決定要不要保留。

## 結果（2026-11-12）：通過

記錄檔在 `output/answer_prompt_01/`（gitignore）：結果檔 `eval_20261112-004153.md`（`eval_results/` 也有一份）、eval log、server log、watchdog、判讀說明 `judge_brief.md`、判讀 `judge_a.md`／`judge_b.md`、裁決 `judgement.md`、對照 `comparison.md`；完整測試 log `output/answer_prompt_unittest.log`。

### 實作與測試
- `rag_lab/pipeline.py`：`ANSWER_INSTRUCTIONS`，`query_kwargs` 加 `user_prompt`；`rag_lab/__main__.py`：eval 表頭另列「回答附加指示」一行（換行改空格），固定查詢設定不列 `user_prompt`。
- 紅燈：CLI `query` 5 種模式＋`--vlm-enhanced` 6 個情境紅（`Additional Instructions: n/a`）；實作後綠。Python API 與 eval 的測試寫在實作之後，用 `git stash` 拿掉實作確認 5 個情境紅、還原後綠。
- 完整測試：`Ran 285 tests in 1245.676s`、`OK`。

### eval（事實）
- 2026-11-12 00:41:52～01:02:02，20 分 10 秒，28 格都成功、失敗 0。`iogpu.wired_limit_mb=26000`，watchdog 27 GB／3 秒，wired 峰值 22 GB，沒有觸發。
- 查詢關鍵字沿用 gemma4_02 寫進快取的 Gemma 關鍵字（第一個請求就是答案請求，沒有關鍵字抽取），所以檢索條件相同，唯一變因是回答附加指示。
- 結果檔表頭有「回答附加指示」全文。

### 判讀
- A、B 4 題分歧（內容分數 cross-02、debit-negate-01；卡別規則 rule-02、debit-wrongcard-01），裁決見 `output/answer_prompt_01/judgement.md`。

| | 加指示前 內容 ✓ | 加指示後 內容 ✓ | 加指示前 最終 ✓ | 加指示後 最終 ✓ |
|---|---|---|---|---|
| 信用卡 20 題 | 10 | 10 | 3 | 4 |
| 金融卡 8 題 | 4 | 6 | 3 | 4 |
| 合計 | 14 | 16 | 6 | 8 |

- 金融卡：debit-wrongcard-01 ✗ → ✓（指出 0.5% 是簽帳金融卡、Richart 信用卡是 0.3%）、debit-confuse-01 △ → ✓（信用卡 200 元、簽帳金融卡 100 元）、debit-wrongcard-02 ✗ → △。debit-negate-01 仍是 ✗（改說這張卡不存在）。
- 信用卡：內容 ✓ 進 2 題（switch-03、benefit-01）、出 2 題（benefit-03、offer-01），benefit-02、terms-02 從 △ 變 ✗；rule-01、cross-01 從 ✗ 變 △。變差的題目錯在數字（保額 1,000 萬、門檻 1,303 元）或答「資料沒有」，和卡別無關；是指示造成還是每次生成的差異，沒有量（每個設定只跑一次）。
- 卡別規則觸發題數：20 → 16。

逐題：

| id | 加指示前 內容 | 加指示後 內容 | 加指示前 最終 | 加指示後 最終 |
|---|---|---|---|---|
| switch-01 | △ | △ | △ | △ |
| switch-02 | ✓ | ✓ | △ | △ |
| switch-03 | △ | ✓ | △ | △ |
| switch-04 | △ | △ | △ | △ |
| benefit-01 | △ | ✓ | △ | △ |
| benefit-02 | △ | ✗ | △ | ✗ |
| benefit-03 | ✓ | △ | △ | △ |
| rule-01 | ✗ | △ | ✗ | △ |
| rule-02 | △ | △ | △ | △ |
| rule-03 | ✓ | ✓ | ✓ | ✓ |
| fee-01 | ✓ | ✓ | △ | △ |
| fee-02 | ✓ | ✓ | ✓ | ✓ |
| fee-03 | ✓ | ✓ | △ | △ |
| terms-01 | ✓ | ✓ | △ | ✓ |
| terms-02 | △ | ✗ | △ | ✗ |
| offer-01 | ✓ | △ | △ | △ |
| offer-02 | ✓ | ✓ | △ | △ |
| offer-03 | ✓ | ✓ | ✓ | ✓ |
| cross-01 | ✗ | △ | ✗ | △ |
| cross-02 | ✗ | ✗ | ✗ | ✗ |
| debit-confuse-01 | △ | ✓ | △ | ✓ |
| debit-confuse-02 | ✓ | ✓ | ✓ | ✓ |
| debit-fact-01 | ✓ | ✓ | △ | ✓ |
| debit-fact-02 | ✓ | ✓ | ✓ | ✓ |
| debit-negate-01 | ✗ | ✗ | ✗ | ✗ |
| debit-negate-02 | ✓ | ✓ | ✓ | △ |
| debit-wrongcard-01 | ✗ | ✓ | ✗ | △ |
| debit-wrongcard-02 | ✗ | △ | ✗ | △ |

### 驗收
- 金融卡內容 ✓ 6 > 4，信用卡內容 ✓ 10（≥ 9）：**通過**。
