# 03: hermes 隔離安裝

**What to build:** hermes-agent 整個裝在 `~/GitHub/hermes-sandbox/`，透過那裡的 `run-hermes.sh` 使用；家目錄、shell 設定、`~/.claude` 都沒有留下 hermes 的東西。開發者第一次使用 hermes，由 agent 逐步帶著做，每個會改動檔案的步驟先說明再執行。規格見 `../spec.md` 的「hermes 的安裝與隔離」。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 安裝前快照（存在 sandbox 外的暫存位置，安裝後比對）：`~/.local`、`~/.cache`、`~/Library/Caches`、`~/Library/LaunchAgents` 的檔案清單與修改時間；`~/.zshrc`、`~/.zprofile` 內容備份；`~/.claude` 的修改時間；`~/.hermes`、`~/.local/bin/hermes` 是否存在
- [x] 安裝前讀過實際下載的安裝腳本，確認旗標與先前查證的一致
- [x] 以 `--hermes-home <sandbox>/home --dir <sandbox>/home/hermes-agent --non-interactive --skip-browser --skip-computer-use` 安裝，同時設 `UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR` 指向 sandbox 內的資料夾
- [x] 記錄 hermes 實際使用的 Python：執行期版本與路徑（預期 PM 鎖定的 3.14.9、在 sandbox 內）、啟動 PM 用的是哪一個（預期 Homebrew 的 python3.14）。不改用 pyenv 3.12.12：hermes 只支援 3.14
- [x] 看過內容後刪除 `~/.local/bin/hermes` 與 rc 檔裡 `# Hermes Agent command` 那幾行；和備份比對只差這幾行
- [x] `run-hermes.sh` 設好 `HERMES_HOME` 後呼叫 hermes 的實際入口；`run-hermes.sh --version`（或等效指令）可以執行
- [x] 設定 `auth.adopt_external_logins: false`；沒有執行 `hermes setup`、`hermes import-agent`
- [x] 安裝後快照，和安裝前比對：sandbox 外所有新增或修改的項目列給開發者（預期只有 `~/.local/bin/hermes` 與 rc 檔的 PATH 行），由開發者決定怎麼處理
- [x] 驗收：`~/.hermes`、`~/.cache/uv` 不存在；`~/.claude` 的修改時間與安裝前相同；記錄 sandbox 佔用的磁碟空間
- [x] sandbox 裡若要放我們自己寫的 Python 腳本，用 pyenv 3.12.12 建 venv（本 ticket 預期不需要：`run-hermes.sh` 是 shell 腳本）
- [x] 結果與遇到的差異寫在本檔末尾的 Comments

## Comments

2026-11-24 完成（安裝 02:28–02:30，約 2 分鐘，結束碼 0；hermes commit caafe5389a）。

- 安裝腳本：官網 `install.sh` 與 repo main 的 `scripts/install.sh` 相同（sha256 c73dad4d…3214）。`rm -rf` 只刪自己的暫存資料夾；`sudo` 只在 Linux 分支。執行的是讀過的那份本機複本。
- 安裝前快照與 marker 在 `output/telegram_trial/`（不進版控）。安裝前 `~/.local/share/uv` 已存在（與 hermes 無關），`~/.cache/uv`、`~/.hermes` 不存在。
- Python：執行期 3.14.9，位於 `home/tools/python-3.14.9+20261021-darwin-arm64/`（sandbox 內）。啟動 PM 用的 Python 安裝 log 沒記錄；`uv-python/` 是空的，表示沒有另外下載。
- `UV_CACHE_DIR` 有效：`~/.cache/uv` 沒出現，sandbox 的 `uv-cache/` 有內容。
- sandbox 外的變動（安裝前後比對）只有：`~/.local/bin/hermes`、`hermes-acp`、`hermes-agent`（三個兩行的啟動檔，沒有設 `HERMES_HOME`），以及 `~/.zprofile` 新增 3 行（空行、`# Hermes Agent command`、把 `~/.local/bin` 加進 PATH）。`~/.zshrc` 沒有變動。三個啟動檔已刪除、`~/.zprofile` 還原為備份，與安裝前逐字相同；新的 login shell 找不到 `hermes` 指令。
- 實際入口在沒設 `HERMES_HOME` 時會用 `~/.hermes`（入口腳本裡 `get_default_hermes_root()`），所以一律用 `run-hermes.sh`。`run-hermes.sh --version` 正常（Python 3.14.9），執行後 `~/.hermes` 仍不存在。
- `~/.claude`：安裝期間變動的只有 Claude Code 自己的 `history.jsonl`、`sessions/`、`backups/`、`plugins/store`；`install.sh` 全文沒有出現 `.claude`。
- `~/Library/Keychains/login.keychain-db` 在安裝期間（02:29:35）修改時間變動；鑰匙圈裡沒有名稱含 hermes 或 nous 的項目。原因沒查出來（候選：git clone 時 `credential.helper=osxkeychain`，或 macOS 本身）。hermes 有 `agent/vault_keychain.py` 會在執行期把 vault key 存進鑰匙圈（service「Hermes Agent vault key」），移除時要檢查。
- 設定：`auth.adopt_external_logins` 改為 false（原檔備份 `home/config.yaml.orig`）；`telemetry.shared_metrics` 預設 `enabled: false`、`send: false`，不需改。
- sandbox 佔用 2.8 GB。
- 給 ticket 04：安裝同步了 44 個內建 skill（含 imessage、findmy、apple-notes、apple-reminders、claude-code、codex、github 等），也預設啟用背景的 skill curator（約 7 天後第一次執行）。04 要確認客服 agent 看不到這些 skill，並暫停 curator。
