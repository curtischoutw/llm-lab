"""範例：在自己的 Python 程式裡對已建好的知識庫提問。

為什麼存在：CLI（`python -m rag_lab query`）適合手動問一題；要在程式裡拿到答案字串再自行處理時，
直接呼叫 rag_lab.pipeline.query。這支範例示範最少的用法：一份問題清單，逐題提問、印出問答。

執行方式（在 repo 根目錄；需要先 ingest 過、兩個模型 server 都開著）：
    .venv/bin/python -m examples.query_from_python

關鍵設計決策：
- 用 `python -m` 從 repo 根目錄執行：這樣 `import rag_lab` 才找得到套件，`.env` 裡 WORKING_DIR 等
  相對路徑也才會指向 repo 內的知識庫。
- 設定全部來自 `.env`（與 CLI 相同），範例不另外傳端點或路徑。
- 不攔例外：.env 缺欄位拋 ConfigError、server 沒開拋 EndpointError、查詢失敗拋 PipelineError，
  直接帶 traceback 結束，讀者看得到是哪一種錯。

已知極限：query() 每次呼叫都會重新建立 RAGAnything 實例並載入知識庫（每題多幾秒），
適合少量提問，不適合當常駐服務。

Dependencies: rag_lab。
"""

from rag_lab.pipeline import query

QUESTIONS = [
    "What are the two retrieval levels in LightRAG?",
    "What is the main idea of RAG-Anything?",
]


def main() -> None:
    """以 mix 模式逐題提問並印出問答。"""
    for question in QUESTIONS:
        # mode 可選 naive、local、global、hybrid、mix
        answer = query(question, mode="mix")
        print(f"Q: {question}")
        print(f"A: {answer}")
        print()


if __name__ == "__main__":
    main()
