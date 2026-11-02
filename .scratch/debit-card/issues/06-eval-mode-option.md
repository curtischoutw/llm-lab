# 06: eval 可以只跑指定的查詢模式

**What to build:** 使用者執行 `eval` 時可以指定只跑某幾種查詢模式（例如只跑 mix），結果檔與報告只含那幾種模式；不指定時照現在跑 5 種模式。Python API 的 evaluate 有同樣的參數。金融卡的兩次 eval 都只跑 mix，一次從約 1 小時 45 分鐘降到約 20 分鐘（spec：`.scratch/debit-card/spec.md`「題庫與 eval」，grill Q21）。

**Blocked by:** 增量更新（`.scratch/incremental-update/`）推上 main 之後才開工，從那時的 main 開分支（增量更新也改了 CLI，避免衝突）。和 01 可以同時做。

**Status:** resolved

- [x] `eval` 新增選擇模式的選項（名稱由實作決定），可以給一種或多種；不給時跑 5 種，輸出和現在完全相同。
- [x] 給了不存在的模式名稱時，以使用錯誤結束（和現有的使用錯誤相同結束碼），訊息列出可用的模式。
- [x] 結果檔與報告只含指定的模式；統計與現有格式一致。
- [x] Python API 的 evaluate 有同樣的參數，行為和 CLI 相同。
- [x] 測試沿用 CLI 子行程＋Python API、假 OpenAI server 的縫；現有測試全綠。
- [x] README 的 eval 說明加上這個選項。

## 實作結果（2026-11-02）

**做了什麼**
- CLI：`eval` 新增 `--modes`（`nargs="+"`，`choices` 為 naive、local、global、hybrid、mix）。例：`eval q.jsonl --modes mix`。
- Python API：`rag_lab.pipeline.evaluate(questions, modes=None)` 與 `Session.evaluate(questions, modes=None)`。`rag_lab.evaluation.resolve_modes` 負責整理與驗證，CLI 與 API 共用。
- 結果檔與統計：`render_report` 多一個必填參數 `modes`，表格的模式欄、「結果：N 格」、stdout 的「完成：N 格」都只算指定的模式。不給 `--modes` 時 `modes` 是五種，輸出和原本相同（既有的 eval 與 Python API 測試未改動並通過）。
- 不存在的模式名稱：CLI 由 argparse 以結束碼 2 拒絕，訊息列出五種可用的模式，發生在載入題目檔與連任何端點之前。Python API 拋 `ValueError`（訊息同樣列出可用的模式），發生在連線檢查之前。
- README 的 eval 說明加上 `--modes` 與 Python API 的 `modes`。

**紅燈**
- 實作暫時 stash 掉後，`EvalModesOptionTest` 4 個測試全紅（`rag_lab: error: unrecognized arguments: --modes mix`，結束碼 2 != 0），`EvaluateModesTest` 2 個全紅（`TypeError: Session.evaluate() takes 2 positional arguments but 3 were given`）。
- 開發順序：先寫 CLI 的第一個測試並確認紅燈，實作後轉綠；其餘 3 個 CLI 測試與 2 個 API 測試是在實作完成之後補寫，再用 stash 實作的方式一次確認它們在沒有實作時會紅。

**測試**
- CLI（`tests/test_eval.py`，`EvalModesOptionTest`）：單一模式（欄位、請求數、統計）、多個模式的固定順序與重複名稱、失敗只算指定的模式、不存在的模式。
- Python API（`tests/test_python_api.py`，`EvaluateModesTest`）：模組函式與 Session 兩種呼叫方式的 `modes`，以及不認得的名稱與空序列。
- 主套件最後一次結果：`python -m unittest` 跑 268 個測試（原本 262 個加上新增的 6 個），`Ran 268 tests in 1193.313s`、`OK`。本票沒有動 `scripts/`，下載腳本套件沒有跑。

**ASSUMPTION**
- 結果檔的模式欄順序固定依 naive、local、global、hybrid、mix，不依命令列順序；重複的名稱算一次。理由：不同次 eval 的欄位位置一致。
- `--modes` 後面接多個值（`nargs="+"`），所以題目檔路徑要放在 `--modes` 之前（`eval q.jsonl --modes mix naive`）；放在後面會被當成模式名稱而以結束碼 2 拒絕。
- Python API 的空序列視為使用錯誤（`ValueError`），不當成「全部」；要全部用 `None`。
- 表頭沒有另外記錄「只跑了哪些模式」，由表格的欄位表示。
