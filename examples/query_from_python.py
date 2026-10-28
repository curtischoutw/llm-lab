"""範例：在自己的 Python 程式裡對已建好的知識庫提問。

為什麼存在：CLI（`python -m rag_lab query`）適合手動問一題；要在程式裡拿到答案字串再自行處理時，
用 rag_lab.pipeline.Session。這支範例示範最少的用法：開一個 Session，逐題提問、印出問答。

執行方式（在 repo 根目錄；需要先 ingest 過、兩個模型 server 都開著）：
    .venv/bin/python -m examples.query_from_python

關鍵設計決策：
- 用 `python -m` 從 repo 根目錄執行：這樣 `import rag_lab` 才找得到套件，`.env` 裡 WORKING_DIR 等
  相對路徑也才會指向 repo 內的知識庫。
- 設定全部來自 `.env`（與 CLI 相同），範例不另外傳端點或路徑。
- 所有問題在同一個 Session 裡問：知識庫只在開 Session 時載入一次，離開 `with` 時寫回快取並關閉。
  只問一題時也可以直接呼叫 `rag_lab.pipeline.query()`（它等於開一個 Session、問一題、關閉）。
- 不攔例外：.env 缺欄位拋 ConfigError、server 沒開拋 EndpointError、查詢失敗拋 PipelineError，
  直接帶 traceback 結束，讀者看得到是哪一種錯。

已知極限：Session 是同步介面，不能直接在 Jupyter 或 async 函式裡使用；同一個 process 同一時間只能
開一個 Session（規則見 rag_lab.pipeline.Session）。

Dependencies: rag_lab。
"""

from rag_lab.pipeline import Session

QUESTIONS = [
    "What are the two retrieval levels in LightRAG?",
    "What is the main idea of RAG-Anything?",
]


def main() -> None:
    """在一個 Session 裡以 mix 模式逐題提問並印出問答。"""
    with Session() as session:
        for question in QUESTIONS:
            # mode 可選 naive、local、global、hybrid、mix
            answer = session.query(question, mode="mix")
            print(f"Q: {question}")
            print(f"A: {answer}")
            print()


if __name__ == "__main__":
    main()
