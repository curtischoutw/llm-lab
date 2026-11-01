# 01: 匯入報告的各階段時間和文件耗時用同一個時鐘

**What to build:** 使用者看 `ingest` 的報告（CLI 輸出與 Python API 的 `IngestSummary`）時，每份文件的解析、建圖、多模態三個階段時間，和文件耗時用同一個時鐘量測，不含 Mac 睡眠的時間。現在的報告裡，Mac 中途睡眠時，階段時間會比文件耗時還長。2026-10-31 實測：`attachment_SPECIAL_2026.pdf` 的文件耗時 2,911.5 s，多模態階段 11,333.6 s，原因是 19:00 到 21:25 合蓋睡眠。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 三個階段時間由 rag_lab 自己量，用 RAG-Anything 的開始與完成 callback（`on_parse_start`／`on_parse_complete`、`on_text_insert_start`／`on_text_insert_complete`、`on_multimodal_start`／`on_multimodal_complete`），時鐘和文件耗時相同（`time.perf_counter`），不再使用 callback 傳來的 `duration_seconds`。
- [ ] 同一份文件的三個階段時間加總，不超過該文件的耗時。
- [ ] 解析快取命中、文件略過、匯入失敗時，報告的欄位和現在一樣（略過的文件仍只有解析時間）。
- [ ] 報告或 README 寫明：時間不含電腦睡眠的時間。
- [ ] 測試沿用既有的縫（CLI 子行程＋Python API）。驗證「階段時間加總不超過文件耗時」，且每個階段時間都不是負數。
- [ ] 現有測試全綠。

## 已查到的事實（RAG-Anything 1.4.3）

- `raganything/processor.py` 用 `time.time()` 算各階段的 `duration_seconds`（第 653、676、899、979、2083、2111 行等），這是牆上時間，包含睡眠。
- rag_lab 的文件耗時用 `time.perf_counter()`（`rag_lab/pipeline.py` 第 548、554 行）。在 macOS 上，`perf_counter` 不含系統睡眠的時間。
- `rag_lab/pipeline.py` 的 `StageTimer` 目前只接 `on_parse_complete`、`on_text_insert_complete`、`on_multimodal_complete`，讀的是 `duration_seconds`。解析時間只記第一次，因為 `process_document_complete` 裡第二次 parse 是快取命中，這個規則要保留。

ASSUMPTION：統一成「不含睡眠」。理由：報告用來比較各份文件的處理量，睡眠時間和文件無關。

## Comments
