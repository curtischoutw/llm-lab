# 12: 大表格拆成小表，表格描述失敗時文件記成失敗

**What to build:** 匯入時，太大的表格不能讓 LLM server 記憶體不足而停掉。匯入前先縮短表格，太大的再拆成幾張小表，每張都有描述，內容全部保留。圖、表、公式的描述，或多模態內容寫入索引，只要有一項失敗，那份文件就記成失敗：重新執行時會重試，不會被當成已完成而略過。

**Blocked by:** None（10、11 已合併）

**Status:** resolved

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

- [x] 表格縮短不改內容：拿掉值為 1 的 `rowspan`／`colspan` 這類預設值屬性，儲存格文字與合併儲存格的結構不變。
- [x] 縮短後仍超過上限的表格，按列切成幾張小表，每張都重複表頭列，每張都送去描述，原表的每一列都出現在某一張小表裡。
  - 上限用 LightRAG 的 tokenizer 計算。上限取多少、為什麼，寫在 docstring 與實作結果裡。目標是表格描述 prompt 與那個 chunk 的實體抽取 prompt，都不超過全量匯入時實際成功過的大小（7,099 token），或明確說明為什麼可以更大。
  - 表頭怎麼判斷（例如第一列）標 ASSUMPTION。
- [x] 已匯入的文件不受影響：
  - 文件 ID 與解析快取 key 不變；
  - 已完整處理的文件重新匯入時照常略過，不呼叫模型；
  - 表格不大的文件，送去描述的內容和現在一樣。
- [x] 圖、表、公式的描述失敗，或多模態內容寫入索引失敗時：
  - 那份文件在報告裡是失敗，並寫出原因；
  - 結束碼非零；
  - 重新執行時這份文件會重試，不會被略過；
  - 同一批的其他文件照常匯入。
- [x] `description_error` 原本建議刪除整個 `WORKING_DIR` 與 `PARSER_OUTPUT_DIR`，這段訊息要改成符合新行為。改動用到的測試、README 第 4 節與 `docs/architecture.md` 的說明一併更新。
- [x] 以 CLI 子行程與 Python API 兩個既有的縫測試。
  - 假 mineru 可以加一種主檔名前綴，輸出一張大表格；假 OpenAI server 記錄收到的請求，測試用它檢查每個描述 prompt 的大小與小表的數量。
  - 描述失敗與寫入失敗要用假 server 模擬。
- [x] 主測試套件全綠。
- [x] 實機驗證：主對話用真的 server 重匯 `attachment_SPECIAL_2026.pdf`，確認 server 沒有停掉、最大的 prompt 在上限內、小表的描述都寫進知識庫。這一項由主對話做，implementer 不跑真的 server。

## 實作結果（2026-10-31）

**做了什麼**
- `rag_lab/tables.py`（新）：`limit_table_sizes(content_list, count_tokens)`。`table_body` 超過 `TABLE_BODY_MAX_TOKENS = 800` 的表格，先拿掉值為 1 的 `rowspan`／`colspan`；縮短後仍超過，依列切成小表，每張重複表頭列，每張是 content list 裡獨立的一個 table 項目（`table_caption` 多一句「第幾張／共幾張」）。800 以內的表格是原物件，一個字元都不改。
- `rag_lab/pipeline.py`：新增 `LabRAGAnything(RAGAnything)`，`build_rag` 改用它。
  - 覆寫 `parse_document`：呼叫 RAG-Anything 原本的 `parse_document`（它依原始 content list 算好文件 ID、存好解析快取）之後，才對回傳的 content list 套用 `limit_table_sizes`，tokenizer 是 `self.lightrag.tokenizer`。
  - 覆寫 `_process_multimodal_content_batch_type_aware`：失敗時 `models.record_write_failure` 計數再原樣重拋（RAG-Anything 隨後吞掉這個例外、改走逐項處理的備援流程，仍標成已完成）。
  - `_ingest_one` 比對匯入前後的失敗計數，有增加就在 `report.error` 寫出原因；`_ingest` 在整批結束後呼叫 `_mark_swallowed_failures`，把這些文件在索引裡改記成 `failed`（`multimodal_processed=False`）。重新執行時 `is_document_fully_processed` 為 False，走原本「清掉舊紀錄再重匯」的路徑。
  - `IngestSummary.description_error` 的訊息改成：N 份文件已記成失敗，修好端點後重新執行同一個 ingest 就會重試，不需要刪除 `WORKING_DIR` 或 `PARSER_OUTPUT_DIR`；`IngestReport` 多 `write_failed` 與 `doc_id`。
- `rag_lab/models.py`：`DescriptionStats` 多 `write_failed`、`last_write_error`；新增 `record_write_failure`、`failure_counts`、`describe_failures`。`rag_lab/__main__.py`：拿掉已不會走到的「其中 N 項描述失敗」一行（有失敗的文件現在是 `匯入失敗` 一行）。
- 測試夾具：`tests/fake_mineru.py` 的 `bigtable`（60 列 × 6 欄、儲存格帶 `rowspan=1 colspan=1`、一組 rowspan=2）、`bigspan`（第 20 列第一格 rowspan 跨到表尾）、`spans`（小表格帶預設屬性）三個主檔名前綴；`tests/fake_openai_server.py` 多 `fail_embed_containing`（輸入含指定字串的 embeddings 請求回 500）。
- README 第 4 節、`docs/architecture.md`（依賴圖、`tables.py` 一列、`pipeline.py`／`models.py`／fake 夾具／`ingest` 錯誤說明）已更新。

**掛勾點：選了哪一種、理由**
- 選：子類別覆寫 `parse_document`，改的是回傳給呼叫端的 content list。理由：文件 ID 與解析快取在 RAG-Anything 內部早就依原始內容算好、存好，所以 ID、快取 key、快取內容都不用特別處理就維持原樣（`already_imported.py` 與測試驗證）；`process_document_complete` 與 `_ingest_one` 都經由 `parse_document` 取得 content list，一處掛勾涵蓋兩條路徑；每張小表是獨立項目，描述 prompt、表格 chunk、實體抽取 prompt 三個地方同時變小。約 15 行。
- 不選：
  - 包住 table processor（`generate_description_only`／`generate_chunk_sections`）：`table_body` 同時被放進描述 prompt 與 `table_chunk`（實體抽取的輸入），批次處理與逐項備援是兩條不同的路徑（`generate_chunk_sections` 與 `process_multimodal_content`），要改三處；只縮小描述 prompt，chunk 仍是整張表。
  - 自己呼叫 `insert_content_list`：繞過 `process_document_complete` 的 callback、doc_status 與錯誤處理，等於重寫流程。
  - 改解析快取或 MinerU 的輸出檔：快取內容與 key 變了，已匯入的文件會被重新解析，違反限制。
  - 改 `.venv` 裡的 RAG-Anything：不允許。

**上限值：800 token（`table_body` 字串本身，LightRAG tokenizer）**
- 描述 prompt ＝ 範本 228 ＋ 系統提示 15 ＋ 前後文（RAG-Anything `max_context_tokens` 預設 2000，只含文字區塊）＋ 表格，表格 800 時最多約 3,100 token。
- 實體抽取 prompt ＝ 系統提示含範例約 3,200 ＋ chunk（範本 39 ＋ 表格 ＋ 描述）；有 gleaning 時再加第一次回覆與 394 的續問。LightRAG 文字 chunk 預設 1,200 token，全量匯入時 7,099 的最大 prompt 推測就是這種 chunk 加 gleaning（沒有逐個 prompt 紀錄，推測）。表格 800 ＋ 描述約 400 ＝ 1,200，量級相同。800 比 1,200 保守，是因為描述的長度無法在不呼叫模型時量。
- 實測（`/Users/curtis/.claude/jobs/db9cfed9/tmp/t12/real_table.py`，只讀）：道路救援那張表 46,786 字元／21,515 token → 縮短後 18,606 字元／13,061 token → 切成 25 張小表，每張 661–780 token，最大一張 780；79 列資料列都在某一張小表，順序不變，儲存格文字與合併結構不變。
- 副作用：25 張小表是 25 次描述呼叫與 25 個 chunk，不是 1 次；表頭每張重複約 100 token。

**ASSUMPTION**
- 表頭是第一列（第一列的 rowspan 跨到的列也算表頭）。道路救援那張表第一列是「縣市／鄉鎮區／名稱」的欄位標題，符合。
- 表格描述的 JSON 約 400 token（上限值的推算依據，未驗證）。
- 切到被 rowspan 連住的列時，先退回到最近的「一組列」起點再切；一組列單獨就超過上限（道路救援那張表的第 24 列有一個空儲存格 rowspan=57，跨到表尾）時才從中間切開，跨過來的儲存格在下一張小表的第一列補一份（文字相同、rowspan 縮短），欄位位置維持對齊。代價：跨列儲存格的文字在兩張小表各出現一次（那個 rowspan=57 的格子是空的）。
- 描述失敗與寫入失敗的文件在整批結束後才改記成 `failed`：LightRAG 每次插入新文件時，會順便重跑索引裡 `failed` 的文件並把狀態改回 `processed`（不帶 `multimodal_processed`）。實測在批次途中改記時，後面文件的插入把它蓋掉，狀態統計變成 `processed=2`。批次中途被中斷（Ctrl-C）時，還沒改記的文件仍是 `processed`，重跑會略過。

**紅燈時的輸出**
- `tests.test_pipeline.OversizedTableTest.test_a_big_table_is_described_as_several_small_tables_...`：`AssertionError: 1 not greater than 1 : 太大的表格應該拆成多張小表，每張各送一次描述`
- `...test_default_span_attributes_are_dropped_but_real_spans_stay`：`AssertionError: 'rowspan=1' unexpectedly found in '<table><tr><td rowspan=1 colspan=1>H0</td>...`
- `tests.test_pipeline.DescriptionFailureTest` 4 個測試：`AssertionError: '匯入失敗：paper.pdf' not found in ...`（表格描述失敗）、`'寫入' not found in ...`（embedding 失敗）、`'匯入失敗：bigtable\\.pdf' not found`（同批其他文件）。
- 加上 `tests/test_python_api.py` 的 `OversizedTableTest`（Session 與模組函式各一）。
- 特徵化測試在修改前就是綠燈，目的是證明沒動到：`test_a_small_table_is_described_with_its_body_unchanged`、`test_document_id_and_parse_cache_come_from_the_original_table`、`test_reingesting_a_document_with_a_big_table_skips_it_and_calls_no_model`、`test_rows_joined_by_a_rowspan_stay_in_the_same_small_table`。
- 做出來才發現的問題：第一版把被 rowspan 連在一起的列當成不可拆的單位，真實表格的最後一張小表因此有 9,193 token（rowspan=57）；改成上面的做法，並加了 `bigspan` 測試。批次中途改記 `failed` 被後面的文件蓋掉（見 ASSUMPTION），改成整批結束後再改，`test_other_documents_in_the_same_batch_are_still_ingested` 確認。

**最後一次測試**
- 主套件 `/Users/curtis/GitHub/llm-lab/.venv/bin/python -m unittest`：`Ran 136 tests in 535.120s` / `OK`。
- 一次性驗證（沒進 repo，`already_imported.py`）：用 integration 分支的程式碼（`git archive` 展開）匯入 `bigtable.pdf` 與 `paper.pdf`，再用本分支重匯：兩份都「已完整處理過，略過」，模型請求數不變（50），doc_status 與解析快取（key 與內容）逐項相同。

**沒做到或有疑慮**
- 實機驗證（真的 server、真的 MinerU 與道路救援 PDF）沒做，留給主對話。尤其要確認：25 張小表的描述都成功、最大 prompt 在範圍內、25 個 chunk 的實體抽取時間可接受。
- 已知極限：只處理 HTML 的 `table_body`；表頭本身或單獨一列超過 800 token 時沒辦法再拆。
- 寫入失敗的計數掛在 RAG-Anything 的私有方法 `_process_multimodal_content_batch_type_aware`，改記狀態用私有方法 `_upsert_doc_status`；升級 RAG-Anything 時要檢查這兩個。批次處理失敗後備援的逐項處理若成功，文件仍記成失敗（保守，重跑時 LLM 快取讓重做便宜）；逐項處理自己的單項失敗不另外計數。
- ticket 12 之前匯入、而且描述失敗過的文件，仍是 `processed`＋`multimodal_processed=True`，不會自動重試（README 已寫明）。

## 實機驗證（2026-10-31，主對話）

合併到 integration（51bba3e）之後，用真的 server 單獨重匯 `attachment_SPECIAL_2026.pdf`。log 在 `output/taishin_full/ingest_special_2026.log`，server log 在 `output/taishin_full/lm_server3.log`，watchdog 在 `output/taishin_full/watchdog3/`。

- 結束碼 0。`Generated descriptions for 25/25 multimodal items`，沒有描述失敗，也沒有寫入失敗。
- 文件狀態是 processed，有 26 個 chunk（1 段文字、25 張小表），`multimodal_processed=True`。
- 從 server 重開、刪除紀錄到這次重匯結束，LLM server 收到的最大 prompt 是 4,293 token。出事那次是 20,731，全量匯入的最大值是 7,099。
- wired 記憶體最高 12 GB，兩個 server 都還在執行。
- 報告寫這份文件耗時 2,911.5 s，多模態階段卻是 11,333.6 s，比文件耗時還長。原因是 19:00 到 21:25 Mac 合上蓋子，進入睡眠：
  - 文件耗時用 `time.perf_counter`，不計睡眠的時間；
  - 各階段的計時含睡眠。
  - 這是範圍外的觀察，沒有修。
- 圖譜從實體 14,184、關係 28,301，增加到實體 15,321、關係 30,404。增加的部分包含權益附件其他 8 份。
- 附帶發生的事：上次被中斷而卡在 processing 的 `attachment_TSCC-11312.pdf`，這次被 LightRAG 順便處理完文字，狀態變成 processed，但沒有 `multimodal_processed`。下次匯入資料夾時，rag_lab 會把它當成未完成，清掉紀錄後重匯。
