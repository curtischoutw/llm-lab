# LLM 與 VLM 換成 Gemma 4 26B A4B

**Status:** ready-for-agent

## Problem Statement

目前的 LLM（`mlx-community/Qwen3-4B-Instruct-2507-4bit`）和 VLM（`mlx-community/Qwen3-VL-4B-Instruct-4bit`）都是 4B 等級，低於 LightRAG 文件建議的 32B。台新知識庫 28 題 eval（2026-11-04，Qwen，匯入金融卡後）在 mix 模式下只有內容 ✓ 8 題、最終 ✓ 2 題。使用者想知道換成較大的 Gemma 4 能不能提升回答品質，並且讓它在 32 GB 的 M2 Pro 上跑得起來。

## Solution

用一顆 `mlx-community/gemma-4-26b-a4b-it-4bit` 同時當 LLM 和 VLM（Gemma 4 每個尺寸都能看圖），由 `mlx_vlm.server` 一起提供，不再另開 `mlx_lm.server`。embedding 和 reranker 不動，知識庫不重建。分兩步：先確認 26B 在預設 GPU 記憶體上限下跑得起來，再用同一份知識庫跑 28 題，跟 Qwen 的結果比較。

## User Stories

1. As a 使用者, I want LLM 和 VLM 用同一顆 Gemma 4 26B A4B, so that 記憶體只需要放一份權重，放得下比 4B 大的模型。
2. As a 使用者, I want embedding（Qwen3-Embedding-0.6B，1024 維）和 reranker（bge-reranker-v2-m3）不動, so that 不用重建 324 份文件的知識庫。
3. As a 使用者, I want Gemma 4 的 thinking 模式關掉, so that 輸出 token 不會被推理過程吃掉，也符合 LightRAG 建圖不建議用推理模型的說明。
4. As a 使用者, I want 先在預設 GPU 記憶體上限下量 26B 的記憶體峰值, so that 撞到上限時知道差多少，再由我決定要不要調 `iogpu.wired_limit_mb`。
5. As a 使用者, I want 用 26B 跑跟 2026-11-04 相同的 28 題 mix eval，判讀方式相同, so that 新舊模型可以直接比較。
6. As a 使用者, I want 通過驗收才把 README 和 `.env.example` 的預設模型改成 Gemma, so that 沒通過時文件仍描述在用的設定。

## Implementation Decisions

### 模型與 server（grill Q1–Q3、Q6）

- LLM 與 VLM：`mlx-community/gemma-4-26b-a4b-it-4bit`（第三方頁面列的大小約 15.3 GB；model card 沒有直接查看過）。
- 一個 `mlx_vlm.server`（經 `scripts/vlm_server.py`）同時載入 Gemma 4、embedding 和 reranker；`.env` 的 `LLM_BASE_URL` 和 `VLM_BASE_URL` 指向同一個 port，`LLM_MODEL` 和 `VLM_MODEL` 都填 Gemma 4。
- 本機 mlx-vlm 0.7.10 的套件內有 `gemma4` 模型目錄；實際能不能載入由 ticket 01 確認。
- `mlx_lm.server` 現有的 `--max-tokens 4096`、`--prompt-cache-bytes 4GB` 在 `mlx_vlm.server` 上的對應設定由 ticket 01 查明；沒有對應的要記下來。
- thinking 關閉。關閉的方式（chat template 參數、server 選項或 request 欄位）由 ticket 01 查明，並以實際回應確認沒有推理內容。
- 不動：`EMBED_MODEL`、`EMBED_DIM`、`RERANK_MODEL`、`LLM_MAX_ASYNC=1`、`LLM_MAX_TOKENS=4096`、`VLM_MAX_TOKENS=1024`。

### 記憶體（grill Q5）

- 機器：M2 Pro、32 GB，`iogpu.wired_limit_mb=0`（系統預設）。
- 估算：Gemma 4 權重約 15.3 GB，加 embedding 約 0.7 GB、reranker 約 2.1 GB，合計約 18 GB，剩給 KV cache 的空間不多。Qwen 4B 在 2026-11-04 就曾經在 wired 22 GB 時被 watchdog 停掉。
- 先用預設上限跑，watchdog 門檻 22 GB（和之前相同）。OOM 或觸發 watchdog 就停下來回報給使用者，不自動調 `iogpu.wired_limit_mb`。

### 查詢條件（grill Q8）

- `QUERY_MAX_TOTAL_TOKENS` 維持 12000，跟 Qwen 的條件相同。

### 對照與驗收（grill Q9–Q11）

- 題目：`eval/questions.taishin.jsonl` 的 28 題（第 21–28 行是金融卡題），只跑 mix（`--modes mix`）。
- Qwen 基準沿用 2026-11-04 匯入後的 eval，不重跑：`output/debit05/eval_after/eval_20261104-074606.md`，判讀在 `output/debit05/judge_after_a.md`、`judge_after_b.md`、`judgement.md`。使用者確認之後知識庫沒有變動。
- **跑 Gemma 之前要先從 `WORKING_DIR` 的 `kv_store_llm_response_cache.json` 刪掉 key 含 `:query:` 的項目**；快取 key 不含 `LLM_MODEL`，不刪的話 28 題會直接拿到 Qwen 的答案。刪之前先備份這個檔案。
- 判讀方式和 debit-card ticket 05 相同：兩位判讀者各自評分再比對分歧，主對話裁決；內容分數只比對 reference 的核心事實；卡別規則（答案講權益或費用卻沒說是哪一種卡片時最多 △）照用。
- 主指標是內容 ✓：Gemma 要大於 8 題，而且 eval 全程沒有 OOM、沒有觸發 watchdog。最終 ✓（Qwen 2 題）也列出來，但不拿來判定。

### 通過之後（grill Q12）

- 通過：README 第 3 節的啟動指令與 `.env.example` 的預設模型改成 Gemma 4，Qwen 的啟動方式留一小段當退路。
- 沒通過：README 和 `.env.example` 不改，結果寫進 ticket，`.env` 換回 Qwen。

## Testing Decisions

- 這份 spec 只改設定和文件，不改 `rag_lab/` 的程式碼，不新增自動測試。如果 ticket 01 發現必須改程式碼（例如 thinking 要從 request 關掉），先停下來回報，另行決定。
- 驗收靠實機量測：ticket 01 的記憶體峰值和 thinking 檢查，ticket 02 的 eval 與判讀。

## Out of Scope

- 用 Gemma 4 重新抽取圖譜（重新 ingest）：等這份 spec 的結果出來再決定（grill Q7）。
- 換 embedding（例如 EmbeddingGemma 2，768 維，要重建知識庫）、換 reranker。
- 調高 `QUERY_MAX_TOTAL_TOKENS`。
- 試 thinking 模式、31B 或其他尺寸。
- 主動調高 `iogpu.wired_limit_mb`（只有使用者同意後才做）。

## Further Notes

- LightRAG 1.4.16 文件建議 LLM 至少 32B；26B A4B 仍低於這個建議（README:513）。
- 26B A4B 是 MoE，每個 token 約 4B 參數參與運算，生成速度預期接近目前的 4B，但這是推估，沒有實測。
