# 01: 啟動 Gemma 4 server、關掉 thinking、量記憶體

**What to build:** 用一個 `mlx_vlm.server`（經 `scripts/vlm_server.py`）載入 `mlx-community/gemma-4-26b-a4b-it-4bit`、Qwen3-Embedding 和 bge-reranker，LLM 與 VLM 都指向它；確認 thinking 關掉，並在預設 GPU 記憶體上限下量出峰值（spec：`.scratch/gemma4-switch/spec.md`「模型與 server」「記憶體」，grill Q2、Q3、Q5、Q6）。

**Blocked by:** 無

**Status:** resolved

- [ ] 下載模型，確認 mlx-vlm 0.7.10 載入得了；載入失敗就停下來回報錯誤訊息，不自行升級 mlx-vlm。
- [ ] 查明 thinking 的關閉方式，用一個文字請求和一個圖片請求確認回應裡沒有推理內容。必須改 `rag_lab/` 的程式碼才能關掉時，停下來回報。
- [ ] 查明 `mlx_lm.server` 的 `--max-tokens 4096`、`--prompt-cache-bytes 4GB` 在 `mlx_vlm.server` 上有沒有對應設定，結果寫進下方。
- [ ] `.env` 的 `LLM_BASE_URL`、`VLM_BASE_URL` 指向同一個 port，`LLM_MODEL`、`VLM_MODEL` 都填 Gemma 4。改之前先備份 `.env`。
- [ ] 開 watchdog（`zsh output/crash_repro/tools/watchdog.sh <log 資料夾> 22 15`），跑一次 `query --mode mix` 和一次 `query --vlm-enhanced`，題目從 `eval/questions.taishin.jsonl` 挑，prompt 要接近 12000 token 上限。記錄 wired 記憶體峰值、server 記憶體、prompt token 數、耗時。
- [ ] OOM 或觸發 watchdog：停下來，回報峰值和差多少，由使用者決定要不要調 `iogpu.wired_limit_mb`；不自動調整，也不往 02 走。
- [ ] 記錄檔放在 `output/gemma4_01/`（gitignore），結果寫進下方。

## 結果（2026-11-11，停在 watchdog 觸發，等使用者決定）

記錄檔在 `output/gemma4_01/`（gitignore）：`download.log`、`vlm_server.log`、`thinking_check.txt`、`query_mix.err`、`watchdog/`，`.env` 備份 `env.qwen.bak`。

**已完成**
- 模型下載：3 個 safetensors 共 15.3 GB；mlx-vlm 0.7.10 載入成功，不用升級。
- thinking：mlx_vlm.server 預設不開（沒給 `--enable-thinking`），chat template 的 `enable_thinking` 預設 false，會在回答前放一段空的 `<|channel>thought` 區塊。文字與圖片請求各一次，回應的 `reasoning_content` 都是 null，內容沒有推理段落。不用改 `rag_lab/`。
- server 參數：`--max-tokens 4096` 有對應；`--prompt-cache-bytes` 沒有對應選項。rag_lab 每個請求自己帶 `max_tokens`（`rag_lab/models.py:347`、`:389`），server 的 `--max-tokens` 只在請求沒帶時生效。
- `.env`：`LLM_BASE_URL` 改成 `http://127.0.0.1:8081/v1`，`LLM_MODEL`、`VLM_MODEL` 改成 Gemma 4。
- 速度：生成約 46–52 token/s。

**記憶體**
- 文字請求（29 token）`peak_memory` 18.35 GB；圖片請求（275 token）19.10 GB。
- `query --mode mix`（新問句，避開 Qwen 的快取）：關鍵字抽取（704 token prompt）完成；rerank 收到 18,218 token 的候選 chunk，執行 5.6 秒，這段期間 wired 從 2 GB 升到 22 GB，22:47:51 觸發 watchdog（門檻 22 GB），server 被停掉。最後產生答案的 LLM 呼叫還沒開始，所以 12k token prompt 生成時的峰值沒有量到。
- watchdog 的 `vlm_fp` 欄位量到的是包住 server 的 shell 行程（固定 2656 KB），不是 server 本身；wired 數字不受影響。

**第一次卡住**
- 預設 GPU 上限加 22 GB watchdog 門檻下，rerank 階段就超過門檻，還沒到生成。依 spec 不自動調 `iogpu.wired_limit_mb`，由使用者決定。

**第二次量測（使用者同意後，`iogpu.wired_limit_mb=26000`）**
- 使用者關掉其他軟體後，執行前：free 22.1 GB、inactive 3.2 GB、系統 wired 2.5 GB。
- watchdog 門檻改成 27 GB、每 3 秒取樣。watchdog 量的是全系統 wired，含 macOS 本身約 2.5 GB。
- 記錄檔在 `output/gemma4_01/run2/`。
- `query --mode mix`：成功，58 秒。rerank 18,218 token；產生答案的 prompt 11,179 token，輸出 593 token，43.3 秒。全系統 wired 峰值 22 GB。關鍵字抽取命中第一次寫進快取的結果，沒有呼叫模型。
- `query --mode mix --vlm-enhanced`：關鍵字抽取（699 token）、embedding、rerank（20,466 token）都完成；產生答案的請求 prompt 10,999 token、1 張圖片，prefill 期間 wired 在 23–27 GB 之間來回，23:00:58 到 27 GB 觸發 watchdog，server 被停掉，沒有產生答案。
- 同樣約 11k token 的 prompt，有圖片時的峰值比純文字高約 5 GB；原因沒有查證。

**第二次卡住**
- 純文字的 mix 查詢在 26 GB 上限下跑得完；`--vlm-enhanced` 查詢在 prefill 階段超過 27 GB 門檻。等使用者決定。

**結案（2026-11-11）**：使用者決定直接進 ticket 02。eval 固定 `vlm_enhanced=False`（`rag_lab/evaluation.py`），走的是已跑通的純文字路徑；`--vlm-enhanced` 在 26B 上超過 27 GB 門檻記為已知限制，不在本票處理。ticket 02 沿用 `iogpu.wired_limit_mb=26000`（重開機會恢復）、watchdog 27 GB／3 秒。
