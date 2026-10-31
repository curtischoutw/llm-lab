# 12: 大表格拆成小表，表格描述失敗時文件記成失敗

**What to build:** 匯入時，太大的表格不能讓 LLM server 記憶體不足而停掉。匯入前先縮短表格，太大的再拆成幾張小表，每張都有描述，內容全部保留。圖、表、公式的描述，或多模態內容寫入索引，只要有一項失敗，那份文件就記成失敗：重新執行時會重試，不會被當成已完成而略過。

**Blocked by:** None（10、11 已合併）

**Status:** ready-for-agent

## 背景（2026-10-31 實測）

- 道路救援 PDF `attachment_SPECIAL_2026.pdf` 只有一張表：80 列 × 21 欄的特殊地區清單。
  - MinerU 轉成 46,786 字元的 HTML。多數字元是 `rowspan=1 colspan=1` 這類預設值屬性：拿掉之後剩 18,606 字元，儲存格的純文字只有 5,820 字。
- RAG-Anything 把整張表放進同一個描述 prompt，共 20,731 token。mlx_lm.server 回報 `[METAL] ... Insufficient Memory` 後停止產生，wired 記憶體升到 23 GB，watchdog 依 22 GB 門檻關掉兩個 server。
  - 全量匯入的 286 份文件，最大的 prompt 是 7,099 token。查詢的 `QUERY_MAX_TOTAL_TOKENS=12000` 在同一組 server 上跑得過。
- 表格描述失敗與多模態內容寫入失敗（embedding 回 500）都被 RAG-Anything 吞掉，文件仍標成 processed，而且 `multimodal_processed=True`。結果知識庫裡只有 301 字的說明文字，沒有那張表，重新執行時又會被略過。
  - 這份文件的紀錄已在使用者確認後刪除。解析快取與 `output/attachment_SPECIAL_2026_894c2754/` 保留，實作時可以拿來驗證。

## 使用者決定（2026-10-31）

- 表格太大時拆成小表，內容全部保留，每張小表都要有描述。不截斷，也不跳過。
- 描述失敗的文件記成失敗，不再標成已完成。這取代原本「匯入完成但描述失敗，請刪除整個 WORKING_DIR 與 PARSER_OUTPUT_DIR 後重匯」的做法。

## 驗收

- [ ] 表格縮短不改內容：拿掉值為 1 的 `rowspan`／`colspan` 這類預設值屬性，儲存格文字與合併儲存格的結構不變。
- [ ] 縮短後仍超過上限的表格，按列切成幾張小表，每張都重複表頭列，每張都送去描述，原表的每一列都出現在某一張小表裡。
  - 上限用 LightRAG 的 tokenizer 計算。上限取多少、為什麼，寫在 docstring 與實作結果裡。目標是表格描述 prompt 與那個 chunk 的實體抽取 prompt，都不超過全量匯入時實際成功過的大小（7,099 token），或明確說明為什麼可以更大。
  - 表頭怎麼判斷（例如第一列）標 ASSUMPTION。
- [ ] 已匯入的文件不受影響：
  - 文件 ID 與解析快取 key 不變；
  - 已完整處理的文件重新匯入時照常略過，不呼叫模型；
  - 表格不大的文件，送去描述的內容和現在一樣。
- [ ] 圖、表、公式的描述失敗，或多模態內容寫入索引失敗時：
  - 那份文件在報告裡是失敗，並寫出原因；
  - 結束碼非零；
  - 重新執行時這份文件會重試，不會被略過；
  - 同一批的其他文件照常匯入。
- [ ] `description_error` 原本建議刪除整個 `WORKING_DIR` 與 `PARSER_OUTPUT_DIR`，這段訊息要改成符合新行為。改動用到的測試、README 第 4 節與 `docs/architecture.md` 的說明一併更新。
- [ ] 以 CLI 子行程與 Python API 兩個既有的縫測試。
  - 假 mineru 可以加一種主檔名前綴，輸出一張大表格；假 OpenAI server 記錄收到的請求，測試用它檢查每個描述 prompt 的大小與小表的數量。
  - 描述失敗與寫入失敗要用假 server 模擬。
- [ ] 主測試套件全綠。
- [ ] 實機驗證：主對話用真的 server 重匯 `attachment_SPECIAL_2026.pdf`，確認 server 沒有停掉、最大的 prompt 在上限內、小表的描述都寫進知識庫。這一項由主對話做，implementer 不跑真的 server。
