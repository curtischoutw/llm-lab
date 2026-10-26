"""CLI 行為測試：從 `python -m rag_lab` 進入，驗證結束碼與輸出。

為什麼存在：spec 的 Testing Decisions 規定唯一測試縫是 CLI。設定驗證、子命令
註冊都只透過 CLI 的外部行為觀察，不 import rag_lab 內部模組。

關鍵設計決策：
- 測試直接設定環境變數，不依賴 .env 檔。「缺漏」以空字串模擬：config 的
  load_dotenv 不覆蓋既有變數，所以空字串能擋住任何殘留的 .env 補值。
- 子行程環境先清掉所有設定欄位，再放入有效的基準設定，避免開發機環境汙染結果。

Dependencies: 僅標準函式庫。
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.fake_openai_server import FakeOpenAIServer

REPO_ROOT = Path(__file__).resolve().parent.parent

# ==============================
# 設定欄位（獨立於 rag_lab.config 的字面清單，來源為 spec／.env.example）
# ==============================

URL_FIELDS = ("LLM_BASE_URL", "VLM_BASE_URL", "EMBED_BASE_URL")
INT_FIELDS = (
    "EMBED_DIM",
    "EMBED_MAX_TOKEN_SIZE",
    "EMBED_MAX_ASYNC",
    "LLM_MAX_ASYNC",
    "LLM_MAX_TOKENS",
    "VLM_MAX_TOKENS",
    "QUERY_MAX_TOTAL_TOKENS",
)
TEXT_FIELDS = (
    "LLM_MODEL",
    "LLM_API_KEY",
    "VLM_MODEL",
    "VLM_API_KEY",
    "EMBED_MODEL",
    "EMBED_API_KEY",
    "WORKING_DIR",
    "PARSER_OUTPUT_DIR",
)
REQUIRED_FIELDS = URL_FIELDS + INT_FIELDS + TEXT_FIELDS
OPTIONAL_FIELDS = ("EMBED_QUERY_PREFIX",)

SECRET = "sk-TOP-SECRET-0123"


# ==============================
# 工具函式
# ==============================


def valid_env(base_url: str = "http://127.0.0.1:9/v1") -> dict[str, str]:
    """組出一份有效的基準設定。

    Args:
        base_url: 三個端點共用的 base URL。

    Returns:
        環境變數 dict，包含所有必填欄位。
    """
    env = {name: base_url for name in URL_FIELDS}
    env.update(
        {
            "EMBED_DIM": "1024",
            "EMBED_MAX_TOKEN_SIZE": "8192",
            "EMBED_MAX_ASYNC": "1",
            "LLM_MAX_ASYNC": "2",
            "LLM_MAX_TOKENS": "4096",
            "VLM_MAX_TOKENS": "1024",
            "QUERY_MAX_TOTAL_TOKENS": "30000",
            "LLM_MODEL": "fake-llm",
            "LLM_API_KEY": SECRET,
            "VLM_MODEL": "fake-vlm",
            "VLM_API_KEY": SECRET,
            "EMBED_MODEL": "fake-embed",
            "EMBED_API_KEY": SECRET,
            "WORKING_DIR": "./rag_storage",
            "PARSER_OUTPUT_DIR": "./output",
        }
    )
    return env


def run_cli(
    args: list[str], overrides: dict[str, str] | None = None, timeout: float = 60
) -> subprocess.CompletedProcess:
    """以子行程執行 `python -m rag_lab`。

    Args:
        args: 命令列引數。
        overrides: 覆蓋基準設定的環境變數。
        timeout: 子行程逾時秒數。

    Returns:
        CompletedProcess（text 模式，已擷取 stdout／stderr）。
    """
    env = {k: v for k, v in os.environ.items() if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS}
    env.update(valid_env())
    env.update(overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "rag_lab", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ==============================
# 子命令註冊
# ==============================
# ingest／query 的行為見 tests/test_pipeline.py；這裡的設定驗證測試用 eval 當探針：
# eval 通過設定驗證後只會印「尚未實作」，不會去連端點或建立索引資料夾。


class SubcommandsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = FakeOpenAIServer(embed_dim=1024)
        cls.server.start()
        cls.addClassCleanup(cls.server.stop)

    def test_valid_config_unimplemented_eval_exits_nonzero_with_message(self):
        result = run_cli(["eval", "questions.jsonl"], valid_env(self.server.base_url))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("尚未實作", result.stderr)
        self.assertNotIn("設定錯誤", result.stderr)


# ==============================
# 設定驗證
# ==============================


class ConfigValidationTest(unittest.TestCase):
    def assert_config_rejected(self, result: subprocess.CompletedProcess, field: str) -> None:
        """斷言 CLI 以非零碼中止、錯誤訊息指出欄位，且不是走到「尚未實作」。"""
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(field, result.stderr)
        self.assertNotIn("尚未實作", result.stderr)

    def test_missing_required_field_names_the_field(self):
        for field in REQUIRED_FIELDS:
            with self.subTest(field=field):
                result = run_cli(["eval", "q.jsonl"], {field: ""})
                self.assert_config_rejected(result, field)

    def test_invalid_url_names_the_field(self):
        for field in URL_FIELDS:
            for bad in ("not-a-url", "ftp://host/v1", "http://", "127.0.0.1:8080/v1"):
                with self.subTest(field=field, value=bad):
                    result = run_cli(["eval", "q.jsonl"], {field: bad})
                    self.assert_config_rejected(result, field)

    def test_non_positive_integer_names_the_field(self):
        for field in INT_FIELDS:
            for bad in ("0", "-5", "abc", "1.5"):
                with self.subTest(field=field, value=bad):
                    result = run_cli(["eval", "q.jsonl"], {field: bad})
                    self.assert_config_rejected(result, field)

    def test_error_output_never_contains_field_values(self):
        leaky = {
            "EMBED_DIM": f"{SECRET}-dim",
            "LLM_BASE_URL": f"ftp://user:{SECRET}@host/v1",
            "VLM_BASE_URL": f"{SECRET}-url",
            "LLM_MAX_TOKENS": f"-{SECRET}",
        }
        for field, bad in leaky.items():
            with self.subTest(field=field):
                result = run_cli(["eval", "q.jsonl"], {field: bad})
                self.assert_config_rejected(result, field)
                combined = result.stdout + result.stderr
                self.assertNotIn(SECRET, combined)
                self.assertNotIn(bad, combined)

    def test_valid_config_never_prints_api_keys(self):
        result = run_cli(["eval", "q.jsonl"])
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_config_is_validated_before_every_subcommand(self):
        for args in (["ingest", "paper.pdf"], ["query", "q"], ["eval", "questions.jsonl"]):
            with self.subTest(args=args):
                result = run_cli(args, {"EMBED_DIM": ""})
                self.assert_config_rejected(result, "EMBED_DIM")


# ==============================
# .env.example
# ==============================


def parse_env_example() -> dict[str, str]:
    """解析 .env.example 的 KEY=VALUE 行（忽略註解與空行）。

    Returns:
        欄位名稱到範本值的 dict。
    """
    values: dict[str, str] = {}
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition("=")
            values[key] = value
    return values


class EnvExampleTest(unittest.TestCase):
    def test_lists_every_field_exactly_once_and_is_itself_a_valid_config(self):
        template = parse_env_example()
        self.assertEqual(set(template), set(REQUIRED_FIELDS + OPTIONAL_FIELDS))
        result = run_cli(["eval", "q.jsonl"], template)
        self.assertIn("尚未實作", result.stderr)
        self.assertNotIn("設定錯誤", result.stderr)


if __name__ == "__main__":
    unittest.main()
