# 02: 知識庫工具，忙碌回覆與錯誤處理

**What to build:** 有查詢進行中時，新的呼叫不排隊，立刻收到「目前有其他人在查詢，請稍候再問」；問題空白、端點連不上或查詢失敗時，客服 agent 收到說明原因的工具錯誤，知識庫工具繼續服務下一個呼叫。每種情況都留紀錄。規格見 `../spec.md`。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 查詢進行中再呼叫：立刻回傳固定的請稍候訊息（一般文字結果），紀錄 status=busy、answer=null、seconds=0；進行中的查詢照常完成
- [ ] 空白問題：回傳工具錯誤（isError），紀錄 status=error
- [ ] `EndpointError`、`PipelineError`（含 rerank 失敗）：回傳工具錯誤，訊息說明原因且不含 API key，紀錄 status=error 與錯誤訊息；之後的呼叫仍能成功
- [ ] 預期之外的例外不吞掉：該次呼叫失敗並留紀錄
- [ ] 自動測試：用 `chat_delay` 拉長查詢製造忙碌（第二次立刻回請稍候、假 server 的同時 chat 請求數不超過單一查詢）；空白問題；`fail_chat` 或 rerank 故障後下一個呼叫成功；錯誤訊息不含測試用的 key
- [ ] 既有的 `python -m unittest` 全部通過
