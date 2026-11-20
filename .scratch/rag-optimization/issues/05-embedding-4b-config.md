# 05: embedding 設定改成 Qwen3-Embedding-4B

**What to build:** 把 embedding 的設定、server 啟動指令與文件從 Qwen3-Embedding-0.6B 改成 `mlx-community/Qwen3-Embedding-4B-4bit-DWQ`（2560 維）（spec：「embedding」；grill-notes 決定 19、20）。

**Blocked by:** 03（兩張都改 `.env`、`.env.example`、README，依序做避免衝突）

**Status:** resolved（已 merge 進 feat/rag-optimization，ba8c9f8）

- [ ] `.env` 與 `.env.example`：`EMBED_MODEL=mlx-community/Qwen3-Embedding-4B-4bit-DWQ`、`EMBED_DIM=2560`，`EMBED_QUERY_PREFIX` 不變。改 `.env` 前先備份。
- [ ] `README.md` 的 server 啟動指令、`scripts/vlm_server.py`、`scripts/smoke_test.py` 裡寫到 0.6B 的地方改成 4B。用 grep 找全部出現的地方，回報改了哪些。
- [ ] 舊知識庫（1024 維）在重匯之前不能再用新設定查詢：README 加一句說明換 embedding 要重建索引（如果還沒有）。
- [ ] 不啟動 server、不匯入；`.venv/bin/python -m unittest` 全綠（README:543；改到 `scripts/fetch_taishin.py` 時加跑 README:549 的下載腳本測試）。
