"""eval 的題目檔讀取與 Markdown 對照表產生。

為什麼存在：eval 要把使用者寫的 JSONL 題目檔跑過五種檢索模式，再輸出一張讓人工比較的表。
讀檔驗證與排版不需要任何模型或 lightrag，獨立成輕量模組，CLI 才能在 import 重量級模組、
連任何端點之前就拒絕格式錯誤的題目檔。查詢本身在 rag_lab.pipeline.evaluate。

關鍵設計決策：
- 題目檔整批驗證：逐行檢查後一次回報所有錯誤（每條含行號與欄位），任何一行有錯就整批拒絕，
  不讓使用者等了幾十分鐘才發現第 9 題的 type 拼錯。空白行略過但仍計入行號。
- 欄位固定為 id、question、reference、type、source，皆為非空字串；type 限 text、figure、
  table、cross-paper；id 不可重複。多出來的欄位視為錯誤（ASSUMPTION：避免欄名拼錯被默默忽略）。
- 對照表每題一列：id、type、source、question、reference 與五種模式各一欄。儲存格內的 `|`
  跳脫、換行換成 `<br>`，確保一題永遠只佔一行。失敗的格寫「失敗」與原因，不留空白。
- 表頭註明固定的查詢設定（vlm_enhanced=False、enable_rerank=False），讓日後翻結果檔時
  知道檢索模式是當時唯一的變因。

已知極限：reference 只是給人工對照的參考答案，不做任何自動評分（spec 明定不使用 LLM 評審）。

Dependencies: 僅標準函式庫。
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ==============================
# 常數與型別
# ==============================

RETRIEVAL_MODES = ("naive", "local", "global", "hybrid", "mix")
QUESTION_TYPES = ("text", "figure", "table", "cross-paper")
QUESTION_FIELDS = ("id", "question", "reference", "type", "source")


class QuestionFileError(ValueError):
    """題目檔格式不合法；訊息逐條列出「第 N 行：欄位 X：原因」。"""


@dataclass(frozen=True)
class Question:
    """一筆評估題目。

    Attributes:
        id: 題目代號（檔內唯一）。
        question: 問題文字。
        reference: 人工撰寫的參考答案。
        type: 題型，QUESTION_TYPES 之一。
        source: 答案出處（論文 ID 或檔名）。
    """

    id: str
    question: str
    reference: str
    type: str
    source: str


@dataclass(frozen=True)
class Cell:
    """對照表的一格：某題在某模式的結果。

    Attributes:
        answer: 成功時的答案文字。
        error: 失敗時的「型別：訊息」；None 表示成功。
    """

    answer: str | None = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        """這一格是否失敗。"""
        return self.error is not None


# ==============================
# 題目檔
# ==============================


def _validate_record(record: object, line_no: int, first_line_of_id: dict[str, int]) -> tuple[Question | None, list[str]]:
    """驗證一行已解析的 JSON。

    Args:
        record: json.loads 的結果。
        line_no: 這一行的行號（從 1 起算）。
        first_line_of_id: 已出現過的 id 與其行號；通過驗證時會把這一行的 id 記進去。

    Returns:
        (通過驗證的 Question 或 None, 錯誤訊息清單)。
    """
    if not isinstance(record, dict):
        return None, [f"第 {line_no} 行：必須是 JSON 物件，實際是 {type(record).__name__}"]
    errors: list[str] = []
    for name in record:
        if name not in QUESTION_FIELDS:
            errors.append(f"第 {line_no} 行：欄位 {name}：不認得的欄位（可用欄位：{', '.join(QUESTION_FIELDS)}）")
    for name in QUESTION_FIELDS:
        if name not in record:
            errors.append(f"第 {line_no} 行：欄位 {name}：缺少")
        elif not isinstance(record[name], str) or not record[name].strip():
            errors.append(f"第 {line_no} 行：欄位 {name}：必須是非空字串")
    if errors:
        return None, errors
    if record["type"] not in QUESTION_TYPES:
        errors.append(f"第 {line_no} 行：欄位 type：{record['type']!r} 不合法（可用值：{', '.join(QUESTION_TYPES)}）")
    if record["id"] in first_line_of_id:
        errors.append(
            f"第 {line_no} 行：欄位 id：{record['id']!r} 與第 {first_line_of_id[record['id']]} 行重複"
        )
    if errors:
        return None, errors
    first_line_of_id[record["id"]] = line_no
    return Question(**{name: record[name] for name in QUESTION_FIELDS}), []


def load_questions(path: Path) -> list[Question]:
    """讀取並驗證 JSONL 題目檔。

    Args:
        path: 題目檔路徑。

    Returns:
        依檔內順序的題目清單。

    Raises:
        QuestionFileError: 檔案不是合法的題目檔（訊息列出所有錯誤與其行號、欄位），
            或檔內沒有任何題目。
        OSError: 檔案不存在或無法讀取。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise QuestionFileError(f"{path}：不是 UTF-8 編碼的文字檔（{exc.reason}，位置 {exc.start}）") from exc
    questions: list[Question] = []
    errors: list[str] = []
    first_line_of_id: dict[str, int] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"第 {line_no} 行：不是合法的 JSON（{exc.msg}，第 {exc.colno} 字元）")
            continue
        question, record_errors = _validate_record(record, line_no, first_line_of_id)
        errors.extend(record_errors)
        if question is not None:
            questions.append(question)
    if not errors and not questions:
        errors.append(f"{path}：沒有任何題目")
    if errors:
        raise QuestionFileError("\n".join(errors))
    return questions


# ==============================
# 對照表
# ==============================


def _escape_cell(text: str) -> str:
    """把文字轉成可放進 Markdown 表格儲存格的單行文字。"""
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


def _cell_text(cell: Cell) -> str:
    """一格結果的顯示文字；失敗的格標示失敗與原因。"""
    if cell.failed:
        return f"**失敗**：{_escape_cell(cell.error or '')}"
    return _escape_cell(cell.answer or "")


def render_report(
    questions: list[Question],
    cells: list[list[Cell]],
    meta: list[tuple[str, str]],
    generated_at: datetime,
) -> str:
    """產生 Markdown 對照表。

    Args:
        questions: 題目清單。
        cells: cells[i][j] 是第 i 題在 RETRIEVAL_MODES[j] 的結果。
        meta: 表頭要列的（名稱, 值）設定說明，依序輸出。
        generated_at: 產生時間。

    Returns:
        Markdown 全文（結尾有換行）。
    """
    failed = sum(cell.failed for row in cells for cell in row)
    total = sum(len(row) for row in cells)
    lines = ["# eval 對照表", ""]
    lines.append(f"- 產生時間：{generated_at.isoformat(timespec='seconds')}")
    lines.extend(f"- {name}：{value}" for name, value in meta)
    lines.append(f"- 結果：{total} 格，失敗 {failed} 格")
    lines.append("")
    header = ["id", "type", "source", "question", "reference", *RETRIEVAL_MODES]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(" --- " for _ in header) + "|")
    for question, row in zip(questions, cells, strict=True):
        fields = [question.id, question.type, question.source, question.question, question.reference]
        lines.append("| " + " | ".join([*(_escape_cell(f) for f in fields), *(_cell_text(c) for c in row)]) + " |")
    return "\n".join(lines) + "\n"
