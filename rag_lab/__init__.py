"""RAG-Anything 本地實驗專案的套件根。

為什麼存在：讓 `python -m rag_lab` 能執行（見 __main__.py），並讓 rag_lab 成為
正式套件而非 namespace package。刻意不在此 import 任何子模組：CLI 啟動時只該
載入設定驗證，避免為了驗 .env 而拖入 lightrag／torch 的載入時間。

Dependencies: 無。
"""
