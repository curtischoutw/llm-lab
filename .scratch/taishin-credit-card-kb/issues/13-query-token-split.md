# 13: 查詢時 entity／relation 的 token 上限改成可設定

**What to build:** 查詢時，entity 與 relation 各自能用多少 token，改成 `.env` 的兩個設定，不再依 LightRAG 的預設比例跟著總上限縮放。總上限 `QUERY_MAX_TOTAL_TOKENS` 維持 12,000，扣掉 entity 與 relation 之後，剩下的 token 都留給文字 chunk。

**Blocked by:** None

**Status:** resolved

## 背景（2026-11-01，ticket 09 的根本原因調查）

- ticket 09 的 eval 在 mix 模式下有 3 類沒通過驗收。逐格判讀、根本原因與診斷腳本都在 `output/taishin_eval/`：`judgement.md`、`probe_context.py`。
- 目前的程式依 LightRAG 預設比例（6,000／8,000 對 30,000）縮放，在 12,000 的總上限下，entity 是 2,400、relation 是 3,200。mix 模式的 context 因此只剩 3–8 個 chunk。
- 總上限維持 12,000，只改 entity／relation 的上限。對沒通過的 7 題只跑檢索，數參考答案的關鍵字句有幾個進了 context（滿分 21）：

  | entity／relation | 關鍵字句 |
  |---|---|
  | 2,400／3,200 | 7 |
  | 1,500／2,000 | 7 |
  | 1,000／1,000 | 10 |
  | 500／500 | 13 |
  | 0／0 | 11 |

- 使用者在 2026-11-01 決定：調整 mix 的 token 分配，而且總上限不增加，因為 12,000 是 GPU 記憶體的實測限制，見 README 與 ticket 03 的紀錄。另外要加 reranker，但那部分另外處理，不在這張 ticket。

## 驗收

- [x] 新增兩個設定 `QUERY_MAX_ENTITY_TOKENS`、`QUERY_MAX_RELATION_TOKENS`，沿用現有設定欄位的規則：必填、缺漏或格式錯誤時 CLI 在啟動時中止。
  - 值要是 0 以上的整數，而且兩者相加要小於 `QUERY_MAX_TOTAL_TOKENS`。違反時的錯誤訊息要指出是哪個欄位、為什麼不合法。
  - 0 是合法值：LightRAG 照常執行，只是不放 entity 或 relation 的描述。這點在診斷時已實測過。
- [x] `query`、`eval`、Python API（`Session.query`、`pipeline.query`、`evaluate`），以及 VLM 增強查詢，都用這兩個設定，取代原本依比例縮放的計算。
- [x] `.env.example` 加上這兩個欄位：
  - 值是 500 與 500，註解寫出上面的實測與理由。
  - 測試檢查 `.env.example` 的欄位和設定欄位相同，要跟著通過。
- [x] eval 對照表的「固定查詢設定」那幾行要寫出 entity／relation 上限，讓之後的 eval 可以比較。
- [x] 以 CLI 子行程與 Python API 兩個既有的縫測試。假 OpenAI server 已經記錄收到的請求；送給 LightRAG 的參數若不能直接觀察，就用最高的縫觀察得到的行為來驗證，並在實作結果說明怎麼驗證的。
- [x] README（設定說明、第 5 節有提到比例縮放的地方）與 `docs/architecture.md` 一併更新。
- [x] 主測試套件全綠。
- [x] 實機驗證，由主對話做，implementer 不跑：
  1. 使用者在 `.env` 加上這兩行；
  2. 刪掉 `kv_store_llm_response_cache.json` 裡 key 含 `:query:` 的項目；
  3. 重跑完整的 20 題 eval，用和 ticket 09 相同的判讀方式比較，原本答對的題目也要檢查有沒有變差。

## 實作結果（2026-11-01）

**做了什麼**
- `rag_lab/config.py`：`Settings` 新增 `query_max_entity_tokens`、`query_max_relation_tokens`，兩者必填、0 以上的整數；兩者相加大於等於 `QUERY_MAX_TOTAL_TOKENS` 時以 `ConfigError` 中止，欄位寫 `QUERY_MAX_ENTITY_TOKENS`，原因寫出另外兩個欄位名稱，不含欄位值。
- `rag_lab/pipeline.py`：`query_kwargs(settings)`、`query_param(mode, settings)` 直接取三個設定，移除比例縮放與 `DEFAULT_MAX_*` 的 import。`_answer`（`query`、`evaluate`、`Session.query` 共用）與 VLM 增強查詢（`aquery_vlm_enhanced`）都走 `query_kwargs`。
- `rag_lab/__main__.py`：eval 對照表表頭加上 `QUERY_MAX_ENTITY_TOKENS`、`QUERY_MAX_RELATION_TOKENS` 兩行（`固定查詢設定` 那組設定的來源在這裡，不在 `evaluation.py`）。
- `.env.example`（500／500 與實測理由）、README（設定說明、第 5 節兩處記錄比例縮放的數據、第 6 節欄位表）、`docs/architecture.md` 第 5 節。

**怎麼驗證參數真的送到 LightRAG**：QueryParam 看不到，所以用假 server 記下的答案請求 prompt 驗證。假 server 抽出的圖譜只有 Alpha、Beta 兩個 entity 與一條 relation，三段描述文字不會出現在文字 chunk；entity 上限設 0 時 prompt 沒有 entity 描述但有 relation 描述，relation 上限設 0 時相反。這個檢查涵蓋 CLI `query`（local、mix）、`query --vlm-enhanced`（mix，VLM 請求的 prompt）、CLI `eval`（五種模式）、Python API 的 `pipeline.query`／`pipeline.evaluate`／`Session.query`／`Session.evaluate`。

**紅燈**（改程式前）：`tests.test_cli` 新增的 6 個斷言失敗（負數與非整數的 token 上限結束碼 2 而不是 3、`.env.example` 缺兩個欄位）；`QueryKnowledgeGraphBudgetTest` 的 entity／relation 為 0 的測試失敗，`'Fake Entity Alpha is a made-up concept.' unexpectedly found in …`（舊程式依比例縮放，6000／8000 的上限下描述還在 prompt）；`EvalQueryBudgetTest`、Python API 的 `QueryBudgetTest` 對舊的 `pipeline.py`／`__main__.py` 同樣失敗（6 個失敗），表頭缺 `QUERY_MAX_ENTITY_TOKENS：500`。

**最後一次主套件**：`/Users/curtis/GitHub/llm-lab/.venv/bin/python -m unittest`，`Ran 146 tests in 524.808s`，`OK`。

**發現與疑慮**
- 兩個上限同時為 0 時，local、global、hybrid 沒有任何 context，LightRAG 回報 `Query returned no results`，查詢失敗；mix 與 naive 有文字 chunk，可以執行。ticket 寫的「0 是合法值，LightRAG 照常執行」只在其中一個為 0（或模式是 mix／naive）時成立。設定檢查沒有擋掉 0／0（ticket 的規則只要求相加小於總上限，且診斷表有 0／0 的資料）；已寫進 `.env.example` 與 README。
- 既有的 `QueryBudgetTest.test_query_context_follows_query_max_total_tokens` 把總上限降到 4,000，而基準設定的 6000／8000 相加超過它，現在會被設定檢查擋下；測試改成同時把兩個上限設 500。
- 實機驗證（ticket 最後一項）沒做：沒有讀 `.env`，沒有對 127.0.0.1:8080／8081 發請求。使用者的 `.env` 沒有新增兩個欄位前，所有 CLI 命令都會因缺欄位而中止。

**ASSUMPTION**
- 設定檢查違反時只丟一個 `ConfigError`，欄位寫 `QUERY_MAX_ENTITY_TOKENS`、訊息提到另外兩個欄位。
- `valid_env` 的基準值用 6000／8000（對 30000），與舊程式在 30000 下算出的值相同。
- README 第 5 節的歷史數據（2,400／3,200 時的結果）保留，只加註當時的上限。

## 實機驗證結果（2026-11-01，主對話）

- 使用者在 `.env` 加上兩個欄位（以 `grep -c` 確認各 1 行，`get_settings` 讀到 12000／500／500）；刪掉 LLM 快取 100 個 `:query:` 項目（備份 `rag_storage/kv_store_llm_response_cache.json.bak-20261101-095116`）。
- 完整 eval：`eval_results/eval_20261101-095122.md`，100 格，失敗 0 格，耗時 1:34:31，GPU wired 峰值 19 GB。判讀與比較在 `output/taishin_eval2/judgement.md`（兩位判讀者 85/100 格一致，分歧都是 △／✗，不影響 ✓ 數）。
- 各模式 ✓：naive 8→8、local 4→2、global 8→4、hybrid 4→1、mix 4→7。naive 的答案兩次逐字相同，判讀的 ✓ 也相同，所以 mix 的變化來自答案本身。
- mix 原本 ✓、這次不是 ✓ 的有 benefit-01、fee-02；從 △ 變 ✗ 的有 switch-03、rule-01。
- local、global、hybrid 變差的原因：global 模式的 probe 顯示 relation 從每題 40 個降到 5–11 個，global 原本答對的 4 題關鍵字句從 12/12 降到 6/12。
- 使用者決定（2026-11-01）：只用 mix，維持 500／500，不依模式分開設定；README 與 `.env.example` 已註明。
