# 02: MinerU 讀的 `MINERU_*` 環境變數也會改變匯入結果，要決定要不要納入拒絕名單

**What to build:** 使用者執行 `ingest` 時，環境變數或 `.env` 裡的 `MINERU_*` 變數（例如 `MINERU_TABLE_ENABLE`、`MINERU_FORMULA_ENABLE`、`MINERU_DEVICE_MODE`）會傳到 MinerU 子行程，改變解析結果（表格、公式有沒有被辨識），但 rag_lab 不會報錯，匯入報告也看不出來。ticket 01 的拒絕名單只涵蓋 lightrag-hku 與 raganything 原始碼讀的變數，沒有這些。這張先調查，再照 ticket 01 的做法（拒絕啟動）決定哪些要收進名單。

**Blocked by:** 01（已完成）

**Status:** ready-for-agent

- [ ] 從已安裝的 MinerU 原始碼產生完整清單：所有讀取的 `MINERU_*` 變數（包含 `os.getenv`、`os.environ.get`、`os.environ[...]` 等寫法），每個變數附檔案:行號與預設值。
- [ ] 分類：會改變解析結果的（例如表格、公式、OCR 的開關），只影響效能或記錄的（例如 log 等級、執行緒數、`MINERU_API_*`、`MINERU_GRADIO_*`）。分類理由寫在 ticket 裡。
- [ ] 確認 rag_lab 呼叫 MinerU 時（RAG-Anything 以子行程執行 `mineru`），哪些變數實際會被讀到：rag_lab 用的後端與解析方法只走其中一部分程式路徑。
- [ ] 會改變解析結果、且實際會被讀到的變數，收進 ticket 01 的名單：出現在環境變數或 `.env` 時，`ingest` 與 Python API 的匯入失敗，訊息只列名稱、不含值。
- [ ] 查詢（`query`、`eval`）不呼叫 MinerU：決定這些變數在查詢時要不要也拒絕，寫出理由。
- [ ] README 的名單段落加上這些變數與 MinerU 版本；升級 MinerU 時要重新產生。
- [ ] 測試沿用 ticket 01 的縫（CLI 子行程＋Python API），現有測試全綠。

## 已知的事實（2026-11-02）

- ticket 01 的 implementer 回報：MinerU 子行程繼承 rag_lab 行程的環境；rag_lab 的 `load_dotenv()` 會把 `.env` 的內容放進行程環境，所以 `.env` 裡的 `MINERU_*` 也會傳到子行程。
- 已安裝的 MinerU 是 3.4.5（`.venv`）。用 `os.getenv(` 與 `os.environ.get(` 兩種寫法搜尋，找到 25 個不同的 `MINERU_*` 名稱，例如 `MINERU_TABLE_ENABLE`、`MINERU_FORMULA_ENABLE`、`MINERU_TABLE_MERGE_ENABLE`、`MINERU_VLM_TABLE_ENABLE`、`MINERU_DEVICE_MODE`、`MINERU_TOOLS_CONFIG_JSON`。`os.environ[...]` 與其他寫法沒有搜尋，這份清單不完整。
- 已經匯入、解析快取命中的文件不會重新解析，所以這些變數只影響新匯入或解析快取沒命中的文件。

## Comments
