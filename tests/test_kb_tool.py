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
from tests.test_cli import OPTIONAL_FIELDS, REPO_ROOT, REQUIRED_FIELDS
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
