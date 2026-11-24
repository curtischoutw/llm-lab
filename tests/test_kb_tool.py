"""知識庫工具（rag_lab.kb_tool）的行為測試：從 MCP 協定的外面驗證。

為什麼存在：客服 agent 只透過 MCP（stdio）呼叫知識庫工具，所以測試也站在同一個位置：以子行程啟動 server，
用官方 MCP SDK 的 client 列工具、發問，只看工具清單、呼叫結果與 JSONL 紀錄，不 import 模組內部。

關鍵設計決策：
- 後端是 tests.fake_openai_server，知識庫先以 CLI 的 `ingest` 匯入一份假 PDF（PipelineCase 的夾具），
  再啟動 server 查詢；環境變數組法與 run_cli 相同（移除外部環境的設定欄位，再套上指向假 server 的設定）。
- 子行程在 repo 根目錄執行，與 hermes 設定的工作目錄相同。

Dependencies: mcp（client 與 StdioServerParameters）、tests.test_pipeline 的 PipelineCase、tests.test_cli 的設定欄位。
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from tests.fake_openai_server import CHAT_REPLY
from tests.test_cli import OPTIONAL_FIELDS, REPO_ROOT, REQUIRED_FIELDS, SECRET
from tests.test_pipeline import INGEST_TIMEOUT, PipelineCase, closed_port_url

TOOL_NAME = "query_knowledge_base"
QUESTION = "What is Fake Entity Alpha?"


class KnowledgeBaseToolCase(PipelineCase):
    """已匯入一份文件的暫存知識庫，加上啟動知識庫工具的輔助函式。"""

    def setUp(self):
        super().setUp()
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log = self.tmp / "calls" / "kb_tool_calls.jsonl"

    def server_params(self, **overrides: str) -> StdioServerParameters:
        """組出以子行程啟動知識庫工具的參數。

        Args:
            **overrides: 覆蓋的環境變數。

        Returns:
            StdioServerParameters（工作目錄為 repo 根目錄）。
        """
        env = {k: v for k, v in os.environ.items() if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS}
        env.update(self.env(**overrides))
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "rag_lab.kb_tool", "--log", str(self.log)],
            env=env,
            cwd=str(REPO_ROOT),
        )

    def run_client(self, steps, **overrides: str):
        """啟動知識庫工具、連上之後執行 steps(client)，回傳它的結果。

        Args:
            steps: 收到已連線 Client 的 async 函式。
            **overrides: 覆蓋的環境變數。

        Returns:
            steps 的回傳值。
        """

        async def session():
            async with Client(self.server_params(**overrides)) as client:
                return await steps(client)

        return asyncio.run(asyncio.wait_for(session(), timeout=INGEST_TIMEOUT))

    def records(self) -> list[dict]:
        """讀出 JSONL 紀錄。

        Returns:
            每一行解析後的 dict。
        """
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


def answer_text(result) -> str:
    """把工具結果的文字內容接起來。

    Args:
        result: CallToolResult。

    Returns:
        所有 text content 串起來的字串。
    """
    return "".join(item.text for item in result.content if item.type == "text")


class ToolListTest(KnowledgeBaseToolCase):
    def test_lists_exactly_one_tool_that_takes_only_a_question(self):
        async def steps(client):
            return (await client.list_tools()).tools

        tools = self.run_client(steps)

        self.assertEqual([tool.name for tool in tools], [TOOL_NAME])
        schema = tools[0].input_schema
        self.assertEqual(set(schema["properties"]), {"question"})
        self.assertEqual(schema["properties"]["question"]["type"], "string")
        self.assertEqual(schema["required"], ["question"])
        self.assertIn("一次問一個完整、獨立的問題", tools[0].description)


class AnswerTest(KnowledgeBaseToolCase):
    def test_returns_the_knowledge_base_answer_and_records_the_call(self):
        async def steps(client):
            return await client.call_tool(TOOL_NAME, {"question": QUESTION})

        result = self.run_client(steps)

        self.assertFalse(result.is_error, answer_text(result))
        self.assertEqual(answer_text(result), CHAT_REPLY)
        [record] = self.records()
        self.assertEqual(record["question"], QUESTION)
        self.assertEqual(record["answer"], CHAT_REPLY)
        self.assertEqual(record["status"], "ok")
        self.assertIsNone(record["error"])
        self.assertEqual(record["mode"], "mix")
        self.assertGreaterEqual(record["seconds"], 0)
        self.assertIsNotNone(datetime_with_zone(record["started_at"]).tzinfo)

    def test_query_runs_in_mix_mode(self):
        async def steps(client):
            return await client.call_tool(TOOL_NAME, {"question": QUESTION})

        self.run_client(steps)

        # LightRAG 的答案快取 key 是 `{檢索模式}:query:{雜湊}`，server 結束時 Session.close() 寫回檔案；
        # 從請求內容分不出 mix 與 hybrid（兩者都抽關鍵字），快取 key 分得出來
        cache = json.loads((self.working_dir / "kv_store_llm_response_cache.json").read_text(encoding="utf-8"))
        modes = {key.split(":", 1)[0] for key in cache if ":query:" in key}
        self.assertEqual(modes, {"mix"})

    def test_two_calls_on_one_server_both_succeed(self):
        async def steps(client):
            first = await client.call_tool(TOOL_NAME, {"question": QUESTION})
            second = await client.call_tool(TOOL_NAME, {"question": "What links Alpha and Beta?"})
            return first, second

        first, second = self.run_client(steps)

        self.assertFalse(first.is_error, answer_text(first))
        self.assertFalse(second.is_error, answer_text(second))
        self.assertEqual([r["status"] for r in self.records()], ["ok", "ok"])


class StartupFailureTest(KnowledgeBaseToolCase):
    def test_unreachable_endpoint_stops_the_server_with_the_reason_on_stderr(self):
        params = self.server_params(LLM_BASE_URL=closed_port_url())

        # 不經 MCP client：server 在 lifespan 開 Session 就失敗，直接看結束碼與 stderr
        result = subprocess.run(
            [params.command, *params.args],
            cwd=params.cwd,
            env=params.env,
            input="",
            capture_output=True,
            text=True,
            timeout=INGEST_TIMEOUT,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EndpointError: LLM 端點", result.stderr)
        self.assertFalse(self.log.exists())


def datetime_with_zone(text: str):
    """解析 ISO 8601 時間字串。

    Args:
        text: ISO 8601 字串。

    Returns:
        datetime。
    """
    from datetime import datetime

    return datetime.fromisoformat(text)


# ==============================
# 忙碌回覆與錯誤處理（ticket 02）
# ==============================

BUSY_MESSAGE = "目前有其他人在查詢，請稍候再問"


class BusyTest(KnowledgeBaseToolCase):
    def test_a_call_during_a_running_query_gets_the_busy_reply_at_once(self):
        self.server.chat_delay = 3.0
        self.server.reset_max_inflight()  # setUp 的匯入會同時送 2 個 chat 請求，只量查詢期間

        async def steps(client):
            first = asyncio.create_task(client.call_tool(TOOL_NAME, {"question": QUESTION}))
            await asyncio.sleep(1.0)
            loop = asyncio.get_running_loop()
            started = loop.time()
            second = await client.call_tool(TOOL_NAME, {"question": "What links Alpha and Beta?"})
            second_seconds = loop.time() - started
            return await first, second, second_seconds

        first, second, second_seconds = self.run_client(steps)

        self.assertFalse(second.is_error, answer_text(second))
        self.assertEqual(answer_text(second), BUSY_MESSAGE)
        self.assertLess(second_seconds, 1.5)  # 不等第一個查詢（每個 chat 請求延遲 3 秒）
        self.assertFalse(first.is_error, answer_text(first))
        self.assertEqual(answer_text(first), CHAT_REPLY)
        self.assertEqual(self.server.max_inflight_chat, 1)
        busy = [r for r in self.records() if r["status"] == "busy"]
        self.assertEqual(len(busy), 1)
        self.assertEqual(busy[0]["question"], "What links Alpha and Beta?")
        self.assertIsNone(busy[0]["answer"])
        self.assertEqual(busy[0]["seconds"], 0)
        self.assertEqual(sorted(r["status"] for r in self.records()), ["busy", "ok"])

    def test_after_the_running_query_finishes_the_next_call_is_answered(self):
        async def steps(client):
            first = await client.call_tool(TOOL_NAME, {"question": QUESTION})
            second = await client.call_tool(TOOL_NAME, {"question": "What links Alpha and Beta?"})
            return first, second

        first, second = self.run_client(steps)

        self.assertEqual(answer_text(second), CHAT_REPLY)
        self.assertNotIn("busy", [r["status"] for r in self.records()])


class ErrorTest(KnowledgeBaseToolCase):
    def test_a_blank_question_is_a_tool_error_without_querying(self):
        async def steps(client):
            return await client.call_tool(TOOL_NAME, {"question": "  \n "})

        before = len(self.server.requests)
        result = self.run_client(steps)

        self.assertTrue(result.is_error)
        self.assertIn("問題是空白的", answer_text(result))
        self.assertEqual(len(self.server.requests), before)  # 沒有送出任何模型請求
        [record] = self.records()
        self.assertEqual(record["status"], "error")
        self.assertIsNone(record["answer"])
        self.assertIn("問題是空白的", record["error"])

    def test_a_failed_query_is_a_tool_error_with_the_reason_and_the_next_call_succeeds(self):
        async def steps(client):
            self.server.fail_chat = True
            failed = await client.call_tool(TOOL_NAME, {"question": QUESTION})
            self.server.fail_chat = False
            ok = await client.call_tool(TOOL_NAME, {"question": "What links Alpha and Beta?"})
            return failed, ok

        failed, ok = self.run_client(steps)

        self.assertTrue(failed.is_error)
        self.assertIn("知識庫查詢失敗", answer_text(failed))
        self.assertNotIn(SECRET, answer_text(failed))
        self.assertFalse(ok.is_error, answer_text(ok))
        self.assertEqual(answer_text(ok), CHAT_REPLY)
        error, success = self.records()
        self.assertEqual(error["status"], "error")
        self.assertIsNone(error["answer"])
        self.assertIn("知識庫查詢失敗", error["error"])
        self.assertNotIn(SECRET, error["error"])
        self.assertEqual(success["status"], "ok")

    def test_a_rerank_failure_is_a_tool_error_naming_rerank(self):
        async def steps(client):
            self.server.rerank_fault = "http500"
            failed = await client.call_tool(TOOL_NAME, {"question": QUESTION})
            self.server.rerank_fault = None
            ok = await client.call_tool(TOOL_NAME, {"question": QUESTION})
            return failed, ok

        failed, ok = self.run_client(steps)

        self.assertTrue(failed.is_error)
        self.assertIn("rerank 失敗", answer_text(failed))
        self.assertNotIn(SECRET, answer_text(failed))
        self.assertEqual(answer_text(ok), CHAT_REPLY)
        self.assertEqual([r["status"] for r in self.records()], ["error", "ok"])

    def test_an_unreachable_rerank_endpoint_is_a_tool_error_naming_the_endpoint(self):
        # server 啟動只檢查 LLM 與 embedding；rerank 端點在查詢前檢查，連不上時拋 EndpointError
        async def steps(client):
            return await client.call_tool(TOOL_NAME, {"question": QUESTION})

        result = self.run_client(steps, RERANK_BASE_URL=closed_port_url())

        self.assertTrue(result.is_error)
        self.assertIn("知識庫查詢失敗", answer_text(result))
        self.assertIn("Rerank 端點", answer_text(result))
        [record] = self.records()
        self.assertEqual(record["status"], "error")
        self.assertIn("Rerank 端點", record["error"])

    def test_an_unexpected_exception_is_recorded_and_still_fails_the_call(self):
        crash = {"PYTHONPATH": str(Path(__file__).parent / "query_crash"), "CRASH_QUERY_CONTAINING": "Crash"}

        async def steps(client):
            crashed = await client.call_tool(TOOL_NAME, {"question": "Crash this question"})
            ok = await client.call_tool(TOOL_NAME, {"question": QUESTION})
            return crashed, ok

        crashed, ok = self.run_client(steps, **crash)

        self.assertTrue(crashed.is_error)
        # 預期之外的例外照樣拋出：SDK 只回固定訊息，不含例外內容
        self.assertNotIn("injected unexpected failure", answer_text(crashed))
        self.assertNotIn("知識庫查詢失敗", answer_text(crashed))
        self.assertEqual(answer_text(ok), CHAT_REPLY)
        error, success = self.records()
        self.assertEqual(error["status"], "error")
        self.assertEqual(error["error"], "RuntimeError: injected unexpected failure")
        self.assertIsNone(error["answer"])
        self.assertEqual(success["status"], "ok")
