"""查詢時抽關鍵字的輸出 JSON 有小錯的行為測試：照常查詢，解析不出關鍵字格式時以指出原因的錯誤失敗。

為什麼存在：openai SDK 的嚴格驗證（chat.completions.parse() 用 pydantic 驗證）擋在 LightRAG 的
json_repair 之前，關鍵字輸出有小錯（例如陣列少了 `]`）時整個查詢失敗（見
.scratch/keyword-extraction-json/issues/01）。這裡從假 OpenAI server 的縫驗證修復後的行為：CLI 子行程
（query）、Python API（同一個 process 內呼叫 query）與 eval 的格。

關鍵設計決策：
- 假 server 以 keywords_reply 回傳指定的原文（原樣放進 message.content），模擬模型輸出不合法的 JSON。
- 「修好的關鍵字真的被拿去檢索」從 embeddings 請求觀察：LightRAG 把低階關鍵字串起來後送去 embedding，
  關鍵字被丟掉時（空陣列）問題少於 50 字元會改用整題當關鍵字，請求裡就不會出現標記字串。
- 預期值（response_format 的 schema、錯誤訊息的格式）寫成字面值，不從 rag_lab 取值。

Dependencies: 標準函式庫（其餘夾具來自 tests.test_pipeline、tests.test_python_api、tests.test_eval）。
"""

import json

from tests import test_eval
from tests.fake_openai_server import CHAT_REPLY
from tests.test_cli import SECRET
from tests.test_pipeline import PipelineCase
from tests.test_python_api import PythonApiCase

# 標記字串：只會從關鍵字輸出進入檢索，題目與假索引的內容都不含它
MARKER = "Zebra Marker Keyword"
# 低階關鍵字陣列少了 `]`（調查票 01 量到的失敗樣子）
MISSING_BRACKET = '{"high_level_keywords": ["fake topic"], "low_level_keywords": ["' + MARKER + '"\n}'
NOT_JSON = "Sorry, I cannot extract keywords for this question."
NOT_JSON_MESSAGE = "抽關鍵字的輸出不是合法的 JSON"
# 無法整理成關鍵字格式的輸出：都應該以「不是合法的 JSON」失敗
UNUSABLE_OUTPUTS = {
    "plain text": NOT_JSON,
    "JSON array": '["a", "b"]',
    "JSON string": '"just a string"',
    "empty object": "{}",
    "both fields are not arrays": '{"high_level_keywords": "a", "low_level_keywords": 3}',
}


def keyword_inputs(server) -> list[str]:
    """假 server 收到的 embeddings 請求的所有輸入文字（含建索引與查詢）。"""
    texts: list[str] = []
    for request in server.requests:
        if request["path"] != "/v1/embeddings":
            continue
        inputs = request["payload"]["input"]
        texts.extend([inputs] if isinstance(inputs, str) else inputs)
    return texts


# ==============================
# CLI：query
# ==============================


class QueryKeywordJsonTest(PipelineCase):
    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.requests_before_query = len(self.server.requests)

    def test_a_missing_bracket_is_repaired_and_the_repaired_keywords_are_used_for_retrieval(self):
        self.assertTrue(self.marker_was_retrieved_with(MISSING_BRACKET), "修好的低階關鍵字應該送去 embedding 檢索")

    def marker_was_retrieved_with(self, reply: str) -> bool:
        """以指定的關鍵字輸出查詢一次，確認成功且標記字串被送去檢索。

        Args:
            reply: 假 server 對關鍵字請求回的原文。

        Returns:
            標記字串是否出現在查詢送出的 embeddings 輸入。
        """
        self.server.keywords_reply = reply
        before = len(keyword_inputs(self.server))
        result = self.query()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), CHAT_REPLY)
        return any(MARKER in text for text in keyword_inputs(self.server)[before:])

    def test_a_valid_output_gives_lightrag_the_same_keywords_as_before(self):
        valid = json.dumps({"high_level_keywords": ["fake topic"], "low_level_keywords": [MARKER]})
        self.assertTrue(self.marker_was_retrieved_with(valid))

    def test_think_tags_are_removed_before_parsing(self):
        self.assertTrue(self.marker_was_retrieved_with("<think>reasoning {not json</think>" + MISSING_BRACKET))

    def test_only_string_items_are_kept_and_a_missing_field_counts_as_empty(self):
        mixed = json.dumps({"high_level_keywords": ["fake topic", 1, None], "low_level_keywords": [MARKER, {"x": 1}, ["y"]]})
        self.assertTrue(self.marker_was_retrieved_with(mixed))
        self.assertTrue(self.marker_was_retrieved_with(json.dumps({"low_level_keywords": [MARKER]})))
        self.assertTrue(self.marker_was_retrieved_with(json.dumps({"high_level_keywords": 5, "low_level_keywords": [MARKER]})))

    def test_two_empty_arrays_are_not_a_failure_and_lightrag_falls_back_to_the_question(self):
        self.assertFalse(self.marker_was_retrieved_with('{"high_level_keywords": [], "low_level_keywords": []}'))

    def test_an_output_without_the_keyword_format_fails_naming_the_cause_and_the_start_of_the_output(self):
        for label, output in UNUSABLE_OUTPUTS.items():
            with self.subTest(output=label):
                self.server.keywords_reply = output
                result = self.query()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f"LLM 端點 {self.server.base_url} 失敗：{NOT_JSON_MESSAGE}：{output}", result.stderr)
                self.assertEqual(result.stdout.strip(), "")
                self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_the_failure_message_shows_at_most_the_first_200_characters_of_the_output(self):
        self.server.keywords_reply = "A" * 200 + "TAILMARK"
        result = self.query()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{NOT_JSON_MESSAGE}：{'A' * 200}", result.stderr)
        self.assertNotIn("TAILMARK", result.stderr)

    def test_a_failed_keyword_parse_does_not_retry_the_request(self):
        self.server.keywords_reply = NOT_JSON
        result = self.query()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        keyword_requests = [
            r for r in self.server.requests[self.requests_before_query :] if r["payload"].get("response_format")
        ]
        self.assertEqual(len(keyword_requests), 1)

    def test_the_keyword_request_still_carries_the_same_json_schema(self):
        result = self.query()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        keyword_requests = [
            r
            for r in self.server.requests[self.requests_before_query :]
            if r["path"] == "/v1/chat/completions" and r["payload"].get("response_format")
        ]
        self.assertEqual(len(keyword_requests), 1)
        self.assertEqual(
            keyword_requests[0]["payload"]["response_format"],
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "GPTKeywordExtractionFormat",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "high_level_keywords": {
                                "items": {"type": "string"},
                                "title": "High Level Keywords",
                                "type": "array",
                            },
                            "low_level_keywords": {
                                "items": {"type": "string"},
                                "title": "Low Level Keywords",
                                "type": "array",
                            },
                        },
                        "required": ["high_level_keywords", "low_level_keywords"],
                        "additionalProperties": False,
                        "title": "GPTKeywordExtractionFormat",
                    },
                },
            },
        )


# ==============================
# Python API：query
# ==============================


class ApiKeywordJsonTest(PythonApiCase):
    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)

    def test_a_missing_bracket_does_not_fail_the_query(self):
        self.server.keywords_reply = MISSING_BRACKET
        for mode in ("functions", "session"):
            with self.subTest(mode=mode):
                result = self.run_api("query", "query", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.splitlines(), [f"query {CHAT_REPLY}"] * 2)

    def test_an_output_without_the_keyword_format_raises_naming_the_cause_and_the_next_query_is_unaffected(self):
        self.server.keywords_reply = NOT_JSON
        for mode in ("functions", "session"):
            with self.subTest(mode=mode):
                result = self.run_api("query_error", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                (line,) = result.stdout.splitlines()
                # LightRAG 把查詢途中的 LLM 例外轉成失敗狀態，pipeline 再轉成 PipelineError；EndpointError 的文字留在訊息裡
                self.assertIn(f"LLM 端點 {self.server.base_url} 失敗：{NOT_JSON_MESSAGE}：{NOT_JSON}", line)
                self.assertTrue(line.startswith("query_error PipelineError "), line)
                self.assertNotIn(SECRET, result.stdout + result.stderr)


# ==============================
# eval：格的成敗
# ==============================


class EvalKeywordJsonTest(test_eval.IngestedEvalCase):
    def test_a_missing_bracket_does_not_fail_any_cell(self):
        # local 模式只用低階關鍵字檢索實體，所以這裡用假索引裡真的有的實體名稱（不是標記字串）
        self.server.keywords_reply = '{"high_level_keywords": ["fake topic"], "low_level_keywords": ["Fake Entity Alpha"\n}'
        result = self.run_eval(self.write_questions(test_eval.question_line()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("完成：5 格，失敗 0 格", result.stdout)

    def test_an_output_without_the_keyword_format_fails_only_the_modes_that_extract_keywords(self):
        self.server.keywords_reply = NOT_JSON
        result = self.run_eval(self.write_questions(test_eval.question_line()))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("完成：5 格，失敗 4 格", result.stdout)
        markdown = self.result_files()[0].read_text(encoding="utf-8")
        (row,) = test_eval.table_rows(markdown)
        cells = dict(zip(test_eval.table_header(markdown), row))
        self.assertEqual(cells["naive"], CHAT_REPLY)
        for mode in ("local", "global", "hybrid", "mix"):
            self.assertIn("失敗", cells[mode], mode)
            self.assertIn(NOT_JSON_MESSAGE, cells[mode], mode)
