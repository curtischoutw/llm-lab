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
import tempfile
import unittest
from pathlib import Path

from tests.fake_openai_server import FakeOpenAIServer

REPO_ROOT = Path(__file__).resolve().parent.parent

# ==============================
# 設定欄位（獨立於 rag_lab.config 的字面清單，來源為 spec／.env.example）
# ==============================

URL_FIELDS = ("LLM_BASE_URL", "VLM_BASE_URL", "EMBED_BASE_URL", "RERANK_BASE_URL")
INT_FIELDS = (
    "EMBED_DIM",
    "EMBED_MAX_TOKEN_SIZE",
    "EMBED_MAX_ASYNC",
    "LLM_MAX_ASYNC",
    "LLM_MAX_TOKENS",
    "VLM_MAX_TOKENS",
    "QUERY_MAX_TOTAL_TOKENS",
)
# 0 以上的整數：0 表示 LightRAG 照常執行、只是不放該類描述
NON_NEGATIVE_INT_FIELDS = ("QUERY_MAX_ENTITY_TOKENS", "QUERY_MAX_RELATION_TOKENS")
TEXT_FIELDS = (
    "LLM_MODEL",
    "LLM_API_KEY",
    "VLM_MODEL",
    "VLM_API_KEY",
    "EMBED_MODEL",
    "EMBED_API_KEY",
    "RERANK_MODEL",
    "RERANK_API_KEY",
    "WORKING_DIR",
    "PARSER_OUTPUT_DIR",
)
REQUIRED_FIELDS = URL_FIELDS + INT_FIELDS + NON_NEGATIVE_INT_FIELDS + TEXT_FIELDS
OPTIONAL_FIELDS = ("EMBED_QUERY_PREFIX",)

SECRET = "sk-TOP-SECRET-0123"


# ==============================
# 工具函式
# ==============================


def valid_env(base_url: str = "http://127.0.0.1:9/v1") -> dict[str, str]:
    """組出一份有效的基準設定。

    Args:
        base_url: 四個端點（LLM、VLM、embedding、rerank）共用的 base URL。

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
            "QUERY_MAX_ENTITY_TOKENS": "6000",
            "QUERY_MAX_RELATION_TOKENS": "8000",
            "LLM_MODEL": "fake-llm",
            "LLM_API_KEY": SECRET,
            "VLM_MODEL": "fake-vlm",
            "VLM_API_KEY": SECRET,
            "EMBED_MODEL": "fake-embed",
            "EMBED_API_KEY": SECRET,
            "RERANK_MODEL": "fake-rerank",
            "RERANK_API_KEY": SECRET,
            "WORKING_DIR": "./rag_storage",
            "PARSER_OUTPUT_DIR": "./output",
        }
    )
    return env


def run_cli(
    args: list[str], overrides: dict[str, str] | None = None, timeout: float = 60, cwd: Path = REPO_ROOT
) -> subprocess.CompletedProcess:
    """以子行程執行 `python -m rag_lab`。

    Args:
        args: 命令列引數。
        overrides: 覆蓋基準設定的環境變數。
        timeout: 子行程逾時秒數。
        cwd: 子行程的工作目錄（預設 repo 根目錄）。

    Returns:
        CompletedProcess（text 模式，已擷取 stdout／stderr）。
    """
    env = {k: v for k, v in os.environ.items() if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS}
    env.update(valid_env())
    env.update(overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "rag_lab", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ==============================
# 子命令註冊
# ==============================
# ingest／query 的行為見 tests/test_pipeline.py，eval 見 tests/test_eval.py；這裡的設定驗證測試
# 用 eval 搭配一個不存在的題目檔當探針：eval 通過設定驗證後會先讀題目檔並以「輸入錯誤」結束，
# 不會去連端點或建立索引資料夾。


class SubcommandsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = FakeOpenAIServer(embed_dim=1024)
        cls.server.start()
        cls.addClassCleanup(cls.server.stop)

    def test_valid_config_eval_reaches_the_command_and_rejects_a_missing_question_file(self):
        result = run_cli(["eval", "questions.jsonl"], valid_env(self.server.base_url))
        self.assertEqual(result.returncode, 2)
        self.assertIn("輸入錯誤", result.stderr)
        self.assertIn("questions.jsonl", result.stderr)
        self.assertNotIn("設定錯誤", result.stderr)


# ==============================
# 設定驗證
# ==============================


class ConfigValidationTest(unittest.TestCase):
    def assert_config_rejected(self, result: subprocess.CompletedProcess, field: str) -> None:
        """斷言 CLI 以設定錯誤的結束碼中止，錯誤訊息指出欄位，且沒有走到子命令本身的輸入檢查。"""
        self.assertEqual(result.returncode, 3)
        self.assertIn("設定錯誤", result.stderr)
        self.assertIn(field, result.stderr)
        self.assertNotIn("輸入錯誤", result.stderr)

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

    def test_negative_or_non_integer_token_limit_names_the_field(self):
        for field in NON_NEGATIVE_INT_FIELDS:
            for bad in ("-1", "abc", "1.5"):
                with self.subTest(field=field, value=bad):
                    result = run_cli(["eval", "q.jsonl"], {field: bad})
                    self.assert_config_rejected(result, field)

    def test_zero_token_limit_is_valid(self):
        for field in NON_NEGATIVE_INT_FIELDS:
            with self.subTest(field=field):
                result = run_cli(["eval", "q.jsonl"], {field: "0"})
                self.assertIn("輸入錯誤", result.stderr)
                self.assertNotIn("設定錯誤", result.stderr)

    def test_entity_and_relation_limits_must_sum_to_less_than_the_total(self):
        # 相加等於總上限時，文字 chunk 一個 token 都沒有
        overrides = {"QUERY_MAX_TOTAL_TOKENS": "12000", "QUERY_MAX_ENTITY_TOKENS": "5000"}
        for relation in ("7000", "7001"):
            with self.subTest(relation=relation):
                result = run_cli(["eval", "q.jsonl"], {**overrides, "QUERY_MAX_RELATION_TOKENS": relation})
                self.assertEqual(result.returncode, 3)
                self.assertIn("設定錯誤", result.stderr)
                for field in ("QUERY_MAX_ENTITY_TOKENS", "QUERY_MAX_RELATION_TOKENS", "QUERY_MAX_TOTAL_TOKENS"):
                    self.assertIn(field, result.stderr)
        result = run_cli(["eval", "q.jsonl"], {**overrides, "QUERY_MAX_RELATION_TOKENS": "6999"})
        self.assertNotIn("設定錯誤", result.stderr)

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
# rag_lab 沒有管理的 LightRAG／RAG-Anything 環境變數
# ==============================

# 來自 ticket 的範例（獨立於 rag_lab.config 的名單）：查詢、匯入、儲存位置、RAG-Anything 各取幾個
UNMANAGED_SAMPLE = ("TOP_K", "COSINE_THRESHOLD", "CHUNK_SIZE", "WORKSPACE", "ENABLE_TABLE_PROCESSING", "MINERU_PARSE_METHOD")
# MinerU 3.4.5 讀的、會改變 `mineru -b pipeline -m auto` 解析結果的變數（來自 ticket env-02 的清單，獨立於 rag_lab.config 的名單）
MINERU_RESULT_ENV = (
    "MINERU_TOOLS_CONFIG_JSON",
    "MINERU_DEVICE_MODE",
    "MINERU_FORMULA_ENABLE",
    "MINERU_TABLE_ENABLE",
    "MINERU_OCR_DET_MASK_INLINE_FORMULA_ENABLE",
    "MINERU_TABLE_MERGE_ENABLE",
    "MINERU_FORMULA_CH_SUPPORT",
    "MINERU_MODEL_SOURCE",
)
# MinerU 讀、但只影響速度、記憶體、log、服務維運，或 rag_lab 的 `-b pipeline` 走不到的變數：不在名單內
MINERU_NON_RESULT_ENV = (
    "MINERU_LOG_LEVEL",
    "MINERU_PROCESSING_WINDOW_SIZE",
    "MINERU_VIRTUAL_VRAM_SIZE",
    "MINERU_PDF_RENDER_THREADS",
    "MINERU_INTRA_OP_NUM_THREADS",
    "MINERU_API_MAX_CONCURRENT_REQUESTS",
    "MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS",
    "MINERU_GRADIO_DEFAULT_LOCALE",
    "MINERU_VLM_TABLE_ENABLE",
    "MINERU_VLM_FORMULA_ENABLE",
    "MINERU_VL_SERVER",
)
# rag_lab 已經明確傳給 LightRAG／RAG-Anything 的參數所對應的變數：不在名單內
MANAGED_ENV_NAMES = (
    "MAX_TOTAL_TOKENS",
    "MAX_ENTITY_TOKENS",
    "MAX_RELATION_TOKENS",
    "CHUNK_TOP_K",
    "RERANK_BY_DEFAULT",
    "MIN_RERANK_SCORE",
    "MAX_ASYNC",
    "MAX_PARALLEL_INSERT",
    "EMBEDDING_FUNC_MAX_ASYNC",
    "WORKING_DIR",
    "OUTPUT_DIR",
    "PARSER",
    "PARSE_METHOD",
)


class UnmanagedLightragEnvTest(unittest.TestCase):
    def assert_rejected_naming(self, result: subprocess.CompletedProcess, names: tuple[str, ...]) -> None:
        """斷言以設定錯誤結束，訊息列出每個變數名稱，且沒有走到子命令本身的輸入檢查。"""
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("設定錯誤", result.stderr)
        for name in names:
            self.assertIn(name, result.stderr)
        self.assertNotIn("輸入錯誤", result.stderr)

    def test_every_subcommand_rejects_a_listed_variable_naming_it_and_never_printing_its_value(self):
        value = "sentinel-value-7731"
        for args in (["ingest", "paper.pdf"], ["query", "q"], ["eval", "questions.jsonl"]):
            for name in UNMANAGED_SAMPLE:
                with self.subTest(args=args[0], name=name):
                    result = run_cli(args, {name: value})
                    self.assert_rejected_naming(result, (name,))
                    self.assertNotIn(value, result.stdout + result.stderr)

    def test_all_offending_variables_are_listed_in_one_message(self):
        result = run_cli(["eval", "q.jsonl"], {name: "1" for name in UNMANAGED_SAMPLE})
        self.assert_rejected_naming(result, UNMANAGED_SAMPLE)

    def test_an_empty_value_is_still_rejected(self):
        result = run_cli(["eval", "q.jsonl"], {"TOP_K": ""})
        self.assert_rejected_naming(result, ("TOP_K",))

    def test_the_error_is_raised_before_any_endpoint_is_contacted(self):
        server = FakeOpenAIServer(embed_dim=1024)
        server.start()
        self.addCleanup(server.stop)
        result = run_cli(["query", "q"], {**valid_env(server.base_url), "TOP_K": "5"})
        self.assert_rejected_naming(result, ("TOP_K",))
        self.assertEqual(server.requests, [])

    def test_parameters_rag_lab_passes_explicitly_are_not_listed(self):
        for name in MANAGED_ENV_NAMES:
            with self.subTest(name=name):
                result = run_cli(["eval", "q.jsonl"], {name: "1"})
                self.assertIn("輸入錯誤", result.stderr)
                self.assertNotIn("設定錯誤", result.stderr)

    def test_every_subcommand_rejects_a_mineru_variable_that_changes_parsing_naming_it_and_never_printing_its_value(self):
        value = "sentinel-value-7731"
        for args in (["ingest", "paper.pdf"], ["query", "q"], ["eval", "questions.jsonl"]):
            for name in MINERU_RESULT_ENV:
                with self.subTest(args=args[0], name=name):
                    result = run_cli(args, {name: value})
                    self.assert_rejected_naming(result, (name,))
                    self.assertNotIn(value, result.stdout + result.stderr)

    def test_a_mineru_variable_in_the_working_directory_dotenv_is_checked_too(self):
        # MinerU 子行程繼承 rag_lab 行程的環境，.env 的內容經 load_dotenv 進入行程環境
        with tempfile.TemporaryDirectory() as cwd:
            Path(cwd, ".env").write_text("MINERU_TABLE_ENABLE=false\n", encoding="utf-8")
            result = run_cli(["eval", "q.jsonl"], {"PYTHONPATH": str(REPO_ROOT)}, cwd=Path(cwd))
        self.assert_rejected_naming(result, ("MINERU_TABLE_ENABLE",))
        self.assertNotIn("false", result.stderr)

    def test_mineru_variables_that_only_affect_speed_logs_or_unreached_backends_are_not_listed(self):
        for name in MINERU_NON_RESULT_ENV:
            with self.subTest(name=name):
                result = run_cli(["eval", "q.jsonl"], {name: "1"})
                self.assertIn("輸入錯誤", result.stderr)
                self.assertNotIn("設定錯誤", result.stderr)

    def test_the_list_covers_the_three_libraries_whose_variables_it_was_generated_from(self):
        from rag_lab.config import UNMANAGED_LIBRARY_ENV_VERSIONS

        self.assertEqual(set(UNMANAGED_LIBRARY_ENV_VERSIONS), {"lightrag-hku", "raganything", "mineru"})

    def test_the_list_was_generated_for_the_installed_library_versions(self):
        # 升級 lightrag-hku、raganything 或 mineru 後這個測試會失敗：照 rag_lab/config.py 模組 docstring 重新產生名單，
        # 更新 UNMANAGED_LIBRARY_ENV 與 UNMANAGED_LIBRARY_ENV_VERSIONS，並同步 README
        from importlib.metadata import version

        from rag_lab.config import UNMANAGED_LIBRARY_ENV_VERSIONS

        installed = {name: version(name) for name in UNMANAGED_LIBRARY_ENV_VERSIONS}
        self.assertEqual(installed, UNMANAGED_LIBRARY_ENV_VERSIONS)

    def test_a_dotenv_file_in_the_working_directory_is_checked_too(self):
        # LightRAG 在 import 時讀的是目前工作目錄的 .env，不是 repo 根目錄的
        with tempfile.TemporaryDirectory() as cwd:
            Path(cwd, ".env").write_text("CHUNK_SIZE=300\n", encoding="utf-8")
            result = run_cli(["eval", "q.jsonl"], {"PYTHONPATH": str(REPO_ROOT)}, cwd=Path(cwd))
        self.assert_rejected_naming(result, ("CHUNK_SIZE",))
        self.assertNotIn("300", result.stderr)


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
        self.assertIn("輸入錯誤", result.stderr)
        self.assertNotIn("設定錯誤", result.stderr)


if __name__ == "__main__":
    unittest.main()
