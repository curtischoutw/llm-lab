# 06: eval 可以只跑指定的查詢模式

**What to build:** 使用者執行 `eval` 時可以指定只跑某幾種查詢模式（例如只跑 mix），結果檔與報告只含那幾種模式；不指定時照現在跑 5 種模式。Python API 的 evaluate 有同樣的參數。金融卡的兩次 eval 都只跑 mix，一次從約 1 小時 45 分鐘降到約 20 分鐘（spec：`.scratch/debit-card/spec.md`「題庫與 eval」，grill Q21）。

**Blocked by:** 增量更新（`.scratch/incremental-update/`）推上 main 之後才開工，從那時的 main 開分支（增量更新也改了 CLI，避免衝突）。和 01 可以同時做。

**Status:** ready-for-agent

- [ ] `eval` 新增選擇模式的選項（名稱由實作決定），可以給一種或多種；不給時跑 5 種，輸出和現在完全相同。
- [ ] 給了不存在的模式名稱時，以使用錯誤結束（和現有的使用錯誤相同結束碼），訊息列出可用的模式。
- [ ] 結果檔與報告只含指定的模式；統計與現有格式一致。
- [ ] Python API 的 evaluate 有同樣的參數，行為和 CLI 相同。
- [ ] 測試沿用 CLI 子行程＋Python API、假 OpenAI server 的縫；現有測試全綠。
- [ ] README 的 eval 說明加上這個選項。
