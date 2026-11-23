# 03: hermes 隔離安裝

**What to build:** hermes-agent 整個裝在 `~/GitHub/hermes-sandbox/`，透過那裡的 `run-hermes.sh` 使用；家目錄、shell 設定、`~/.claude` 都沒有留下 hermes 的東西。開發者第一次使用 hermes，由 agent 逐步帶著做，每個會改動檔案的步驟先說明再執行。規格見 `../spec.md` 的「hermes 的安裝與隔離」。

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [ ] 先記錄安裝前狀態：`~/.zshrc`、`~/.zprofile` 內容備份；`~/.hermes`、`~/.local/bin/hermes` 是否存在
- [ ] 安裝前讀過實際下載的安裝腳本，確認旗標與先前查證的一致
- [ ] 以 `--hermes-home <sandbox>/home --dir <sandbox>/home/hermes-agent --non-interactive --skip-browser --skip-computer-use` 安裝
- [ ] 看過內容後刪除 `~/.local/bin/hermes` 與 rc 檔裡 `# Hermes Agent command` 那幾行；和備份比對只差這幾行
- [ ] `run-hermes.sh` 設好 `HERMES_HOME` 後呼叫 hermes 的實際入口；`run-hermes.sh --version`（或等效指令）可以執行
- [ ] 設定 `auth.adopt_external_logins: false`；沒有執行 `hermes setup`、`hermes import-agent`
- [ ] 驗收：`~/.hermes` 不存在；`~/.claude` 的修改時間與安裝前相同；記錄 sandbox 佔用的磁碟空間
- [ ] 結果與遇到的差異寫在本檔末尾的 Comments
