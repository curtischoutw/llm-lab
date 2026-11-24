# 05: Telegram 試用上線

**What to build:** 試用者在手機的 Telegram 上和客服 agent 對話；只有白名單內的人拿得到回覆；試用結束後，hermes 的完整對話匯出到 llm-lab 的 `output/`，和知識庫工具的 JSONL 放在一起。規格見 `../spec.md` 的「Telegram」與「試用的執行與紀錄」。

**Blocked by:** 02, 04

**Status:** ready-for-human

- [ ] 開發者用 @BotFather 建 bot；`TELEGRAM_BOT_TOKEN`、`TELEGRAM_ALLOWED_USERS` 只寫在 sandbox 的 `.env`，不進任何 repo
- [ ] 試用前檢查清單寫進本檔：設 iogpu 26000、啟動 MLX server、Mac 不睡眠、`run-hermes.sh gateway` 前景執行
- [ ] 手機對話：04 的四類問題在 Telegram 上行為相同
- [ ] 白名單外的帳號傳訊息拿不到知識庫內容
- [ ] 確認 gateway 是否一次只處理一則訊息（兩個聊天室幾乎同時發問，觀察 MLX server 的同時請求與知識庫工具的 busy 紀錄）並記錄
- [ ] 白名單：04 確認 session_search 不存在才加入其他試用者；否則只有開發者本人
- [ ] 試用結束：`hermes sessions export` 匯出到 `output/`；記錄兩份紀錄的路徑
- [ ] 記錄移除步驟是否照 spec 的 Further Notes 可行（試用結束不一定要移除）
- [ ] 結果寫在本檔末尾的 Comments

## 試用前檢查清單

1. iTerm 執行 `sudo sysctl iogpu.wired_limit_mb=26000`，再用 `sysctl iogpu.wired_limit_mb` 讀回確認（重開機會恢復）。
2. 在 llm-lab 啟動 MLX server（:8081，Gemma 4＋embedding＋reranker，`--mlx-cache-limit-gb 1`），等它就緒。
3. server 就緒後啟動 watchdog：`zsh output/crash_repro/tools/watchdog.sh <log 資料夾> 27 3`。
4. Mac 不睡眠：`caffeinate -dimsu`（筆電要接電源、不要蓋螢幕）。
5. 前景執行 `~/GitHub/hermes-sandbox/run-hermes.sh gateway run`；結束時 Ctrl-C。
6. 試用說明告訴試用者：一次問一題；換話題時輸入 `/new`；查詢一次約 1–2 分鐘；別人在查詢時會收到「請稍候」。

## Comments

2026-11-24 Telegram 連線受阻（未解決）：
- token 與白名單 ID 已寫進 sandbox 的 `home/.env`（只在 sandbox）。`gateway run` 啟動時自動在 sandbox 內安裝 telegram extra（uv、Python、快取路徑都在 `home/` 底下）。
- 連線每一輪都是：第 1 次約 20 秒逾時，第 2 次回 `Flood control exceeded. Retry in 32 seconds`；reconnect watcher 每 60／120 秒重試，結果相同。已停 gateway。
- 停 10 分鐘後只送一次 `getMe`：34 秒後回 429「retry after 32」。另建第二個 bot，第一次 `getMe` 同樣 34 秒後 429。假 token 的 `getMe` 1.5 秒回 401。本機沒有 proxy、VPN，路由走 Wi-Fi（en0）。
- 判斷：Telegram 對這個網路的對外 IP 呼叫有效 token 的請求限流（原因未證實）。下一步可改用 iPhone 熱點只送一次 `getMe`。第二個 bot 的 token 尚未寫進 `.env`。
- 兩個 token 都出現在 Claude 對話紀錄中；試用結束要在 @BotFather `/revoke` 或 `/deletebot`。
- 暫時改用本機 CLI 試用（同一份設定），教學寫在 `~/GitHub/hermes-sandbox/README.md`。

2026-11-24 改用 Discord（開發者決定；試用者只有開發者與另一位，不考慮需要公開 webhook 的 LINE）：
- hermes 的 Discord 連線由 Mac 主動連出，不需要公開網址，安全範圍和 Telegram 相同。
- bot：開發者在 Discord Developer Portal 建立，開啟 Message Content Intent、關閉 Public Bot（關閉前要先把 Installation 的安裝連結設為「無」）；邀請進只有試用者與 bot 的私人伺服器。
- sandbox `home/.env`：`DISCORD_BOT_TOKEN`、`DISCORD_ALLOWED_USERS`（開發者的使用者 ID）；Telegram token 已清空。`platform_toolsets.discord` 改為只開 `mcp-rag_kb`（`tools list --platform discord` 確認內建 toolset 全部停用）。
- `gateway run` 第一次啟動自動在 sandbox 內安裝 Discord extra；連線成功。「Opus codec not found」只影響語音頻道，不影響文字。hermes 在 Discord 註冊 `/skill` 指令（對應無法停用的說明 skill），agent 仍只有知識庫工具。
- 伺服器頻道內 hermes 預設只回應有 @bot 的訊息（`DISCORD_REQUIRE_MENTION` 預設 true），斜線指令不受影響；試用建議用私訊。
- 對話脈絡依使用者分開（私訊一人一段；頻道內 `group_sessions_per_user: true`）；知識庫答案快取由所有試用者共用，只以問題文字為 key。
- 開發者用私訊錄影試用，每則約 70 秒～2 分鐘回覆，無錯誤。錄影中發現 Richart 年費問法不同就漏答各等級年費，原因是年費表只在一個圖表 chunk、隨問法掉出檢索結果（案例記在 `output/telegram_trial/知識庫案例_年費表措辭.html`）。
- 試用者回饋回覆太長，處理見 ticket 06。
- 試用結束要在 Developer Portal 按 Reset Token（token 出現在 Claude 對話紀錄）。
