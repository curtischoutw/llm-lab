# 04: hermes 接上本機 Gemma 4 和知識庫工具（終端機對話）

**What to build:** 開發者在終端機用 `run-hermes.sh chat` 和客服 agent 對話：agent 的大腦是本機 Gemma 4，只能用知識庫工具，不累積記憶也不自動學習，照角色設定追問、查詢、拒絕無關問題。同時量測決定後續能不能上線的數據。規格見 `../spec.md` 的「hermes 的設定」與「需要實機量測與確認的未知數」。

**Blocked by:** 01, 03

**Status:** ready-for-human

- [ ] 模型：custom provider 指向 `.env` 的 LLM 端點（:8081），模型為 Gemma 4
- [ ] 工具：MCP 設定指向專案 venv 的 Python 與知識庫工具，工作目錄為 llm-lab；`tools.include` 只暴露知識庫工具；內建 toolset 全部停用。確認 agent 可用的工具清單只有這一個
- [ ] 凍結學習：`memory.memory_enabled: false`、`memory.user_profile_enabled: false`、`auxiliary.background_review.enabled: false`；確認 `memory`、`skill_manage` 不在工具清單（若仍在，記錄並回報）
- [ ] 角色設定五條（只答台新卡片、查不到就說查不到、不清楚先追問、繁體中文、轉述保留答案內容與卡別）
- [ ] 實際對話至少涵蓋：沒說卡別的問題（應追問）、明確的問題（應呼叫工具）、接續追問（「那它的年費呢？」）、無關問題（應拒絕）
- [ ] 量測並記錄：hermes 送給模型的 prompt token 數；Gemma 4 是否在現有記憶體設定下跑完（有無 OOM）；每次知識庫查詢秒數（取自 JSONL）；session_search 是否存在
- [ ] 任一未知數不成立（跑不動、session_search 關不掉、仍讀 `~/.hermes`）就停下回報開發者，不自行繞過
- [ ] 結果寫在本檔末尾的 Comments
