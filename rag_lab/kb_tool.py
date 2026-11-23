"""知識庫工具：以 MCP（stdio）提供查詢主知識庫的唯一一個工具，給客服 agent（例如 hermes-agent）呼叫。

為什麼存在：客服 agent 由自己的 LLM 主導對話，查知識庫只能透過這個工具（見 `.scratch/telegram-trial/spec.md`）。
包成 MCP server 而不是 hermes plugin，程式碼留在 llm-lab 的版控裡，也能給其他支援 MCP 的 agent 使用。

啟動：`python -m rag_lab.kb_tool [--log 路徑]`，工作目錄為 repo 根目錄（設定沿用 `.env`，與 CLI 相同）。

關鍵設計決策：
- 工具只收一個 `question`，以 mix 模式查詢、不開 VLM 增強，回傳 `Session.query` 的答案原文
  （保留回答附加指示產生的段首卡別標記）；檢索模式不讓 agent 選。
- `Session` 只能在建立它的執行緒使用，且該執行緒不能有執行中的 event loop；MCP SDK 是 asyncio，
  同步工具函式又由 anyio 的執行緒池在不固定的執行緒上執行，所以 `Session` 放在專用的 worker 執行緒，
  查詢以佇列交給它。
- `Session` 在 server 的 lifespan 裡建立：SDK 進入 stdio 模式後才把 fd 1 導到 stderr，
  在那之前建立的話，LightRAG／MinerU 印到 stdout 的內容會混進 MCP 協定的訊息。
- 同一時間只跑一個查詢：有查詢進行中時，新的呼叫不排隊，立刻回傳 BUSY_MESSAGE（一般文字結果，讓 agent 轉告
  使用者）；本機模型一題約 43 秒，排隊會讓後來的人看不出發生什麼事。
- 空白問題、端點或查詢失敗（EndpointError、PipelineError）以 MCP 工具錯誤（ToolError → isError）回傳，訊息說明原因
  （rag_lab 的錯誤訊息本身不含 API key）；預期之外的例外留紀錄後照樣拋出。server 繼續服務下一個呼叫。
- 每次呼叫附加一行 JSONL 紀錄（預設 `output/kb_tool_calls.jsonl`），即使之後移除客服 agent，
  也看得到知識庫實際被問了什麼、答了什麼。

已知極限：
- 讀到的是 server 啟動當下的知識庫；server 開著的期間另一個 process 匯入的內容看不到（`Session` 的限制），
  重新匯入後要重啟 server。

Dependencies: mcp（官方 MCP Python SDK）、anyio（mcp 帶入）、rag_lab.pipeline。
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import Future
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from rag_lab import pipeline
from rag_lab.models import EndpointError
from rag_lab.pipeline import PipelineError

SERVER_NAME = "rag-lab-knowledge-base"
TOOL_NAME = "query_knowledge_base"
MODE = "mix"
DEFAULT_LOG = Path("output") / "kb_tool_calls.jsonl"

BUSY_MESSAGE = "目前有其他人在查詢，請稍候再問"
EMPTY_QUESTION_MESSAGE = "問題是空白的，請提供要查詢的問題"

TOOL_DESCRIPTION = (
    "查詢台新銀行信用卡與金融卡的知識庫，回傳知識庫產生的完整答案。"
    "一次問一個完整、獨立的問題：對話中前面提過的卡名、卡別（信用卡或金融卡）等上下文，"
    "要自己寫進問題裡，知識庫看不到對話紀錄。"
)


# ==============================
# 持有 Session 的 worker 執行緒
# ==============================


class SessionThread:
    """在專用執行緒上開一個 `Session`，依序執行交給它的查詢。"""

    def __init__(self) -> None:
        self._requests: queue.Queue[tuple[str, Future[str]] | None] = queue.Queue()
        self._ready: Future[None] = Future()
        self._thread = threading.Thread(target=self._run, name="kb-session", daemon=False)

    def start(self) -> None:
        """啟動執行緒並等到 `Session` 開好。

        Raises:
            Session 建構時的例外（ConfigError、EndpointError、PipelineError 等），原樣拋出。
        """
        self._thread.start()
        self._ready.result()

    def ask(self, question: str) -> str:
        """把問題交給 worker 執行緒查詢並等待答案。

        Args:
            question: 問題文字。

        Returns:
            `Session.query(question, MODE)` 的答案。

        Raises:
            `Session.query` 拋出的例外，原樣拋出。
        """
        future: Future[str] = Future()
        self._requests.put((question, future))
        return future.result()

    def close(self) -> None:
        """請 worker 執行緒關閉 `Session` 並結束，等它結束。"""
        self._requests.put(None)
        self._thread.join()

    def _run(self) -> None:
        """worker 執行緒本體：開 `Session`、依序處理查詢、收到結束訊號時關閉。"""
        try:
            session = pipeline.Session()
        except BaseException as exc:  # 交給 start() 在呼叫端拋出
            self._ready.set_exception(exc)
            return
        self._ready.set_result(None)
        try:
            while (item := self._requests.get()) is not None:
                question, future = item
                try:
                    future.set_result(session.query(question, MODE))
                except BaseException as exc:  # 交給 ask() 在呼叫端拋出
                    future.set_exception(exc)
        finally:
            session.close()


# ==============================
# 呼叫紀錄
# ==============================


def append_record(log_path: Path, record: dict[str, object]) -> None:
    """把一筆呼叫紀錄附加成 JSONL 的一行。

    Args:
        log_path: 紀錄檔路徑；上層資料夾不存在時建立。
        record: 一筆紀錄。
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ==============================
# MCP server
# ==============================


def build_server(log_path: Path) -> MCPServer:
    """建立提供知識庫工具的 MCP server。

    Args:
        log_path: 呼叫紀錄的 JSONL 檔路徑。

    Returns:
        尚未啟動的 MCPServer；`Session` 在它啟動時（lifespan）才開。
    """
    worker = SessionThread()

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[None]:
        await anyio.to_thread.run_sync(worker.start)
        try:
            yield
        finally:
            await anyio.to_thread.run_sync(worker.close)

    server = MCPServer(name=SERVER_NAME, lifespan=lifespan)
    # 同一時間只跑一個查詢；工具函式都在 server 的 event loop 上執行，檢查與設定之間沒有 await，不需要鎖
    busy = False

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION, structured_output=False)
    async def query_knowledge_base(question: str) -> str:
        nonlocal busy
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        start = time.monotonic()

        def record(status: str, answer: str | None = None, error: str | None = None) -> None:
            seconds = 0.0 if status == "busy" else round(time.monotonic() - start, 3)
            append_record(
                log_path,
                {
                    "started_at": started_at,
                    "question": question,
                    "answer": answer,
                    "status": status,
                    "error": error,
                    "seconds": seconds,
                    "mode": MODE,
                },
            )

        if not question.strip():
            record("error", error=EMPTY_QUESTION_MESSAGE)
            raise ToolError(EMPTY_QUESTION_MESSAGE)
        if busy:
            record("busy")
            return BUSY_MESSAGE
        busy = True
        try:
            answer = await anyio.to_thread.run_sync(worker.ask, question)
        except (EndpointError, PipelineError) as exc:
            message = f"知識庫查詢失敗：{exc}"
            record("error", error=message)
            raise ToolError(message) from exc
        except Exception as exc:
            # 預期之外的失敗：留紀錄後照樣拋出，SDK 回給 agent 的只有固定的「Error executing tool」
            record("error", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            busy = False
        record("ok", answer=answer)
        return answer

    return server


def main(argv: list[str] | None = None) -> None:
    """解析參數並以 stdio 執行 MCP server，直到 client 關閉連線。

    Args:
        argv: 命令列參數；None 表示 sys.argv。
    """
    parser = argparse.ArgumentParser(prog="python -m rag_lab.kb_tool", description="以 MCP（stdio）提供知識庫工具")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help=f"呼叫紀錄 JSONL 檔（預設 {DEFAULT_LOG}）")
    args = parser.parse_args(argv)
    build_server(args.log).run("stdio")


if __name__ == "__main__":
    main()
