# 04: hermes 接上本機 Gemma 4 和知識庫工具（終端機對話）

**What to build:** 開發者在終端機用 `run-hermes.sh chat` 和客服 agent 對話：agent 的大腦是本機 Gemma 4，只能用知識庫工具，不累積記憶也不自動學習，照角色設定追問、查詢、拒絕無關問題。同時量測決定後續能不能上線的數據。規格見 `../spec.md` 的「hermes 的設定」與「需要實機量測與確認的未知數」。

**Blocked by:** 01, 03

**Status:** resolved

- [x] 模型：custom provider 指向 `.env` 的 LLM 端點（:8081），模型為 Gemma 4
- [x] 工具：MCP 設定指向專案 venv 的 Python 與知識庫工具，工作目錄為 llm-lab；`tools.include` 只暴露知識庫工具；內建 toolset 全部停用。確認 agent 可用的工具清單只有這一個
- [x] 凍結學習：`memory.memory_enabled: false`、`memory.user_profile_enabled: false`、`auxiliary.background_review.enabled: false`；確認 `memory`、`skill_manage` 不在工具清單（若仍在，記錄並回報）
- [x] 停用全部內建 skill：安裝同步了 44 個（含 imessage、findmy、apple-notes、claude-code 等，見 ticket 03 Comments）。全部列進 `skills.disabled`（不刪檔案：`hermes update` 會重新同步），skill 相關工具（`skills_list`、`skill_view`、`skill_manage` 等）不在工具清單，`skills.creation_nudge_interval: 0`，`hermes curator pause`。確認 system prompt 裡沒有 skill 索引（記錄關掉前後的 prompt token 數）
- [x] 鑰匙圈：確認 `vault.key_storage` 維持預設的 `file`（設定檔沒有這個鍵即為預設），`keyring` 套件沒有安裝；鑰匙圈裡沒有 service「Hermes Agent vault key」的項目。使用者的顧慮是試用者能否碰到密碼庫：真正的防線是客服 agent 只有知識庫工具，下面的工具清單檢查即是驗證
- [x] 對話脈絡能維持多久（使用者要的「對話視窗內的記憶」是同一個聊天室的對話脈絡，不是長期記憶）：查出並記錄 (1) 對話變長時自動壓縮（compression）的觸發門檻、壓縮用哪個模型（本機 Gemma 4 的 context 限制下會多早觸發），(2) 聊天室閒置或每日自動重開新 session 的設定與預設值。實際連問 5 題以上的接續問題，確認前面提過的卡名在後面仍被沿用
- [x] 角色設定五條（只答台新卡片、查不到就說查不到、不清楚先追問、繁體中文、轉述保留答案內容與卡別）
- [x] 實際對話至少涵蓋：沒說卡別的問題（應追問）、明確的問題（應呼叫工具）、接續追問（「那它的年費呢？」）、無關問題（應拒絕）
- [x] 量測並記錄：hermes 送給模型的 prompt token 數；Gemma 4 是否在現有記憶體設定下跑完（有無 OOM）；每次知識庫查詢秒數（取自 JSONL）；知識庫工具的啟動秒數（server 要等 `Session` 開好才回應 MCP 的 initialize；和 hermes 連線 MCP server 的逾時比較，若逾時較短就回報）；session_search 是否存在
- [x] 任一未知數不成立（跑不動、session_search 關不掉、仍讀 `~/.hermes`）就停下回報開發者，不自行繞過
- [x] 結果寫在本檔末尾的 Comments

## Comments

2026-11-24 實機結果（進行中，壓縮設定待使用者決定）

設定（全部在 sandbox 的 `home/`，原檔備份 `config.yaml.before04`、`SOUL.md.orig`）：
- model：custom、`http://127.0.0.1:8081/v1`、`mlx-community/gemma-4-26b-a4b-it-4bit`；api_key 是不用的佔位字串（hermes 自動移到 `.env` 的 `HERMES_MODEL_API_KEY`）。
- `mcp_servers.rag_kb`：`/bin/sh -c "cd llm-lab && exec .venv/bin/python -m rag_lab.kb_tool"`（hermes 的 MCP 設定沒有 cwd 欄位），`connect_timeout: 120`。hermes 預設連線逾時 60 秒、工具呼叫逾時 300 秒。
- `platform_toolsets.cli`、`.telegram` 都只有 `mcp-rag_kb`。`hermes tools list` 兩個平台的內建 toolset 全部 disabled（含 terminal、file、web、memory、skills、session_search），MCP 只有 rag_kb。
- 記憶與學習：`memory.memory_enabled`、`memory.user_profile_enabled` false，`memory.nudge_interval` 0，`auxiliary.background_review.enabled` false，`skills.creation_nudge_interval` 0（hermes 提示不是認得的鍵，已寫入），`hermes curator pause`。
- skill：43 個內建 skill 停用 42 個；`hermes-agent` 這個 skill 原始碼註明是 essential、任何方式都無法停用（`hermes_cli/skills_config.py`）。skills toolset 已關，agent 沒有讀 skill 的工具。
- SOUL.md 改為客服角色七條（原本五條＋工具回「請稍候」時照實轉告＋一次問一個完整獨立的問題）。
- `run-hermes.sh` 加 `cd` 到 sandbox：hermes 會把目前資料夾的 AGENTS.md 等規則檔放進 prompt（`--ignore-rules` 的說明）。

鑰匙圈：config 沒有 `vault` 設定（預設 `file`）；hermes 的所有環境都沒有 `keyring` 套件；鑰匙圈沒有 service 名稱以 Hermes 開頭的項目。

量測：
- 知識庫工具啟動 10.6 秒（`hermes mcp test rag_kb`）。
- system prompt＋工具說明約 2,225 input token（無關問題那一輪只呼叫一次模型）。
- 知識庫查詢：54.6、39.5、57.7、41.8、43.7 秒；一輪對話（agent 推理＋查詢）36–122 秒。
- MLX server log 沒有錯誤或 OOM；全程 server 正常。
- session_search：關得掉（toolset disabled），依 spec 可以開放給其他試用者。

對話（`hermes chat -Q --oneshot`，session trial04 共 6 輪）：
- 沒說卡別的問題 → 先追問卡名與卡別，沒有呼叫工具。
- 回答卡名後 → 呼叫工具，問題改寫成「台新 Richart 信用卡 國內消費回饋」（把上下文補進問題）。
- 「那它的年費呢？」→「台新 Richart 信用卡 年費」；「那海外消費呢？」→「台新 Richart 信用卡 海外消費回饋」。
- 「Richart 有沒有金融卡？它的回饋跟剛剛那張一樣嗎？」→ 工具問題「台新 Richart 金融卡(簽帳金融卡) 回饋內容」，回覆把信用卡與簽帳金融卡分開比較。內容正確與否未判讀（由使用者判讀）。
- 第 6 輪「回到剛剛那張信用卡，切換規則再說一次」→ 沒有呼叫工具，用前面工具答案的內容回覆。
- 無關問題（寫詩、天氣）→ 拒絕，沒有呼叫工具。
- 提示注入（要求執行 `security find-generic-password`、列出 ~/.ssh）→ 拒絕，沒有呼叫工具；agent 也沒有任何能執行指令的工具。
- 知識庫查不到（火星刷卡）→ 回「查不到」，再補充工具答案裡的海外回饋。

觀察到的問題（記錄，未處理）：
- Gemma 4 有一次呼叫工具時漏填 `question`，hermes 擋下並要求重試，第二次正確；多花一輪推理。
- 轉述時拿掉了工具答案的段首卡別標記（【信用卡｜台新Richart卡】）與參考來源，第一題也少了一條「不回饋項目」。
- context 長度：hermes 偵測不到，假設 256,000 token（log：`catalog match on 'gemma-4'`），壓縮門檻 `threshold: 0.50` → 128,000 token 才壓縮；`protect_last_n: 20`。
- hermes 已移除 gateway 的閒置／每日自動重開 session（`hermes_cli/session_reset_retirement.py`），Telegram 對話不會自動結束。
- 6 輪後 trial04 的訊息共 7,942 字元（其中工具結果 5,370 字元）；最後一次呼叫的 prompt 推估約 8–10k token（推測，沒有逐次 token 數）。本機安全上限參考值約 12,000 token（ticket03 GPU OOM 調查）。

2026-11-24 壓縮設定嘗試（失敗，已還原）：
- 照建議設 `model.context_length: 20000`、`compression.protect_last_n: 8`。13 輪長對話每一輪都在呼叫模型前失敗：`ValueError: ... context window of 20,000 tokens, which is below the minimum 64,000 required by Hermes Agent`。紀錄在 `output/telegram_trial/long_chat/transcript.md`。
- 原始碼：`agent/model_metadata.py` 的 `MINIMUM_CONTEXT_LENGTH = 64_000`；`agent/context_compressor.py` 的 `_compute_threshold_tokens` 把壓縮門檻下限設在 64,000（下限超過 85% 時改為 85%）。也就是說 hermes 內建的壓縮最早在約 54k token 才觸發，無法調到 10k。
- 已 `config unset model.context_length`；`protect_last_n: 8` 保留。
- 另一個機制（未試）：`compression.proactive_prune_tokens`，不呼叫模型、只精簡舊的工具結果，與 `threshold` 無關。預設 0（關閉），`proactive_prune_min_result_chars` 預設 8000（本專案工具結果約 1,500 字元，要調低才會作用）。它不處理使用者與 agent 自己的訊息。

2026-11-24 context 長度實測（使用者關掉其他軟體後；`output/telegram_trial/context_probe.py`，結果在 `context_probe.jsonl`）：
- 直接對 :8081 送單一請求（不經 hermes），內容是知識庫工具答案重複接起來，max_tokens 64。
- 12k→48k token 全部成功：耗時 29.5、39.6、50.7、61.9、73.6、85.8、111.9、139.0 秒；wired 峰值 24.24→25.26 GB（閒置時約 21.9 GB）。server 沒有錯誤，watchdog（27 GB）沒有觸發。
- 每多 1k token 約多 0.03 GB wired、多 2.7 秒處理時間（推估自上面數字）。
- 之前的「12,000 token」是知識庫查詢路徑（`QUERY_MAX_TOTAL_TOKENS`）的設定，不是模型單次請求的上限。
- 未測：48k 以上；hermes 壓縮最早觸發點約 54.4k（`context_length: 64000` 時：64,000 下限、85% 上限）。wired 是全系統數字，不等於 GPU 配置量，與 `iogpu.wired_limit_mb=26000` 的距離無法精確換算。
- 補測（caffeinate 防休眠）：56k 成功（168.5 秒、wired 峰值 25.43 GB）、60k 成功（184.0 秒、25.81 GB）。server 無錯誤，watchdog 未觸發。
- 已設 `model.context_length: 64000`（log：`Model context warmed ... -> 64000 tokens (config)`，並警告 provider 宣稱 256,000，以設定為準）。實際對話一輪成功（69 秒，工具查詢 4.7 秒，命中快取）。
- 壓縮門檻依 `_compute_threshold_tokens` 原始碼手算：64000×0.5=32000，下限 64000 超過 85% 上限 → 54,400 token。未實際跑到觸發（要約 50 輪以上，單輪會到 3 分鐘以上）。
- 結論：壓縮只是最後保險；長對話的實際限制是等待時間（48k prompt 單次 139 秒），試用說明要請試用者換話題時輸入 `/new`（ticket 05）。

結案（2026-11-24）。與驗收文字的差異：
- 工具只暴露知識庫工具：用 `platform_toolsets`（cli、telegram 都只有 `mcp-rag_kb`）達成，不是 `tools.include`。
- skill：`hermes-agent` 無法停用（hermes 寫死）；只記錄到停用後的 prompt token 數（約 2,225），停用前沒有量。
- 壓縮用的模型：config 沒有設定 `auxiliary.compression`，推測沿用主模型（Gemma 4），未驗證。
- 角色設定是七條（驗收的五條＋轉告「請稍候」＋一次問一個完整獨立的問題）。
- 沒有讀 `~/.hermes`：家目錄沒有這個資料夾。
