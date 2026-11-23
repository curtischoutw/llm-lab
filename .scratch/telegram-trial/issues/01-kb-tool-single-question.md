# 01: 知識庫工具，一問一答走通

**What to build:** 客服 agent（或任何 MCP client）能以 stdio 啟動知識庫工具，看到唯一一個工具，送一個問題就拿到主知識庫以 mix 模式產生的完整答案（原樣不改），每次呼叫都在 `output/` 底下留一行 JSONL 紀錄。設定沿用 llm-lab 的 `.env`。規格見 `../spec.md` 的「知識庫工具」一節。

新增依賴：官方 `mcp` Python SDK（使用者已同意），寫進 requirements。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 以 `python -m` 啟動的 MCP server（stdio），整個生命週期共用一個 `Session`，結束時 close；`Session` 在專用 worker thread 上建立與使用
- [x] 工具清單只有一個工具，輸入 schema 只有必填的字串欄位 `question`；工具說明寫明「一次問一個完整、獨立的問題」
- [x] 回傳 `Session.query(question, "mix")` 的答案原文，不開 VLM 增強
- [x] 每次呼叫附加一行 JSONL：開始時間（ISO 8601 含時區）、question、answer、status=ok、error=null、seconds、mode=mix；寫入失敗不吞錯
- [x] 啟動時端點不可達：server 啟動失敗，stderr 說明原因
- [x] 自動測試（子行程＋MCP client＋`fake_openai_server`＋暫存知識庫）：工具清單、正常回答與紀錄內容、同一個 server 連續兩次呼叫都成功
- [x] 既有的 `python -m unittest` 全部通過
- [x] `docs/architecture.md` 與 README 補上知識庫工具的用途與啟動方式

## Comments

2026-11-24 完成。

- `mcp` 2.3.0（requirements 限制 `>=2.3,<3`：2.x 的 `FastMCP` 改名為 `MCPServer`，與 1.x 不相容）。
- `tests/test_kb_tool.py` 5 個測試通過；完整 `python -m unittest` 355 個測試通過（1316 秒）。
- fresh-context 審查（verdict：可合併）指出「測試分不出 mix 與 hybrid」並以 mutation 證實；改為檢查答案快取 key 的模式（`mix:query:`），把實作改成 hybrid 時該測試失敗、改回後通過。
- 審查的其他觀察：server 要等 `Session` 開好才回應 initialize（啟動秒數已加進 ticket 04 的量測）；閒置時 SIGINT 不會結束 server，是 SDK 本身的行為（最小 `MCPServer` 同樣如此），SIGTERM 與 stdin EOF 正常結束。
- 查詢例外時 SDK 只回固定的 `Error executing tool query_knowledge_base`、不寫紀錄，由 ticket 02 處理。
