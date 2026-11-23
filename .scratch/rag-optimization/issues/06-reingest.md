# 06: 刪除舊知識庫並全量重匯

**What to build:** 使用者確認之後刪除舊知識庫，用新設定（中文、領域實體類型、標頭與依標題切塊、4B embedding、新檔名）全量重匯 `data/taishin_credit_card/`，記錄時間與記憶體（spec：「重匯」；grill-notes 決定 16、17）。

**Blocked by:** 01, 02, 03, 04, 05

**Status:** resolved（2026-11-23 05:47 重匯完成）

- [x] 確認前置條件：`iogpu.wired_limit_mb` 讀到 26000（使用者開機後自己設）；`.env` 已有 `KB_LANGUAGE`、`KB_ENTITY_TYPES`、`DOCUMENT_HEADERS_FILE=data/taishin_credit_card/_meta/document_headers.json`、4B embedding。
- [x] 列出 `rag_storage/` 與 `output/rag_opt/kb_copy/` 的大小與檔案數，以及其他 `output/rag_opt/kb_*` 副本，交使用者確認。確認之前不刪。
- [x] 刪除之後，用 4B embedding 啟動 8081 server（不開 thinking），開 watchdog（`output/crash_repro/tools/watchdog.sh <dir> 27 3`）。
- [x] 依 README 的方式逐一匯入每個類別資料夾。記錄每個資料夾的開始與結束時間、各階段時間、wired 峰值、失敗文件。
- [x] 中途 OOM 或觸發 watchdog：停下來回報，不自行調整上限。
- [x] 完成後記錄 chunk、實體、關係的數量，並和舊知識庫（2,341／18,297／37,027）對照。抽 3 個 chunk 確認開頭有真實的卡片標籤標頭、實體名稱與描述是中文、實體類型是新的 10 類。
- [x] 記錄檔放在 `output/rag_opt/reingest/`（gitignore），結果寫進下方。

## 結果

- 2026-11-20 17:58:34 → 2026-11-23 05:47:46，共 59:49:12。11 個資料夾都 rc=0；325 份 doc status 全是 processed，沒有失敗文件。wired 峰值 25 GB，watchdog（27 GB）沒有觸發，沒有 OOM。
- 各資料夾耗時見 README 第 7 節。log：`output/rag_opt/reingest/`（steps.log、ingest_<資料夾>.log、sampler.log、server.log）。
- 數量：chunk 3,325、實體 11,552、關係 30,463（graphml 節點／邊數一致）；舊知識庫 2,341／18,297／37,027。chunk +42%（依標題切塊、多 31 份），實體 −37%、關係 −18%，原因未查證（中英名稱不再重複，或格式錯誤丟棄變多），由 07 的 eval 看影響。
- 標頭：抽 3 個 chunk 都有卡片標籤；全量掃描 3,300／3,325 有。缺的 25 個是 RAG-Anything 的程式碼（22，多是 MinerU 把「LINE」誤判成程式碼）、公式（2）、圖表（1）分析 chunk，卡片標籤只加在表格與圖片 caption。數量少，不處理。
- 中文：9,248／11,552（80%）實體名稱含中文；其餘多為品牌名與英文圖片描述抽出的實體。
- 實體類型：10 類都有用到（最多：商店或通路 2,536）；另有 `other` 835、`UNKNOWN` 710、RAG-Anything 的 `image`／`table` 1,043、約 50 種零星自創類型，約四分之一不在 10 類內。
- 已知問題（範圍外，另列待辦）：抽取格式錯誤被整筆丟棄（cards 實體 2.1%、關係 5.6%）；44 次抽取輸出寫到 4096 token 上限（重複迴圈或思考文字外漏）；1 張圖片描述解析失敗；模型偶爾把實體名稱寫壞（例：「國ta航空」）。
