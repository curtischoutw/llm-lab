# 03: hermes 隔離安裝

**What to build:** hermes-agent 整個裝在 `~/GitHub/hermes-sandbox/`，透過那裡的 `run-hermes.sh` 使用；家目錄、shell 設定、`~/.claude` 都沒有留下 hermes 的東西。開發者第一次使用 hermes，由 agent 逐步帶著做，每個會改動檔案的步驟先說明再執行。規格見 `../spec.md` 的「hermes 的安裝與隔離」。

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [ ] 安裝前快照（存在 sandbox 外的暫存位置，安裝後比對）：`~/.local`、`~/.cache`、`~/Library/Caches`、`~/Library/LaunchAgents` 的檔案清單與修改時間；`~/.zshrc`、`~/.zprofile` 內容備份；`~/.claude` 的修改時間；`~/.hermes`、`~/.local/bin/hermes` 是否存在
- [ ] 安裝前讀過實際下載的安裝腳本，確認旗標與先前查證的一致
- [ ] 以 `--hermes-home <sandbox>/home --dir <sandbox>/home/hermes-agent --non-interactive --skip-browser --skip-computer-use` 安裝，同時設 `UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR` 指向 sandbox 內的資料夾
- [ ] 記錄 hermes 實際使用的 Python：執行期版本與路徑（預期 PM 鎖定的 3.14.9、在 sandbox 內）、啟動 PM 用的是哪一個（預期 Homebrew 的 python3.14）。不改用 pyenv 3.12.12：hermes 只支援 3.14
- [ ] 看過內容後刪除 `~/.local/bin/hermes` 與 rc 檔裡 `# Hermes Agent command` 那幾行；和備份比對只差這幾行
- [ ] `run-hermes.sh` 設好 `HERMES_HOME` 後呼叫 hermes 的實際入口；`run-hermes.sh --version`（或等效指令）可以執行
- [ ] 設定 `auth.adopt_external_logins: false`；沒有執行 `hermes setup`、`hermes import-agent`
- [ ] 安裝後快照，和安裝前比對：sandbox 外所有新增或修改的項目列給開發者（預期只有 `~/.local/bin/hermes` 與 rc 檔的 PATH 行），由開發者決定怎麼處理
- [ ] 驗收：`~/.hermes`、`~/.cache/uv` 不存在；`~/.claude` 的修改時間與安裝前相同；記錄 sandbox 佔用的磁碟空間
- [ ] sandbox 裡若要放我們自己寫的 Python 腳本，用 pyenv 3.12.12 建 venv（本 ticket 預期不需要：`run-hermes.sh` 是 shell 腳本）
- [ ] 結果與遇到的差異寫在本檔末尾的 Comments
