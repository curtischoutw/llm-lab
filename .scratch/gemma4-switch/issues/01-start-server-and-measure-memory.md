# 01: 啟動 Gemma 4 server、關掉 thinking、量記憶體

**What to build:** 用一個 `mlx_vlm.server`（經 `scripts/vlm_server.py`）載入 `mlx-community/gemma-4-26b-a4b-it-4bit`、Qwen3-Embedding 和 bge-reranker，LLM 與 VLM 都指向它；確認 thinking 關掉，並在預設 GPU 記憶體上限下量出峰值（spec：`.scratch/gemma4-switch/spec.md`「模型與 server」「記憶體」，grill Q2、Q3、Q5、Q6）。

**Blocked by:** 無

**Status:** ready-for-agent

- [ ] 下載模型，確認 mlx-vlm 0.7.10 載入得了；載入失敗就停下來回報錯誤訊息，不自行升級 mlx-vlm。
- [ ] 查明 thinking 的關閉方式，用一個文字請求和一個圖片請求確認回應裡沒有推理內容。必須改 `rag_lab/` 的程式碼才能關掉時，停下來回報。
- [ ] 查明 `mlx_lm.server` 的 `--max-tokens 4096`、`--prompt-cache-bytes 4GB` 在 `mlx_vlm.server` 上有沒有對應設定，結果寫進下方。
- [ ] `.env` 的 `LLM_BASE_URL`、`VLM_BASE_URL` 指向同一個 port，`LLM_MODEL`、`VLM_MODEL` 都填 Gemma 4。改之前先備份 `.env`。
- [ ] 開 watchdog（`zsh output/crash_repro/tools/watchdog.sh <log 資料夾> 22 15`），跑一次 `query --mode mix` 和一次 `query --vlm-enhanced`，題目從 `eval/questions.taishin.jsonl` 挑，prompt 要接近 12000 token 上限。記錄 wired 記憶體峰值、server 記憶體、prompt token 數、耗時。
- [ ] OOM 或觸發 watchdog：停下來，回報峰值和差多少，由使用者決定要不要調 `iogpu.wired_limit_mb`；不自動調整，也不往 02 走。
- [ ] 記錄檔放在 `output/gemma4_01/`（gitignore），結果寫進下方。

## 結果

（待填）
