"""label_cards.py 的行為測試：標籤規則的純函式，以及對小型假資料夾的端到端產生。

為什麼存在：卡片標籤的正確性最後靠使用者抽查，但規則本身（卡名比對、全部／多卡的判定、標頭長度改寫、
沿用來源頁面的標籤）要能重跑得到一樣的結果。測試資料全部是這個檔案內組出來的假 manifest 與假 html，
不依賴 data/ 裡的真實文件。

關鍵設計決策：
- 測試只從公開介面進入：find_cards、make_label、label_data_dir、render_review、main。
  期望值是手寫的字面值（從 spec 與 GLOSSARY 的標籤定義推出），不用腳本自己的規則重算。
- 假資料夾的檔案結構與 fetch_taishin.py 的輸出相同：類別資料夾、_meta/manifest.jsonl、
  _meta/html（原始 HTML）、_meta/print（主內容區）。

執行方式：.venv/bin/python -m unittest scripts/test_label_cards.py

Dependencies: 僅標準函式庫（被測的 label_cards 另外用 tiktoken）。
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import label_cards  # noqa: E402
from label_cards import Card  # noqa: E402


# ==============================
# 假資料
# ==============================

CATALOG = [
    Card("信用卡", "台新Richart卡", ("台新Richart卡", "Richart卡")),
    Card("信用卡", "雙幣信用卡", ("雙幣信用卡", "雙幣卡")),
    Card("信用卡", "太陽卡", ("太陽卡",)),
    Card("金融卡", "VISA金融卡", ("VISA金融卡",)),
    Card("金融卡", "元氣VISA金融卡", ("元氣VISA金融卡",)),
    Card("金融卡", "Richart簽帳金融卡", ("Richart簽帳金融卡", "遛狗卡")),
]


def names(cards: list[Card]) -> list[str]:
    """卡片清單轉成卡名清單，方便比對。

    Args:
        cards: Card 清單。

    Returns:
        每張卡的 name。
    """
    return [card.name for card in cards]


# ==============================
# find_cards：在文字裡比對已知卡名
# ==============================

class FindCardsTest(unittest.TestCase):
    def test_finds_known_card_by_name(self) -> None:
        found = label_cards.find_cards("限台新Richart卡持卡人參加", CATALOG)
        self.assertEqual(names(found), ["台新Richart卡"])

    def test_finds_card_by_alias(self) -> None:
        found = label_cards.find_cards("刷雙幣卡享 3% 回饋", CATALOG)
        self.assertEqual(names(found), ["雙幣信用卡"])

    def test_returns_nothing_when_no_known_card_is_mentioned(self) -> None:
        self.assertEqual(label_cards.find_cards("限台新信用卡持卡人", CATALOG), [])

    def test_whitespace_and_case_are_ignored(self) -> None:
        found = label_cards.find_cards("使用 Richart  簽帳金融卡 與 visa 金融卡", CATALOG)
        self.assertEqual(names(found), ["VISA金融卡", "Richart簽帳金融卡"])

    def test_longer_card_name_hides_the_shorter_name_inside_it(self) -> None:
        found = label_cards.find_cards("元氣VISA金融卡", CATALOG)
        self.assertEqual(names(found), ["元氣VISA金融卡"])

    def test_shorter_name_still_counts_when_it_also_appears_alone(self) -> None:
        found = label_cards.find_cards("元氣VISA金融卡與VISA金融卡", CATALOG)
        self.assertEqual(names(found), ["VISA金融卡", "元氣VISA金融卡"])


# ==============================
# make_label：卡片清單轉成標籤
# ==============================

def card(catalog_name: str) -> Card:
    """依卡名從測試用清單取卡。

    Args:
        catalog_name: CATALOG 裡某張卡的 name。

    Returns:
        該張卡。
    """
    return next(c for c in CATALOG if c.name == catalog_name)


class MakeLabelTest(unittest.TestCase):
    def test_single_card(self) -> None:
        label = label_cards.make_label([card("台新Richart卡")], CATALOG)
        self.assertEqual(
            label,
            {
                "kind": "信用卡",
                "cards": ["台新Richart卡"],
                "short_name": "台新Richart卡",
                "header": "卡別：信用卡｜適用卡片：台新Richart卡",
            },
        )

    def test_several_cards_of_one_kind(self) -> None:
        label = label_cards.make_label([card("台新Richart卡"), card("雙幣信用卡")], CATALOG)
        self.assertEqual(label["kind"], "信用卡")
        self.assertEqual(label["cards"], ["台新Richart卡", "雙幣信用卡"])
        self.assertEqual(label["short_name"], "多卡")
        self.assertEqual(label["header"], "卡別：信用卡｜適用卡片：台新Richart卡／雙幣信用卡")

    def test_every_card_of_a_kind_becomes_all_cards_of_that_kind(self) -> None:
        credit = [c for c in CATALOG if c.kind == "信用卡"]
        label = label_cards.make_label(credit, CATALOG)
        self.assertEqual(label["cards"], ["全部信用卡"])
        self.assertEqual(label["short_name"], "全部")
        self.assertEqual(label["header"], "卡別：信用卡｜適用卡片：全部信用卡")

    def test_both_kinds_are_labelled_with_both_kinds(self) -> None:
        label = label_cards.make_label([card("台新Richart卡"), card("Richart簽帳金融卡")], CATALOG)
        self.assertEqual(label["kind"], "信用卡及金融卡")
        self.assertEqual(label["cards"], ["台新Richart卡", "Richart簽帳金融卡"])
        self.assertEqual(label["short_name"], "多卡")

    def test_all_cards_of_both_kinds(self) -> None:
        label = label_cards.make_label(list(CATALOG), CATALOG)
        self.assertEqual(label["kind"], "信用卡及金融卡")
        self.assertEqual(label["cards"], ["全部信用卡", "全部金融卡"])
        self.assertEqual(label["short_name"], "全部")

    def test_all_of_one_kind_plus_one_card_of_the_other_is_several_cards(self) -> None:
        credit = [c for c in CATALOG if c.kind == "信用卡"]
        label = label_cards.make_label(credit + [card("VISA金融卡")], CATALOG)
        self.assertEqual(label["cards"], ["全部信用卡", "VISA金融卡"])
        self.assertEqual(label["short_name"], "多卡")

    def test_header_over_150_tokens_points_to_the_first_paragraph(self) -> None:
        many = [Card("信用卡", f"台新測試聯名卡第{i:02d}號", ()) for i in range(30)]
        catalog = many + [Card("信用卡", "另一張卡", ())]
        label = label_cards.make_label(many, catalog)
        self.assertEqual(label["header"], "卡別：信用卡｜適用 30 張卡（清單見本文件第一段）")
        self.assertEqual(len(label["cards"]), 30)


# ==============================
# label_data_dir：對假資料夾產生標籤
# ==============================

FOLDERS = {
    "卡片": "cards",
    "權益": "rights",
    "下載": "downloads",
    "權益附件": "rights_attachments",
    "活動": "offers",
    "活動圖片": "offer_images",
    "金融卡卡片頁": "debit_cards",
    "金融卡約定條款 PDF": "debit_terms",
    "金融卡說明頁": "debit_info",
    "Richart 卡片頁": "richart",
    "Richart 優惠細則": "richart_discounts",
}
WWW = "https://www.taishinbank.com.tw"


class FakeData:
    """在暫存資料夾裡組一份和 fetch_taishin.py 輸出同結構的小型假資料。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.rows: list[dict] = []
        (root / "_meta" / "html").mkdir(parents=True)
        (root / "_meta" / "print").mkdir(parents=True)

    def add(
        self,
        category: str,
        filename: str,
        url: str,
        *,
        html: str | None = None,
        main: str | None = None,
        exists: bool = True,
    ) -> str:
        """加一筆 manifest 紀錄，並依參數建立實體檔與頁面快照。

        Args:
            category: manifest 的類別（中文名稱，決定資料夾）。
            filename: 文件檔名。
            url: 文件網址。
            html: 原始 HTML 內容；None 表示沒有頁面快照。
            main: 主內容區 HTML（_meta/print）；None 時沿用 html。
            exists: False 表示 manifest 有紀錄但沒有實體檔。

        Returns:
            文件相對於資料根目錄的路徑（labels 的 key）。
        """
        folder = FOLDERS[category]
        self.rows.append({"url": url, "category": category, "filename": filename, "html_sha256": "x" if html else ""})
        if exists:
            (self.root / folder).mkdir(exist_ok=True)
            (self.root / folder / filename).write_bytes(b"%PDF")
        if html is not None:
            stem = filename.rsplit(".", 1)[0]
            (self.root / "_meta" / "html" / f"{stem}.html").write_text(html, encoding="utf-8")
            (self.root / "_meta" / "print" / f"{stem}.html").write_text(main if main is not None else html, encoding="utf-8")
        return f"{folder}/{filename}"

    def finish(self) -> Path:
        """寫出 manifest。

        Returns:
            資料根目錄。
        """
        lines = (json.dumps(row, ensure_ascii=False) for row in self.rows)
        (self.root / "_meta" / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.root


def card_page(h1: str) -> str:
    """假的卡片頁 HTML：官網的 <title> 是共用的總覽標題，卡名在 h1。

    Args:
        h1: 卡名。

    Returns:
        HTML 字串。
    """
    return f"<html><head><title>信用卡總覽 - 台新銀行</title></head><body><h1>{h1}</h1><p>卡片介紹</p></body></html>"


def page(text: str, title: str = "活動標題") -> str:
    """假的活動或權益頁 HTML。

    Args:
        text: 內文。
        title: <title> 內容。

    Returns:
        HTML 字串。
    """
    return f"<html><head><title>{title}</title></head><body><div><p>{text}</p></div></body></html>"


class LabelDataDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = FakeData(Path(self._tmp.name))
        self.cards = [
            ("card_cg047_card001.pdf", "cg047", "台新Richart卡"),
            ("card_cg039_card001.pdf", "cg039", "雙幣信用卡"),
            ("card_cg012_card0001.pdf", "cg012", "太陽卡"),
        ]
        for filename, cg, h1 in self.cards:
            self.data.add("卡片", filename, f"{WWW}/TSB/personal/credit/intro/overview/{cg}/card001/", html=card_page(h1))

    def label(self) -> dict:
        """對目前的假資料產生標籤。

        Returns:
            label_data_dir 的結果。
        """
        return label_cards.label_data_dir(self.data.finish())

    def test_card_page_is_labelled_with_the_card_named_in_its_heading(self) -> None:
        entry = self.label()["cards/card_cg047_card001.pdf"]
        self.assertEqual(entry["kind"], "信用卡")
        self.assertEqual(entry["cards"], ["台新Richart卡"])
        self.assertEqual(entry["short_name"], "台新Richart卡")
        self.assertEqual(entry["header"], "卡別：信用卡｜適用卡片：台新Richart卡")
        self.assertEqual(entry["source"], "卡片頁")
        self.assertFalse(entry["needs_review"])

    def test_offer_is_labelled_with_the_known_cards_its_text_mentions(self) -> None:
        key = self.data.add(
            "活動",
            "offer_WM_1.pdf",
            "https://mkp.taishinbank.com.tw/tscccms/promotion/detail/WM_1",
            html=page("限台新Richart卡與雙幣信用卡持卡人參加"),
        )
        entry = self.label()[key]
        self.assertEqual(entry["kind"], "信用卡")
        self.assertEqual(entry["cards"], ["台新Richart卡", "雙幣信用卡"])
        self.assertEqual(entry["short_name"], "多卡")
        self.assertEqual(entry["source"], "頁面內文")
        self.assertFalse(entry["needs_review"])

    def test_offer_text_that_names_no_known_card_needs_review(self) -> None:
        key = self.data.add(
            "活動",
            "offer_WM_2.pdf",
            "https://mkp.taishinbank.com.tw/tscccms/promotion/detail/WM_2",
            html=page("限台新信用卡持卡人參加"),
        )
        entry = self.label()[key]
        self.assertTrue(entry["needs_review"])
        self.assertEqual(entry["cards"], [])
        self.assertIsNone(entry["short_name"])
        self.assertIsNone(entry["header"])
        self.assertIn("沒有比對到", entry["reason"])

    def test_manifest_rows_without_a_file_get_no_label(self) -> None:
        self.data.add("活動", "offer_WM_3.pdf", f"{WWW}/x", html=page("太陽卡"), exists=False)
        self.assertNotIn("offers/offer_WM_3.pdf", self.label())


class CardNameTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = FakeData(Path(self._tmp.name))

    def test_slash_in_a_card_name_becomes_a_middle_dot_and_the_original_still_matches(self) -> None:
        self.data.add("卡片", "card_cg008_card001.pdf", f"{WWW}/overview/cg008/card001/", html=card_page("新光三越御璽/鈦金/白金卡"))
        key = self.data.add("活動", "offer_WM_1.pdf", f"{WWW}/WM_1", html=page("新光三越御璽/鈦金/白金卡 刷卡 9 折"))
        labels = label_cards.label_data_dir(self.data.finish())
        self.assertEqual(labels["cards/card_cg008_card001.pdf"]["cards"], ["新光三越御璽・鈦金・白金卡"])
        self.assertEqual(labels[key]["short_name"], "新光三越御璽・鈦金・白金卡")

    def test_extra_alias_for_a_card_family_matches_one_member_of_the_family(self) -> None:
        self.data.add("卡片", "card_cg008_card001.pdf", f"{WWW}/overview/cg008/card001/", html=card_page("新光三越御璽/鈦金/白金卡"))
        key = self.data.add("活動", "offer_WM_1.pdf", f"{WWW}/WM_1", html=page("持新光三越白金卡消費"))
        labels = label_cards.label_data_dir(self.data.finish())
        self.assertEqual(labels[key]["cards"], ["新光三越御璽・鈦金・白金卡"])

    def test_credit_and_debit_cards_with_the_same_group_number_stay_separate(self) -> None:
        self.data.add("卡片", "card_cg003_card001.pdf", f"{WWW}/credit/overview/cg003/card001/", html=card_page("國泰航空翱翔鈦金卡/鈦金卡"))
        self.data.add("金融卡卡片頁", "debit_card_cg003_card01.pdf", f"{WWW}/credit/payment/cg003/card01/", html=card_page("財富管理Visa金融卡"))
        labels = label_cards.label_data_dir(self.data.finish())
        self.assertEqual(labels["cards/card_cg003_card001.pdf"]["kind"], "信用卡")
        self.assertEqual(labels["debit_cards/debit_card_cg003_card01.pdf"]["kind"], "金融卡")
        self.assertEqual(labels["debit_cards/debit_card_cg003_card01.pdf"]["cards"], ["財富管理Visa金融卡"])

    def test_richart_pages_are_labelled_by_file_name(self) -> None:
        self.data.add("卡片", "card_cg047_card001.pdf", f"{WWW}/overview/cg047/card001/", html=card_page("台新Richart卡"))
        # 兩頁內文都提到對方的卡名（Richart 兩種卡最容易搞混），標籤不能靠內文
        credit = self.data.add("Richart 卡片頁", "richart_credit-card.pdf", "https://richart.tw/card/credit-card", html=page("台新Richart卡；也可搭配Richart簽帳金融卡"))
        debit = self.data.add("Richart 卡片頁", "richart_debit-card.pdf", "https://richart.tw/card/debit-card", html=page("Richart簽帳金融卡（遛狗卡）；信用卡請看台新Richart卡"))
        labels = label_cards.label_data_dir(self.data.finish())
        self.assertEqual((labels[credit]["kind"], labels[credit]["cards"]), ("信用卡", ["台新Richart卡"]))
        self.assertEqual((labels[debit]["kind"], labels[debit]["cards"]), ("金融卡", ["Richart簽帳金融卡"]))
        self.assertEqual(labels[debit]["source"], "卡片頁")

    def test_page_naming_every_debit_card_is_labelled_all_debit_cards(self) -> None:
        self.data.add("金融卡卡片頁", "debit_card_cg001_card01.pdf", f"{WWW}/payment/cg001/card01/", html=card_page("VISA金融卡"))
        self.data.add("金融卡卡片頁", "debit_card_cg006_card001.pdf", f"{WWW}/payment/cg006/card001/", html=card_page("勞動保障卡"))
        key = self.data.add("金融卡說明頁", "debit_info_card-list.pdf", f"{WWW}/payment/notice/card-list", html=page("VISA金融卡、勞動保障卡、Richart簽帳金融卡"))
        labels = label_cards.label_data_dir(self.data.finish())
        self.assertEqual(labels[key]["cards"], ["全部金融卡"])
        self.assertEqual(labels[key]["short_name"], "全部")


class LinkedDocumentTest(unittest.TestCase):
    """沒有頁面快照的文件：沿用連到它的頁面的標籤。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = FakeData(Path(self._tmp.name))
        self.data.add("卡片", "card_cg047_card001.pdf", f"{WWW}/overview/cg047/card001/", html=card_page("台新Richart卡"))
        self.data.add("卡片", "card_cg039_card001.pdf", f"{WWW}/overview/cg039/card001/", html=card_page("雙幣信用卡"))
        self.data.add("卡片", "card_cg012_card0001.pdf", f"{WWW}/overview/cg012/card0001/", html=card_page("太陽卡"))

    def rights_page(self, name: str, text: str, pdf_href: str) -> str:
        """加一個權益子頁，內文有一個 PDF 連結。

        Args:
            name: 檔名主檔名（不含副檔名）。
            text: 內文。
            pdf_href: 連結的 href（相對或絕對）。

        Returns:
            標籤檔的 key。
        """
        body = f'<p>{text}</p><a href="{pdf_href}">下載</a>'
        return self.data.add("權益", f"{name}.docx", f"{WWW}/rights/oversea/{name}/", html=f"<html><body><div>{body}</div></body></html>")

    def test_attachment_takes_the_label_of_the_rights_page_that_links_to_it(self) -> None:
        self.rights_page("right0101", "台新Richart卡專屬", "/TSB/export/sites/TSB/files/creditcard/a%20b.pdf")
        key = self.data.add("權益附件", "attachment_a_b.pdf", f"{WWW}/TSB/export/sites/TSB/files/creditcard/a%20b.pdf")
        entry = label_cards.label_data_dir(self.data.finish())[key]
        self.assertEqual(entry["cards"], ["台新Richart卡"])
        self.assertEqual(entry["source"], "沿用連到它的頁面：rights/right0101.docx")
        self.assertFalse(entry["needs_review"])

    def test_attachment_linked_from_two_pages_takes_the_cards_of_both(self) -> None:
        self.rights_page("right0101", "台新Richart卡專屬", "/files/x.pdf")
        self.rights_page("right0102", "雙幣信用卡專屬", "https://www.taishinbank.com.tw/files/x.pdf")
        key = self.data.add("權益附件", "attachment_x.pdf", f"{WWW}/files/x.pdf")
        entry = label_cards.label_data_dir(self.data.finish())[key]
        self.assertEqual(entry["cards"], ["台新Richart卡", "雙幣信用卡"])

    def test_attachment_that_no_page_links_to_needs_review(self) -> None:
        self.rights_page("right0101", "台新Richart卡專屬", "/files/other.pdf")
        key = self.data.add("權益附件", "attachment_x.pdf", f"{WWW}/files/x.pdf")
        entry = label_cards.label_data_dir(self.data.finish())[key]
        self.assertTrue(entry["needs_review"])
        self.assertIn("沒有任何權益頁連到", entry["reason"])

    def test_attachment_linked_only_from_a_page_that_needs_review_needs_review(self) -> None:
        self.rights_page("right0101", "只寫台新信用卡", "/files/x.pdf")
        key = self.data.add("權益附件", "attachment_x.pdf", f"{WWW}/files/x.pdf")
        entry = label_cards.label_data_dir(self.data.finish())[key]
        self.assertTrue(entry["needs_review"])
        self.assertIn("rights/right0101.docx", entry["reason"])

    def test_offer_image_takes_the_label_of_its_offer_page(self) -> None:
        self.data.add("活動", "offer_WM_20260903.pdf", f"{WWW}/WM_20260903", html=page("雙幣信用卡限定"))
        key = self.data.add("活動圖片", "offer_image_WM_20260903_banner_image.jpg", "https://mkp.example/upload/WM_20260903/WM_20260903_banner_image.jpg")
        entry = label_cards.label_data_dir(self.data.finish())[key]
        self.assertEqual(entry["cards"], ["雙幣信用卡"])
        self.assertEqual(entry["source"], "沿用連到它的頁面：offers/offer_WM_20260903.pdf")

    def test_offer_image_without_its_offer_page_needs_review(self) -> None:
        key = self.data.add("活動圖片", "offer_image_WM_9_banner_image.jpg", "https://mkp.example/WM_9/WM_9_banner_image.jpg")
        self.assertTrue(label_cards.label_data_dir(self.data.finish())[key]["needs_review"])

    def test_documents_with_no_known_source_page_need_review(self) -> None:
        download = self.data.add("下載", "download_x.pdf", f"{WWW}/files/download_x.pdf")
        terms = self.data.add("金融卡約定條款 PDF", "debit_term_x.pdf", f"{WWW}/payment/x.pdf")
        labels = label_cards.label_data_dir(self.data.finish())
        for key in (download, terms):
            self.assertTrue(labels[key]["needs_review"], key)
            self.assertIn("沒有頁面快照", labels[key]["reason"])


class ReviewAndOutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = FakeData(self.root / "data")
        for cg, h1 in (("cg047", "台新Richart卡"), ("cg039", "雙幣信用卡"), ("cg012", "太陽卡")):
            self.data.add("卡片", f"card_{cg}_card001.pdf", f"{WWW}/overview/{cg}/card001/", html=card_page(h1))
        for number in range(5):
            self.data.add("活動", f"offer_WM_{number}.pdf", f"{WWW}/WM_{number}", html=page("台新Richart卡限定", title=f"活動 {number}"))
        self.data.add("活動", "offer_WM_9.pdf", f"{WWW}/WM_9", html=page("太陽卡與雙幣卡", title="活動 9"))
        self.data.add("下載", "download_x.pdf", f"{WWW}/files/download_x.pdf")
        self.data.finish()

    def run_main(self) -> tuple[Path, Path]:
        """對假資料跑 main，輸出到暫存資料夾。

        Returns:
            (標籤檔, 抽查報告) 的路徑。
        """
        labels_path = self.root / "document_labels.json"
        review_path = self.root / "out" / "labels_review.md"
        with contextlib.redirect_stdout(io.StringIO()):
            code = label_cards.main(["--data-dir", str(self.root / "data"), "--labels", str(labels_path), "--review", str(review_path)])
        self.assertEqual(code, 0)
        return labels_path, review_path

    def test_labels_file_has_one_entry_per_document_with_a_file(self) -> None:
        labels_path, _ = self.run_main()
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        expected = {f"{FOLDERS[row['category']]}/{row['filename']}" for row in self.data.rows}
        self.assertEqual(set(labels), expected)
        self.assertEqual(labels["offers/offer_WM_0.pdf"]["short_name"], "台新Richart卡")

    def test_rerun_gives_identical_files(self) -> None:
        labels_path, review_path = self.run_main()
        first = (labels_path.read_bytes(), review_path.read_bytes())
        self.run_main()
        self.assertEqual((labels_path.read_bytes(), review_path.read_bytes()), first)

    def test_review_counts_documents_per_folder_and_per_label_kind(self) -> None:
        _, review_path = self.run_main()
        review = review_path.read_text(encoding="utf-8")
        self.assertIn("| cards | 3 | 0 |", review)
        self.assertIn("| offers | 6 | 0 |", review)
        self.assertIn("| downloads | 1 | 1 |", review)
        self.assertIn("| 信用卡 | 9 |", review)
        self.assertIn("| 一張卡 | 8 |", review)
        self.assertIn("| 多卡 | 1 |", review)
        self.assertIn("| 全部 | 0 |", review)
        self.assertIn("| 待人工確認 | 1 |", review)

    def test_review_lists_documents_that_need_review_with_the_reason(self) -> None:
        _, review_path = self.run_main()
        self.assertIn("- `downloads/download_x.pdf`：沒有頁面快照，查不到它從哪個頁面連過去", review_path.read_text(encoding="utf-8"))

    def test_review_samples_three_documents_per_folder_with_title_and_label(self) -> None:
        _, review_path = self.run_main()
        review = review_path.read_text(encoding="utf-8")
        offers = review.split("### offers")[1].split("###")[0]
        self.assertEqual(offers.count("\n- `offer_WM_"), 3)
        self.assertRegex(offers, r"`offer_WM_\d+\.pdf`｜頁面標題：活動 \d｜標籤：信用卡｜")
        cards = review.split("### cards")[1].split("###")[0]
        self.assertIn("`card_cg047_card001.pdf`｜頁面標題：台新Richart卡｜標籤：信用卡｜台新Richart卡", cards)
        downloads = review.split("### downloads")[1]
        self.assertIn("頁面標題：（沒有頁面快照）｜標籤：待人工確認", downloads)


if __name__ == "__main__":
    unittest.main()
