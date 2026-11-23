# 01: 知識庫工具，一問一答走通

**What to build:** 客服 agent（或任何 MCP client）能以 stdio 啟動知識庫工具，看到唯一一個工具，送一個問題就拿到主知識庫以 mix 模式產生的完整答案（原樣不改），每次呼叫都在 `output/` 底下留一行 JSONL 紀錄。設定沿用 llm-lab 的 `.env`。規格見 `../spec.md` 的「知識庫工具」一節。

新增依賴：官方 `mcp` Python SDK（使用者已同意），寫進 requirements。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 以 `python -m` 啟動的 MCP server（stdio），整個生命週期共用一個 `Session`，結束時 close；`Session` 在專用 worker thread 上建立與使用
- [ ] 工具清單只有一個工具，輸入 schema 只有必填的字串欄位 `question`；工具說明寫明「一次問一個完整、獨立的問題」
- [ ] 回傳 `Session.query(question, "mix")` 的答案原文，不開 VLM 增強
- [ ] 每次呼叫附加一行 JSONL：開始時間（ISO 8601 含時區）、question、answer、status=ok、error=null、seconds、mode=mix；寫入失敗不吞錯
- [ ] 啟動時端點不可達：server 啟動失敗，stderr 說明原因
- [ ] 自動測試（子行程＋MCP client＋`fake_openai_server`＋暫存知識庫）：工具清單、正常回答與紀錄內容、同一個 server 連續兩次呼叫都成功
- [ ] 既有的 `python -m unittest` 全部通過
- [ ] `docs/architecture.md` 與 README 補上知識庫工具的用途與啟動方式
