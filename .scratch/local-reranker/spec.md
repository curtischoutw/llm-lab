Status: ready-for-agent

# Spec：查詢時用本機 reranker 重新排序候選 chunk

## Problem Statement

使用者用 mix 模式問台新信用卡知識庫，部分題目答錯或只答對一半。原因之一是送給 LLM 的 context 被不相關的 chunk 占掉：

- 第二次 eval（entity／relation 上限 500／500）中，mix 模式的 context 大量來自優惠活動文件。只跑檢索時，11 題的 context 裡有 42 個 chunk 來自活動頁。
- LightRAG 是依向量相似度和圖譜關聯挑出候選 chunk，排序沒有直接比較「這個 chunk 和問題有多相關」。候選數多於 token 上限放得下的數量時，排在前面的未必是答案需要的。
- LightRAG 支援在截斷前用 reranker 重新排序候選 chunk，但專案目前完全沒有啟用（所有查詢都關掉 rerank）。
- 外部的 rerank API（Cohere、Jina、阿里雲）會把知識庫內容送出本機，而台新的資料只能留在本機，所以不能用。

## Solution

查詢時，用本機的 reranker 模型重新排序 LightRAG 交出來的候選 chunk，再依 token 上限截斷：

- reranker 由現有的 VLM／embedding server 提供。這個 server 本身就有 rerank endpoint，啟動時多指定一個 reranker 模型即可，不新增第三方套件，也不多開程序。
- 模型用 `BAAI/bge-reranker-v2-m3`。
- 所有查詢入口（CLI 的 `query`、`eval`，Python API，VLM 增強查詢）一律開 rerank。
- rerank 失敗時，查詢直接失敗並說明原因，不會在使用者不知道的情況下退回原本的排序。

開工前的實驗（2026-11-01）：
- 用 bge 對 13 題重跑 mix 答案，✓ 從 4 題增加到 6 題，沒有題目變差。
- 只跑檢索時，11 題的關鍵字句從 23/33 增加到 24/33，context 裡活動頁的 chunk 從 42 個減少到 15 個。
- GPU wired 記憶體峰值 21 GB（不開 rerank 時是 19 GB），watchdog 門檻 22 GB。

## User Stories

1. 身為使用者，我想讓查詢時的候選 chunk 依和問題的相關程度重新排序，這樣 context 才會放進答案需要的段落，而不是排在前面的活動頁。
2. 身為使用者，我想讓 reranker 在本機執行，這樣知識庫的內容不會送到任何外部服務。
3. 身為使用者，我想讓 reranker 由現有的 VLM／embedding server 提供，這樣我不用多管理一個程序。
4. 身為使用者，我想讓 server 啟動時就載入 reranker，這樣第一次查詢不會因為載入模型而變慢，記憶體用量也從一開始就固定。
5. 身為使用者，我想在 README 的 server 啟動指令裡看到 reranker 參數，這樣照著文件啟動就能直接查詢。
6. 身為使用者，我想用 `.env` 的三個欄位設定 reranker 的位址、模型名稱與 API key，寫法和現有的 LLM、VLM、embedding 欄位一致。
7. 身為使用者，我想讓這三個欄位是必填，缺漏或格式錯誤時 CLI 在啟動時就中止並指出是哪個欄位，這樣不會跑到一半才發現。
8. 身為使用者，我想讓 `.env.example` 列出這三個欄位與建議值，這樣我知道要加什麼。
9. 身為使用者，我想讓 CLI 的 `query` 一律使用 rerank，這樣我不用記得加參數。
10. 身為使用者，我想讓 `eval` 也使用 rerank，這樣評估結果反映我實際使用時的設定。
11. 身為使用者，我想讓 Python API（`Session.query`、`pipeline.query`、`evaluate`）也使用 rerank，這樣用程式呼叫和用 CLI 得到一樣的結果。
12. 身為使用者，我想讓 VLM 增強查詢也使用 rerank，這樣不同查詢入口的檢索行為一致。
13. 身為使用者，當 reranker 沒有回應、回傳錯誤或格式不對時，我想讓查詢失敗並看到原因，而不是拿到一個沒有經過 rerank 的答案卻以為有。
14. 身為使用者，我想讓錯誤訊息指出是 rerank 失敗，並包含 endpoint 回報的錯誤內容，但不包含 API key，這樣我能判斷是 server 沒開、模型沒載入，還是請求有問題。
15. 身為使用者，我想讓 `eval` 在某一格 rerank 失敗時，把那一格記成失敗，和現有的查詢失敗處理方式一樣，這樣對照表不會混進沒有 rerank 的答案。
16. 身為使用者，我想讓 eval 對照表的表頭寫出 reranker 模型名稱，這樣之後比較不同次的 eval 時，知道當時用了哪個模型。
17. 身為使用者，我想讓匯入流程不受 reranker 影響，這樣這個功能不會改變已建好的知識庫。
18. 身為使用者，我想讓候選 chunk 數（chunk_top_k）與分數門檻維持 LightRAG 的預設值，這樣第一版不用調更多設定。
19. 身為使用者，我想在 README 看到 reranker 的實測效果、記憶體峰值與每題查詢時間，這樣我知道它換到了什麼、付出了什麼。
20. 身為使用者，我想在架構文件看到 rerank 在查詢流程裡的位置，以及失敗時怎麼處理，這樣之後改查詢流程的人知道有這一層。
21. 身為維護者，我想讓測試用假 server 的 rerank endpoint 驗證 rerank 結果真的影響送給 LLM 的 context 順序，這樣不必啟動真的模型也能確認功能接上了。
22. 身為維護者，我想讓測試涵蓋 rerank endpoint 回錯誤時查詢會失敗，這樣之後升級 LightRAG 時，若它改變吞例外的行為，測試會抓到。
23. 身為維護者，我想讓實機驗收用和 ticket 09 相同的雙判讀方式，這樣結果能和前兩次 eval 直接比較。
24. 身為維護者，我想在實機驗收時確認 GPU 記憶體峰值低於 watchdog 門檻，這樣多載入一個模型不會讓 server 被 watchdog 關掉。

## Implementation Decisions

**reranker 的位置與模型**
- 由現有的 mlx-vlm server（port 8081，0.7.10）提供，用它內建的 `/v1/rerank` endpoint。
  - 回應格式是 `results` 陣列，每項有 `index` 與 `relevance_score`，和 LightRAG 的 Jina／Cohere 標準格式相同。
- server 啟動時用 `--reranker-model` 預先載入模型。
  - mlx-vlm 把 reranker 放在獨立的快取群組，和 VLM、embedding 模型同時存在。
- 模型：`BAAI/bge-reranker-v2-m3`，F32，權重檔約 2.1 GB，model_type 是 xlm-roberta 序列分類。
- 不新增第三方套件。

**設定**
- 新增 `RERANK_BASE_URL`、`RERANK_MODEL`、`RERANK_API_KEY` 三個必填欄位，驗證規則沿用現有的 `*_BASE_URL`、`*_MODEL`、`*_API_KEY`。
- 不新增 rerank 開關。chunk_top_k 維持 LightRAG 預設 20，min_rerank_score 維持 0，不設 instruction。
  - LightRAG 也能用環境變數 `CHUNK_TOP_K`、`MIN_RERANK_SCORE` 改這兩個預設值；rag_lab 不讀也不設定它們，`.env.example` 也不列。
- eval 對照表表頭的模型名稱取自 `RERANK_MODEL` 的設定值。

**接上 LightRAG**
- rag_lab 提供一個 rerank 函式，用設定的位址、模型與 API key 呼叫 rerank endpoint，回傳 LightRAG 要的 index＋分數格式。可以沿用 LightRAG 內建的通用 rerank 函式來送請求。
- rerank 函式必須在建立 LightRAG 實例時傳入。
  - mix 等圖譜模式處理 chunk 時，讀的是儲存層在初始化時拿到的設定副本；初始化之後才改 rerank 函式不會生效。這點在 LightRAG 1.4.16 實測過。
- 所有查詢都把 enable_rerank 設為開啟。目前查詢參數的組裝集中在一處，改那裡即可。
  - 程式說明文字裡寫著「不開 rerank」的地方要一起更新。

**失敗處理**
- LightRAG 在 rerank 發生例外時會記錄錯誤、改用原本的排序，查詢照常成功。
- LightRAG 在兩種情況下也會不報錯、改用原本的排序：rerank 回傳空結果，以及回傳的 index 超出範圍。
- rag_lab 不接受這些行為：
  - rerank 函式要把以下情況都記成失敗：請求例外、HTTP 錯誤、回傳空結果、index 超出範圍。
  - 查詢結束後只要有失敗，就讓該次查詢以查詢失敗的錯誤結束，訊息包含 endpoint 回報的錯誤，不含 API key。
  - 失敗只算在發生當下的那一次查詢，不會帶到下一次查詢（eval 連續查 100 格時也一樣）。
  - 候選 chunk 有空白內容時，mlx-vlm 會回 400，這也算 rerank 失敗。
- 做法比照 ticket 12 處理 RAG-Anything 吞掉多模態寫入失敗的方式：在 rag_lab 這一層記錄、在結果層判定。
- `eval` 照現有的單格失敗處理，記成失敗格。

**文件**
- README：
  - server 啟動指令加上 reranker 參數；
  - 設定說明加上三個欄位；
  - 記錄實機驗收結果：記憶體峰值、每題查詢時間、eval 比較。
- `.env.example`：三個欄位與建議值。
- 架構文件：查詢流程補上 rerank 這一步與失敗處理。
- eval 對照表的「固定查詢設定」加上 reranker 模型名稱。

## Testing Decisions

**好測試的標準**
- 只透過公開入口觀察外部行為：CLI 子行程的結束碼與輸出、Python API 的回傳值與例外、假 server 記錄到的請求。
- 不測 rag_lab 內部函式。

**測試縫**（沿用既有的兩個，使用者已在 grill 的 Q5 確認）
- CLI 子行程縫：`query`、`eval`、`query --vlm-enhanced`。
- Python API 縫：`pipeline.query`、`pipeline.evaluate`、`Session.query`、`Session.evaluate`。

**假 server 擴充**
- 現有的假 OpenAI server 新增 `/v1/rerank`。
- 它要記錄收到的請求（query、documents、model、Authorization 標頭），並依測試指定的規則回傳順序，例如把某段文字排到最前面或最後面。
- 也要能讓測試指定回傳 HTTP 500。

**要驗的行為**
1. 查詢時會呼叫 rerank endpoint，請求帶設定的模型名稱與 API key，documents 是候選 chunk 的內容。
2. rerank 的順序會反映在答案請求的 prompt 裡。
   - 例：假 server 把某個 chunk 排到最後；token 上限設得只放得下前幾個 chunk 時，該 chunk 不會出現在 prompt 裡。
   - 反過來排序時，它就會出現。
   - QueryParam 本身觀察不到，所以用最高的縫觀察到的行為驗證，和 ticket 13 的做法相同。
3. rerank endpoint 回 500 時，`query` 以查詢失敗的結束碼結束，Python API 拋出查詢失敗的例外，`eval` 把該格記成失敗。訊息不含 API key。
4. 三個新欄位任一缺漏或格式錯誤時，CLI 在啟動時中止，結束碼與既有的設定錯誤相同。
5. `.env.example` 的欄位與設定欄位一致（既有測試要跟著通過）。
6. eval 對照表表頭包含 reranker 模型名稱。
7. 匯入不呼叫 rerank endpoint。

**可參考的既有測試**
- ticket 13 的查詢 token 上限測試（`QueryKnowledgeGraphBudgetTest`、`EvalQueryBudgetTest`、Python API 的 `QueryBudgetTest`）：用假 server 記錄的 prompt 驗證送進 LightRAG 的參數。
- ticket 12 的寫入失敗測試：被下層吞掉的失敗，在結果層變成失敗。
- 設定欄位缺漏的 CLI 結束碼測試。CLI 測試檔裡有一份獨立於 rag_lab 的設定欄位字面清單，新的三個欄位要加進去。
- 假 server 的排序規則與觸發 500 的方式，由 implementer 比照假 server 現有的設定方式決定，標註 ASSUMPTION。

**完成條件**
- 上面 7 項行為都有測試，並先看過它們在改程式前失敗（紅燈）。
- 主測試套件 `python -m unittest`（在 repo 根目錄用專案的 venv 執行）全綠。

**實機驗收**（主對話做，implementer 不跑）
1. 使用者在 `.env` 加上三個欄位，用帶 `--reranker-model` 的指令重啟 8081 server。
2. probe（只跑檢索，`output/taishin_eval/probe_context.py` 搭配真的 rerank）：11 題（rule-01／02／03、terms-01／02、cross-01／02、switch-02／03、fee-03、offer-01）的關鍵字句不少於 23/33。開工前的實驗是 24/33。
3. 清掉 LLM 快取的 `:query:` 項目後跑完整 eval（20 題 × 5 模式），兩位判讀者獨立判讀：
   - mix 的 ✓ 不少於 7 題；
   - 和第二次 eval 比較，原本 ✓ 而這次不是的題目逐題說明原因。
   - 開工前的實驗只跑了 13 題，✓ 是 6 題。
     - 第二次 eval 的 mix 有 7 題 ✓：其中 4 題（rule-03、switch-02、fee-03、offer-02）在實驗中仍是 ✓；switch-01、benefit-03、offer-01 這 3 題沒有在實驗中跑過。
     - 實驗另外讓 benefit-01、fee-02 變成 ✓。
     - 沒跑過的 3 題若維持 ✓，預期是 9 題。
   - 未達 7 題時停下來回報使用者，不放寬標準。
4. eval 期間 GPU wired 記憶體峰值低於 22 GB；超過時停下來回報，再研究 FP16 版本。
5. 記錄每題查詢時間，和第二次 eval 比較。
6. 不要求 ticket 09（台新知識庫）的驗收通過：約定條款與跨卡比較兩類，在開 rerank 的實驗中仍沒有 ✓。

## Out of Scope

- **Qwen3-Reranker**：`Qwen/Qwen3-Reranker-0.6B`（BF16）與 `mlx-community/Qwen3-Reranker-0.6B-4bit` 在 mlx-vlm 0.7.10 的 rerank endpoint 能載入，但不論文件內容，分數都相同，無法排序。原因沒有追查。
- **bge 轉 FP16**：只有在實機驗收的記憶體峰值超過 22 GB 時才做。
- **調整 rerank 參數**：chunk_top_k、min_rerank_score、instruction 都不調。
- **跨卡題拆成單卡子問題**：改善提案的方案 C，另外決定。
- **依查詢模式分開設定 entity／relation 上限**：使用者只用 mix，決定維持現狀。
- **關鍵字抽取的 JSON 錯誤**：4B LLM 抽關鍵字時偶爾輸出不合法的 JSON，導致查詢失敗；這和 rerank 無關。
- **匯入時的記憶體**：預先載入 reranker 後，匯入期間的記憶體峰值沒有重新量，等下次匯入時再量。

## Further Notes

- 決定過程與實驗數據：
  - `.scratch/taishin-credit-card-kb/proposal-answer-quality.md`（方案 B）；
  - 2026-11-01 的 grill（Q1–Q13）；
  - `output/taishin_eval_rerank/judgement.md`、`output/taishin_eval2/judgement.md`（只在本機）。
- 實作沿用 `integration/taishin-credit-card-kb` 分支，因為 ticket 09 的重新評估要用到它。
- LightRAG 1.4.16 的 rerank 處理順序：
  1. 對全部候選排序，只保留分數最高的 chunk_top_k 個（rerank 時就傳 top_n）；
  2. 依 min_rerank_score 過濾；
  3. 再依 chunk_top_k 截斷，這時已經不會再少；
  4. 最後依 token 上限截斷。
- 實驗中 rerank 後的 context 從每題 7–12 個 chunk 減少到 3–8 個，因為排在前面的 chunk 比較長（`output/taishin_eval2/probe_rerank_none.log`、`probe_rerank_bge.log`）。
