# 03: rag_lab 設定語言與實體類型

**What to build:** rag_lab 新增 `KB_LANGUAGE` 與 `KB_ENTITY_TYPES` 兩個必填設定，經 `build_rag` 的 `addon_params` 傳給 LightRAG（spec：「語言與實體類型」）。

**Blocked by:** 無

**Status:** ready-for-agent

- [ ] `rag_lab/config.py` 的 Settings 新增兩個欄位。`KB_ENTITY_TYPES` 是逗號分隔，去掉前後空白，空項目或整個空字串以 ConfigError 中止。缺少時 ConfigError，訊息照現有欄位的格式。
- [ ] `rag_lab/pipeline.py` 的 `build_rag` 把 `addon_params={"language": ..., "entity_types": [...]}` 放進 `lightrag_kwargs`。`SUMMARY_LANGUAGE`、`ENTITY_TYPES` 仍留在 `UNMANAGED_LIBRARY_ENV`。
- [ ] 更新 config 與 pipeline 的模組 docstring（新欄位、為什麼由 rag_lab 管理）。
- [ ] `.env`、`.env.example`、README 的設定說明加上兩個欄位，值照 spec。
- [ ] 測試：缺少欄位時 ConfigError；值有傳進 LightRAG 實例的 `addon_params`。`.venv/bin/python -m unittest` 全綠（README:543；改到 `scripts/fetch_taishin.py` 時加跑 README:549 的下載腳本測試）。
