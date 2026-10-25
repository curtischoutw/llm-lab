# 07: README 與搬機器說明

**What to build:** 一份 README，讓一個月後的使用者能照著重建環境、啟動本地模型 server、跑三個指令，並知道搬到別台機器時要改 `.env` 的哪些項目。

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] 說明如何啟動 LLM server（含 `--max-tokens 4096` 與原因）與 VLM 加 embedding 的 server。
- [ ] 說明如何建立 Python 3.12.12 venv 並安裝鎖定的相依套件。
- [ ] 說明 `ingest`、`query`、`eval` 的用法，各附一個可執行的範例指令。
- [ ] 說明搬機器：哪些 `.env` 欄位要改（三組端點、模型名稱、並行數、輸出長度）、哪個欄位不能改（embedding 模型與維度；更換需要重建索引）。
- [ ] 說明換成更大的 LLM 時，只改 LLM 的 base URL 與模型名稱。
- [ ] 記錄第 03、04 張實測得到的耗時與圖譜品質觀察，標明是哪個模型組合下量到的。
- [ ] README 中的每個指令都在寫完後實際執行過一次；沒執行過的不寫入。
