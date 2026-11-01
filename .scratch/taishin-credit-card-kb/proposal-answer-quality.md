# 提案：改善 eval 沒通過的題目（討論用，2026-11-01）

狀態：順序已決定，還沒有 ticket。

使用者的決定（2026-11-01）：
- 照第 5 節的順序做：第二次 eval → A 的實驗 → C 的 probe → B 的 spec → D 視情況。
- 方案 A 的回答規則照第 3 節的草案寫。
- 方案 E 不做。
- 方案 B（reranker）要做，設計還沒討論。

這份提案處理 ticket 09 第一次 eval 時，mix 模式沒有答對的 7 題。逐格判讀與根本原因的資料在 `output/taishin_eval/judgement.md`（只在本機）。

### 名詞

- **chunk**：文件切成的一段文字；**context**：查詢時送給 LLM 的資料，由 chunk、entity（圖譜節點）與 relation（圖譜關係）的描述組成。
- **mix、naive**：LightRAG 的檢索模式。naive 只用 chunk 的向量相似度；mix 同時用圖譜與 chunk。
- **關鍵字句**：從每題參考答案挑出的 3 個字句，用來數 context 有沒有包含答案（7 題共 21 個）。
- **候選池**：LightRAG 截斷到 token 上限之前取得的 chunk，reranker 只能從這裡面重新排序。
- **活動頁**：`data/taishin_credit_card/offers/` 下的優惠活動文件。
- **probe**：`output/taishin_eval/probe_context.py`，只跑檢索、不叫 LLM 生成答案的診斷腳本。
- **watchdog**：監看 GPU wired 記憶體的腳本，超過門檻就關掉兩個 MLX server（LLM 在 port 8080，VLM 與 embedding 在 8081）。

## 1. 問題重述

- mix 模式有 3 類沒有通過驗收：回饋規則、約定條款、跨卡比較。
- 依第一次 eval 的 mix 設定（entity／relation 2,400／3,200）下 probe 數到的關鍵字句，失敗的 7 題分成兩種：
  - **資料拿到了，LLM 答錯**：terms-01（3/3）、rule-03（2/3）。
    - terms-01 的 context 有 3 個關鍵字句，答案仍混進 iCash 聯名卡的條款。
    - rule-03 用 naive 模式時 context 有正確日期（3/3），模型自己重算，答錯。
  - **需要的 chunk 沒進 context**：rule-02（0/3）、rule-01（1/3）、terms-02（0/3）、cross-01（1/3）、cross-02（0/3）。
    - rule-02 在 entity／relation 1,000／1,000 時變成 3/3，預期 ticket 13 會改善。但 naive 模式 context 有 3/3 時，答案仍漏掉一個條件，所以它也有答錯的成分。
    - rule-01 的「完全沒有回饋」在知識庫裡找不到相同字句（原文用詞不同），所以最多只能數到 2/3。
- 已在進行的部分：
  - ticket 13 把 entity／relation 上限從 2,400／3,200 調成 500／500，第二次 eval 正在跑（`output/taishin_eval2/eval.log`）。
  - 只跑檢索（mix 模式）時，7 題的關鍵字句進入 context 的數量從 7/21 增加到 13/21。

### 隱含的限制

1. **GPU 記憶體**：watchdog 門檻 22 GB，是啟動 watchdog 時給的參數（`watchdog.sh output/taishin_full/watchdog3 22 15`）。目前量到的 wired 記憶體峰值如下（`output/taishin_full/watchdog3/sampler.log`）：
   - 第一次 eval：21 GB，時間是 10-31 23:36:33。第一次 eval 在 22:5x 開始，這個峰值在 eval 期間。
   - 第二次 eval（11-01 09:51 開始）：到 10:49 為止是 19 GB。
2. **總上限**：`QUERY_MAX_TOTAL_TOKENS=12000` 維持不變。使用者在 ticket 13 已經決定。
3. **新依賴**：要新增第三方套件，先回報使用者。
4. **資料位置**：台新資料只放本機，不送外部服務。所以 Cohere、Jina、阿里雲的 rerank API 都不考慮。
5. **題庫大小**：每類只有 2–4 題，一題變對或變錯，就會改變一整類是否通過。所以每個改動除了看驗收，也要看原本答對的題目有沒有變差。

### 做完之後的不同

mix 模式 7 類都至少有 1 題 ✓，而且第一次 eval 答對的題目沒有變差。

## 2. 判準

有一點要先說明：這 5 條判準是在上一則對話列出改善方向**之後**才寫的，不符合「判準先於方案寫定」的要求。請把這張分數表當成整理用，不要當成獨立的評分。

| # | 判準 | 怎麼判定 |
|---|---|---|
| C1 | 依現有證據，預期能修好幾題失敗題 | 有診斷資料支持才算，推測的另外標出 |
| C2 | GPU 記憶體峰值留在 22 GB 以下 | 有實測或可估計的數字 |
| C3 | 不新增第三方套件 | 只下載模型不算新套件，但要列出來 |
| C4 | 可以單獨量測 | 能用 `probe_context.py`，或只重跑失敗的題目來驗證 |
| C5 | 工作量 | 小：不改 rag_lab 程式；中：一張 ticket；大：要另開 spec |

## 3. 方案

### A. 回答規則寫進 `user_prompt`（處理「資料拿到了，LLM 答錯」）

- LightRAG 的 `QueryParam.user_prompt`（`lightrag/base.py` 第 154 行）會把額外指示放進回答的 prompt。這個功能已經有了，不必改 LightRAG。
- 規則草案：
  - 只用和問題同一張卡的文件內容回答；別張卡、聯名卡的條款不能拿來回答。
  - 日期、金額、比率照原文寫出，不自己重算。原文前後不一致時，兩個值都寫出來並註明。
  - 條件逐條列出；原文沒寫的寫「文件未提及」。
- 查詢快取的 key 已經包含 `user_prompt` 與 `enable_rerank`（`lightrag/operate.py` 第 3290、5123 行）。所以改規則後不必手動清快取，舊答案也不會被誤用。
- 預期效果（推測，還沒驗證）：
  - terms-01：混進別張卡的條款，對應「只用同一張卡」這條規則；
  - rule-03：自己重算日期，對應「不重算」這條規則。
  - rule-02 在 naive 模式漏掉條件，「條件逐條列出」能不能補上，我不確定。rule-01 主要是檢索的問題，A 預期幫不上。
- 風險：4B 模型可能不照規則做。規則也可能讓原本答對的題目變成過度保守的「未提及」。

### B. 本機 reranker（處理「沒進 context」；使用者已決定要做）

- LightRAG 的 `generic_rerank_api` 可以指定 `base_url`，接受 Jina／Cohere 格式（`lightrag/rerank.py` 第 182 行）。所以只要在本機提供一個相同格式的 `/rerank` endpoint 就能接上。
- 模型的選項（大小與記憶體都還沒量）：
  - **b1**：`BAAI/bge-reranker-v2-m3`，用 `.venv` 裡已有的 `torch`（2.14.1）與 `transformers`（4.57.6）執行。
    - 不新增套件，只下載模型。
    - 但會在兩個 MLX server 之外，再多一個 torch 的程序占用 GPU。
  - **b2**：Qwen3-Reranker 系列，用 mlx-lm 計算 yes／no 的機率。
    - 我不知道 mlx-community 有沒有現成的轉檔，也不知道 mlx-lm 能不能直接取得這個分數，要先查。
- 已經有的證據：
  - 在 500／500 的設定下，候選池裡有 15/21 個關鍵字句，最後的 context 裡有 13/21。
  - terms-02 需要的 2 個 chunk 在候選池裡，reranker 有機會把它們排進 context。
  - cross-01 的街口卡、cross-02 的 3 個關鍵字句都不在候選池裡，reranker 救不回這兩題。
- 推測，還沒驗證：
  - 活動頁占掉 context 名額（rule-02 的基準組，6 個 chunk 全是活動頁），reranker 可能讓這種情況變少；
  - 若真的變少，terms-01 混進別張卡條款的情況可能也會減少。
- 實作上的限制：rerank 函式要在建立 LightRAG 時傳入（`operate.py` 第 4317 行讀的是初始化時的 `global_config`），初始化之後才設定不會生效。

### C. 跨卡問題拆成每張卡各查一次（處理 cross-01、cross-02）

- 做法：
  1. 從題目裡比對出卡名（卡名清單取自 `data/taishin_credit_card/cards/` 的 16 張卡）；
  2. 每張卡各檢索一次；
  3. 把每張卡的 context 在 12000 token 內合併；
  4. 交給 LLM 回答一次。
- 依目前證據，不知道有沒有效：整題檢索時，cross-02 的關鍵字句連候選池都沒進。改成單卡問題能不能撈到，還沒測過。
- 不寫程式也能先驗證：用 `probe_context.py` 對 cross-01、cross-02 各卡的子問題（例如「Richart 卡的年費」）只跑檢索，數關鍵字句的覆蓋。
  - 覆蓋沒有改善，這個方案就不做。
- 這個方案要在 rag_lab 的查詢流程裡加一層，還會讓題目裡有卡名時走不同的路徑，所以要另開 spec。

### D. 換較大的 LLM，例如 Qwen3-8B 4-bit（處理「資料拿到了，LLM 答錯」）

- 4B 模型的權重檔在磁碟上是 2.1 GB（`du` 量 `~/.cache/huggingface/hub/models--mlx-community--Qwen3-4B-Instruct-2507-4bit/snapshots/`）。8B 估計約 2 倍，這是估計，沒有查過實際大小。
- 第一次 eval 的峰值已經是 21 GB，離 22 GB 門檻只有 1 GB。換 8B 很可能要降低 `QUERY_MAX_TOTAL_TOKENS`，這會和方案 B 想增加 chunk 名額的方向衝突。
- 只換查詢時用的 LLM、不重建知識庫，技術上可行，因為匯入與查詢的 LLM 是分開呼叫的。但查詢時的關鍵字抽取也會換成 8B，檢索結果也會跟著變。
- 要先量 8B 在 12000 token 下的記憶體峰值，量到之前不能判斷可不可行。

### E. 依文件類別過濾活動頁（不建議）

- 例如題目沒提到「活動」「優惠」時就排除 `offers/` 的 chunk。
- 這是用關鍵字判斷的特例規則。權益類的答案有時只寫在活動頁上，排除之後可能讓別的題目答錯。
- reranker（B）處理的是同一個現象，所以這個方案不另外做。

## 4. 分數表

| 方案 | C1 預期修好 | C2 記憶體 | C3 新套件 | C4 可單獨量測 | C5 工作量 |
|---|---|---|---|---|---|
| A 回答規則 | 推測 terms-01、rule-03（2 題） | 不增加 | 無 | 可：只重跑失敗題 | 小（實驗）；收進設定是中 |
| B reranker | 有機會：terms-02 需要的 chunk 在候選池，但沒證明 reranker 會選它；推測活動頁占位減少 | 增加，未量 | b1 無，b2 未查 | 可：probe 加 eval | 大：另開 spec，使用者已決定要做 |
| C 拆卡查詢 | 未知，要先 probe | 不增加（總上限不變） | 無 | 可：先 probe 子問題 | 大：另開 spec |
| D 8B LLM | 推測 terms-01、rule-03，沒有證據 | 很可能超過 22 GB | 無，要下載模型 | 可，但要先量記憶體 | 中 |
| E 過濾活動頁 | 推測，和 B 重疊 | 不增加 | 無 | 可 | 小，但會產生特例規則 |

## 5. 建議的順序

1. **等第二次 eval 跑完**（目前約 57/100 個查詢），判讀，和第一次比較。後面每一步都以這次的結果當基準。
2. **方案 A 的實驗**：
   - 不改 rag_lab 程式，用一支實驗腳本帶 `user_prompt`，只重跑 mix 模式的 7 題失敗題，加上第一次 eval 在 mix 答對的 4 題（switch-02、benefit-01、fee-02、offer-02）。
   - 每題約 1 分鐘，總共約 11–15 分鐘。
   - 有效，才把它收成一個 `.env` 設定與一張 ticket。
3. **方案 C 的 probe**：只跑檢索，測各卡子問題的覆蓋，約 1 分鐘。結果決定 C 要不要寫 spec。
4. **方案 B 的 spec**：用 grill-with-docs 討論，見第 7 節的問題。
5. **方案 D**：做完 A、B 之後，「答錯」那幾題還沒改善，才去量 8B 的記憶體。

A、C 的實驗都不改程式，只是查詢，各自能單獨量測。2 和 3 會用到 port 8080／8081，要在第二次 eval 跑完之後才做。

## 6. 對抗自查：這個計畫最可能出錯的 3 個地方

1. **回答規則只對這 20 題有效**：規則是看著這幾題的錯寫的，換一批題目不一定有用。
   - 能降低但不能排除：規則用一般性的寫法，不提特定卡名或日期；同時檢查原本答對的題目。
   - 寫進風險欄。
2. **reranker 加上兩個 MLX server，記憶體超過 22 GB**：第二次 eval 的峰值目前是 19 GB，reranker 的用量還沒量，現在無法排除。
   - spec 的驗收要包含：加 reranker 之後跑完整 eval，期間 watchdog 的峰值低於 22 GB。
3. **reranker 把原本答對所依賴的 chunk 排掉**：目前沒有證據，無法排除。
   - 檢驗方式：原本 ✓ 的題目，加 rerank 前後關鍵字句覆蓋不能減少，用 probe 數。

## 7. reranker spec 要討論的問題（下一輪 grill 用）

1. 模型用 b1 還是 b2？我傾向先查 b2 能不能用 mlx-lm 執行；不能就用 b1。
2. reranker 放在哪裡：加進 `scripts/vlm_server.py`（port 8081），還是另開一個程序？
3. 候選池多大（`chunk_top_k`），要不要設最低分數門檻？
4. 哪些模式開 rerank？naive 和 mix 會用到文字 chunk，local、global 的 chunk 也會經過 rerank，要確認。
5. 新設定欄位（開關、endpoint、模型名稱）要放進 `.env`，和現有的 server 設定放在一起嗎？
6. 測試縫：沿用假 OpenAI server，加一個記錄 rerank 請求的 `/rerank` endpoint？

## 8. 實驗結果（2026-11-01）

### 第二次 eval（ticket 13 的 500／500）

- 判讀在 `output/taishin_eval2/judgement.md`。mix 的 ✓ 從 4 題增加到 7 題，驗收從 4/7 類變成 5/7 類；約定條款、跨卡比較仍未通過。
- local、global、hybrid 的 ✓ 減少（4→2、8→4、4→1）。global 的 probe 顯示 relation 從每題 40 個降到 5–11 個，原本答對的 4 題關鍵字句從 12/12 降到 6/12。

### 方案 A：回答規則

- 11 題和第二次 eval 的 mix 相比，✓ 沒有增加也沒有減少；terms-01 仍混入 iCash 條款。判讀在 `output/taishin_eval_promptA/judgement.md`。
- 結論：沒有效果，不收進設定。

### 方案 C：拆成單卡子問題（只跑檢索）

| 題目 | 原題（mix，500／500） | 3 個子問題的 context 合起來 |
| --- | --- | --- |
| cross-01 | 2/3 | 3/3（街口子問題撈到「街口商務鈦金卡」） |
| cross-02 | 0/3 | 2/3（雙幣卡撈到「2.5%」，昇恆昌撈到「總上限2,500」） |

- log 在 `output/taishin_eval2/probe_subq.log` 與 `probe_subq_dualcurrency.log`。
- 「部分歐洲國家實體商店」在 4 個 cross-02 的檢索中都沒有進入 context。
- 雙幣卡子問題第一次的寫法，在抽關鍵字時 4B 模型輸出的 JSON 格式不合法，LightRAG 解析失敗，查詢失敗；換一種寫法後成功。
- 這只證明檢索覆蓋增加；3 份 context 合併後是否放得進 12,000 token、模型能否答對，還沒有測。
