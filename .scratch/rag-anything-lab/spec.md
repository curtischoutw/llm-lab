Status: ready-for-agent

# Spec：RAG-Anything 本地實驗專案

## Problem Statement

我想動手建一套 RAG（檢索增強生成）機制，學會從文件解析、建知識圖譜到檢索問答的完整流程，之後把同一套程式搬到別台機器，換成更大的模型與實際應用。應用還沒決定，所以現在不需要產品功能，需要的是一個能重跑、能比較、能搬機器的實驗環境。

目前缺的是：

- 一個固定版本、可重現的 RAG-Anything 環境。
- 一組在這台機器（M2 Pro、32GB）上能跑的本地小模型（LLM、VLM、embedding）。
- 一個批次比較不同檢索模式的方法，讓我判斷圖譜帶來多少幫助，以及之後換模型後效果有沒有變好。
- 一條不綁死在這台機器上的模型接線方式。

## Solution

一個 Python 命令列專案。使用者用 `ingest` 匯入 PDF、用 `query` 提問、用 `eval` 對一組評估題目批次比較五種檢索模式。

三個模型（LLM、VLM、embedding）都透過 OpenAI 相容 HTTP 端點呼叫，端點位址與模型名稱全部寫在 `.env`。本機用 MLX server 提供；搬到別台機器時只改 `.env`，程式碼不動。

第一批測試語料是 3–5 篇 RAG 主題的 arXiv 論文。評估題目由使用者撰寫，專案提供格式範本，並把五種檢索模式的回答輸出成一張 Markdown 對照表，由使用者人工判斷好壞。

## User Stories

1. 作為實驗者，我想用一份 `.env` 設定 LLM、VLM、embedding 三組端點，以便搬到別台機器時只改設定、不改程式。
2. 作為實驗者，我想在啟動時就驗證設定（必填欄位、URL 格式、正整數），以便錯誤在第一步就以清楚訊息中止，而不是在建索引到一半才失敗。
3. 作為實驗者，我想有一份 `.env.example` 列出所有欄位與預設值說明，以便知道每個欄位的用途。
4. 作為實驗者，我想在建任何索引之前先跑冒煙測試，確認 chat、vision（base64 圖片）、embedding 三個端點都可用，以便模型端的問題不會被誤認為 pipeline 的問題。
5. 作為實驗者，我想冒煙測試在任一項失敗時以非零碼結束並印出原始錯誤，以便我決定怎麼處理，而不是被自動繞過。
6. 作為實驗者，我想冒煙測試印出 embedding 的實測維度，以便 `EMBED_DIM` 設定值有依據。
7. 作為實驗者，我想用一個指令把清單中的 arXiv 論文下載到本地資料夾，以便語料可以重現。
8. 作為實驗者，我想下載清單中的每個 arXiv ID 都經過確認，以便抓到的真的是我要的論文。
9. 作為實驗者，我想用 `ingest` 匯入單一 PDF，也能匯入整個資料夾，以便先用 1 篇驗證、再擴充。
10. 作為實驗者，我想 `ingest` 印出每篇論文的解析耗時與建圖耗時，以便評估本地模型的速度與之後換模型的差異。
11. 作為實驗者，我想 PDF 內的圖片、表格、公式都被處理（圖片由 VLM 描述），以便驗證 RAG-Anything 的多模態能力。
12. 作為實驗者，我想重複匯入同一篇論文時不會重複建立資料，以便可以安全重跑。
13. 作為實驗者，我想用 `query` 以指定模式（naive、local、global、hybrid、mix）提問，預設為 mix，以便手動探索各模式的差異。
14. 作為實驗者，我想 `query` 印出答案，以便直接閱讀。
15. 作為實驗者，我想 `eval` 讀一份 JSONL 題目檔，每題跑 naive、local、global、hybrid、mix 五種模式，以便比較圖譜相關模式與純向量檢索（naive）的差異。
16. 作為實驗者，我想 `eval` 輸出一份 Markdown 對照表（每題一列、每種模式一欄，並附參考答案與題型），以便人工判斷哪個模式答得好。
17. 作為實驗者，我想 `eval` 的結果檔以時間戳記命名且不被版本控管，以便多次實驗的結果不互相覆蓋。
18. 作為實驗者，我想題目檔格式包含 id、question、reference、type（text／figure／table／cross-paper）、source，並附 2 筆範例，以便照著寫正式題目。
19. 作為實驗者，我想 `eval` 在單題或單一模式失敗時，在對照表該格標示失敗與原因並繼續其他格，以便一次失敗不會浪費整批已跑完的時間。
20. 作為實驗者，我想 `eval` 結束時以非零碼反映有失敗格，以便腳本能偵測。
21. 作為實驗者，我想查詢時 embedding 對查詢端加 instruction 前綴、對文件端不加，以便符合 Qwen3-Embedding 的使用方式。
22. 作為實驗者，我想 LLM 的最大輸出長度可由設定控制，並且預設夠大，以便實體抽取的輸出不被截斷。
23. 作為實驗者，我想 LLM 並行請求數可由設定控制且預設偏低，以便本地 MLX server 不被打爆。
24. 作為實驗者，我想索引資料、解析輸出、下載的論文、評估結果都放在不進版本控管的資料夾，以便 repo 只含程式與設定。
25. 作為實驗者，我想 `.env`（可能含金鑰）不被版本控管，以便換成雲端 API 時金鑰不會被提交。
26. 作為實驗者，我想相依套件版本被鎖定（RAG-Anything 1.4.3），以便環境可重現。
27. 作為實驗者，我想有一份 README，說明如何啟動兩個本地 server、建立環境、跑 ingest／query／eval，以及搬機器時要改 `.env` 的哪幾項，以便一個月後我還能照著做。
28. 作為實驗者，我想 README 明確寫出 embedding 模型建索引後不能換（換了要重建索引），以便搬機器時不會誤換。
29. 作為實驗者，我想換成更大的 LLM 時只改 `LLM_BASE_URL` 與 `LLM_MODEL`，以便驗證 4B 與大模型在圖譜品質上的差異。
30. 作為實驗者，我想 `ingest` 後能檢視圖譜的實體數與關係數，以便判斷 4B 模型抽取的品質夠不夠。
31. 作為實驗者，我想任一模型端點不可達時，錯誤訊息指出是哪一個端點（LLM、VLM、embedding）與其位址，以便快速定位。
32. 作為實驗者，我想日常測試不需要真的啟動 MLX 模型，以便修改程式後能很快得到回饋。

## Implementation Decisions

**範圍與版本**

- 使用 RAG-Anything 1.4.3，其底層為 LightRAG（目前解析到 1.4.16，限制 `<1.5`）。不使用 LangChain 或 LlamaIndex：RAG-Anything 的依賴中沒有這兩者，解析、切塊、建圖、檢索、生成都已涵蓋。
- Python 3.12.12，用 pyenv 的 Python 建立 venv，以 pip 安裝；不使用 uv。
- 專案已執行 `git init`。

**模型接線（可攜性）**

- 程式碼只透過 OpenAI 相容 HTTP 端點呼叫三個模型，不 import mlx。三組端點（base URL、API key、模型名稱）全部來自設定。
- 設定模組負責讀取 `.env` 與環境變數並驗證；缺漏或格式錯誤時以專用例外中止，不提供預設值掩蓋。
- 模型模組提供三個函式給 RAG-Anything：文字 LLM、看圖 VLM、embedding。沿用官方範例的函式簽名與 VLM 三種輸入分支（messages、單張 base64 圖片、純文字）。使用 lightrag 內建的 OpenAI 相容 helper，不自己重寫 HTTP client。
- 這些函式寫成模組層級，不使用 closure，沿用官方 LM Studio 範例的寫法。

**本地模型選型（本機預設）**

- LLM：`mlx-community/Qwen3-4B-Instruct-2507-4bit`，由 `mlx_lm.server` 提供（port 8080）。必須設定 `--max-tokens 4096`：該 server 預設 512，會截斷實體抽取輸出。
- VLM：`mlx-community/Qwen3-VL-4B-Instruct-4bit`。
- Embedding：`mlx-community/Qwen3-Embedding-0.6B-8bit`，維度實測 1024。
- VLM 與 embedding 在同一個 `mlx_vlm.server`（port 8081）以 `--model` 與 `--embedding-model` 同時載入，已實測可行。mlx-vlm 以 pipx 安裝，與專案 venv 分開，避免與 MinerU、torch 的依賴衝突。
- 呼叫 VLM 時由程式明確帶 `max_tokens`，不依賴 server 預設。

**Embedding**

- embedding 為非對稱：LightRAG 建索引時以 `context="document"` 呼叫、檢索時以 `context="query"` 呼叫。查詢端加上可設定的 instruction 前綴，文件端不加前綴。
- 維度由設定提供並由 LightRAG 的 `EmbeddingFunc` 在每次呼叫時驗證。
- 索引建好後 embedding 模型與維度鎖定；更換需要重建索引。預設的 NanoVectorDB 向量檔名不含模型名或維度（已實測；`model_name` 只對 postgres／qdrant 後端有隔離效果），所以更換 embedding 時必須同時更換儲存資料夾，否則新舊向量會混在同一個庫。

**解析與處理**

- 解析器使用 MinerU（RAG-Anything 預設）；啟用圖片、表格、公式處理。
- MinerU 版本限制在 4 以下（`mineru[core]<4`，目前 3.4.5）：RAG-Anything 1.4.3 以舊版 CLI 參數呼叫 MinerU，4.x 已改成 `mineru parse`，且版本檢查仍會通過、到解析時才失敗。這是已在環境中處理好的決定。
- RAG-Anything 以 subprocess 依 PATH 尋找 `mineru`；CLI 必須確保專案 venv 的 bin 目錄在 PATH 上，使用者不需要先 activate。
- 並行度（`LLM_MAX_ASYNC`）預設設為 1–2，實測後再調整。圖片、表格、公式描述的並行度另受 `max_parallel_insert` 控制，不受 `LLM_MAX_ASYNC` 限制。

**失敗偵測（RAG-Anything／LightRAG 會吞錯誤，已實測）**

- `aquery` 在 LLM 失敗時回傳 `None`，非法模式也回傳 `None`；預設的 VLM 路徑則拋出無意義的 `TypeError`。所有需要判斷成功與否的查詢（`query`、`eval`）改用 LightRAG 的 `aquery_llm`，它回傳 `status` 與含原例外文字的 `message`。模式合法值由 CLI 自己檢查。
- 匯入時 LLM 或 embedding 失敗會拋錯，但訊息不含端點名稱；「指出是哪個端點」要由我們在模型函式外層加上端點名稱。
- **VLM 失敗不會讓匯入失敗**：圖片描述會變成原始 dict 的 fallback 文字，匯入仍標示成功。因此「圖片描述來自 VLM」必須主動驗證（在 vision 函式內計數成功次數，或檢查 chunk 內容不是 fallback）。
- 重複匯入：文件 ID 由內容雜湊產生（含圖片絕對路徑），所以搬動專案目錄或更改解析輸出資料夾會被當成新文件。重複匯入同一份不會重呼叫模型，但單檔路徑會留下 `failed` 的重複紀錄，並讓原文件卡在 `handling`，之後 `get_status_counts()` 拋 `KeyError`。避免方式：先解析取得文件 ID，已完整處理就不再呼叫匯入。

**查詢行為**

- `vlm_enhanced` 預設開啟，且適用所有模式（含 naive）：只要檢索內容含可用圖片，最終答案就改由 VLM 產生。這會讓五種模式的答案由不同模型產生，混淆比較。`eval` 一律固定 `vlm_enhanced=False`，只讓檢索模式這個變因變動；`query` 預設也關閉，需要時用選項開啟。
- 查詢一律傳 `enable_rerank=False`（預設為開，沒有 rerank 模型時每次查詢都警告）。
- 圖片安全目錄檢查的是設定中的解析輸出資料夾，不是匯入呼叫傳入的輸出資料夾，兩者必須指向同一處，否則 VLM 增強會靜默失效。
- 實體與關係統計時，RAG-Anything 會額外加入 `belongs_to` 類型的邊（關鍵字 `belongs_to,contained_in,part_of`）；回報關係數時要說明是否包含這些邊。

**CLI 介面**

- `ingest <路徑>`：路徑可為單一 PDF 或資料夾；印出各階段耗時。
- `query "<問題>" [--mode MODE]`：預設 mix。
- `eval <題目檔>`：每題五種模式，輸出 Markdown 對照表到有時間戳記的結果檔。單一格失敗時在表中標示失敗與原因，其餘繼續，整體以非零碼結束。

**語料與評估**

- 語料為 3–5 篇 RAG 主題的 arXiv 論文，由實作者挑選。候選：RAG（2005.11401）、GraphRAG（2404.16130）、LightRAG（2410.05779）、Self-RAG（2310.11511）、RAG-Anything（ID 待查）。下載前需逐一確認 ID 與標題相符。
- 評估題約 10 題，涵蓋純文字、圖表、跨論文三類，由使用者撰寫；專案只提供 JSONL 格式範本（欄位：id、question、reference、type、source）。不使用 LLM 當評審，一律人工判斷。

**失敗處理原則**

- 任一模型端點在冒煙測試失敗（例如 VLM 不接受 base64 圖片、embedding 端點不支援該模型架構）時，停下來回報，附錯誤輸出與可行選項；不自行更換框架、不寫 workaround。

**安全與依賴**

- 外部輸入（設定、題目檔、命令列路徑、端點回應）先驗證再使用。
- 金鑰只來自 `.env`／環境變數，不進程式碼、log、錯誤訊息。
- 第三方依賴僅限 RAG-Anything 及其帶入的套件；`python-dotenv` 與 `openai` 已由其帶入。新增其他依賴前先回報使用者。

## Testing Decisions

- **測試縫只有一個：CLI（`ingest`／`query`／`eval`）。** 測試從 CLI 進入，對三個 OpenAI 相容 HTTP 端點出去，不為設定、模型函式等內部模組另開縫。
- **好測試的標準**：只驗證外部可觀察的行為，包括結束碼、標準輸出／錯誤、產生的檔案（例如 `eval` 的 Markdown 對照表、索引資料夾是否產生），不驗證內部函式呼叫或私有狀態。
- **快速測試**：CLI 對一個假的 OpenAI 相容 server（回傳固定的 chat、vision、embedding 回應，embedding 維度與設定一致）。涵蓋：設定缺漏時中止、`eval` 單格失敗時整體非零碼且表中標示、題目檔格式錯誤時拒絕、`ingest` 重複匯入不重複建立。
- **端到端驗證**：對真實本地 MLX server 執行冒煙測試（三個端點）及 1 篇論文的 `ingest`，再各模式 `query` 一次，最後以範例題目檔跑 `eval`。
- **既有範例（prior art）**：目前只有冒煙測試腳本，已對真實 server 實測通過（chat、vision、embedding 維度 1024）；沒有其他自動化測試。

## Out of Scope

- LangChain、LlamaIndex，以及 agent 化（把 RAG 包成工具）。
- Web UI 與 LightRAG Server；本專案只提供 CLI。
- Reranker。
- 雲端模型（雖然因為端點可換，之後可以直接使用）。
- LLM 當評審的自動評分。
- Office 檔案與 HTML 的解析（只處理 PDF；LibreOffice 與 Docling 都不安裝）。
- 實際應用場景與產品化。
- 部署到別台機器（本 spec 只要求做到「只改 `.env` 即可搬」）。

## Further Notes

**實作現況**（以此為起點，避免重做）：

- 已完成並驗證：mlx-vlm 以 pipx 安裝；Qwen3-VL-4B 與 Qwen3-Embedding-0.6B 已下載；冒煙測試腳本已寫好，三項全過。
- 專案已建立 Python 3.12.12 的 venv，並安裝 `raganything==1.4.3`；已寫好設定模組與模型模組。
- 尚未實作：pipeline 模組、CLI、`.env.example`、`.gitignore`、論文下載腳本、評估範本、README，以及快速測試。
- 先前的對話中，兩個本地 server 在背景執行中（8080 為 LLM，8081 為 VLM 與 embedding），尚未提交任何 git commit。

**對原計畫的兩項修正**：

1. 原計畫認為 Qwen3-Embedding 的檢索品質會因為「不區分查詢與文件」而打折，此限制不成立；LightRAG 支援非對稱 embedding（`context` 參數與查詢前綴）。
2. `mlx_lm.server` 預設輸出上限 512 tokens 會截斷實體抽取，必須明確設為 4096。

**已知風險**：

- 4B 的 LLM 低於 LightRAG 官方建議的本地下限（Qwen3-30B-A3B-Instruct），圖譜品質可能不佳。已接受此取捨；升級路徑是把 LLM 換成該下限模型。第一篇論文的 `ingest` 後要檢視實體與關係的品質，作為判斷依據。
- MinerU 在沒有 CUDA 的 Mac 上解析 PDF 的速度尚未實測。
- 以 base64 圖片餵給 mlx-vlm 的行為已實測通過（單張純色圖）；真實論文中的圖表描述品質尚未驗證。
