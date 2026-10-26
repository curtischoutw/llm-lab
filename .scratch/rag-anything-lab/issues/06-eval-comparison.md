# 06: eval 批次比較

**What to build:** `eval` 讀使用者撰寫的題目檔，每題跑五種檢索模式，輸出一份 Markdown 對照表（每題一列、每種模式一欄），讓使用者人工判斷哪種模式答得好，並用來比較之後換模型的效果。不使用 LLM 當評審。

**Blocked by:** 01, 05

**Status:** resolved

- [x] 題目檔為 JSONL，欄位：id、question、reference、type（text／figure／table／cross-paper）、source。格式不合法（缺欄位、type 非法、id 重複）時整批拒絕，指出是第幾行與哪個欄位。
- [x] 有 2 筆範例題目檔供使用者照著寫；正式題目由使用者撰寫，本張不撰寫。
- [x] 每題以 naive、local、global、hybrid、mix 五種模式各跑一次。
- [x] 輸出一份 Markdown 對照表，檔名含時間戳記、放在不進版本控管的結果資料夾；表中每題一列，附題型與參考答案，每種模式一欄。
- [x] 查詢固定 `vlm_enhanced=False` 與 `enable_rerank=False`，讓檢索模式是唯一變因；對照表開頭註明這兩項設定。
- [x] 單一格失敗時，在表中該格標示失敗與原因（使用可回報失敗的查詢介面，不得把 `None` 當空答案），其他格繼續執行；整體以非零碼結束。
- [x] 快速測試（對假 server）涵蓋格式錯誤、單格失敗兩種情形，並通過；貼出實際輸出。
- [x] 用範例題目檔對真實本地 server 跑一次，貼出產生的對照表。

## 實測結果（2026-10-27）

快速測試：merge 進 integration 後 `Ran 69 tests ... OK`。

以 `eval/questions.example.jsonl`（2 題）對真實 server 執行（知識庫為 ticket 05 的 3 篇論文）：rc=0，522 s，stdout：

```
對照表：/Users/curtis/GitHub/llm-lab/eval_results/eval_20261027-015632.md
完成：10 格，失敗 0 格
```

對照表開頭：

```
# eval 對照表

- 產生時間：2026-10-27T01:56:32
- 題目檔：/Users/curtis/GitHub/llm-lab/eval/questions.example.jsonl
- 題數：2
- 固定查詢設定：vlm_enhanced=False、enable_rerank=False（檢索模式是唯一變因）
- QUERY_MAX_TOTAL_TOKENS：12000
- LLM_MODEL：mlx-community/Qwen3-4B-Instruct-2507-4bit
- EMBED_MODEL：mlx-community/Qwen3-Embedding-0.6B-8bit
- 結果：10 格，失敗 0 格
```

10 格都有答案（中文作答）。text-01 五個模式都回答 low-level／high-level 兩層。cross-01 中 naive、local、hybrid、mix 都提到 RAG-Anything 的雙圖架構；global 的答案把 LightRAG 寫成「雙層檢索驅動的圖譜建構方式」，把檢索與建圖混在一起。完整內容見結果檔（gitignore，24 KB）。範例題 cross-01 的參考答案已對照 RAG-Anything 原文 §2.2.1 確認。
