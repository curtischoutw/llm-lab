# 在 Telegram 上試用客服 agent

**Status:** ready-for-agent

用語見 `GLOSSARY.md`：**客服 agent**、**知識庫工具**、**試用**、**試用者**。「測試」只指 `python -m unittest`。

## Problem Statement

知識庫目前只能從指令列或 Python 的 `Session` 提問，只有開發者自己用得到，而且每次都是一問一答：問題要一次問清楚，問不清楚也不會被追問。開發者想知道「真人在手機上用通訊軟體、像問客服一樣自然地問」時，這套知識庫撐不撐得住，但現在沒有任何管道能讓真人這樣用它，也沒有留下這類對話的紀錄可以事後判讀。

開發者選擇用開源的 hermes-agent 當客服 agent：由 agent 自己的 LLM 主導對話（追問、改寫、拆解問題），知識庫只是它的一個工具。開發者是第一次用 hermes，也預期試用結束後不常使用，所以它必須和 Claude Code 及系統環境隔離，要能乾淨移除。

## Solution

1. 在 llm-lab 裡新增**知識庫工具**：一個以 MCP（stdio）提供的 server，內部用 `rag_lab.pipeline.Session` 查詢主知識庫，回傳完整答案；每次呼叫寫一行 JSONL 紀錄；同一時間只跑一個查詢，有查詢進行中時立刻回覆請稍候。
2. 把 hermes-agent 裝在獨立資料夾（不在家目錄、不在 llm-lab 裡），透過啟動腳本使用，不匯入 `~/.claude`、不借用 Claude Code 登入、不留 PATH 設定。
3. 設定 hermes：大腦用本機 Gemma 4（同一台 MLX server），只開放知識庫工具，關掉長期記憶與背景學習，寫好客服角色設定。
4. 建立 Telegram bot，以白名單限定試用者，在試用時段於開發者的 Mac 上執行 gateway；開發者用手機的 Telegram 對話。
5. 試用結束時匯出 hermes 的完整對話紀錄，和知識庫工具的 JSONL 一起留在 llm-lab 的 `output/`。

```
手機 Telegram ─► Telegram Bot API ◄─(long polling)─ hermes gateway（Mac）
                                                       └ hermes 的 LLM（Gemma 4，:8081）
                                                            │ 呼叫知識庫工具（MCP stdio）
                                                            ▼
                                                   知識庫工具 ─► Session.query（mix）─► :8081
```

## User Stories

1. 身為試用者，我想在手機的 Telegram 上傳訊息給客服 agent，就能問台新卡片的問題，不必碰電腦或指令列。
2. 身為試用者，我想用口語、不完整的方式提問（例如沒說是哪張卡），讓客服 agent 先追問清楚再回答，這樣才像真的客服。
3. 身為試用者，我想在同一段對話裡接著問（「那它的年費呢？」），客服 agent 能理解前面講的是哪張卡。
4. 身為試用者，我想收到的回答來自知識庫，並說明是信用卡還是金融卡，這樣我不會把兩種卡的規則搞混。
5. 身為試用者，當知識庫查不到時，我想得到「查不到」的明確回覆，而不是 agent 自己編出來的內容。
6. 身為試用者，當我問和台新卡片無關的問題時，我想得到禮貌的拒絕，知道這個客服的服務範圍。
7. 身為試用者，當其他人正在查詢時，我想立刻收到「目前有其他人在查詢，請稍候再問」，而不是對著「輸入中…」乾等、以為壞掉了。
8. 身為試用者，我想用繁體中文和客服 agent 對話並收到繁體中文回覆。
9. 身為不在白名單內的人，我傳訊息給 bot 時不會得到任何知識庫內容。
10. 身為試用者，我不希望客服 agent 能看到或提到其他試用者說過的話。
11. 身為開發者，我想讓客服 agent 只能用知識庫工具，不能在我的 Mac 上執行指令、讀寫檔案或上網，這樣試用者無法透過對話操作我的電腦。
12. 身為開發者，我想讓客服 agent 在試用期間行為固定（不累積記憶、不自動建立 skill），這樣不同時間的試用結果可以互相比較。
13. 身為開發者，我想讓客服 agent 的大腦用本機的 Gemma 4，這樣受測的全部是本機方法與模型。
14. 身為開發者，我想知道 hermes 送給模型的 prompt 有多大，才能判斷本機 Gemma 4 會不會撞上 GPU 記憶體上限。
15. 身為開發者，我想讓 hermes 的所有檔案都在一個獨立資料夾裡，刪掉那個資料夾就能移除乾淨。
16. 身為開發者，我不希望 hermes 讀取或匯入 `~/.claude` 的任何內容，也不借用 Claude Code 的登入。
17. 身為開發者，我不希望 hermes 在我的 shell 設定或 `~/.local/bin` 留下東西。
18. 身為開發者，我想用一個啟動腳本開關 hermes，不必記住環境變數。
19. 身為開發者，我想讓知識庫工具每次被呼叫都留下時間、agent 送來的問題、知識庫的答案、花費秒數與結果狀態，這樣即使之後移除 hermes，也看得到知識庫實際被問了什麼、答了什麼。
20. 身為開發者，我想在試用結束時把 hermes 的完整對話（含 agent 自己的回覆與工具呼叫）匯出到 llm-lab，這樣可以比對 agent 怎麼轉述知識庫的答案。
21. 身為開發者，我想讓知識庫工具在端點連不上或查詢失敗時回傳清楚的錯誤給 agent，而不是讓整個工具掛掉、後面的問題都無法回答。
22. 身為開發者，我想讓知識庫工具一啟動就連到主知識庫，設定沿用 llm-lab 的 `.env`，不必另外維護一份設定。
23. 身為開發者，我想知道一次查詢實際要幾秒，才能決定「忙碌時直接回覆」要不要改成排隊。
24. 身為開發者，我想讓知識庫工具也能被其他支援 MCP 的 agent 使用，不綁死 hermes。
25. 身為開發者，我想讓知識庫工具有自動測試，從 MCP 協定的外面驗證它的行為，不需要真的啟動模型或 hermes。
26. 身為開發者，試用結束後不再使用時，我想有明確的移除步驟。

## Implementation Decisions

**知識庫工具（llm-lab 內的新模組）**

- 新增一個 MCP server 模組，以 stdio 傳輸，用官方 `mcp` Python SDK（新增依賴，使用者已同意）。以 `python -m` 方式啟動，hermes 的 `mcp_servers` 設定指向專案 venv 的 Python 與這個模組，工作目錄設為 llm-lab 根目錄。
- 只提供一個工具。輸入：一個字串欄位 `question`（必填、非空白）。輸出：知識庫產生的完整答案文字，原樣不改（保留回答附加指示產生的段首卡別標記）。工具說明要寫清楚：一次問一個完整、獨立的問題（客服 agent 要自己把追問的上下文補進問題）。
- 檢索模式固定 mix（與 CLI 預設相同），不讓 agent 選；不開 VLM 增強。
- 設定完全沿用 `rag_lab` 讀 `.env` 的方式，不另立設定。啟動時開一個 `Session`，整個 server 生命週期共用，結束時 close。
- `Session` 只能在建立它的 thread 使用，且該 thread 上不能有執行中的 event loop；SDK 是 asyncio，所以 `Session` 放在專用的 worker thread，由工具處理函式把查詢交給它並等待結果。
- 同時只跑一個查詢：有查詢進行中時，新的呼叫**不排隊**，立刻回傳固定訊息「目前有其他人在查詢，請稍候再問」（以一般文字結果回傳，讓 agent 轉告試用者），並在紀錄中標為 busy。實機量到查詢很快的話，之後再決定是否改為排隊（不在本 spec 範圍）。
- 錯誤處理：`EndpointError`、`PipelineError`、`ValueError`（空問題）等可預期的失敗，以 MCP 工具錯誤（`isError`）回傳，訊息說明原因，不含 API key；server 繼續服務下一個呼叫。不吞例外：預期之外的例外照樣讓該次呼叫失敗並留紀錄。
- 紀錄：每次呼叫附加一行 JSONL 到 `output/` 底下一個固定檔案（檔名在 ticket 決定）。欄位：開始時間（ISO 8601，含時區）、`question`、`answer`（失敗或 busy 時為 null）、`status`（ok／busy／error）、`error`（訊息或 null）、`seconds`（查詢秒數，busy 為 0）、`mode`。寫入失敗不吞錯。
- 啟動時若端點不可達，`Session` 照現行行為拋 `EndpointError`；server 啟動失敗並在 stderr 說明，讓 hermes 的 log 看得到原因。

**hermes 的安裝與隔離（不進 llm-lab 版控）**

- 安裝在 `~/GitHub/hermes-sandbox/`（不建 git repo）。安裝指令用 `--hermes-home <sandbox>/home`、`--dir <sandbox>/home/hermes-agent`、`--non-interactive`、`--skip-browser`、`--skip-computer-use`。
- 安裝腳本無法關閉的兩處：`~/.local/bin/hermes` 啟動檔與 `~/.zshrc`、`~/.zprofile` 的 PATH 行（`# Hermes Agent command`）。安裝後手動刪除，刪之前先看內容。
- sandbox 裡放 `run-hermes.sh`：設好 `HERMES_HOME` 再呼叫 hermes 的實際入口；之後一律用它，不直接打 `hermes`。要實機確認只靠 `HERMES_HOME` 就能運作、不會落回 `~/.hermes`。
- 設定：`auth.adopt_external_logins: false`；不執行互動式 `hermes setup`；不執行 `hermes import-agent`；不安裝 gateway 為 launchd 服務（試用時段手動前景執行）。

**hermes 的設定**

- 模型：`model.provider: custom`，`base_url` 指向 `.env` 裡 LLM 端點（:8081）、模型名稱用 Gemma 4。
- 工具：只開放知識庫工具；內建 toolset（terminal、檔案、web、browser 等）全部停用。用 MCP 的 `tools.include` 只暴露那一個工具。
- 凍結學習：`memory.memory_enabled: false`、`memory.user_profile_enabled: false`、`auxiliary.background_review.enabled: false`；skill 自動建立盡量關閉（文件沒有完全停用 `skill_manage` 的開關，實機確認其是否因工具限制而不存在）。
- session_search：文件沒寫怎麼關；實機確認只開知識庫工具後它是否也不存在。關得掉才把其他人加入白名單；關不掉就只有開發者本人試用。
- 角色設定（SOUL.md 或 system prompt）四條：只回答台新信用卡與金融卡的問題，其他禮貌拒絕；知識庫查不到就說查不到，不用自己的知識補；問題不清楚（例如沒說哪張卡）先追問再查；使用繁體中文。另加一條：轉述時盡量保留知識庫答案的內容與卡別，不自己補充。
- Telegram：開發者用 @BotFather 建 bot，`TELEGRAM_BOT_TOKEN` 與 `TELEGRAM_ALLOWED_USERS` 寫在 sandbox 的 `.env`（不進任何 repo）。long polling，不用 webhook，不需公開網址。

**試用的執行與紀錄**

- 試用時段：先啟動 MLX server（含每次開機要設的 iogpu 26000），Mac 不能睡眠，再用 `run-hermes.sh gateway` 前景執行。
- 試用結束：`hermes sessions export`（JSONL）匯出到 llm-lab 的 `output/` 底下，和知識庫工具的紀錄放在一起。
- 判讀方式由開發者事後自行處理；本 spec 不做自動評分、不跑 eval 題庫。

**需要實機量測與確認的未知數**（任一不成立就回報開發者，不自行繞過）

- hermes 送給模型的 prompt 大小，本機 Gemma 4 能否在現有記憶體設定（QUERY_MAX_TOTAL_TOKENS 等）下跑。
- session_search 能否關閉。
- 只靠 `HERMES_HOME` 啟動是否完全不碰 `~/.hermes`。
- gateway 是否一次只處理一則訊息（決定 hermes 的推理會不會和知識庫查詢同時打到 MLX server）。
- 一次知識庫查詢的秒數。

## Testing Decisions

- 好的測試只看外部行為：把知識庫工具當子行程啟動，用 MCP client（同一個 `mcp` SDK）透過 stdio 對話，檢查列出的工具、呼叫結果與 JSONL 紀錄；不 import 模組內部、不檢查 worker thread 怎麼實作。
- 唯一的自動測試切入點是知識庫工具這個 MCP server。後端用既有的 `tests/fake_openai_server.py`，知識庫用測試時以假 server 匯入的小型暫存知識庫，環境變數組法沿用 CLI／Python API 測試。
- 要涵蓋的行為：
  - 工具清單只有一個工具，輸入 schema 只有 `question`。
  - 正常提問回傳知識庫答案（假 server 的固定回覆），紀錄一行 status=ok、含問題、答案、秒數、mode=mix。
  - 查詢進行中（以 `chat_delay` 拉長）再呼叫一次，第二次立刻回傳請稍候訊息、紀錄 status=busy；第一次照常完成。假 server 的 `max_inflight_chat` 不超過單一查詢的量。
  - 空白問題回傳工具錯誤、紀錄 status=error。
  - 查詢失敗（例如 `fail_chat` 或 rerank 故障）回傳工具錯誤、訊息不含 API key，之後的下一個呼叫仍能成功。
  - 連續兩個呼叫都成功（Session 在同一 server 內重複使用）。
- Prior art：`tests/test_python_api.py`（子行程＋假 server＋只看 stdout／結束碼）、`tests/test_cli.py` 的環境變數組法、`tests/test_pipeline.py` 的暫存知識庫夾具。
- hermes 那一側（安裝隔離、設定、Telegram、session_search、prompt 大小、秒數）不寫自動測試，寫成 ready-for-human 的 ticket，附實機檢查步驟與要記錄的數據。

## Out of Scope

- LINE 或其他平台；webhook；公開網址；雲端部署；24 小時常駐。
- 每位試用者各自的長期記憶（需多個 bot 與 profile）。
- HTTP API。
- 用 Claude 或其他雲端模型當客服 agent 的大腦。
- 自動評分、把 eval 題庫送進客服 agent、和最終 ✓ 16 的基準比較（開發者事後自行做）。
- 忙碌時改為排隊（量到查詢秒數後再決定）。
- 修改 `rag_lab` 既有的查詢、回答指示或知識庫內容。

## Further Notes

- hermes-agent 的事實（安裝旗標、設定鍵、檔案位置）來自 2026-11-23 讀取的官方文件與 `scripts/install.sh`；部分頁面只讀了前段，實作時以實機行為為準。
- 移除步驟：`hermes gateway stop`（若在跑）→ 刪除 `~/GitHub/hermes-sandbox/` → 確認 `~/.local/bin/hermes` 與 rc 檔的 PATH 行已不存在。llm-lab 裡的知識庫工具與紀錄保留。
- 依「一律先開 branch」的慣例，本 spec 與後續 tickets 的 commit 走 branch，不直接進 main。
