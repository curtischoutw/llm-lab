"""eval 子命令的 CLI 行為測試：對假 OpenAI server 與假 mineru 跑題目檔。

為什麼存在：ticket 06 的 eval 要批次比較五種檢索模式並輸出 Markdown 對照表。spec 的測試縫
只有 CLI，所以這裡從 `python -m rag_lab eval` 進入，只觀察結束碼、stdout／stderr、產生的
結果檔，以及假 server 在 HTTP 邊界收到的請求。

關鍵設計決策：
- 題目檔格式錯誤的測試不需要索引：驗證在連任何端點、建任何資料夾之前完成，所以測試順便斷言
  假 server 沒收到請求、索引與結果資料夾都沒建立。
- 執行類測試先 ingest 一份假 PDF，再對同一份索引跑 eval。
- 範例題目檔（eval/questions.example.jsonl）直接拿來當輸入，同時驗證它是合法的題目檔；
  斷言用的 id、題型、參考答案從該檔讀出，不在測試裡另寫一份。

Dependencies: 僅標準函式庫。
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from tests.fake_openai_server import CHAT_REPLY
from tests.test_cli import REPO_ROOT, SECRET, run_cli
from tests.test_pipeline import INGEST_TIMEOUT, PipelineCase, closed_port_url

EXAMPLE_FILE = REPO_ROOT / "eval" / "questions.example.jsonl"
MODES = ("naive", "local", "global", "hybrid", "mix")
QUESTION_TYPES = ("text", "figure", "table", "cross-paper")


# ==============================
# 工具函式
# ==============================


def question_line(**overrides: object) -> str:
    """組出一行合法的題目 JSON，再以 overrides 覆蓋或刪除（值為 None 表示刪除）欄位。

    Args:
        **overrides: 要覆蓋的欄位。

    Returns:
        一行 JSON 字串。
    """
    record: dict[str, object] = {
        "id": "q1",
        "question": "What is Fake Entity Alpha?",
        "reference": "A made-up concept.",
        "type": "text",
        "source": "fake.pdf",
    }
    record.update(overrides)
    return json.dumps({k: v for k, v in record.items() if v is not None}, ensure_ascii=False)


def table_rows(markdown: str) -> list[list[str]]:
    """取出 Markdown 表格的資料列（不含表頭與分隔線），每列依未跳脫的 `|` 切成儲存格。

    Args:
        markdown: 結果檔全文。

    Returns:
        每個資料列的儲存格文字（已去除前後空白）。
    """
    lines = [line for line in markdown.splitlines() if line.startswith("|")]
    rows = []
    for line in lines[2:]:
        cells = re.split(r"(?<!\\)\|", line)[1:-1]
        rows.append([cell.strip() for cell in cells])
    return rows


def table_header(markdown: str) -> list[str]:
    """取出 Markdown 表格的表頭欄名。"""
    header = next(line for line in markdown.splitlines() if line.startswith("|"))
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", header)[1:-1]]


class EvalCase(PipelineCase):
    """在 PipelineCase 之上提供 eval 執行輔助與結果資料夾。"""

    def setUp(self):
        super().setUp()
        self.results_dir = self.tmp / "eval_results"

    def write_questions(self, *lines: str, name: str = "questions.jsonl") -> Path:
        """把題目行寫成題目檔。

        Args:
            *lines: 檔案內容的每一行。
            name: 檔名。

        Returns:
            題目檔路徑。
        """
        path = self.tmp / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def run_eval(self, questions: Path, *extra: str, **overrides: str) -> subprocess.CompletedProcess:
        """執行 `eval`，結果檔放進暫存資料夾。"""
        return run_cli(
            ["eval", str(questions), "--output-dir", str(self.results_dir), *extra],
            self.env(**overrides),
            timeout=INGEST_TIMEOUT,
        )

    def result_files(self) -> list[Path]:
        """結果資料夾內的 Markdown 結果檔。"""
        return sorted(self.results_dir.glob("*.md")) if self.results_dir.exists() else []


class IngestedEvalCase(EvalCase):
    """先匯入一份假 PDF，之後的 eval 對這份索引查詢。"""

    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.requests_before_eval = len(self.server.requests)

    def eval_requests(self) -> list[dict]:
        """匯入完成後才收到的請求。"""
        return self.server.requests[self.requests_before_eval :]

    def answer_requests(self) -> list[dict]:
        """匯入完成後送出的答案請求（不含關鍵字抽取）。"""
        return [
            r
            for r in self.eval_requests()
            if r["path"] == "/v1/chat/completions" and not r["payload"].get("response_format")
        ]

    def keyword_requests(self) -> list[dict]:
        """匯入完成後送出的關鍵字抽取請求。"""
        return [
            r
            for r in self.eval_requests()
            if r["path"] == "/v1/chat/completions" and r["payload"].get("response_format")
        ]


# ==============================
# 題目檔格式
# ==============================


class EvalQuestionFileTest(EvalCase):
    def assert_rejected_before_any_work(self, result: subprocess.CompletedProcess) -> None:
        """斷言整批被拒絕：非零碼、沒有任何端點請求、沒有索引或結果資料夾。"""
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.working_dir.exists())
        self.assertFalse(self.results_dir.exists())

    def test_invalid_files_are_rejected_whole_naming_the_line_and_the_field(self):
        cases = {
            "缺欄位": ([question_line(), question_line(id="q2", reference=None)], ["第 2 行", "reference"]),
            "type 非法": ([question_line(type="chart")], ["第 1 行", "type", "cross-paper"]),
            "id 重複": ([question_line(), question_line(question="other")], ["第 2 行", "id", "第 1 行"]),
            "不是合法 JSON": ([question_line(), "", "{not json"], ["第 3 行", "JSON"]),
            "不是物件": (["[1, 2]"], ["第 1 行", "物件"]),
            "欄位是空字串": ([question_line(question="  ")], ["第 1 行", "question"]),
            "欄位型別錯": ([question_line(reference=42)], ["第 1 行", "reference"]),
            "多餘欄位": ([question_line(rank=1)], ["第 1 行", "rank"]),
        }
        for name, (lines, expected) in cases.items():
            with self.subTest(case=name):
                result = self.run_eval(self.write_questions(*lines))
                self.assert_rejected_before_any_work(result)
                for text in expected:
                    self.assertIn(text, result.stderr)

    def test_every_error_is_reported_not_only_the_first(self):
        path = self.write_questions(
            question_line(type="chart"), question_line(id="q2"), question_line(id="q3", source=None)
        )
        result = self.run_eval(path)
        self.assert_rejected_before_any_work(result)
        self.assertRegex(result.stderr, r"第 1 行.*type")
        self.assertRegex(result.stderr, r"第 3 行.*source")

    def test_empty_or_missing_file_is_rejected(self):
        empty = self.write_questions("", name="empty.jsonl")
        self.assert_rejected_before_any_work(self.run_eval(empty))
        missing = self.run_eval(self.tmp / "nope.jsonl")
        self.assert_rejected_before_any_work(missing)
        self.assertIn("nope.jsonl", missing.stderr)


# ==============================
# 執行與對照表
# ==============================


class EvalRunTest(IngestedEvalCase):
    def test_produces_a_timestamped_table_with_one_row_per_question_and_one_column_per_mode(self):
        questions = [
            json.loads(question_line(id="q1", question="What is Fake Entity Alpha?", reference="A made-up concept.")),
            json.loads(
                question_line(
                    id="q2",
                    question="Which entity works together with Fake Entity Beta?",
                    reference="Fake Entity Alpha.",
                    type="table",
                    source="fake.pdf p.2",
                )
            ),
        ]
        path = self.write_questions(*(json.dumps(q) for q in questions))

        result = self.run_eval(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        files = self.result_files()
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^eval_\d{8}-\d{6}\.md$")
        self.assertIn(str(files[0].resolve()), result.stdout)

        markdown = files[0].read_text(encoding="utf-8")
        header = table_header(markdown)
        self.assertEqual(header[-5:], list(MODES))
        rows = table_rows(markdown)
        self.assertEqual([row[0] for row in rows], ["q1", "q2"])
        for row, question in zip(rows, questions):
            self.assertEqual(len(row), len(header))
            for field in ("type", "source", "question", "reference"):
                self.assertIn(question[field], row)
            self.assertEqual(row[-5:], [CHAT_REPLY] * 5)

    def test_shipped_example_file_is_a_valid_question_file_with_two_rows(self):
        examples = [json.loads(line) for line in EXAMPLE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(examples), 2)

        result = self.run_eval(EXAMPLE_FILE)
        # 假索引只有「Fake Entity」的內容，範例題目（針對真實論文）在這裡檢索不到內容，格會失敗；
        # 這個測試只確認範例檔本身能通過驗證並產出每題一列的表
        self.assertNotIn("題目檔錯誤", result.stderr)
        markdown = self.result_files()[0].read_text(encoding="utf-8")
        rows = table_rows(markdown)
        self.assertEqual([row[0] for row in rows], [e["id"] for e in examples])
        for row, example in zip(rows, examples):
            self.assertIn(example["reference"], row)
            self.assertIn(example["type"], row)

    def test_every_documented_question_type_is_accepted(self):
        lines = [
            question_line(id=f"q-{kind}", question=f"What is Fake Entity Alpha as {kind}?", type=kind)
            for kind in QUESTION_TYPES
        ]
        result = self.run_eval(self.write_questions(*lines))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([row[0] for row in table_rows(self.result_files()[0].read_text(encoding="utf-8"))],
                         [f"q-{kind}" for kind in QUESTION_TYPES])

    def test_runs_all_five_modes_per_question_without_vlm_enhancement(self):
        path = self.write_questions(
            question_line(id="q1", question="What is Fake Entity Alpha?"),
            question_line(id="q2", question="Which entity works together with Fake Entity Beta?"),
        )
        result = self.run_eval(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.answer_requests()), 2 * 5, "每題五種模式各一個答案請求")
        # naive 不做關鍵字抽取，其餘四種各一次
        self.assertEqual(len(self.keyword_requests()), 2 * 4)
        image_requests = [
            r
            for r in self.eval_requests()
            if r["path"] == "/v1/chat/completions"
            and any(isinstance(m["content"], list) for m in r["payload"]["messages"])
        ]
        self.assertEqual(image_requests, [], "eval 固定 vlm_enhanced=False，不該有任何帶圖片的請求")

    def test_report_header_states_the_fixed_query_settings(self):
        result = self.run_eval(self.write_questions(question_line()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        markdown = self.result_files()[0].read_text(encoding="utf-8")
        preamble = markdown.split("| id |")[0]
        self.assertIn("vlm_enhanced=False", preamble)
        self.assertIn("enable_rerank=False", preamble)
        self.assertIn("fake-llm", preamble)

    def test_pipes_and_newlines_in_fields_cannot_break_the_row(self):
        path = self.write_questions(
            question_line(
                question="What is Fake Entity Alpha | really?\nSecond line.",
                reference="Line one\nLine two with a | pipe",
            )
        )
        result = self.run_eval(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        markdown = self.result_files()[0].read_text(encoding="utf-8")
        rows = table_rows(markdown)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), len(table_header(markdown)))
        self.assertIn("What is Fake Entity Alpha \\| really?<br>Second line.", rows[0])
        self.assertIn("Line one<br>Line two with a \\| pipe", rows[0])

    def test_results_default_to_eval_results_under_the_working_directory_and_never_overwrite(self):
        path = self.write_questions(question_line())
        workdir = self.tmp / "cwd"
        workdir.mkdir()
        env = {**self.env(), "PYTHONPATH": str(REPO_ROOT)}
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-m", "rag_lab", "eval", str(path)],
                cwd=workdir,
                env={**os.environ, **env},
                capture_output=True,
                text=True,
                timeout=INGEST_TIMEOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list((workdir / "eval_results").glob("eval_*.md"))), 2)


# ==============================
# 結果檔
# ==============================


class EvalResultFileTest(IngestedEvalCase):
    def test_a_result_file_name_already_taken_never_costs_the_finished_run_or_overwrites_it(self):
        # 檔名只到秒：同一秒啟動的兩個 eval 會撞名。這裡把「現在起一段時間內」每一秒的檔名都先佔住，
        # 不論 eval 的時間戳記落在哪一秒都會撞名
        self.results_dir.mkdir()
        now = datetime.now()
        taken = {}
        for offset in range(-5, 121):
            path = self.results_dir / f"eval_{now + timedelta(seconds=offset):%Y%m%d-%H%M%S}.md"
            path.write_text(f"existing {offset}", encoding="utf-8")
            taken[path] = f"existing {offset}"

        result = self.run_eval(self.write_questions(question_line()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path, content in taken.items():
            self.assertEqual(path.read_text(encoding="utf-8"), content)
        new_files = [path for path in self.result_files() if path not in taken]
        self.assertEqual(len(new_files), 1)
        self.assertIn(str(new_files[0].resolve()), result.stdout)
        self.assertEqual(len(table_rows(new_files[0].read_text(encoding="utf-8"))), 1)

    def test_an_unwritable_output_dir_fails_before_any_query_is_sent(self):
        self.results_dir.mkdir()
        self.results_dir.chmod(0o555)
        self.addCleanup(self.results_dir.chmod, 0o755)
        result = self.run_eval(self.write_questions(question_line()))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(self.results_dir), result.stderr)
        self.assertEqual(self.eval_requests(), [], "結果寫不進去時不該先跑完整批查詢")


# ==============================
# 單格失敗與端點錯誤
# ==============================


class EvalFailureTest(IngestedEvalCase):
    def test_a_failing_question_is_marked_in_its_row_while_other_rows_still_run(self):
        self.server.fail_chat_containing = "Poisoned"
        path = self.write_questions(
            question_line(id="ok-1", question="What is Fake Entity Alpha?"),
            question_line(id="bad", question="Poisoned: what is Fake Entity Beta?"),
            question_line(id="ok-2", question="Which entity works together with Fake Entity Beta?"),
        )
        result = self.run_eval(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

        rows = {row[0]: row for row in table_rows(self.result_files()[0].read_text(encoding="utf-8"))}
        self.assertEqual(list(rows), ["ok-1", "bad", "ok-2"])
        for question_id in ("ok-1", "ok-2"):
            self.assertEqual(rows[question_id][-5:], [CHAT_REPLY] * 5)
        for cell in rows["bad"][-5:]:
            self.assertIn("失敗", cell)
            self.assertIn("injected chat failure", cell)
        self.assertIn("失敗 5 格", self.result_files()[0].read_text(encoding="utf-8"))
        self.assertRegex(result.stderr, r"失敗：bad / naive：.*injected chat failure")
        self.assertIn("完成：15 格，失敗 5 格", result.stdout)

    def test_a_failure_in_one_mode_only_marks_that_column(self):
        # 關鍵字抽取失敗只影響會做關鍵字抽取的四種模式；naive 不做，應該照常回答
        self.server.fail_keywords = True
        result = self.run_eval(self.write_questions(question_line()))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

        header = table_header(self.result_files()[0].read_text(encoding="utf-8"))
        (row,) = table_rows(self.result_files()[0].read_text(encoding="utf-8"))
        cells = dict(zip(header, row))
        self.assertEqual(cells["naive"], CHAT_REPLY)
        for mode in ("local", "global", "hybrid", "mix"):
            self.assertIn("失敗", cells[mode], mode)

    def test_all_cells_failing_still_writes_the_table_and_exits_nonzero(self):
        self.server.fail_chat = True
        result = self.run_eval(self.write_questions(question_line()))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        (row,) = table_rows(self.result_files()[0].read_text(encoding="utf-8"))
        self.assertTrue(all("失敗" in cell for cell in row[-5:]))
        self.assertNotIn(CHAT_REPLY, row[-5:])

    def test_an_unreachable_endpoint_is_named_and_no_table_is_written(self):
        dead = closed_port_url()
        result = self.run_eval(self.write_questions(question_line()), LLM_BASE_URL=dead)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LLM", result.stderr)
        self.assertIn(dead, result.stderr)
        self.assertEqual(self.result_files(), [])

    def test_api_keys_never_appear_in_the_output_or_the_table(self):
        self.server.fail_chat = True
        result = self.run_eval(self.write_questions(question_line()))
        combined = result.stdout + result.stderr + self.result_files()[0].read_text(encoding="utf-8")
        self.assertNotIn(SECRET, combined)
