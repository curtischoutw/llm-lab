"""ingest／query 的 CLI 行為測試：對假 OpenAI server 與假 mineru 跑完整流程。

為什麼存在：ticket 03 的第一條完整路徑（匯入一篇文件、再問答）需要快速、不依賴
真實模型的回歸保護。spec 的測試縫只有 CLI，所以這裡全部從 `python -m rag_lab` 進入，
只觀察結束碼、stdout／stderr、產生的檔案，以及假 server 在 HTTP 邊界收到的請求。

關鍵設計決策：
- 每個測試用獨立的暫存資料夾放索引（WORKING_DIR）與解析輸出（PARSER_OUTPUT_DIR），
  彼此不汙染，也不碰 repo 內的 rag_storage／output。
- 假 mineru 以 PATH 上的可執行檔提供（tests/fake_mineru.py），讓 RAG-Anything 走它真實的
  subprocess 路徑；PDF 內容不重要，只要檔案存在。
- 假 LibreOffice（tests/fake_libreoffice.py）以 `libreoffice` 與 `soffice` 兩個名稱放在 PATH 最前面，
  Office 文件的內容不重要（假 LibreOffice 與假 mineru 都不讀內容），所以 Office 測試檔寫的是文字，不是真的 Office 檔。
- 圖片文件要用 Pillow 讀得動的真圖片：假 mineru 不讀內容，但 RAG-Anything 會先用 Pillow 把
  非 png／jpg 的圖片轉成 png 才交給 mineru，所以 `write_image` 用 Pillow 產生各格式的小圖。
- 「端點不可達」用一個已關閉的本機埠模擬。

Dependencies: 標準函式庫；Pillow（RAG-Anything 的依賴，只用來產生測試用的小圖）。
"""

import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import tiktoken
from PIL import Image

from tests.fake_mineru import BIG_TABLE_COLUMNS, BIG_TABLE_ROWS, BIG_TABLE_SPAN_START, big_table_html
from tests.fake_openai_server import CHAT_REPLY, VISION_REPLY, FakeOpenAIServer
from tests.test_cli import REPO_ROOT, SECRET, run_cli, valid_env

INGEST_TIMEOUT = 180
# 支援的副檔名；刻意不從 rag_lab.formats 取值，測試的期望要有獨立的來源（spec 的「支援的格式」）
SUPPORTED_EXTENSIONS = (
    ".pdf",
    ".ppt",
    ".pptx",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
    ".gif",
    ".webp",
)
# 表格送去描述的內容（table_body）的 token 上限；這是 ticket 12 決定的上限值，不從 rag_lab 取值，測試的期望要有獨立的來源
TABLE_BODY_MAX_TOKENS = 800
# 端點失敗後應在這個秒數內結束（正常約 10 秒，含 LightRAG 限流器 shutdown 最多等 5 秒）
HANG_TIMEOUT = 60
# .env 內以字面 \n 表示換行；CLI 讀進來後是真正的換行
QUERY_PREFIX_ENV = r"Instruct: Given a question, retrieve relevant passages that answer the question\nQuery:"

# ==============================
# 工具函式
# ==============================


def closed_port_url() -> str:
    """取得一個沒有任何程式在聽的本機 base URL。

    Returns:
        指向已關閉埠的 http URL（含 /v1）。
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def write_image(path: Path) -> Path:
    """在 path 寫出一張 Pillow 讀得動的小圖，格式由副檔名決定。

    Args:
        path: 圖片路徑；副檔名決定格式（大小寫不分）。

    Returns:
        path 本身。
    """
    Image.new("RGB", (8, 8), "red").save(path)
    return path


def write_office(path: Path) -> Path:
    """在 path 寫出一個 Office 文件的替身。

    假 LibreOffice 與假 mineru 都不讀內容，只看副檔名與主檔名，所以內容是一行文字，不是真的 Office 檔。

    Args:
        path: 文件路徑；副檔名決定格式。

    Returns:
        path 本身。
    """
    path.write_text(f"fake office document: {path.name}\n", encoding="utf-8")
    return path


def parsed_office_sources(output_dir: Path) -> list[str]:
    """列出 output_dir 底下每份解析結果記下的 Office 來源（假 LibreOffice 寫進 PDF、假 mineru 帶進內容清單的那一行）。

    Args:
        output_dir: PARSER_OUTPUT_DIR。

    Returns:
        每個 `*_content_list.json` 各一個來源文字，依文字排序；沒有來源標記的內容清單（PDF、圖片）不列入。
    """
    prefix = "Converted from Office document: "
    sources = []
    for path in output_dir.rglob("*_content_list.json"):
        for block in json.loads(path.read_text(encoding="utf-8")):
            if block.get("text", "").startswith(prefix):
                sources.append(block["text"].removeprefix(prefix))
    return sorted(sources)


class _CellReader(HTMLParser):
    """把 HTML 表格讀成「每列是 (文字, rowspan, colspan) 的清單」；沒寫的 rowspan／colspan 當作 1。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple[str, int, int]]] = []
        self._cell: list | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tr":
            self.rows.append([])
        elif tag == "td":
            self._cell = ["", int(attributes.get("rowspan", 1)), int(attributes.get("colspan", 1))]

    def handle_data(self, data):
        if self._cell is not None:
            self._cell[0] += data

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None:
            self.rows[-1].append((self._cell[0], self._cell[1], self._cell[2]))
            self._cell = None


def table_rows(html: str) -> list[list[tuple[str, int, int]]]:
    """讀出表格每一列的儲存格。

    Args:
        html: `<table>...</table>`。

    Returns:
        每列一個 (文字, rowspan, colspan) 清單。
    """
    reader = _CellReader()
    reader.feed(html)
    return reader.rows


def table_bodies(requests: list[dict]) -> list[str]:
    """取出每個表格描述請求裡的 table_body（prompt 中 `Body:` 之後的 `<table>...</table>`）。

    Args:
        requests: FakeOpenAIServer.requests。

    Returns:
        依請求順序排列的 table_body；不是表格描述的請求不列入。
    """
    bodies = []
    for request in requests:
        if request["path"] != "/v1/chat/completions":
            continue
        for message in request["payload"]["messages"]:
            match = re.search(r"Body: (<table>.*</table>)", message["content"], re.DOTALL) if isinstance(message["content"], str) else None
            if match:
                bodies.append(match.group(1))
    return bodies


# 假 server 抽出的圖譜固定是 Alpha、Beta 兩個 entity 與一條 relation。這三段描述只會出現在圖譜 context，
# 不會出現在文字 chunk，所以查詢 prompt 含不含它們，就是 LightRAG 實際用了哪個 entity／relation 上限的觀察結果。
ALPHA_DESCRIPTION = "Fake Entity Alpha is a made-up concept."
BETA_DESCRIPTION = "Fake Entity Beta is a made-up method."
LINK_DESCRIPTION = "Alpha is related to Beta."


def query_prompts(requests: list[dict]) -> list[str]:
    """取出查詢時送給模型產生答案的 prompt 文字（不含關鍵字抽取請求）。

    Args:
        requests: 假 server 記錄的請求。

    Returns:
        每個答案請求（純文字或帶圖片）所有訊息的文字串接。
    """
    prompts = []
    for request in requests:
        payload = request["payload"]
        if request["path"] != "/v1/chat/completions" or payload.get("response_format"):
            continue
        texts = []
        for message in payload["messages"]:
            content = message["content"]
            if isinstance(content, list):
                texts.extend(part["text"] for part in content if part.get("type") == "text")
            else:
                texts.append(content)
        prompts.append("\n".join(texts))
    return prompts


class PipelineCase(unittest.TestCase):
    """提供假 server、假 mineru、暫存資料夾與 CLI 執行輔助的測試基底。"""

    def setUp(self):
        self.server = FakeOpenAIServer(embed_dim=1024)
        self.server.start()
        self.addCleanup(self.server.stop)

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        mineru = bin_dir / "mineru"
        mineru.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{REPO_ROOT}/tests/fake_mineru.py" "$@"\n')
        mineru.chmod(mineru.stat().st_mode | stat.S_IXUSR)
        self.bin_dir = bin_dir

        # 假 LibreOffice 以兩個名稱放在另一個資料夾，PATH 最前面：RAG-Anything 先找 libreoffice 再找 soffice，
        # 兩個名稱都放，機器上裝了真的 LibreOffice 時測試也不會用到它。「沒有 LibreOffice」的測試把 PATH 改成只有 bin_dir
        office_bin = self.tmp / "office_bin"
        office_bin.mkdir()
        for name in ("libreoffice", "soffice"):
            wrapper = office_bin / name
            wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{REPO_ROOT}/tests/fake_libreoffice.py" "$@"\n')
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        self.office_bin = office_bin

        self.working_dir = self.tmp / "rag_storage"
        self.output_dir = self.tmp / "output"
        self.document = self.tmp / "paper.pdf"
        self.document.write_bytes(b"%PDF-1.4 fake")

    def env(self, **overrides: str) -> dict[str, str]:
        """組出指向假 server 與暫存資料夾的環境變數。

        Args:
            **overrides: 覆蓋的環境變數。

        Returns:
            可傳給 run_cli 的 overrides。
        """
        env = valid_env(self.server.base_url)
        env.update(
            WORKING_DIR=str(self.working_dir),
            PARSER_OUTPUT_DIR=str(self.output_dir),
            EMBED_QUERY_PREFIX=QUERY_PREFIX_ENV,
            PATH=os.pathsep.join([str(self.office_bin), str(self.bin_dir), os.environ["PATH"]]),
        )
        env.update(overrides)
        return env

    def ingest(self, path: Path | None = None, **overrides: str):
        """執行 `ingest`。"""
        return run_cli(["ingest", str(path or self.document)], self.env(**overrides), timeout=INGEST_TIMEOUT)

    def query(self, question: str = "What is Fake Entity Alpha?", *extra: str, **overrides: str):
        """執行 `query`。"""
        return run_cli(["query", question, *extra], self.env(**overrides), timeout=INGEST_TIMEOUT)


# ==============================
# 太大的表格
# ==============================


class OversizedTableTest(PipelineCase):
    def setUp(self):
        super().setUp()
        self.big = self.tmp / "bigtable.pdf"
        self.big.write_bytes(b"%PDF-1.4 big table")

    def test_a_big_table_is_described_as_several_small_tables_that_together_cover_every_row(self):
        result = self.ingest(self.big)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bodies = table_bodies(self.server.requests)
        self.assertGreater(len(bodies), 1, "太大的表格應該拆成多張小表，每張各送一次描述")
        encoding = tiktoken.encoding_for_model("gpt-4o-mini")
        for body in bodies:
            self.assertLessEqual(len(encoding.encode(body)), TABLE_BODY_MAX_TOKENS)
            for column in range(BIG_TABLE_COLUMNS):
                self.assertIn(f">H{column}<", body, "每張小表都要重複表頭列")
        joined = "\n".join(bodies)
        for row in range(BIG_TABLE_ROWS):
            self.assertIn(f">R{row}C1<", joined, f"第 {row} 列沒有出現在任何一張小表")

    def test_cell_text_and_merged_cells_are_unchanged_after_shortening_and_splitting(self):
        self.assertEqual(self.ingest(self.big).returncode, 0)
        original_rows = table_rows(big_table_html())
        header, data_rows = original_rows[0], original_rows[1:]
        described_rows = []
        for body in table_bodies(self.server.requests):
            rows = table_rows(body)
            self.assertEqual(rows[0], header)
            described_rows.extend(rows[1:])
        self.assertEqual(described_rows, data_rows)

    def test_rows_joined_by_a_rowspan_that_alone_exceeds_the_limit_are_split_with_the_spanning_cell_repeated(self):
        spanning = self.tmp / "bigspan.pdf"
        spanning.write_bytes(b"%PDF-1.4 big span")
        self.assertEqual(self.ingest(spanning).returncode, 0)
        bodies = table_bodies(self.server.requests)
        encoding = tiktoken.encoding_for_model("gpt-4o-mini")
        self.assertGreater(len(bodies), 2)
        for body in bodies:
            self.assertLessEqual(len(encoding.encode(body)), TABLE_BODY_MAX_TOKENS)
            # 每一列的欄數（含上方 rowspan 佔到的欄）都是 BIG_TABLE_COLUMNS：切開後欄位仍然對齊
            occupied: dict[int, int] = {}
            for index, row in enumerate(table_rows(body)):
                width = sum(colspan for _, _, colspan in row) + sum(1 for last in occupied.values() if last >= index)
                self.assertEqual(width, BIG_TABLE_COLUMNS, f"第 {index} 列欄數不對：{row}")
                for column, (_, rowspan, _) in enumerate(row):
                    if rowspan > 1:
                        occupied[100 + column] = index + rowspan - 1
        described = [row for body in bodies for row in table_rows(body)[1:]]
        for row_number in range(BIG_TABLE_ROWS):
            self.assertTrue(
                any((f"R{row_number}C1", 1, 1) in row for row in described), f"第 {row_number} 列沒有出現在任何一張小表"
            )
        # 跨列的那一格：文字出現在每一張涵蓋它的小表，沒有被丟掉
        for body in bodies:
            if f">R{BIG_TABLE_SPAN_START + 1}C1<" in body:
                self.assertIn(f">R{BIG_TABLE_SPAN_START}C0<", body)

    def test_default_span_attributes_are_dropped_but_real_spans_stay(self):
        self.assertEqual(self.ingest(self.big).returncode, 0)
        joined = "\n".join(table_bodies(self.server.requests))
        self.assertNotIn("rowspan=1", joined)
        self.assertNotIn("colspan=1", joined)
        self.assertIn("rowspan=2", joined)

    def test_rows_joined_by_a_rowspan_stay_in_the_same_small_table(self):
        self.assertEqual(self.ingest(self.big).returncode, 0)
        for body in table_bodies(self.server.requests):
            for first in range(0, BIG_TABLE_ROWS, 10):
                # 第 first 列的第一格 rowspan=2，跨到第 first+1 列
                self.assertEqual(f">R{first}C0<" in body, f">R{first + 1}C1<" in body, f"跨列的兩列被拆開：{first}")

    def test_a_small_table_is_described_with_its_body_unchanged(self):
        # 不大的表格連預設的 rowspan=1 colspan=1 都不動：已匯入文件重新處理時送去描述的內容和以前一樣
        small = self.tmp / "spans.pdf"
        small.write_bytes(b"%PDF-1.4 small table")
        self.assertEqual(self.ingest(small).returncode, 0)
        self.assertEqual(
            table_bodies(self.server.requests),
            [
                "<table><tr><td rowspan=1 colspan=1>a</td><td rowspan=1 colspan=1>b</td></tr>"
                "<tr><td rowspan=1 colspan=1>1</td><td rowspan=1 colspan=1>2</td></tr></table>"
            ],
        )

    def test_document_id_and_parse_cache_come_from_the_original_table(self):
        self.assertEqual(self.ingest(self.big).returncode, 0)
        content_list_path = next(self.output_dir.rglob("bigtable_content_list.json"))
        original = json.loads(content_list_path.read_text(encoding="utf-8"))
        # RAG-Anything 的文件 ID 規則：各區塊的識別文字用換行串起來取 md5，前綴 doc-（不從 rag_lab 取值）
        parts = []
        for block in original:
            if block["type"] == "text":
                parts.append(block["text"].strip())
            elif block["type"] == "image":
                # RAG-Anything 讀進來時把圖片的相對路徑換成絕對路徑
                parts.append(f"image:{(content_list_path.parent / block['img_path']).resolve()}")
            elif block["type"] == "table":
                parts.append(f"table:{block['table_body']}")
            else:
                parts.append(f"equation:{block['text']}")
        expected_id = "doc-" + hashlib.md5("\n".join(parts).encode()).hexdigest()
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text(encoding="utf-8"))
        self.assertEqual(list(statuses), [expected_id])
        cache = json.loads((self.working_dir / "kv_store_parse_cache.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cache), 1)
        (entry,) = cache.values()
        self.assertEqual(entry["doc_id"], expected_id)
        cached_tables = [block for block in entry["content_list"] if block["type"] == "table"]
        self.assertEqual([block["table_body"] for block in cached_tables], [original[3]["table_body"]])

    def test_reingesting_a_document_with_a_big_table_skips_it_and_calls_no_model(self):
        self.assertEqual(self.ingest(self.big).returncode, 0)
        requests_after_first = len(self.server.requests)
        second = self.ingest(self.big)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("略過", second.stdout)
        self.assertEqual(len(self.server.requests), requests_after_first)


class DescriptionFailureTest(PipelineCase):
    """圖／表／公式描述失敗、多模態內容寫入索引失敗：文件記成失敗，重新執行會重試。"""

    def doc_statuses(self) -> dict[str, dict]:
        return json.loads((self.working_dir / "kv_store_doc_status.json").read_text(encoding="utf-8"))

    def assert_failed_then_retried(self, failed):
        """failed 是失敗的那次 ingest；確認它被記成失敗，修好 server 後重新執行會重試並完成。"""
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertIn("匯入失敗：paper.pdf", failed.stderr)
        self.assertIn("重新執行", failed.stderr)
        self.assertIn("不需要刪除", failed.stderr, "文件已記成失敗，重新執行就會重試；要告訴使用者不必刪資料重來")
        self.assertNotIn("請修好端點後刪除", failed.stderr)
        self.assertEqual([record["status"] for record in self.doc_statuses().values()], ["failed"])

        self.server.fail_chat_containing = None
        self.server.fail_embed_containing = None
        requests_before = len(self.server.requests)
        retried = self.ingest()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertNotIn("略過", retried.stdout, "失敗的文件不能被當成已完成而略過")
        self.assertGreater(len(self.server.requests), requests_before)
        self.assertEqual([record["status"] for record in self.doc_statuses().values()], ["processed"])
        again = self.ingest()
        self.assertIn("略過", again.stdout)

    def test_a_failed_table_description_marks_the_document_failed_and_a_rerun_retries_it(self):
        self.server.fail_chat_containing = "Body: <table>"
        failed = self.ingest()
        self.assertIn("injected chat failure", failed.stderr)
        self.assert_failed_then_retried(failed)

    def test_a_failed_equation_description_marks_the_document_failed_and_a_rerun_retries_it(self):
        self.server.fail_chat_containing = "mc^2"
        self.assert_failed_then_retried(self.ingest())

    def test_a_failed_write_of_the_described_content_marks_the_document_failed_and_a_rerun_retries_it(self):
        # 描述成功，但表格 chunk 寫入向量索引時 embedding 失敗；RAG-Anything 吞掉這個錯誤
        self.server.fail_embed_containing = "Table Analysis:"
        failed = self.ingest()
        self.assertIn("寫入", failed.stderr)
        self.assertIn("injected embedding failure", failed.stderr)
        self.assert_failed_then_retried(failed)

    def test_other_documents_in_the_same_batch_are_still_ingested(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        (folder / "bigtable.pdf").write_bytes(b"%PDF-1.4 big")
        (folder / "other.pdf").write_bytes(b"%PDF-1.4 other")
        self.server.fail_chat_containing = "R59C1"
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r"匯入失敗：bigtable\.pdf")
        self.assertNotRegex(result.stderr, r"匯入失敗：other\.pdf")
        statuses = self.doc_statuses()
        self.assertEqual(sorted(record["status"] for record in statuses.values()), ["failed", "processed"], statuses)


# ==============================
# ingest
# ==============================


class IngestTest(PipelineCase):
    def test_ingests_one_document_and_reports_stage_timings(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("paper.pdf", result.stdout)
        self.assertIn("解析", result.stdout)
        self.assertIn("建圖", result.stdout)
        self.assertTrue((self.working_dir / "graph_chunk_entity_relation.graphml").is_file())

    def test_images_tables_and_equations_are_described_and_vlm_calls_are_counted(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        chats = [r["payload"] for r in self.server.requests if r["path"] == "/v1/chat/completions"]
        image_requests = [c for c in chats if any(isinstance(m["content"], list) for m in c["messages"])]
        self.assertEqual(len(image_requests), 1, "圖片應以 base64 data URI 送給 VLM 恰一次")
        image_part = next(
            part
            for m in image_requests[0]["messages"]
            if isinstance(m["content"], list)
            for part in m["content"]
            if part["type"] == "image_url"
        )
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))
        described = [c for c in chats if "detailed_description" in str(c["messages"])]
        self.assertEqual(len(described), 3, "圖、表、公式各一次描述請求")
        self.assertIn("多模態", result.stdout)
        self.assertIn("VLM 呼叫：成功 1，失敗 0", result.stdout)
        self.assertIn("The image shows a red square", result.stdout)

    def test_graph_counts_are_reported_with_belongs_to_edges_separated(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("圖譜：實體 5，關係 7", result.stdout)
        self.assertIn("belongs_to 邊 6", result.stdout)

    def test_reingesting_the_same_document_creates_nothing_and_calls_no_model(self):
        first = self.ingest()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        requests_after_first = len(self.server.requests)

        second = self.ingest()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("略過", second.stdout)
        self.assertEqual(len(self.server.requests), requests_after_first, "重複匯入不該再呼叫任何模型")
        for result in (first, second):
            self.assertIn("processed=1", result.stdout)
            self.assertIn("failed=0", result.stdout)
        self.assertIn("圖譜：實體 5，關係 7", second.stdout)

    def test_retrying_a_failed_document_processes_it_without_a_dup_record(self):
        self.server.fail_chat = True
        failed = self.ingest()
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)

        self.server.fail_chat = False
        retried = self.ingest()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("processed=1", retried.stdout)
        self.assertIn("failed=0", retried.stdout)
        self.assertIn("圖譜：實體 5，關係 7", retried.stdout)
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text())
        self.assertEqual([doc_id for doc_id in statuses if doc_id.startswith("dup-")], [])

    def test_ingests_every_document_in_a_folder(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        for name in ("a.pdf", "b.pdf"):
            (folder / name).write_bytes(b"%PDF-1.4 " + name.encode())
        (folder / "notes.txt").write_text("not a pdf")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("a.pdf", result.stdout)
        self.assertIn("b.pdf", result.stdout)
        self.assertIn("processed=2", result.stdout)

    def test_a_folder_ingests_supported_formats_in_name_order_and_reports_skipped_files_without_failing(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        (folder / "b.pdf").write_bytes(b"%PDF-1.4 b")
        write_image(folder / "a.png")
        (folder / "notes.txt").write_text("not supported")
        (folder / "data.csv").write_text("x,y")
        (folder / "sub").mkdir()
        (folder / "sub" / "c.pdf").write_bytes(b"%PDF-1.4 c")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("略過不支援的格式：notes.txt", result.stdout)
        self.assertIn("略過不支援的格式：data.csv", result.stdout)
        self.assertNotIn("c.pdf", result.stdout)
        self.assertNotIn("notes.txt", result.stderr)
        self.assertIn("processed=2", result.stdout, "子資料夾裡的 c.pdf 不該被匯入（不遞迴）")
        self.assertLess(result.stdout.index("[1/2] a.png"), result.stdout.index("[2/2] b.pdf"))

    def test_each_document_in_a_folder_reports_its_own_total_elapsed_time(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        for name in ("a.pdf", "b.pdf"):
            (folder / name).write_bytes(b"%PDF-1.4 " + name.encode())
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"\[1/2\] a\.pdf.*耗時 \d+\.\d s")
        self.assertRegex(result.stdout, r"\[2/2\] b\.pdf.*耗時 \d+\.\d s")

    def test_a_folder_does_not_treat_lock_files_and_hidden_files_as_documents(self):
        # Word 開檔時產生的 ~$ 鎖定檔、macOS 在非 HFS 磁碟上寫的 ._ AppleDouble 檔、.DS_Store：
        # 不是文件，不匯入（匯入會在轉檔或解析時失敗），也不印成「略過不支援的格式」
        folder = self.tmp / "papers"
        folder.mkdir()
        (folder / "a.pdf").write_bytes(b"%PDF-1.4 a")
        write_office(folder / "report.docx")
        write_office(folder / "~$report.docx")
        (folder / "._a.pdf").write_bytes(b"\x00\x05\x16\x07 appledouble")
        (folder / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        (folder / "notes.txt").write_text("not supported")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[1/2] a.pdf", result.stdout)
        self.assertIn("[2/2] report.docx", result.stdout)
        self.assertIn("processed=2", result.stdout)
        self.assertIn("略過不支援的格式：notes.txt", result.stdout, "一般的不支援檔案照舊列出")
        for name in ("~$report.docx", "._a.pdf", ".DS_Store"):
            self.assertNotIn(name, result.stdout)
            self.assertNotIn(name, result.stderr)

    def test_a_folder_with_only_lock_and_hidden_files_has_no_documents(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        write_office(folder / "~$report.docx")
        (folder / "._a.pdf").write_bytes(b"\x00\x05\x16\x07 appledouble")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("資料夾內沒有支援的文件", result.stderr)

    def test_a_file_given_directly_is_ingested_even_if_its_name_starts_with_a_dot(self):
        result = self.ingest((self.tmp / "paper.pdf").rename(self.tmp / ".hidden.pdf"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[1/1] .hidden.pdf", result.stdout)
        self.assertIn("processed=1", result.stdout)

    def test_one_failing_document_is_named_others_are_kept_and_exit_code_is_nonzero(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        for name in ("a.pdf", "broken.pdf", "c.pdf"):
            (folder / name).write_bytes(b"%PDF-1.4 " + name.encode())
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r"匯入失敗：broken\.pdf：.*Mineru")
        self.assertNotRegex(result.stderr, r"匯入失敗：[ac]\.pdf")
        self.assertIn("[2/3] broken.pdf", result.stdout)
        self.assertIn("processed=2", result.stdout)
        self.assertIn("failed=0", result.stdout)
        self.assertTrue((self.working_dir / "graph_chunk_entity_relation.graphml").is_file())
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text())
        self.assertEqual(sorted(v["status"] for v in statuses.values()), ["processed", "processed"])

    def test_document_stuck_in_handling_from_an_interrupted_run_is_reported_not_fatal(self):
        # 前一次 ingest 在多模態階段被中斷時，文件停在 RAG-Anything 的 handling 狀態；
        # 之後 ingest 別的文件不該在最後統計文件狀態時失敗
        first = self.ingest()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        status_file = self.working_dir / "kv_store_doc_status.json"
        statuses = json.loads(status_file.read_text())
        self.assertEqual(len(statuses), 1)
        for record in statuses.values():
            record["status"] = "handling"
        status_file.write_text(json.dumps(statuses))

        other = self.tmp / "other.pdf"
        other.write_bytes(b"%PDF-1.4 other")
        result = self.ingest(other)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("handling=1", result.stdout)
        self.assertIn("processed=1", result.stdout)
        self.assertRegex(result.stdout, r"1 篇文件停在 handling")

    def test_vlm_failure_does_not_hide_the_per_document_report_or_other_documents_errors(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        for name in ("a.pdf", "broken.pdf", "c.pdf"):
            (folder / name).write_bytes(b"%PDF-1.4 " + name.encode())
        self.server.fail_vision = True
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("[1/3] a.pdf", result.stdout)
        self.assertIn("[2/3] broken.pdf", result.stdout)
        self.assertIn("[3/3] c.pdf", result.stdout)
        self.assertIn("圖譜：實體", result.stdout)
        self.assertRegex(result.stderr, r"匯入失敗：broken\.pdf：.*Mineru")
        self.assertIn("VLM", result.stderr)
        self.assertIn(self.server.base_url, result.stderr)
        self.assertIn("injected vision failure", result.stderr)

    def test_failed_table_description_fails_ingest_and_names_the_llm_endpoint(self):
        # 表格描述走 llm_model_func；RAG-Anything 的 modal processor 會吞掉失敗並寫入 fallback 實體
        self.server.fail_chat_containing = "<table>"
        result = self.ingest()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("paper.pdf", result.stdout)
        self.assertIn("LLM", result.stderr)
        self.assertIn(self.server.base_url, result.stderr)
        self.assertIn("injected chat failure", result.stderr)

    def test_failed_equation_description_fails_ingest_and_names_the_llm_endpoint(self):
        self.server.fail_chat_containing = "mc^2"
        result = self.ingest()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("LLM", result.stderr)
        self.assertIn(self.server.base_url, result.stderr)
        self.assertIn("injected chat failure", result.stderr)

    def test_rejects_a_missing_path(self):
        result = self.ingest(self.tmp / "nope.pdf")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("輸入錯誤", result.stderr)
        self.assertIn("路徑不存在", result.stderr)
        self.assertEqual(self.server.requests, [])

    def test_rejects_a_single_file_in_an_unsupported_format_and_lists_the_supported_formats(self):
        text_file = self.tmp / "notes.txt"
        text_file.write_text("hello")
        result = self.ingest(text_file)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("輸入錯誤", result.stderr)
        self.assertIn("不支援的格式：notes.txt", result.stderr)
        for extension in SUPPORTED_EXTENSIONS:
            self.assertIn(extension, result.stderr)
        self.assertEqual(self.server.requests, [])

    def test_rejects_a_folder_without_any_supported_document_and_lists_the_supported_formats(self):
        empty_dir = self.tmp / "empty"
        empty_dir.mkdir()
        only_unsupported = self.tmp / "only_unsupported"
        only_unsupported.mkdir()
        (only_unsupported / "notes.txt").write_text("hello")
        for folder in (empty_dir, only_unsupported):
            with self.subTest(folder=folder.name):
                result = self.ingest(folder)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("輸入錯誤", result.stderr)
                self.assertIn("資料夾內沒有支援的文件", result.stderr)
                for extension in SUPPORTED_EXTENSIONS:
                    self.assertIn(extension, result.stderr)
                self.assertEqual(self.server.requests, [])

    def test_mineru_is_called_with_the_chosen_backend(self):
        result = self.ingest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        argv_files = list(self.output_dir.rglob("argv.json"))
        self.assertEqual(len(argv_files), 1)
        argv = json.loads(argv_files[0].read_text())
        self.assertEqual(argv[argv.index("-b") + 1], "pipeline")

    def test_llm_concurrency_follows_llm_max_async(self):
        self.server.chat_delay = 0.2
        serial = self.ingest(LLM_MAX_ASYNC="1")
        self.assertEqual(serial.returncode, 0, serial.stdout + serial.stderr)
        self.assertEqual(self.server.max_inflight_chat, 1)

    def test_higher_llm_max_async_allows_parallel_requests(self):
        self.server.chat_delay = 0.2
        parallel = self.ingest(LLM_MAX_ASYNC="3")
        self.assertEqual(parallel.returncode, 0, parallel.stdout + parallel.stderr)
        self.assertGreater(self.server.max_inflight_chat, 1)

    def test_exits_with_llm_error_when_generation_dies_mid_ingest(self):
        # 真實 mlx_lm.server GPU 記憶體不足時：正在生成的請求不回應，其他請求回 404。
        # 曾因 LightRAG 的限流 worker 吞掉取消、asyncio.run 收尾時永遠等不到它結束而卡住。
        self.server.chat_delay = 0.2
        self.server.die_after_chat = 3
        document = self.tmp / "multichunk.pdf"
        document.write_bytes(b"%PDF-1.4 fake")
        try:
            result = run_cli(["ingest", str(document)], self.env(LLM_MAX_ASYNC="2"), timeout=HANG_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.fail(f"LLM 端點失敗後 ingest 超過 {HANG_TIMEOUT} 秒沒有結束")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LLM", result.stderr)
        self.assertIn("generation thread died", result.stderr)

    def test_embedding_concurrency_follows_embed_max_async(self):
        self.server.embed_delay = 0.2
        serial = self.ingest(EMBED_MAX_ASYNC="1")
        self.assertEqual(serial.returncode, 0, serial.stdout + serial.stderr)
        self.assertEqual(self.server.max_inflight_embed, 1)

    def test_higher_embed_max_async_allows_parallel_requests(self):
        self.server.embed_delay = 0.2
        parallel = self.ingest(EMBED_MAX_ASYNC="4")
        self.assertEqual(parallel.returncode, 0, parallel.stdout + parallel.stderr)
        self.assertGreater(self.server.max_inflight_embed, 1)


# ==============================
# ingest：圖片
# ==============================


class IngestImageTest(PipelineCase):
    def test_ingests_a_png_and_its_parsed_content_reaches_the_answer_prompt(self):
        image = write_image(self.tmp / "diagram.png")
        result = self.ingest(image)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("diagram.png", result.stdout)
        self.assertIn("processed=1", result.stdout)
        self.assertIn("failed=0", result.stdout)

        before = len(self.server.requests)
        answer = self.query("What is Fake Entity Alpha?", "--mode", "naive")
        self.assertEqual(answer.returncode, 0, answer.stdout + answer.stderr)
        self.assertEqual(answer.stdout.strip(), CHAT_REPLY)
        prompts = [str(r["payload"]["messages"]) for r in self.server.requests[before:] if r["path"] == "/v1/chat/completions"]
        self.assertTrue(
            any("A Study of Fake Entities in diagram" in prompt for prompt in prompts),
            "圖片解析出的文字應該進入回答時的 context",
        )

    def test_reingesting_the_same_image_skips_it_and_calls_no_model(self):
        # .webp 要先轉成 png：每次轉出來的暫存檔路徑不同，重複匯入仍要認得是同一張
        for name in ("scan.png", "scan.webp"):
            with self.subTest(name=name):
                image = write_image(self.tmp / name)
                first = self.ingest(image)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                requests_after_first = len(self.server.requests)

                second = self.ingest(image)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("已完整處理過，略過", second.stdout)
                self.assertEqual(len(self.server.requests), requests_after_first, "重複匯入不該再呼叫任何模型")

    def test_retrying_a_failed_image_processes_it_without_a_dup_record(self):
        image = write_image(self.tmp / "retry.webp")
        self.server.fail_chat = True
        failed = self.ingest(image)
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)

        self.server.fail_chat = False
        retried = self.ingest(image)
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("processed=1", retried.stdout)
        self.assertIn("failed=0", retried.stdout)
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text())
        self.assertEqual(len(statuses), 1)
        self.assertEqual([doc_id for doc_id in statuses if doc_id.startswith("dup-")], [])

    def test_every_other_image_format_can_be_ingested_including_those_converted_to_png(self):
        # .jpg／.jpeg 直接交給 mineru；其餘由 RAG-Anything 先用 Pillow 轉成 png。副檔名大小寫不分
        names = [f"pic_{ext[1:]}{ext}" for ext in (".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp")]
        names += ["UPPER.PNG", "UPPER_WEBP.WEBP"]
        for name in names:
            with self.subTest(name=name):
                result = self.ingest(write_image(self.tmp / name))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"[1/1] {name}", result.stdout)
                self.assertIn("failed=0", result.stdout)
                self.assertNotIn("輸入錯誤", result.stderr)


# ==============================
# ingest：Office 文件
# ==============================


class IngestOfficeTest(PipelineCase):
    def test_ingests_a_pptx_and_its_parsed_content_reaches_the_answer_prompt(self):
        deck = write_office(self.tmp / "slides.pptx")
        result = self.ingest(deck)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("slides.pptx", result.stdout)
        self.assertIn("processed=1", result.stdout)
        self.assertIn("failed=0", result.stdout)

        before = len(self.server.requests)
        answer = self.query("What is Fake Entity Alpha?", "--mode", "naive")
        self.assertEqual(answer.returncode, 0, answer.stdout + answer.stderr)
        self.assertEqual(answer.stdout.strip(), CHAT_REPLY)
        prompts = [str(r["payload"]["messages"]) for r in self.server.requests[before:] if r["path"] == "/v1/chat/completions"]
        self.assertTrue(
            any("A Study of Fake Entities in slides" in prompt for prompt in prompts),
            "Office 文件轉成 PDF 再解析出的文字應該進入回答時的 context",
        )

    def test_every_office_format_can_be_ingested_and_its_extension_is_case_insensitive(self):
        # 主檔名各不相同：同主檔名的文件共用轉檔 PDF 與解析資料夾，會被當成已處理過（README 已知限制）
        names = ["slides_old.ppt", "slides_new.pptx", "text_old.doc", "text_new.docx", "sheet_old.xls", "sheet_new.xlsx", "UPPER.DOCX"]
        for name in names:
            with self.subTest(name=name):
                requests_before = len(self.server.requests)
                result = self.ingest(write_office(self.tmp / name))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"[1/1] {name}", result.stdout)
                self.assertIn("failed=0", result.stdout)
                self.assertNotIn("輸入錯誤", result.stderr)
                self.assertNotIn("已完整處理過，略過", result.stdout, "這份文件沒有真的走完建圖")
                self.assertIn("建圖", result.stdout)
                self.assertGreater(len(self.server.requests), requests_before, "這份文件沒有呼叫任何模型")

    def test_report_labels_the_parse_stage_as_including_the_office_to_pdf_conversion(self):
        result = self.ingest(write_office(self.tmp / "slides.pptx"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"解析（含 Office 轉 PDF）：\d+\.\d s")
        self.assertNotIn("轉檔：", result.stdout, "不另外計算轉檔時間")

    def test_report_labels_the_parse_stage_without_office_wording_for_pdf_and_images(self):
        folder = self.tmp / "no_office"
        folder.mkdir()
        (folder / "a.pdf").write_bytes(b"%PDF-1.4 a")
        write_image(folder / "b.png")
        write_office(folder / "c.docx")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 每份文件的報告以「[i/n] 檔名」開頭，下一行是解析階段；只有 Office 文件的標籤提到轉 PDF
        lines = result.stdout.splitlines()
        labels = {}
        for index, line in enumerate(lines):
            match = re.match(r"\[\d+/\d+\] (.+?)：耗時", line)
            if match:
                labels[match.group(1)] = lines[index + 1].split("：")[0].strip()
        self.assertEqual(labels, {"a.pdf": "解析", "b.png": "解析", "c.docx": "解析（含 Office 轉 PDF）"})

    def test_without_libreoffice_the_document_fails_and_the_error_says_how_to_install_it(self):
        # PATH 只放假 mineru：shutil.which 找不到 libreoffice 與 soffice，機器上有沒有裝真的都一樣
        result = self.ingest(write_office(self.tmp / "slides.pptx"), PATH=str(self.bin_dir))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r"匯入失敗：slides\.pptx：.*LibreOffice")
        self.assertIn("brew install --cask libreoffice", result.stderr)
        self.assertIn("slides.pptx", result.stdout)

    def test_a_failed_office_conversion_is_named_and_the_other_documents_in_the_folder_are_kept(self):
        folder = self.tmp / "mixed"
        folder.mkdir()
        write_office(folder / "a.docx")
        write_office(folder / "broken.pptx")
        (folder / "c.pdf").write_bytes(b"%PDF-1.4 c")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r"匯入失敗：broken\.pptx：.*LibreOffice")
        self.assertNotRegex(result.stderr, r"匯入失敗：[ac]\.")
        self.assertIn("[2/3] broken.pptx", result.stdout)
        self.assertIn("processed=2", result.stdout)
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text())
        self.assertEqual(sorted(v["status"] for v in statuses.values()), ["processed", "processed"])

    def test_reingesting_the_same_office_document_skips_it_and_calls_no_model(self):
        # 轉檔輸出每次都是新的 PDF；重複匯入仍要認得是同一份文件
        for name in ("deck.pptx", "legacy.doc"):
            with self.subTest(name=name):
                document = write_office(self.tmp / name)
                first = self.ingest(document)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                requests_after_first = len(self.server.requests)

                second = self.ingest(document)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("已完整處理過，略過", second.stdout)
                self.assertEqual(len(self.server.requests), requests_after_first, "重複匯入不該再呼叫任何模型")

    def test_the_converted_pdf_is_written_to_the_parser_output_folder_not_next_to_the_source(self):
        folder = self.tmp / "office_folder"
        folder.mkdir()
        write_office(folder / "deck.pptx")
        write_office(folder / "report.docx")
        before = sorted(path.name for path in folder.iterdir())
        first = self.ingest(folder)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

        self.assertEqual(sorted(path.name for path in folder.iterdir()), before, "來源資料夾不該多出轉檔結果")
        converted = sorted(path.name for path in self.output_dir.rglob("*.pdf"))
        self.assertEqual(converted, ["deck.pdf", "report.pdf"], "轉出的 PDF 應該在 PARSER_OUTPUT_DIR 底下")

        second = self.ingest(folder)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("[1/2] deck.pptx", second.stdout)
        self.assertIn("[2/2] report.docx", second.stdout)
        self.assertNotIn("/3]", second.stdout, "再次匯入資料夾時，轉出的 PDF 不該被當成新文件")
        self.assertEqual(second.stdout.count("已完整處理過，略過"), 2)

    def test_two_documents_with_the_same_stem_in_one_folder_are_both_ingested_with_their_own_pdf_and_parse_output(self):
        folder = self.tmp / "same_stem"
        folder.mkdir()
        write_office(folder / "a.docx")
        write_office(folder / "a.pptx")
        result = self.ingest(folder)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("processed=2", result.stdout)
        self.assertIn("failed=0", result.stdout)
        self.assertEqual(len(list(self.output_dir.rglob("a.pdf"))), 2, "兩份文件各有自己轉出的 PDF，不共用同一個路徑")
        self.assertEqual(
            parsed_office_sources(self.output_dir),
            ["fake office document: a.docx", "fake office document: a.pptx"],
            "兩份文件各有自己的解析輸出，內容沒有被另一份覆蓋",
        )

        before = len(self.server.requests)
        answer = self.query("What is Fake Entity Alpha?", "--mode", "naive")
        self.assertEqual(answer.returncode, 0, answer.stdout + answer.stderr)
        prompt = "".join(str(r["payload"]["messages"]) for r in self.server.requests[before:] if r["path"] == "/v1/chat/completions")
        for source in ("fake office document: a.docx", "fake office document: a.pptx"):
            self.assertIn(source, prompt, f"{source} 的內容查得到")

        second = self.ingest(folder)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(second.stdout.count("已完整處理過，略過"), 2)

    def test_two_documents_with_the_same_name_in_different_folders_are_both_ingested_with_their_own_pdf_and_parse_output(self):
        for folder, text in (("x", "from folder x"), ("y", "from folder y")):
            (self.tmp / folder).mkdir()
            (self.tmp / folder / "a.docx").write_text(text + "\n", encoding="utf-8")
        first = self.ingest(self.tmp / "x" / "a.docx")
        second = self.ingest(self.tmp / "y" / "a.docx")
        for result in (first, second):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("failed=0", result.stdout)
        self.assertNotIn("已完整處理過，略過", second.stdout, "y/a.docx 是另一份文件，不是 x/a.docx 的重複")
        self.assertEqual(len(list(self.output_dir.rglob("a.pdf"))), 2)
        self.assertEqual(parsed_office_sources(self.output_dir), ["from folder x", "from folder y"])
        statuses = json.loads((self.working_dir / "kv_store_doc_status.json").read_text())
        self.assertEqual(sorted(v["status"] for v in statuses.values()), ["processed", "processed"])

    def test_a_pdf_and_an_image_keep_their_parser_output_path(self):
        # 主知識庫已用這個路徑匯入 PDF 與圖片：路徑是 <主檔名>_<原檔絕對路徑 md5 的前 8 碼>，不能因為修 Office 撞名而改變
        pdf = self.document
        image = write_image(self.tmp / "figure.png")
        self.assertEqual(self.ingest(pdf).returncode, 0)
        self.assertEqual(self.ingest(image).returncode, 0)
        for document in (pdf, image):
            digest = hashlib.md5(str(document.resolve()).encode()).hexdigest()[:8]
            expected = self.output_dir / f"{document.stem}_{digest}" / document.stem
            found = [d for d in ("auto", "ocr") if (expected / d / f"{document.stem}_content_list.json").is_file()]
            self.assertEqual(len(found), 1, f"{document.name} 的解析輸出應該在 {expected}")
        self.assertEqual(
            sorted(path.name for path in self.output_dir.iterdir()),
            sorted(f"{d.stem}_{hashlib.md5(str(d.resolve()).encode()).hexdigest()[:8]}" for d in (pdf, image)),
            "輸出資料夾底下只有這兩份文件的解析資料夾，沒有多出別的路徑",
        )

    def test_an_office_document_ingested_before_is_skipped_without_parsing_again(self):
        # 已匯入的 Office 文件，其解析輸出在舊路徑或新路徑都一樣：略過的判斷只靠索引裡的解析快取，與輸出資料夾無關。
        # 把整個解析輸出資料夾刪掉再匯入一次，若重新解析，輸出資料夾會再出現、也會呼叫模型。
        deck = write_office(self.tmp / "deck.pptx")
        first = self.ingest(deck)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        shutil.rmtree(self.output_dir)
        requests_after_first = len(self.server.requests)

        second = self.ingest(deck)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("已完整處理過，略過", second.stdout)
        self.assertEqual(len(self.server.requests), requests_after_first)
        self.assertFalse(self.output_dir.exists(), "略過的文件不該重新轉檔或解析")


# ==============================
# query
# ==============================


class QueryTest(PipelineCase):
    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.requests_before_query = len(self.server.requests)

    def query_requests(self) -> list[dict]:
        """匯入完成後才收到的請求。"""
        return self.server.requests[self.requests_before_query :]

    def test_prints_the_answer_in_mix_mode_by_default(self):
        result = self.query()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), CHAT_REPLY)
        keyword_calls = [r for r in self.query_requests() if r["payload"].get("response_format")]
        self.assertEqual(len(keyword_calls), 1, "mix 模式每次查詢會先做關鍵字抽取")

    def test_every_mode_answers_and_naive_skips_keyword_extraction(self):
        for mode in ("naive", "local", "global", "hybrid", "mix"):
            with self.subTest(mode=mode):
                before = len(self.server.requests)
                result = self.query("What is Fake Entity Alpha?", "--mode", mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), CHAT_REPLY)
                keyword_calls = [r for r in self.server.requests[before:] if r["payload"].get("response_format")]
                self.assertEqual(len(keyword_calls), 0 if mode == "naive" else 1)

    def test_answers_without_mineru_on_path(self):
        # RAG-Anything 初始化時（查詢也會）檢查 `mineru --version`；使用者沒 activate venv
        # 時 PATH 上沒有 mineru，CLI 要自己補上專案 venv 的 bin 目錄
        result = self.query(PATH=os.pathsep.join(["/usr/bin", "/bin"]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), CHAT_REPLY)

    def query_image_requests(self) -> list[dict]:
        """匯入完成後送出、帶圖片的聊天請求。"""
        return [
            r
            for r in self.query_requests()
            if r["path"] == "/v1/chat/completions"
            and any(isinstance(m["content"], list) for m in r["payload"]["messages"])
        ]

    def test_vlm_enhancement_is_off_by_default(self):
        result = self.query()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), CHAT_REPLY)
        self.assertEqual(self.query_image_requests(), [])

    def test_vlm_enhanced_flag_sends_retrieved_images_to_the_vlm_and_prints_its_answer(self):
        result = self.query("What is Fake Entity Alpha?", "--vlm-enhanced")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), VISION_REPLY)
        self.assertEqual(len(self.query_image_requests()), 1)

    def test_vlm_enhanced_works_in_every_mode(self):
        for mode in ("naive", "local", "global", "hybrid", "mix"):
            with self.subTest(mode=mode):
                result = self.query("What is Fake Entity Alpha?", "--mode", mode, "--vlm-enhanced")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), VISION_REPLY)

    def test_rejects_unknown_mode(self):
        result = self.query("q", "--mode", "bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("bogus", result.stderr)

    def test_query_side_embeddings_carry_the_instruction_prefix_and_documents_do_not(self):
        prefix = QUERY_PREFIX_ENV.replace("\\n", "\n")
        document_inputs = [
            text
            for r in self.server.requests[: self.requests_before_query]
            if r["path"] == "/v1/embeddings"
            for text in r["payload"]["input"]
        ]
        self.assertTrue(document_inputs)
        self.assertFalse([t for t in document_inputs if t.startswith("Instruct:")])

        result = self.query("What is Fake Entity Alpha?")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        query_inputs = [
            text for r in self.query_requests() if r["path"] == "/v1/embeddings" for text in r["payload"]["input"]
        ]
        self.assertTrue(query_inputs)
        self.assertTrue(all(t.startswith(prefix) for t in query_inputs), query_inputs)

    def test_failed_llm_call_exits_nonzero_with_the_original_error_and_no_answer(self):
        self.server.fail_chat = True
        result = self.query()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("injected chat failure", result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class QueryModeValidationTest(PipelineCase):
    def test_unknown_mode_is_rejected_before_any_work_and_lists_the_valid_modes(self):
        for bad in ("bogus", "Mix", ""):
            with self.subTest(mode=bad):
                result = self.query("q", "--mode", bad)
                self.assertEqual(result.returncode, 2)
                for valid in ("naive", "local", "global", "hybrid", "mix"):
                    self.assertIn(valid, result.stderr)
                self.assertEqual(self.server.requests, [])
                self.assertFalse(self.working_dir.exists())


class QueryBudgetTest(PipelineCase):
    def setUp(self):
        super().setUp()
        # multichunk 會切出約 20 個 chunk，naive 模式全部檢索得到，預設 30k 的上限放得下大部分
        self.document = self.tmp / "multichunk.pdf"
        self.document.write_bytes(b"%PDF-1.4 fake")
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)

    def answer_prompt_chars(self, question: str, budget: str) -> int:
        """以指定的 QUERY_MAX_TOTAL_TOKENS 跑 naive 查詢，回傳答案請求的訊息總字元數。

        Args:
            question: 問題；每次要不同，LightRAG 的 LLM 快取 key 不含 token 上限，同題會命中快取。
            budget: QUERY_MAX_TOTAL_TOKENS 的值。

        Returns:
            答案請求所有訊息的字元數總和。
        """
        before = len(self.server.requests)
        # naive 模式沒有圖譜 context；entity／relation 上限只是要小於最小的總上限（設定檢查要求相加小於總上限）
        result = self.query(
            question,
            "--mode",
            "naive",
            QUERY_MAX_TOTAL_TOKENS=budget,
            QUERY_MAX_ENTITY_TOKENS="500",
            QUERY_MAX_RELATION_TOKENS="500",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        answers = [
            r
            for r in self.server.requests[before:]
            if r["path"] == "/v1/chat/completions" and not r["payload"].get("response_format")
        ]
        self.assertEqual(len(answers), 1)
        return sum(len(m["content"]) for m in answers[0]["payload"]["messages"])

    def test_query_context_follows_query_max_total_tokens(self):
        large = self.answer_prompt_chars("What relates to Fake Entity 3-17?", "30000")
        small = self.answer_prompt_chars("What relates to Fake Entity 5-40?", "4000")
        # 英文約 4 字元一個 token；4000 token 的上限換算不會超過 4 * 4000 字元
        self.assertLess(small, 4 * 4000)
        self.assertGreater(large, 2 * small)


class QueryKnowledgeGraphBudgetTest(PipelineCase):
    """QUERY_MAX_ENTITY_TOKENS／QUERY_MAX_RELATION_TOKENS 決定圖譜 context 放多少 entity 與 relation 描述。"""

    def setUp(self):
        super().setUp()
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.asked = 0

    def answer_prompt(self, mode: str, *extra: str, **limits: str) -> str:
        """以指定的 entity／relation 上限查詢一次，回傳答案請求的 prompt 文字。

        Args:
            mode: 檢索模式。
            *extra: 額外的命令列引數。
            **limits: 覆蓋的環境變數（QUERY_MAX_ENTITY_TOKENS、QUERY_MAX_RELATION_TOKENS）。

        Returns:
            答案請求的 prompt 文字。每次的題目不同，LightRAG 的 LLM 快取 key 不含 token 上限。
        """
        self.asked += 1
        before = len(self.server.requests)
        result = self.query(f"What is Fake Entity Alpha? ({self.asked})", "--mode", mode, *extra, **limits)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        prompts = query_prompts(self.server.requests[before:])
        self.assertEqual(len(prompts), 1)
        return prompts[0]

    def test_graph_context_has_entities_and_relations_when_both_limits_are_large(self):
        for mode in ("local", "mix"):
            with self.subTest(mode=mode):
                prompt = self.answer_prompt(mode, QUERY_MAX_ENTITY_TOKENS="2000", QUERY_MAX_RELATION_TOKENS="2000")
                for text in (ALPHA_DESCRIPTION, BETA_DESCRIPTION, LINK_DESCRIPTION):
                    self.assertIn(text, prompt)

    def test_zero_entity_limit_leaves_out_entity_descriptions_only(self):
        for mode in ("local", "mix"):
            with self.subTest(mode=mode):
                prompt = self.answer_prompt(mode, QUERY_MAX_ENTITY_TOKENS="0", QUERY_MAX_RELATION_TOKENS="2000")
                self.assertNotIn(ALPHA_DESCRIPTION, prompt)
                self.assertNotIn(BETA_DESCRIPTION, prompt)
                self.assertIn(LINK_DESCRIPTION, prompt)

    def test_zero_relation_limit_leaves_out_relation_descriptions_only(self):
        for mode in ("local", "mix"):
            with self.subTest(mode=mode):
                prompt = self.answer_prompt(mode, QUERY_MAX_ENTITY_TOKENS="2000", QUERY_MAX_RELATION_TOKENS="0")
                self.assertIn(ALPHA_DESCRIPTION, prompt)
                self.assertNotIn(LINK_DESCRIPTION, prompt)

    def test_vlm_enhanced_query_uses_the_same_limits(self):
        large = self.answer_prompt("mix", "--vlm-enhanced", QUERY_MAX_ENTITY_TOKENS="2000", QUERY_MAX_RELATION_TOKENS="2000")
        for text in (ALPHA_DESCRIPTION, BETA_DESCRIPTION, LINK_DESCRIPTION):
            self.assertIn(text, large)
        no_entities = self.answer_prompt("mix", "--vlm-enhanced", QUERY_MAX_ENTITY_TOKENS="0", QUERY_MAX_RELATION_TOKENS="2000")
        self.assertNotIn(ALPHA_DESCRIPTION, no_entities)
        self.assertIn(LINK_DESCRIPTION, no_entities)
        no_relations = self.answer_prompt("mix", "--vlm-enhanced", QUERY_MAX_ENTITY_TOKENS="2000", QUERY_MAX_RELATION_TOKENS="0")
        self.assertIn(ALPHA_DESCRIPTION, no_relations)
        self.assertNotIn(LINK_DESCRIPTION, no_relations)


# ==============================
# PATH 處理
# ==============================


class MineruPathTest(PipelineCase):
    def test_unset_path_does_not_put_the_current_directory_ahead_of_the_venv_mineru(self):
        # PATH 沒設定時，PATH 開頭的空項目代表目前目錄；cwd 裡的 mineru 不該比 venv 的先被執行
        cwd = self.tmp / "cwd"
        cwd.mkdir()
        marker = cwd / "trap-ran"
        trap = cwd / "mineru"
        # 用 shell 內建的重導向留記號：被測行程的 PATH 沒有 /usr/bin，找不到 touch
        trap.write_text(f"#!/bin/sh\necho ran > '{marker}'\nexit 0\n")
        trap.chmod(trap.stat().st_mode | stat.S_IXUSR)

        env = {key: value for key, value in os.environ.items() if key != "PATH"}
        env.update(self.env())
        del env["PATH"]
        env["PYTHONPATH"] = str(REPO_ROOT)
        subprocess.run(
            [sys.executable, "-m", "rag_lab", "query", "What is Fake Entity Alpha?"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=INGEST_TIMEOUT,
        )
        self.assertFalse(marker.exists(), "目前目錄的 mineru 被執行了")


# ==============================
# 端點不可達
# ==============================


class UnreachableEndpointTest(PipelineCase):
    def assert_names_endpoint(self, result, label: str, url: str) -> None:
        """斷言非零結束，且 stderr 指出端點名稱與位址。"""
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(label, result.stderr)
        self.assertIn(url, result.stderr)

    def test_ingest_names_each_unreachable_endpoint(self):
        for label, field in (("LLM", "LLM_BASE_URL"), ("VLM", "VLM_BASE_URL"), ("Embedding", "EMBED_BASE_URL")):
            with self.subTest(endpoint=label):
                dead = closed_port_url()
                result = self.ingest(**{field: dead})
                self.assert_names_endpoint(result, label, dead)

    def test_query_names_each_unreachable_endpoint_it_depends_on(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        for label, field in (("LLM", "LLM_BASE_URL"), ("Embedding", "EMBED_BASE_URL")):
            with self.subTest(endpoint=label):
                dead = closed_port_url()
                result = self.query(**{field: dead})
                self.assert_names_endpoint(result, label, dead)

    def test_query_does_not_need_the_vlm_endpoint_unless_vlm_enhanced_is_requested(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        result = self.query(VLM_BASE_URL=closed_port_url())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_vlm_enhanced_query_names_the_unreachable_vlm_endpoint(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        dead = closed_port_url()
        result = self.query("What is Fake Entity Alpha?", "--vlm-enhanced", VLM_BASE_URL=dead)
        self.assert_names_endpoint(result, "VLM", dead)

    def test_vlm_enhanced_query_failures_exit_nonzero_without_an_answer(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.server.fail_vision = True
        vlm_down = self.query("What is Fake Entity Alpha?", "--vlm-enhanced")
        self.assert_names_endpoint(vlm_down, "VLM", self.server.base_url)
        self.assertIn("injected vision failure", vlm_down.stderr)
        self.assertEqual(vlm_down.stdout.strip(), "")

        self.server.fail_vision = False
        self.server.fail_chat = True
        llm_down = self.query("Which entity is related to Fake Entity Beta?", "--vlm-enhanced")
        self.assertNotEqual(llm_down.returncode, 0, llm_down.stdout)
        self.assertEqual(llm_down.stdout.strip(), "")

    def test_endpoint_failing_midway_is_still_attributed_to_the_endpoint(self):
        ingested = self.ingest()
        self.assertEqual(ingested.returncode, 0, ingested.stdout + ingested.stderr)
        self.server.fail_chat = True
        result = self.query()
        self.assert_names_endpoint(result, "LLM", self.server.base_url)

    def test_vlm_failing_midway_fails_ingest_even_though_rag_anything_does_not(self):
        self.server.fail_vision = True
        result = self.ingest()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("VLM", result.stderr)
        self.assertIn(self.server.base_url, result.stderr)
        self.assertIn("injected vision failure", result.stderr)

    def test_errors_never_print_api_keys(self):
        result = self.ingest(LLM_BASE_URL=closed_port_url())
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(SECRET, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
