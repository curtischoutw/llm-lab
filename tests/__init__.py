"""RAG 實驗專案的測試套件（unittest）。

測試縫只有 CLI：每個測試以子行程執行 `python -m rag_lab`，只觀察結束碼與
stdout／stderr。端點用 tests/fake_openai_server.py 的假 server，不啟動真實模型。

Dependencies: 僅標準函式庫。
"""
