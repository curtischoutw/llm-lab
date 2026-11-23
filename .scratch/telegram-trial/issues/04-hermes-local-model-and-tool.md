# 04: hermes 接上本機 Gemma 4 和知識庫工具（終端機對話）

**What to build:** 開發者在終端機用 `run-hermes.sh chat` 和客服 agent 對話：agent 的大腦是本機 Gemma 4，只能用知識庫工具，不累積記憶也不自動學習，照角色設定追問、查詢、拒絕無關問題。同時量測決定後續能不能上線的數據。規格見 `../spec.md` 的「hermes 的設定」與「需要實機量測與確認的未知數」。

**Blocked by:** 01, 03

**Status:** ready-for-human

- [ ] 模型：custom provider 指向 `.env` 的 LLM 端點（:8081），模型為 Gemma 4
- [ ] 工具：MCP 設定指向專案 venv 的 Python 與知識庫工具，工作目錄為 llm-lab；`tools.include` 只暴露知識庫工具；內建 toolset 全部停用。確認 agent 可用的工具清單只有這一個
- [ ] 凍結學習：`memory.memory_enabled: false`、`memory.user_profile_enabled: false`、`auxiliary.background_review.enabled: false`；確認 `memory`、`skill_manage` 不在工具清單（若仍在，記錄並回報）
- [ ] 停用全部內建 skill：安裝同步了 44 個（含 imessage、findmy、apple-notes、claude-code 等，見 ticket 03 Comments）。全部列進 `skills.disabled`（不刪檔案：`hermes update` 會重新同步），skill 相關工具（`skills_list`、`skill_view`、`skill_manage` 等）不在工具清單，`skills.creation_nudge_interval: 0`，`hermes curator pause`。確認 system prompt 裡沒有 skill 索引（記錄關掉前後的 prompt token 數）
- [ ] 鑰匙圈：確認 `vault.key_storage` 維持預設的 `file`（設定檔沒有這個鍵即為預設），`keyring` 套件沒有安裝；鑰匙圈裡沒有 service「Hermes Agent vault key」的項目。使用者的顧慮是試用者能否碰到密碼庫：真正的防線是客服 agent 只有知識庫工具，下面的工具清單檢查即是驗證
- [ ] 對話脈絡能維持多久（使用者要的「對話視窗內的記憶」是同一個聊天室的對話脈絡，不是長期記憶）：查出並記錄 (1) 對話變長時自動壓縮（compression）的觸發門檻、壓縮用哪個模型（本機 Gemma 4 的 context 限制下會多早觸發），(2) 聊天室閒置或每日自動重開新 session 的設定與預設值。實際連問 5 題以上的接續問題，確認前面提過的卡名在後面仍被沿用
- [ ] 角色設定五條（只答台新卡片、查不到就說查不到、不清楚先追問、繁體中文、轉述保留答案內容與卡別）
- [ ] 實際對話至少涵蓋：沒說卡別的問題（應追問）、明確的問題（應呼叫工具）、接續追問（「那它的年費呢？」）、無關問題（應拒絕）
- [ ] 量測並記錄：hermes 送給模型的 prompt token 數；Gemma 4 是否在現有記憶體設定下跑完（有無 OOM）；每次知識庫查詢秒數（取自 JSONL）；知識庫工具的啟動秒數（server 要等 `Session` 開好才回應 MCP 的 initialize；和 hermes 連線 MCP server 的逾時比較，若逾時較短就回報）；session_search 是否存在
- [ ] 任一未知數不成立（跑不動、session_search 關不掉、仍讀 `~/.hermes`）就停下回報開發者，不自行繞過
- [ ] 結果寫在本檔末尾的 Comments
