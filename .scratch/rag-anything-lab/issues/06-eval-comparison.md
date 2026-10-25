# 06: eval 批次比較

**What to build:** `eval` 讀使用者撰寫的題目檔，每題跑五種檢索模式，輸出一份 Markdown 對照表（每題一列、每種模式一欄），讓使用者人工判斷哪種模式答得好，並用來比較之後換模型的效果。不使用 LLM 當評審。

**Blocked by:** 01, 05

**Status:** ready-for-agent

- [ ] 題目檔為 JSONL，欄位：id、question、reference、type（text／figure／table／cross-paper）、source。格式不合法（缺欄位、type 非法、id 重複）時整批拒絕，指出是第幾行與哪個欄位。
- [ ] 有 2 筆範例題目檔供使用者照著寫；正式題目由使用者撰寫，本張不撰寫。
- [ ] 每題以 naive、local、global、hybrid、mix 五種模式各跑一次。
- [ ] 輸出一份 Markdown 對照表，檔名含時間戳記、放在不進版本控管的結果資料夾；表中每題一列，附題型與參考答案，每種模式一欄。
- [ ] 查詢固定 `vlm_enhanced=False` 與 `enable_rerank=False`，讓檢索模式是唯一變因；對照表開頭註明這兩項設定。
- [ ] 單一格失敗時，在表中該格標示失敗與原因（使用可回報失敗的查詢介面，不得把 `None` 當空答案），其他格繼續執行；整體以非零碼結束。
- [ ] 快速測試（對假 server）涵蓋格式錯誤、單格失敗兩種情形，並通過；貼出實際輸出。
- [ ] 用範例題目檔對真實本地 server 跑一次，貼出產生的對照表。
