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
