# 02: 知識庫工具，忙碌回覆與錯誤處理

**What to build:** 有查詢進行中時，新的呼叫不排隊，立刻收到「目前有其他人在查詢，請稍候再問」；問題空白、端點連不上或查詢失敗時，客服 agent 收到說明原因的工具錯誤，知識庫工具繼續服務下一個呼叫。每種情況都留紀錄。規格見 `../spec.md`。

**Blocked by:** 01

**Status:** resolved

- [x] 查詢進行中再呼叫：立刻回傳固定的請稍候訊息（一般文字結果），紀錄 status=busy、answer=null、seconds=0；進行中的查詢照常完成
- [x] 空白問題：回傳工具錯誤（isError），紀錄 status=error
- [x] `EndpointError`、`PipelineError`（含 rerank 失敗）：回傳工具錯誤，訊息說明原因且不含 API key，紀錄 status=error 與錯誤訊息；之後的呼叫仍能成功
- [x] 預期之外的例外不吞掉：該次呼叫失敗並留紀錄
- [x] 自動測試：用 `chat_delay` 拉長查詢製造忙碌（第二次立刻回請稍候、假 server 的同時 chat 請求數不超過單一查詢）；空白問題；`fail_chat` 或 rerank 故障後下一個呼叫成功；錯誤訊息不含測試用的 key
- [x] 既有的 `python -m unittest` 全部通過

## Comments

2026-11-24 完成。

- 忙碌判斷用 server event loop 上的旗標（檢查與設定之間沒有 await），所有路徑在 `finally` 復位。拿掉忙碌判斷時第二個呼叫會排隊拿到答案，證實 SDK 會並行處理同一個 client 的多個工具呼叫，判斷是必要的。
- 預期之外的例外以新夾具 `tests/query_crash/`（包住 `Session.query`）注入；EndpointError 以 rerank 端點不可達測試。
- `tests/test_kb_tool.py` 12 個測試；完整 `python -m unittest` 362 個測試通過（1318 秒）。
- fresh-context 審查（第一次 verdict：需修改）：
  - 忙碌測試的 `max_inflight_chat` 會量到 setUp 匯入時的同時請求而間歇失敗 → 假 server 新增 `reset_max_inflight()`，修正後連跑 3 輪通過。
  - 預期外例外與 EndpointError 分支沒有測試 → 補測試；mutation（吞掉例外、不留紀錄、拿掉 EndpointError）各自被對應測試抓到。
- 沒有處理、記下的兩點：
  - 「錯誤訊息不含 API key」的斷言防護力低：假 server 不回傳 Authorization，實作就算洩漏也測不到。
  - 預期外例外的訊息原文寫進 JSONL，訊息若含 key 會留在紀錄檔（推測，沒有實際例外帶 key 的證據）。
- 審查實驗：client 取消進行中的查詢時，查詢仍跑完才復位 busy，被取消的那次記成 status=ok。
