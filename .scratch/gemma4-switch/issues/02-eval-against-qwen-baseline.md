# 02: 28 題 eval 與 Qwen 基準對照

**What to build:** 用 Gemma 4 跑 `eval/questions.taishin.jsonl` 的 28 題（只跑 mix），用跟 2026-11-04 相同的方式判讀，跟 Qwen 基準比較內容 ✓；通過才把 README 和 `.env.example` 的預設模型改成 Gemma 4（spec：`.scratch/gemma4-switch/spec.md`「對照與驗收」「通過之後」，grill Q9–Q12）。

**Blocked by:** 01

**Status:** resolved

- [x] 備份 `WORKING_DIR` 的 `kv_store_llm_response_cache.json`，再刪掉 key 含 `:query:` 的項目，記下刪了幾筆。
- [x] 照 01 確認過的 server 參數重啟 server，開 watchdog（門檻 22 GB），跑 `eval eval/questions.taishin.jsonl --modes mix`。記錄耗時、wired 峰值、成功格數。
- [x] 判讀：兩位判讀者各自評分再比對分歧，主對話裁決；判準與卡別規則照 `.scratch/debit-card/spec.md` 和 debit-card ticket 05。判讀者只拿題目、reference、答案和判準，不拿 Qwen 的分數。
- [x] 對照表：28 題逐題列出 Qwen（`output/debit05/judgement.md`）和 Gemma 的內容分數與最終分數，加上兩邊的 ✓ 總數。
- [x] 驗收：Gemma 的內容 ✓ > 8（Qwen 基準），且 eval 全程沒有 OOM、沒有觸發 watchdog。最終 ✓ 一起列出，但不拿來判定。
- [x] 通過：README 第 3 節啟動指令與 `.env.example` 的預設模型改成 Gemma 4，Qwen 的啟動方式留一小段當退路。
- [ ] （不適用）沒通過：寫明差多少，README 和 `.env.example` 不改，`.env` 換回 Qwen，由使用者決定下一步。
- [x] 記錄檔放在 `output/gemma4_02/`（gitignore），結果寫進下方。

## 結果（2026-11-11）：通過

記錄檔在 `output/gemma4_02/`（gitignore）：結果檔 `eval_20261111-230359.md`（`eval_results/` 也有一份）、eval log、server log、watchdog、判讀 `judge_a.md`／`judge_b.md`、裁決 `judgement.md`、對照 `comparison.md`、快取備份 `kv_store_llm_response_cache.before.json`。

### 快取
- 刪掉 key 含 `:query:` 的 32 筆。
- 另外刪掉 28 題的 `mix:keywords:` 28 筆（spec 沒寫，開跑前使用者決定）：保留的話 Gemma 會用 Qwen 抽的關鍵字檢索，比較的就只剩產生答案這一步。

### eval（事實）
- 2026-11-11 23:03:58～23:25:12，21 分 14 秒，28 格都成功、失敗 0。
- `iogpu.wired_limit_mb=26000`，watchdog 門檻 27 GB、每 3 秒取樣；全系統 wired 峰值 22 GB，沒有觸發。
- 每題約 40–45 秒；產生答案的 prompt 約 10.7k–11.2k token。

### 判讀
- 兩位判讀者（各自判讀，沒有拿到 Qwen 的分數）內容分數 28 題一致。卡別規則觸發有 2 題分歧：rule-03 裁決不觸發（最終 ✓），debit-fact-01 裁決觸發（最終 △）。理由見 `output/gemma4_02/judgement.md`。
- ASSUMPTION：✓／△／✗ 的文字定義是主對話依 2026-11-04 判讀紀錄整理後寫進判讀說明的，舊紀錄沒有成文定義。

| | Qwen 內容 ✓ | Gemma 內容 ✓ | Qwen 最終 ✓ | Gemma 最終 ✓ |
|---|---|---|---|---|
| 信用卡 20 題 | 4 | 11 | 0 | 3 |
| 金融卡 8 題 | 4 | 4 | 2 | 3 |
| 合計 | 8 | 15 | 2 | 6 |

- 內容 ✓ 新增 7 題：switch-02、benefit-01、benefit-03、rule-03、fee-01、terms-01、offer-03；沒有題目從 ✓ 掉下來。
- 內容分數變差 1 題：debit-negate-01 △ → ✗（沒有回答「沒有」，改列信用卡的機場接送權益）。

逐題：

| id | Qwen 內容 | Gemma 內容 | Qwen 最終 | Gemma 最終 |
|---|---|---|---|---|
| switch-01 | △ | △ | △ | △ |
| switch-02 | △ | ✓ | △ | △ |
| switch-03 | △ | △ | △ | △ |
| switch-04 | △ | △ | △ | △ |
| benefit-01 | △ | ✓ | △ | △ |
| benefit-02 | △ | △ | △ | △ |
| benefit-03 | △ | ✓ | △ | △ |
| rule-01 | ✗ | ✗ | ✗ | ✗ |
| rule-02 | △ | △ | △ | △ |
| rule-03 | △ | ✓ | △ | ✓ |
| fee-01 | △ | ✓ | △ | △ |
| fee-02 | ✓ | ✓ | △ | ✓ |
| fee-03 | ✓ | ✓ | △ | △ |
| terms-01 | △ | ✓ | △ | △ |
| terms-02 | ✗ | △ | ✗ | △ |
| offer-01 | ✓ | ✓ | △ | △ |
| offer-02 | ✓ | ✓ | △ | △ |
| offer-03 | △ | ✓ | △ | ✓ |
| cross-01 | ✗ | △ | ✗ | △ |
| cross-02 | ✗ | ✗ | ✗ | ✗ |
| debit-confuse-01 | ✗ | △ | ✗ | △ |
| debit-confuse-02 | ✓ | ✓ | △ | ✓ |
| debit-fact-01 | ✓ | ✓ | △ | △ |
| debit-fact-02 | ✓ | ✓ | ✓ | ✓ |
| debit-negate-01 | △ | ✗ | △ | ✗ |
| debit-negate-02 | ✓ | ✓ | ✓ | ✓ |
| debit-wrongcard-01 | ✗ | △ | ✗ | △ |
| debit-wrongcard-02 | ✗ | ✗ | ✗ | ✗ |

### 驗收
- 內容 ✓ 15 > 8，eval 全程沒有 OOM、沒有觸發 watchdog：**通過**。
- README 第 3 節改成 Gemma 4 的啟動方式（含 `iogpu.wired_limit_mb` 設定、已知限制、品質數字），Qwen 的啟動方式留在同一節當退路；`.env.example` 的 `LLM_BASE_URL`、`LLM_MODEL`、`VLM_MODEL` 改成 Gemma 4。
- 本機 `.env` 已是 Gemma 4 的設定（Qwen 版備份 `output/gemma4_01/env.qwen.bak`）。

### 範圍外，記下不處理
- `query --vlm-enhanced` 在 26B 上超過 27 GB 門檻（ticket 01）。
- 用 Gemma 4 匯入（ingest）沒有實測；README 第 4 節「從頭重建」與第 5 節的歷史紀錄仍寫兩個 server（Qwen 時期），沒有改。
- 要不要用 Gemma 4 重新抽取圖譜，由使用者另外決定（spec Out of Scope）。
