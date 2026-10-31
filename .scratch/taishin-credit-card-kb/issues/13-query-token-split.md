# 13: 查詢時 entity／relation 的 token 上限改成可設定

**What to build:** 查詢時，entity 與 relation 各自能用多少 token，改成 `.env` 的兩個設定，不再依 LightRAG 的預設比例跟著總上限縮放。總上限 `QUERY_MAX_TOTAL_TOKENS` 維持 12,000，扣掉 entity 與 relation 之後，剩下的 token 都留給文字 chunk。

**Blocked by:** None

**Status:** ready-for-agent

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

- [ ] 新增兩個設定 `QUERY_MAX_ENTITY_TOKENS`、`QUERY_MAX_RELATION_TOKENS`，沿用現有設定欄位的規則：必填、缺漏或格式錯誤時 CLI 在啟動時中止。
  - 值要是 0 以上的整數，而且兩者相加要小於 `QUERY_MAX_TOTAL_TOKENS`。違反時的錯誤訊息要指出是哪個欄位、為什麼不合法。
  - 0 是合法值：LightRAG 照常執行，只是不放 entity 或 relation 的描述。這點在診斷時已實測過。
- [ ] `query`、`eval`、Python API（`Session.query`、`pipeline.query`、`evaluate`），以及 VLM 增強查詢，都用這兩個設定，取代原本依比例縮放的計算。
- [ ] `.env.example` 加上這兩個欄位：
  - 值是 500 與 500，註解寫出上面的實測與理由。
  - 測試檢查 `.env.example` 的欄位和設定欄位相同，要跟著通過。
- [ ] eval 對照表的「固定查詢設定」那幾行要寫出 entity／relation 上限，讓之後的 eval 可以比較。
- [ ] 以 CLI 子行程與 Python API 兩個既有的縫測試。假 OpenAI server 已經記錄收到的請求；送給 LightRAG 的參數若不能直接觀察，就用最高的縫觀察得到的行為來驗證，並在實作結果說明怎麼驗證的。
- [ ] README（設定說明、第 5 節有提到比例縮放的地方）與 `docs/architecture.md` 一併更新。
- [ ] 主測試套件全綠。
- [ ] 實機驗證，由主對話做，implementer 不跑：
  1. 使用者在 `.env` 加上這兩行；
  2. 刪掉 `kv_store_llm_response_cache.json` 裡 key 含 `:query:` 的項目；
  3. 重跑完整的 20 題 eval，用和 ticket 09 相同的判讀方式比較，原本答對的題目也要檢查有沒有變差。
