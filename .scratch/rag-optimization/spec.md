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
8. **不換生成用的 LLM**。embedding 在重匯前決定：如果 probe 結果 a 加 b_rank 的題數 ≥4，就在知識庫副本上只重算 chunk 向量，用 probe 比較 Qwen3-Embedding-0.6B（現行）、Qwen3-Embedding-4B、bge-m3 三個模型的關鍵字句覆蓋，並記錄記憶體峰值（上限 26 GB），再決定重匯時用哪一個。reranker 這次不重新評估：2026-11-01 已經比較過，只有 bge-reranker-v2-m3 能排序；歸因結果顯示問題出在 b_rank 時再回頭評估。
9. **查詢端改動排在匯入端之前**（context 上限、chunk_top_k、thinking 模式）；thinking 模式要等 Q11 結果，而且要先查證 mlx-vlm 怎麼開。
10. **Claude 只當裁判與協作者**：管線內每一步（解析、切塊、實體抽取、關鍵字、embedding、rerank、生成、改寫問題、補前後文摘要）只用本機模型。Claude 負責設計實驗、寫程式、整理關鍵字句、判讀與分析。

## 第二次 grill 的決定（2026-11-18）

11. **每組設定只跑 1 次 eval**（取代決定 2 的 3 次多數決）：解碼是 greedy，重跑雜訊是 0。改 prompt 或 context 時個別題目仍可能升降，所以只有淨增 4 題以上才算進步。
12. **查詢端三個獨立實驗**，每個只改一項，各跑 1 次加雙判讀，和基準比較；有效的再合併跑一次：
    - E1：開 thinking（server 加 `--enable-thinking`），要注意記憶體峰值。
    - E2：`chunk_top_k` 從 20 改成 40。
    - E3：回答附加指示加上「逐項回答每個子問題，每個數字都寫出它屬於哪個產品、哪一年、哪個活動」。
13. **切塊依標題結構**：在 MinerU 標出的標題處切開，同一節超過 1,200 token 時再依 token 數切。chunk 標頭是卡片標籤加上章節名稱。事實：card_cg047 的 content_list 只有 `text_level` 2 一層標題（64 個），所以多數文件的章節名稱只有一層。
14. **不做 Gemma 補前後文摘要**；重匯後如果 c1 類（被別的產品、年度、活動干擾）仍多，再考慮。
15. **實驗不改 rag_lab**：E1–E3 用 `output/rag_opt/run_experiment.py` 覆寫 pipeline 常數；確定有效之後，再開 ticket 正式改程式。
16. **重匯直接取代舊知識庫**：不另外建 WORKING_DIR。重匯前刪除 `rag_storage` 與 `output/rag_opt/kb_copy`，刪除前要列出清單請使用者確認。刪除之後就沒辦法換回舊知識庫，舊的 eval 答案保留在 `eval_results/` 供比對。檔名改了，MinerU 的解析快取對不上，所有文件都要重新解析。
18. **查詢端維持原狀**：E1–E3 都不採用，也不合併起來跑；重匯之後可以在新知識庫上再試一次 E1、E2。embedding 比較的候選是 `mlx-community/Qwen3-Embedding-4B-4bit-DWQ`（2560 維）與 `mlx-community/bge-m3-mlx-8bit`（1024 維）；在 kb_copy 的副本上用候選模型重算三個向量庫（chunk 2,341、entity 18,297、relation 37,027 筆），再跑 probe28 比較（`output/rag_opt/run_embed_compare.sh`）。
17. **順序**：E1–E3 查詢端實驗 → 在 kb_copy 上比較 embedding（結果：換 4B，決定 20）→ 寫正式 spec 與 tickets → 實作（卡片標籤、依標題切塊、中文、實體類型、改檔名）→ 使用者確認後刪除舊知識庫 → 全量重匯 → eval 加雙判讀。

## 查詢端實驗結果（2026-11-19，事實）

基準重新判讀：同一份判讀說明、同一批判讀者（sonnet），判讀基準答案（`output/rag_opt/eval_runs/run2/`）。兩位判讀者在 9 題上分數不一致，所以合計數字會因判讀者不同而差 1–2 題。下表的「變好」「變差」只算兩位判讀者都同意的題目。判讀檔在 `output/rag_opt/judging/`，比對程式是 `output/rag_opt/compare_judges.py`。

| | 內容 ✓（A／B） | 最終 ✓（A／B） | 內容變好 | 內容變差 | 最終變好 | 最終變差 | eval 時間 |
|---|---|---|---|---|---|---|---|
| 基準 | 17／16 | 8／9 | | | | | 約 21 分 |
| E1 thinking | 18／19 | 11／11 | 3 | 2 | 5 | 3 | 1 時 34 分 |
| E2 chunk_top_k 40 | 17／16 | 10／9 | 3 | 3 | 4 | 2 | 約 22 分 |
| E3 逐項回答指示 | 16／15 | 10／10 | 2 | 4 | 4 | 4 | 約 23 分 |

- 三組都沒有達到淨增 4 題（決定 11）。
- E1 和 E2 都修好了 debit-negate-01 和 debit-wrongcard-02；rule-01 三組都變差。
- E1 的代價：
  - `LLM_MAX_TOKENS` 4096 時，抽關鍵字這一步的 thinking 就把上限用完，查詢失敗。改成 16384 才跑得完。
  - offer-01 超過 360 秒的 worker 逾時。把 `LLM_TIMEOUT` 調到 600 秒補跑，結果 thinking 一直產生到 16,384 token 上限，輸出是無意義的重複文字，所以這題算 ✗。
  - wired 峰值 23 GB。

## embedding 比較結果（2026-11-19，事實）

19. **只比較 chunk 向量檢索**（取代決定 18 的「三個向量庫都重算再跑 probe28」）：4B 重算 chunk 2,341 筆花了 97 分鐘，entity 前 1,000 筆花了 12 分鐘；依這個速度，entity 18,297 筆約 3.7 小時、relation 37,027 筆約 7.4 小時，三個向量庫合計約 12.7 小時。所以改成只重算 chunk 向量，用 `output/rag_opt/chunk_retrieval.py` 計算 84 句關鍵字句在 chunk 向量檢索前 K 名的覆蓋（來源檔的 chunk 而且含該句才算）。這個比較不含 mix 的圖譜路徑、rerank 與 token 截斷。

| 模型 | 前 10 名 | 前 20 名 | 前 40 名 | 3 句都在前 20 名的題數 | 重算 chunk 時間 |
|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B（現行） | 59 | 70 | 77 | 19／28 | — |
| Qwen3-Embedding-4B | 70 | 75 | 77 | 23／28 | 97 分 |
| bge-m3（CLS pooling） | 65 | 72 | 75 | 21／28 | 約 4 分 |
| bge-m3（mlx-vlm server 預設，mean pooling） | 4 | 12 | 17 | — | 7 分 |

- 4B 在前 10、前 20 名比 0.6B 多 11、5 句；前 40 名三個模型相同或只差 2 句。
- rule-01 和 cross-02 在三個模型下都檢索不到：rule-01 有 2 句排在第 600 名之後，cross-02 有 2 句排在第 100 名之後。這兩題的問題不在 embedding 模型。
- bge-m3：`mlx-community/bge-m3-mlx-8bit` 缺少 `1_Pooling` 設定，mlx-vlm 的 xlm_roberta 實作因此預設 mean pooling（`mlx_vlm/models/xlm_roberta/xlm_roberta.py:143`），但 bge-m3 用 CLS pooling。用 mean pooling 時，存下的向量和模型直接算的一致（cos 1.0），查詢向量改在同一個 process 內計算，結果也一樣是 4／12／17，所以低分來自 pooling，不是比較程式的錯誤。CLS 的數字是在同一個 process 內直接算 chunk 與查詢向量得到的（`output/rag_opt/` 以外的暫存腳本），server 目前無法用 CLS 提供 bge-m3。
- 記憶體：4B 重算期間 server footprint 峰值 22 GB（`output/rag_opt/watchdog_q4b/sampler.log`）。這段期間只有 embedding 請求，重匯時 Gemma 抽實體與 4B embedding 會交替執行，峰值沒有量過。

20. **重匯改用 Qwen3-Embedding-4B**（`mlx-community/Qwen3-Embedding-4B-4bit-DWQ`，2560 維，查詢前綴沿用現行的 Qwen 指令）：使用者決定（2026-11-19）。影響：
    - 重匯時 embedding 約多 12 小時（依上面實測速度推算），加上 Gemma 抽實體的時間。
    - `.env` 的 `EMBED_MODEL`、`EMBED_DIM` 與 server 啟動參數要改；`scripts/vlm_server.py`、`scripts/smoke_test.py`、`README.md` 有寫到 0.6B，要一起更新。
    - 查詢時的 embedding 延遲與之後增量更新的時間會增加，數字沒有量過，重匯後的 eval 會記錄 eval 總時間。
    - 重匯時用 watchdog 監看記憶體（上限 26 GB）。

## 範圍外發現

- mlx-vlm 對缺少 `1_Pooling` 設定的 xlm-roberta embedding 模型預設用 mean pooling，不會警告。用 bge-m3 前要先解決 pooling 設定。

- rag_lab 收到回答被長度上限截斷（`finish_reason=length`）時，仍當成正常答案收下：E1 補跑 offer-01 時，eval 記為「失敗 0 格」，但答案是 16,384 token 的重複文字。抽關鍵字那一步遇到同樣情況時會拋 LengthFinishReasonError。
- E1 補跑 offer-01 時，eval 從 02:21 啟動，到 02:38 才送出第一個 embedding 請求。這 17 分鐘的空檔原因還沒查。

## 撤回的方案

- 只在查詢端把語言改成中文：圖譜描述仍是英文，兩邊語言不一致；結果變差時無法判斷原因。
- 用小知識庫做語言 A/B：使用者決定直接用中文。

## 準備時發現的事實（2026-11-18）

- 舊 probe 判斷「進 context」的方式是：關鍵字句出現在 context 的任何地方就算。terms-01 的「前24小時」、fee-02 的「3.5%」「150元」，在來源檔裡的寫法其實是「前二十四小時」「百分之三點五」「新臺幣壹佰伍拾元」。舊 probe 比對到的是別份文件，所以這兩題在舊資料裡「進 context」的判定不可靠。新 probe（`output/rag_opt/probe28.py`）改成只算來自參考來源檔的 chunk；84 句關鍵字句都確認過出現在來源檔的 chunk 裡。
- Gemma 4 模型檔的 `generation_config.json` 寫的是 `do_sample: true`、`temperature: 1.0`，rag_lab 沒有傳 temperature。不過實測 server（2026-11-18）時，同一個開放式 prompt 不帶 temperature 送 3 次，回答一字不差，所以 server 實際是 greedy 解碼，沒有套用 generation_config 的取樣設定。生成與關鍵字抽取在輸入相同時應該是確定性的，這一點會用重跑的結果確認。
- thinking 模式：`mlx_vlm.server` 有 `--enable-thinking` 參數（README 第 182 行），目前沒有開。
- 量雜訊的重跑，每次都清掉查詢答案與查詢關鍵字快取（`output/rag_opt/clear_query_cache.py`，清之前先備份），所以雜訊包含關鍵字抽取的變動。因為解碼是 greedy，先只重跑 1 次，逐題和 2026-11-12 的答案比對（知識庫在 11/03 之後沒有變動）；如果完全相同，雜訊就是 0；第 3 次要不要跑、Q25 的多數決要不要改成每組跑 1 次，由使用者決定。

## 歸因結果（2026-11-18，事實）

- 雜訊：清掉 query 與 keywords 快取後重跑一次 eval（`output/rag_opt/eval_runs/run2/`），28 題答案和 2026-11-12 逐字相同。28 格 0 失敗，wired 峰值 23 GB。
- probe（`output/rag_opt/probe/probe.json`，log 在 `output/rag_opt/probe.log`）：內容沒有 ✓ 的 12 題中，c 6 題（switch-01、switch-04、benefit-02、benefit-03、rule-02、offer-01）、a 5 題（rule-01、terms-02、cross-01、cross-02、debit-wrongcard-02）、b_trunc 1 題（debit-negate-01）、b_rank 0 題。rerank 前的候選池每題 20–29 個 chunk，最後放進 context 的 7–10 個。
- a／b 類的共同點是檢索到的是別張卡片的文件：cross-01 的街口卡（cg038）、cross-02 的雙幣卡（cg039）與昇恆昌卡（cg009）都不在候選池裡；debit-negate-01 的金融卡卡片頁被截掉，進 context 的是信用卡的機場接送權益。
- 內容 ✓ 的題目裡也有 4 題被分到 a（fee-02、debit-confuse-02、debit-negate-02、debit-wrongcard-01），代表關鍵字句清單不完整，分類只能當參考。
- Q11（`output/rag_opt/q11_c_analysis.md`）：6 題 c 類共 12 個錯漏點。c1（被同一份文件裡別的產品、別的年度、別的活動干擾）5 點，c3（正確資訊在 context，模型漏寫或改錯數字）5 點，c4（答案需要的資訊不在 context）2 點。c1 的正確 chunk 都排在干擾 chunk 前面。抽查兩點確認無誤：offer-01 的答案寫「1,303」，但 context 裡只有「1,300」；card_cg047 列出各方案回饋率的彙總表 chunk 沒有出現在 6 題的任何一份 context 裡。

## 接下來的步驟

1. 準備（不需要 server）：probe 與 context 傾印腳本，以及金融卡 8 題的關鍵字句。
2. 使用者回到電腦前先執行 `sudo sysctl iogpu.wired_limit_mb=26000`，接著跑 Q8（基準 eval 再跑 2 次），然後跑 Q7（28 題 probe 加 context 傾印）。
3. Q11：逐題分析 (c) 類，看 context 與答案的差距。
4. 第二次 grill：決定切塊、補前後文摘要、查詢端參數，然後把這份草稿寫成正式 spec 與 tickets。

## Out of Scope

- 重新爬官網。
- 換生成用的 LLM。
- 在管線內使用 Claude。
