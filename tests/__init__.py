"""RAG 實驗專案的測試套件（unittest）。

測試縫只有 CLI：每個測試以子行程執行 `python -m rag_lab`，只觀察結束碼與
stdout／stderr。端點用 tests/fake_openai_server.py 的假 server，不啟動真實模型。

測試不讀開發機的 .env：python-dotenv 從呼叫端模組（rag_lab/config.py）所在目錄往上找 .env，
不看子行程的工作目錄，所以 repo 根目錄的 .env 會補進測試沒設的欄位（例如 DOCUMENT_HEADERS_FILE），
結果取決於開發機。這裡設 PYTHON_DOTENV_DISABLED=1，測試行程與它啟動的子行程都不載入任何 .env；
專門測 .env 行為的測試自己把它設回 0。

Dependencies: 標準函式庫；圖片夾具用 Pillow（見 tests/test_pipeline.py）。
"""

import os

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
