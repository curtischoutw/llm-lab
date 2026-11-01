# 01: 匯入報告的各階段時間和文件耗時用同一個時鐘

**What to build:** 使用者看 `ingest` 的報告（CLI 輸出與 Python API 的 `IngestSummary`）時，每份文件的解析、建圖、多模態三個階段時間，和文件耗時用同一個時鐘量測，不含 Mac 睡眠的時間。現在的報告裡，Mac 中途睡眠時，階段時間會比文件耗時還長。2026-10-31 實測：`attachment_SPECIAL_2026.pdf` 的文件耗時 2,911.5 s，多模態階段 11,333.6 s，原因是 19:00 到 21:25 合蓋睡眠。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 三個階段時間由 rag_lab 自己量，用 RAG-Anything 的開始與完成 callback（`on_parse_start`／`on_parse_complete`、`on_text_insert_start`／`on_text_insert_complete`、`on_multimodal_start`／`on_multimodal_complete`），時鐘和文件耗時相同（`time.perf_counter`），不再使用 callback 傳來的 `duration_seconds`。
- [x] 同一份文件的三個階段時間加總，不超過該文件的耗時。
- [x] 解析快取命中、文件略過、匯入失敗時，報告的欄位和現在一樣（略過的文件仍只有解析時間）。
- [x] 報告或 README 寫明：時間不含電腦睡眠的時間。
- [x] 測試沿用既有的縫（CLI 子行程＋Python API）。驗證「階段時間加總不超過文件耗時」，且每個階段時間都不是負數。
- [x] 現有測試全綠。

## 已查到的事實（RAG-Anything 1.4.3）

- `raganything/processor.py` 用 `time.time()` 算各階段的 `duration_seconds`（第 653、676、899、979、2083、2111 行等），這是牆上時間，包含睡眠。
- rag_lab 的文件耗時用 `time.perf_counter()`（`rag_lab/pipeline.py` 第 548、554 行）。在 macOS 上，`perf_counter` 不含系統睡眠的時間。
- `rag_lab/pipeline.py` 的 `StageTimer` 目前只接 `on_parse_complete`、`on_text_insert_complete`、`on_multimodal_complete`，讀的是 `duration_seconds`。解析時間只記第一次，因為 `process_document_complete` 裡第二次 parse 是快取命中，這個規則要保留。

ASSUMPTION：統一成「不含睡眠」。理由：報告用來比較各份文件的處理量，睡眠時間和文件無關。

## Comments

ASSUMPTION（實作時加）：
- 測試模擬「睡眠」的方式：子行程的 `PYTHONPATH` 放 `tests/wall_clock_fast/`，其 `sitecustomize.py` 把 `time.time` 換成走得快 1000 倍的版本，`time.perf_counter` 不動。理由：測試不能真的讓機器睡眠，而舊實作用 `time.time` 量階段，這樣能讓測試在舊實作下失敗（階段加總 562 s、文件耗時 0.6 s）、新實作下通過。
- CLI 測試的報告只印到小數一位，所以「階段加總不超過耗時」的比較容許 0.2 s 的進位誤差（三個階段各最多進位 0.05、耗時最多捨去 0.05）；Python API 測試比較未進位的浮點數，沒有容許值。
- 階段的開始 callback 在 RAG-Anything 提早返回時（多模態已處理過）也會發出，但沒有對應的完成 callback；`StageTimer` 只在完成 callback 才把「完成時刻減開始時刻」加進去，所以這種情況不計時間，和改之前的行為相同。
- README 只在第 4 節加一條說明，不改第 5 節以前實測紀錄裡的數字。

## 實作結果

- `rag_lab/pipeline.py` 的 `StageTimer` 改接 `on_parse_start`、`on_text_insert_start`、`on_multimodal_start` 記 `time.perf_counter()`，在對應的完成 callback 相減；不再讀 `duration_seconds`。解析時間仍只記第一次（第一次 `on_parse_start` 才記開始時刻、`parse_seconds` 設定後忽略之後的 parse callback）。
- 略過、失敗的欄位不變：略過的文件只有解析時間，失敗的文件三個階段都是 0.0（`tests.test_python_api.IngestStageTimingTest` 有測）。
- 測試：`tests/test_pipeline.py` 的 `IngestTest`（CLI）一個、`tests/test_python_api.py` 的 `IngestStageTimingTest`（Python API）三個；夾具在 `tests/wall_clock_fast/sitecustomize.py`。四個測試在舊實作下都失敗（紅）。
- 文件：`README.md` 第 4 節新增一條「匯入報告的時間不含電腦睡眠」；`docs/architecture.md` 更新 `ingest` 回傳說明、測試檔說明與夾具表。
