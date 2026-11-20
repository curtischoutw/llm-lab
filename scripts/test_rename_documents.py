"""rename_documents.py 的行為測試：改檔名的一次性遷移與標頭檔。

為什麼存在：遷移會同時改檔案、manifest、eval 題目與標頭檔，而且要能重跑、能 dry-run、出錯時什麼都不動。
這些行為都靠對小型假資料夾的端到端執行驗證。

關鍵設計決策：
- 只從公開介面進入：migrate（含 dry_run）與命令列 main。期望的檔名是手寫字面值，不用腳本的規則重算。
- 假資料夾直接沿用 test_label_cards.FakeData（和 fetch_taishin.py 輸出同結構）。

執行方式：.venv/bin/python -m unittest scripts/test_rename_documents.py

Dependencies: 僅標準函式庫（被測的 rename_documents 透過 label_cards 用 tiktoken）。
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rename_documents  # noqa: E402
from test_label_cards import WWW, FakeData, card_page, page  # noqa: E402

RICHART_OLD = "card_cg047_card001.pdf"
RICHART_NEW = "信用卡_台新Richart卡_card_cg047_card001.pdf"
DUAL_OLD = "card_cg039_card001.pdf"
DUAL_NEW = "信用卡_雙幣信用卡_card_cg039_card001.pdf"
OFFER_OLD = "offer_WM_1.pdf"
OFFER_NEW = "信用卡_多卡_offer_WM_1.pdf"
UNLABELLED_OLD = "offer_WM_2.pdf"
OFFER_URL = "https://mkp.taishinbank.com.tw/tscccms/promotion/detail/WM_{}"


class RenameFixture(unittest.TestCase):
    """兩張卡片頁、一個比對得到兩張卡的活動、一個比對不到卡的活動、一筆沒有實體檔的紀錄，加 eval 題目。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "taishin"
        self.root.mkdir()
        self.data = FakeData(self.root)
        self.data.add("卡片", RICHART_OLD, f"{WWW}/overview/cg047/card001/", html=card_page("台新Richart卡"))
        self.data.add("卡片", DUAL_OLD, f"{WWW}/overview/cg039/card001/", html=card_page("雙幣信用卡"))
        self.data.add("活動", OFFER_OLD, OFFER_URL.format(1), html=page("限台新Richart卡與雙幣信用卡持卡人參加"))
        self.data.add("活動", UNLABELLED_OLD, OFFER_URL.format(2), html=page("限台新信用卡持卡人參加"))
        self.data.add("活動", "offer_WM_3.pdf", OFFER_URL.format(3), html=page("太陽卡"), exists=False)
        self.data.finish()
        self.eval_file = self.tmp / "questions.jsonl"
        self.questions = [
            {"id": "q1", "question": "Q", "source": RICHART_OLD},
            {"id": "q2", "question": "Q", "source": f"{RICHART_OLD}, {DUAL_OLD}"},
            {"id": "q3", "question": "Q", "source": f"查過 {OFFER_OLD}、{UNLABELLED_OLD}（OCR）"},
            {"id": "q4", "question": "Q", "source": "other_file.pdf"},
        ]
        self.write_questions(self.questions)

    def write_questions(self, questions: list[dict]) -> None:
        """寫出 eval 題目檔（一行一題）。

        Args:
            questions: 題目。
        """
        self.eval_file.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions), encoding="utf-8")

    def migrate(self, **kwargs) -> rename_documents.Report:
        """對假資料夾執行遷移，manual 預設是空的（不讀專案裡的人工標籤檔）。

        Args:
            **kwargs: 傳給 migrate 的參數。

        Returns:
            遷移報告。
        """
        kwargs.setdefault("manual", {})
        kwargs.setdefault("eval_file", self.eval_file)
        return rename_documents.migrate(self.root, **kwargs)

    def manifest_filenames(self) -> list[str]:
        """manifest 的 filename 欄，依列順序。

        Returns:
            檔名清單。
        """
        text = (self.root / "_meta" / "manifest.jsonl").read_text(encoding="utf-8")
        return [json.loads(line)["filename"] for line in text.splitlines()]

    def files(self) -> list[str]:
        """類別資料夾底下所有文件（相對路徑，排序）。

        Returns:
            相對於資料根目錄的路徑清單，不含 _meta。
        """
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file() and "_meta" not in p.parts)

    def snapshot(self) -> dict[str, bytes]:
        """資料夾與題目檔所有檔案的內容，用來確認什麼都沒動。

        Returns:
            路徑對位元組。
        """
        return {str(p): p.read_bytes() for base in (self.root, self.eval_file) for p in ([base] if base.is_file() else base.rglob("*")) if p.is_file()}

    def sources(self) -> dict[str, str]:
        """eval 題目檔裡每題的 source。

        Returns:
            題目 id 對 source。
        """
        rows = [json.loads(line) for line in self.eval_file.read_text(encoding="utf-8").splitlines()]
        return {row["id"]: row["source"] for row in rows}


class MigrateTest(RenameFixture):
    def test_files_with_a_label_get_the_new_name_and_the_manifest_follows(self) -> None:
        self.migrate()
        self.assertEqual(
            self.files(),
            sorted([f"cards/{DUAL_NEW}", f"cards/{RICHART_NEW}", f"offers/{OFFER_NEW}", f"offers/{UNLABELLED_OLD}"]),
        )
        self.assertEqual(self.manifest_filenames(), [RICHART_NEW, DUAL_NEW, OFFER_NEW, UNLABELLED_OLD, "offer_WM_3.pdf"])

    def test_report_counts_renamed_documents_and_lists_the_ones_kept_with_the_old_name(self) -> None:
        report = self.migrate()
        self.assertEqual(len(report.renamed), 3)
        self.assertEqual(report.manifest_rows, 3)
        self.assertEqual(sorted(path for path, _ in report.kept), ["offers/offer_WM_2.pdf", "offers/offer_WM_3.pdf"])

    def test_page_snapshots_keep_their_original_names(self) -> None:
        self.migrate()
        self.assertTrue((self.root / "_meta" / "html" / f"{RICHART_OLD[:-4]}.html").is_file())
        self.assertTrue((self.root / "_meta" / "print" / f"{OFFER_OLD[:-4]}.html").is_file())

    def test_second_run_changes_nothing_and_reports_nothing_to_rename(self) -> None:
        self.migrate()
        before = self.snapshot()
        report = self.migrate()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(report.renamed, {})
        self.assertEqual(report.manifest_rows, 0)
        self.assertEqual(report.eval_changes, {})

    def test_dry_run_reports_the_changes_without_touching_any_file(self) -> None:
        before = self.snapshot()
        report = self.migrate(dry_run=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(report.renamed, {f"cards/{RICHART_OLD}": RICHART_NEW, f"cards/{DUAL_OLD}": DUAL_NEW, f"offers/{OFFER_OLD}": OFFER_NEW})
        self.assertEqual(report.manifest_rows, 3)
        self.assertEqual(sorted(report.eval_changes), ["q1", "q2", "q3"])

    def test_documents_that_need_review_keep_the_old_name_and_get_no_header(self) -> None:
        self.migrate()
        headers = json.loads((self.root / "_meta" / "document_headers.json").read_text(encoding="utf-8"))
        self.assertNotIn(UNLABELLED_OLD, headers)
        self.assertEqual(sorted(headers), sorted([RICHART_NEW, DUAL_NEW, OFFER_NEW]))


class HeadersTest(RenameFixture):
    def test_headers_file_maps_the_new_file_name_to_the_header_text(self) -> None:
        self.migrate()
        headers = json.loads((self.root / "_meta" / "document_headers.json").read_text(encoding="utf-8"))
        self.assertEqual(headers[RICHART_NEW], "卡別：信用卡｜適用卡片：台新Richart卡")
        self.assertEqual(headers[OFFER_NEW], "卡別：信用卡｜適用卡片：台新Richart卡／雙幣信用卡")

    def test_second_run_still_lists_the_documents_that_already_have_new_names(self) -> None:
        self.migrate()
        (self.root / "_meta" / "document_headers.json").unlink()
        self.migrate()
        headers = json.loads((self.root / "_meta" / "document_headers.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(headers), sorted([RICHART_NEW, DUAL_NEW, OFFER_NEW]))

    def test_reviewed_labels_file_wins_over_the_automatic_label(self) -> None:
        labels = {
            f"cards/{RICHART_OLD}": {
                "kind": "金融卡",
                "cards": ["Richart簽帳金融卡"],
                "short_name": "Richart簽帳金融卡",
                "header": "卡別：金融卡｜適用卡片：Richart簽帳金融卡",
                "needs_review": False,
            }
        }
        (self.root / "_meta" / "document_labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
        self.migrate()
        self.assertIn("cards/金融卡_Richart簽帳金融卡_card_cg047_card001.pdf", self.files())
        self.assertIn(f"cards/{DUAL_NEW}", self.files())

    def test_usable_labels_of_documents_missing_from_the_labels_file_are_added_but_pending_ones_are_not(self) -> None:
        (self.root / "_meta" / "document_labels.json").write_text("{}", encoding="utf-8")
        report = self.migrate()
        labels = json.loads((self.root / "_meta" / "document_labels.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(labels), sorted([f"cards/{RICHART_OLD}", f"cards/{DUAL_OLD}", f"offers/{OFFER_OLD}"]))
        self.assertEqual(report.labels_added, 3)

    def test_no_labels_file_and_no_headers_file_are_written_when_no_document_has_a_usable_label(self) -> None:
        for path in (self.root / "cards").iterdir():
            path.unlink()
        self.data.rows = [row for row in self.data.rows if row["category"] != "卡片"]
        self.data.finish()
        self.migrate()
        self.assertEqual(sorted(p.name for p in (self.root / "_meta").iterdir()), ["html", "manifest.jsonl", "print"])

    def test_manual_labels_apply_and_paths_not_in_this_folder_are_reported_not_fatal(self) -> None:
        manual = {
            f"offers/{UNLABELLED_OLD}": {"kind": "信用卡", "cards": ["全部信用卡"], "decision": "使用者確認"},
            "offers/not_here.pdf": {"kind": "信用卡", "cards": ["全部信用卡"]},
        }
        report = self.migrate(manual=manual)
        self.assertIn("offers/信用卡_全部_offer_WM_2.pdf", self.files())
        self.assertEqual(report.unused_manual, ["offers/not_here.pdf"])


class EvalSourcesTest(RenameFixture):
    def test_source_fields_follow_the_new_names_including_lists_and_free_text(self) -> None:
        report = self.migrate()
        self.assertEqual(
            self.sources(),
            {
                "q1": RICHART_NEW,
                "q2": f"{RICHART_NEW}, {DUAL_NEW}",
                "q3": f"查過 {OFFER_NEW}、{UNLABELLED_OLD}（OCR）",
                "q4": "other_file.pdf",
            },
        )
        self.assertEqual(report.eval_changes["q2"], (f"{RICHART_OLD}, {DUAL_OLD}", f"{RICHART_NEW}, {DUAL_NEW}"))

    def test_other_fields_and_unchanged_lines_stay_byte_identical(self) -> None:
        before = self.eval_file.read_text(encoding="utf-8").splitlines()
        self.migrate()
        after = self.eval_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(after[3], before[3])
        self.assertEqual(json.loads(after[0])["question"], "Q")

    def test_a_name_that_is_only_the_tail_of_a_longer_name_is_not_replaced(self) -> None:
        self.write_questions([{"id": "q1", "question": "Q", "source": f"x{RICHART_OLD}"}])
        self.migrate()
        self.assertEqual(self.sources(), {"q1": f"x{RICHART_OLD}"})

    def test_rerun_after_an_interruption_still_rewrites_sources_of_files_already_renamed(self) -> None:
        self.migrate()
        self.write_questions(self.questions)
        report = self.migrate()
        self.assertEqual(sorted(report.eval_changes), ["q1", "q2", "q3"])
        self.assertEqual(self.sources()["q1"], RICHART_NEW)

    def test_migration_without_an_eval_file_only_changes_the_data_folder(self) -> None:
        report = self.migrate(eval_file=None)
        self.assertEqual(report.eval_changes, {})
        self.assertEqual(self.sources()["q1"], RICHART_OLD)


class BackupTest(RenameFixture):
    def test_manifest_and_eval_file_are_copied_before_anything_changes(self) -> None:
        manifest_before = (self.root / "_meta" / "manifest.jsonl").read_bytes()
        eval_before = self.eval_file.read_bytes()
        backup = self.tmp / "backup"
        self.migrate(backup_dir=backup)
        self.assertEqual((backup / "manifest.jsonl").read_bytes(), manifest_before)
        self.assertEqual((backup / self.eval_file.name).read_bytes(), eval_before)

    def test_dry_run_creates_no_backup(self) -> None:
        backup = self.tmp / "backup"
        self.migrate(backup_dir=backup, dry_run=True)
        self.assertFalse(backup.exists())

    def test_second_run_with_nothing_to_change_creates_no_backup(self) -> None:
        self.migrate()
        backup = self.tmp / "backup"
        self.migrate(backup_dir=backup)
        self.assertFalse(backup.exists())


class RefusalTest(RenameFixture):
    def test_two_documents_with_the_same_new_name_stop_the_migration_before_any_change(self) -> None:
        # 不同資料夾、同一個原檔名、同一個標籤：標頭檔的 key（檔名）會撞
        self.data.add("活動圖片", RICHART_OLD, f"{WWW}/img/a", html=card_page("台新Richart卡"))
        self.data.finish()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "同一個新檔名"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_unsafe_character_in_a_short_name_stops_the_migration_before_any_change(self) -> None:
        labels = {
            f"cards/{RICHART_OLD}": {
                "kind": "信用卡",
                "cards": ["a/b"],
                "short_name": "a/b",
                "header": "卡別：信用卡｜適用卡片：a/b",
                "needs_review": False,
            }
        }
        (self.root / "_meta" / "document_labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "不安全"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_existing_file_with_the_target_name_stops_the_migration_before_any_change(self) -> None:
        (self.root / "cards" / RICHART_NEW).write_bytes(b"other")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "已經有檔案"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)


class CommandLineTest(RenameFixture):
    def run_main(self, *args: str) -> tuple[int, str]:
        """執行命令列，回傳結束碼與 stdout。

        Args:
            *args: 命令列參數。

        Returns:
            (結束碼, stdout)。
        """
        out = io.StringIO()
        manual = self.tmp / "manual.json"
        manual.write_text("{}", encoding="utf-8")
        with contextlib.redirect_stdout(out):
            code = rename_documents.main(
                ["--data-dir", str(self.root), "--questions", str(self.eval_file), "--manual", str(manual), *args]
            )
        return code, out.getvalue()

    def test_dry_run_prints_the_counts_the_kept_documents_and_the_changed_questions(self) -> None:
        before = self.snapshot()
        code, output = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("dry-run", output)
        self.assertIn("改名 3 份", output)
        self.assertIn("manifest 3 筆", output)
        self.assertIn(f"cards/{RICHART_OLD} -> {RICHART_NEW}", output)
        self.assertIn("保留原檔名 2 份", output)
        self.assertIn("offers/offer_WM_3.pdf", output)
        self.assertIn("eval 題目 3 題：q1、q2、q3", output)

    def test_applying_without_a_backup_dir_is_refused(self) -> None:
        before = self.snapshot()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_main()
        self.assertEqual(self.snapshot(), before)

    def test_applying_renames_and_the_second_run_reports_nothing_to_do(self) -> None:
        backup = self.tmp / "backup"
        code, _ = self.run_main("--backup-dir", str(backup))
        self.assertEqual(code, 0)
        self.assertIn(f"cards/{RICHART_NEW}", self.files())
        _, output = self.run_main("--backup-dir", str(self.tmp / "backup2"))
        self.assertIn("改名 0 份", output)


if __name__ == "__main__":
    unittest.main()
