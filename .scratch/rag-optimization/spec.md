Status: needs-info（等歸因結果：Q7 probe、Q8 雜訊、Q11 逐題分析；之後第二次 grill 決定切塊與查詢端做法）

# Spec 草稿：台新知識庫的回答品質優化

## Problem Statement

28 題 eval（mix＋rerank，Gemma 4 26B A4B，加回答附加指示）的結果是內容 ✓ 16、最終 ✓ 8（`eval_results/eval_20261112-004153.md`，判讀 `output/answer_prompt_01/judgement.md`）。之前試過但沒有效果的做法：回答規則 A、拆子問題（方案 C）、換 Qwen3-8B（方案 D）。

已知的設定現況：

- `SUMMARY_LANGUAGE` 沒有設定，LightRAG 用預設的 English。它同時決定匯入時實體與描述的語言、查詢時關鍵字抽取的語言（`lightrag/prompt.py:387`）。
- 實體類型是 LightRAG 的通用預設（Person、Organization、Data、Artifact 等），沒有信用卡領域的類型。
- 切塊是 LightRAG 預設：每塊 1,200 token、重疊 100，依 token 數切。表格另外切成 800 token 以下（`rag_lab/tables.py`）。
- 圖譜是 Qwen 時期抽的；Gemma 4 還沒有實測過匯入。
- 檔名（例如 `card_cg047_card001.pdf`）看不出是哪張卡片；chunk 切開後沒有卡片名稱。

## 初步歸因（舊資料，待 Q7 重跑確認）

用 2026-11-03 的 probe（`output/chunk_trunc/probe_after.json`，Qwen 4B 抽關鍵字）對照 2026-11-12 的判讀，內容沒有 ✓ 的 12 題：

| 類別 | 題目 |
|---|---|
| (c) 3 句關鍵字句都進 context，仍答錯 | switch-01、switch-04、benefit-02、benefit-03、rule-02、offer-01 |
| (a／b) 關鍵字句沒有全部進 context | terms-02（0/3）、cross-02（0/3）、cross-01（2/3）、rule-01（1/2） |
| 沒有 probe 資料 | debit-negate-01、debit-wrongcard-02 |

限制：關鍵字抽取模型已經換了；每題只檢查 3 句；重跑差異沒有量過。

## 已定案的決定（grill 2026-11-18）

1. **量尺**：28 題 eval 加雙判讀，只用 mix 模式評估（eval 一律加 `--modes mix`，probe 也只跑 mix；naive、local、global、hybrid 都不跑）。目標是內容 ✓ 16→≥20、最終 ✓ 8→≥12，原本 ✓ 的題目不能變錯。
2. **雜訊**：基準設定與改動後的設定各跑 3 次，每題取多數決（3 次中至少 2 次 ✓ 才算 ✓），目標用多數決結果比較。每次都由兩位判讀者各自判讀，再用程式逐題比對。
3. **先歸因再改**：失敗分成 (a) 檢索漏掉、(b) 有檢索到但被排掉或截斷、(c) 進了 context 仍答錯，依分布決定改哪一層。
4. **重匯最多一次**，所有匯入端的改動一起放進這次重匯（見 `docs/adr/0001-single-bundled-reingest.md`）。不重新爬官網，用 `data/taishin_credit_card/` 現有的檔案。
5. **重匯時確定放入**：
   - 語言設為繁體中文，由 rag_lab 管理（現在 config 會拒絕直接用 `SUMMARY_LANGUAGE` 環境變數）。
   - 實體類型改成：卡片、權益、回饋方案、回饋規則、費用、約定條款、活動、商店或通路、支付工具、機構。
   - 卡片標籤（定義見 GLOSSARY），檔名與 chunk 標頭兩處都放。
6. **卡片標籤**：
   - 由程式從 manifest 網址與 `_meta/html` 的官網頁面標題產生，交給使用者抽查。
   - 檔名格式：`<卡別>_<簡短卡名｜多卡｜全部>_<原檔名>`，例如 `信用卡_台新Richart卡_card_cg047_card001.pdf`。改名寫在 `scripts/fetch_taishin.py` 的 `document_filename`，另外寫一次性遷移腳本，改現有檔案、manifest 與 `eval/questions.taishin.jsonl` 的 `source`。
   - chunk 標頭放卡別與完整的適用卡片清單；超過 150 token 時改寫成「適用 N 張卡（清單見本文件第一段）」，完整清單只放在第一個 chunk。
7. **重匯內容等歸因後再定案**：切塊方式、Gemma 補前後文摘要（contextual retrieval）兩項，在第二次 grill 決定。切塊優化排在 (c) 類問題之後，只針對 (a／b) 類設計。
8. **不換生成用的 LLM**。如果 (a) 類占多數，再評估換大一點的 embedding（例如 Qwen3-Embedding-4B，前提是在 26 GB 上限內）。
9. **查詢端改動排在匯入端之前**（context 上限、chunk_top_k、thinking 模式）；thinking 模式要等 Q11 結果，而且要先查證 mlx-vlm 怎麼開。
10. **Claude 只當裁判與協作者**：管線內每一步（解析、切塊、實體抽取、關鍵字、embedding、rerank、生成、改寫問題、補前後文摘要）只用本機模型。Claude 負責設計實驗、寫程式、整理關鍵字句、判讀與分析。

## 撤回的方案

- 只在查詢端把語言改成中文：圖譜描述仍是英文，兩邊語言不一致；結果變差時無法判斷原因。
- 用小知識庫做語言 A/B：使用者決定直接用中文。

## 準備時發現的事實（2026-11-18）

- 舊 probe 判斷「進 context」的方式是：關鍵字句出現在 context 的任何地方就算。terms-01 的「前24小時」、fee-02 的「3.5%」「150元」，在來源檔裡的寫法其實是「前二十四小時」「百分之三點五」「新臺幣壹佰伍拾元」。舊 probe 比對到的是別份文件，所以這兩題在舊資料裡「進 context」的判定不可靠。新 probe（`output/rag_opt/probe28.py`）改成只算來自參考來源檔的 chunk；84 句關鍵字句都確認過出現在來源檔的 chunk 裡。
- Gemma 4 模型檔的 `generation_config.json` 是 `do_sample: true`、`temperature: 1.0`、`top_k: 64`、`top_p: 0.95`，rag_lab 沒有傳 temperature。mlx-vlm 的 `resolve_sampling_defaults` 在請求沒帶 temperature 時，會用模型設定裡的值，所以推測生成與關鍵字抽取都是取樣，重跑時結果會不同。這一點開 server 時要確認 server 讀的是哪份設定。「調低 temperature」列為第二次 grill 的查詢端候選。
- thinking 模式：`mlx_vlm.server` 有 `--enable-thinking` 參數（README 第 182 行），目前沒有開。
- 量雜訊的重跑，每次都清掉查詢答案與查詢關鍵字快取（`output/rag_opt/clear_query_cache.py`，清之前先備份），所以雜訊包含關鍵字抽取的變動。

## 接下來的步驟

1. 準備（不需要 server）：probe 與 context 傾印腳本，以及金融卡 8 題的關鍵字句。
2. 使用者回到電腦前先執行 `sudo sysctl iogpu.wired_limit_mb=26000`，接著跑 Q8（基準 eval 再跑 2 次），然後跑 Q7（28 題 probe 加 context 傾印）。
3. Q11：逐題分析 (c) 類，看 context 與答案的差距。
4. 第二次 grill：決定切塊、補前後文摘要、查詢端參數，然後把這份草稿寫成正式 spec 與 tickets。

## Out of Scope

- 重新爬官網。
- 換生成用的 LLM。
- 在管線內使用 Claude。
