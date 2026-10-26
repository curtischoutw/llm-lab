# 04: 圖譜品質檢視

**What to build:** `ingest` 完成後能看到知識圖譜的實體數與關係數，並抽樣列出實體，讓使用者判斷 4B 的 LLM 抽取品質夠不夠用。本張只交出數據與觀察；是否升級 LLM 由使用者決定。

**Blocked by:** 03

**Status:** resolved

- [x] `ingest` 結束時印出實體數與關係數。
- [x] 能抽樣列出 10 個實體（含名稱與類型或描述），並列出涉及這些實體的關係。
- [x] 針對第一篇已匯入的論文，回報：實體數、關係數、10 個抽樣實體，以及觀察到的問題類型（格式錯誤造成的漏抽、重複實體、無意義實體等），各附實例。
- [x] 回報結尾列出升級選項（LightRAG 官方建議的本地下限為 Qwen3-30B-A3B-Instruct），但不自行更換 LLM 設定；等使用者決定。
- [x] 結論只寫實際看到的內容，不給「品質良好」之類沒有依據的評語。

## 實測結果（2026-10-27）

條件：論文 2410.05779（LightRAG）一篇；LLM `mlx-community/Qwen3-4B-Instruct-2507-4bit`，`LLM_MAX_ASYNC=1`，`--max-tokens 4096`；LightRAG 預設切塊（1200 token）。抽樣輸出存在 `output/ticket04/graph_sample.txt`（gitignore），由 `python -m rag_lab graph`（10 個、seed=0）產生。

**數量**：實體 354，關係 468（其中 RAG-Anything 加的 belongs_to 邊 183，LLM 抽出的關係 285）。

**10 個抽樣實體**（名稱／類型）：Bin Cui／person、Incremental Knowledge Base Update／method、Kangxiang Jia／person、LightRAG Architecture／concept、Luyu Gao／person、Michael Galkin／person、Natural Language Processing／concept、RAG Evaluation Prompt Template (image)／image、Rampášek et al. (2022)／reference、Retrieval-Augmented Generation／concept。涉及這 10 個實體的關係共 24 條，完整內容見抽樣輸出。

**觀察到的問題**

1. 抽取 prompt 的範例內容被當成論文內容寫進圖譜：13 個實體在論文全文出現 0 次，名稱與 LightRAG `prompt.py` 的 few-shot 範例相同。
   - 體育範例 6 個：Noah Carter、100m Sprint Record（描述為「recently broken by Noah Carter」）、World Athletics Championship、Tokyo、Carbon-Fiber Spikes、World Athletics Federation。來源是 `chunk-1fce35…`，內容是參考文獻列表；這個 chunk 也是 ingest 時唯一出現「Complete delimiter can not be found in extraction result」警告的 chunk。
   - 市場範例 7 個：Global Tech Index、Nexon Technologies、Omega Energy、Gold Futures、Crude Oil、Market Selloff、Federal Reserve Policy Announcement。來源是 `chunk-d7ca85…`，內容以 LaTeX 公式為主。
2. 格式錯誤造成的漏抽：ingest log 中格式警告 1 次（上述 `chunk-1fce35…`）。該 chunk 抽出的實體仍寫入圖譜，漏掉多少無法從 log 判斷。
3. 重複實體（名稱只差大小寫、空格或後綴）9 組，例如：`LightRAG`／`LIGHTRAG`／`Lightrag`、`Naive RAG`／`NaiveRAG`、`Graph-Based Text Indexing`／`Graph-based Text Indexing`、`7.3.2 Prompts for Query Generation`／`7.3.2 PROMPTS FOR QUERY GENERATION`、`Graph Construct Prompt`／`Graph Construct Prompt (image)`。
4. 參考文獻的作者被抽成孤立實體：person 類型 118 個，其中 108 個沒有任何關係（全圖孤立實體 121 個）。例如 Steven Truitt、Jonathan Larson、Luyu Gao。
5. 類型為 UNKNOWN 的實體 33 個，例如 Specific Queries、Deduplication、Key-Value Pair、Entity-Relationship Extraction。另有 `Data`（UNKNOWN），描述卻是「The Agriculture Dataset contains 12 documents...」，名稱與描述對不上。
6. 名稱沒有指涉具體對象的實體，例如 `Mathematical Equation`（12 條關係）、`Query`（11 條關係）、`JSON Format`、`Figure 3`～`Figure 7`、`Table 2`～`Table 4`。抽樣中的 `Natural Language Processing` 描述為「a domain where the equation operates」，與論文內容無關。
7. 多次抽取合併的描述（含 `<SEP>`）的實體 55 個；`100m Sprint Record` 的兩段合併描述內容相同。

**升級選項**（未更換設定，由使用者決定）

- 換成 LightRAG 官方建議的本地下限 `Qwen3-30B-A3B-Instruct`：只改 `.env` 的 `LLM_BASE_URL`、`LLM_MODEL`。這台 32 GB 機器在 4B 模型下 ingest 時 wired 記憶體最高 17 GB，能不能同時放下 30B-A3B 與 VLM 尚未驗證。
- 在記憶體較大的機器或雲端端點上跑 LLM，同樣只改上述兩個欄位；換 LLM 不需要重建 embedding 索引，但要刪除 `WORKING_DIR` 重新 ingest，圖譜才會用新模型抽取。
- 維持 4B：上述問題 1、4 會持續出現在參考文獻與公式密集的 chunk。
