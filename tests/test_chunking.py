"""rag_lab.chunking 的純函式測試：依標題切塊的 chunker 與 content list 改寫。

為什麼存在：ticket 04 的 chunker 決定每個 chunk 的內容與數量，要能不啟動任何服務就驗證；
經假端點的整個匯入流程另在 tests/test_pipeline.py。

關鍵設計決策：
- tokenizer 用「一個字元一個 token」的假物件（CharTokenizer），所以 token 數就是字元數，期望值可以用字面值
  直接寫出，不必用被測程式的算法重算。
- 只從公開函式（chunk_by_headings、rewrite_content_list）進出，檢查輸出的 chunk 內容與數量。

Dependencies: 標準函式庫。
"""

import unittest

from rag_lab.chunking import chunk_by_headings, rewrite_content_list

MARKER_START = "<<<RAG_LAB_HEADER"
MARKER_END = "RAG_LAB_HEADER>>>"


class CharTokenizer:
    """一個字元一個 token 的假 tokenizer。"""

    def encode(self, content: str) -> list[int]:
        return [ord(char) for char in content]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


def document(header: str, *blocks: str) -> str:
    """組出 parse_document 會交給 LightRAG 的文件內容：標頭標記區塊在最前面，各區塊以空行相隔。"""
    return "\n\n".join([f"{MARKER_START}\n{header}\n{MARKER_END}", *blocks])


def chunk(content: str, size: int = 1200, overlap: int = 100) -> list[dict]:
    return chunk_by_headings(CharTokenizer(), content, None, False, overlap, size)


def body(label: str, length: int) -> str:
    """長度剛好 length 個字元、開頭是 label 的內文。"""
    return (label + "。" * length)[:length]


class SplitAtHeadingsTest(unittest.TestCase):
    def test_each_heading_starts_a_chunk_with_header_and_section_name(self):
        content = document(
            "信用卡：甲卡、乙卡",
            "# 回饋方案",
            body("回饋內文", 150),
            "# 年費",
            body("年費內文", 150),
        )

        chunks = chunk(content)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0]["content"].startswith("信用卡：甲卡、乙卡\n章節：回饋方案\n\n回饋內文"))
        self.assertTrue(chunks[1]["content"].startswith("信用卡：甲卡、乙卡\n章節：年費\n\n年費內文"))
        self.assertNotIn("年費內文", chunks[0]["content"])
        self.assertNotIn(MARKER_START, chunks[0]["content"])
        self.assertEqual([c["chunk_order_index"] for c in chunks], [0, 1])
        self.assertEqual([c["tokens"] for c in chunks], [len(c["content"]) for c in chunks])

    def test_content_without_header_block_is_rejected(self):
        with self.assertRaises(ValueError):
            chunk("# 回饋方案\n\n" + body("內文", 150))


class LongSectionTest(unittest.TestCase):
    def test_section_over_the_limit_is_split_by_tokens_with_overlap(self):
        header = "卡：甲"
        text = "".join(chr(0x4E00 + i) for i in range(500))  # 500 個互不相同的字，重疊處看得出來
        content = document(header, "# 長節", text)

        chunks = chunk(content, size=300, overlap=20)

        # 每個 chunk 的開頭是「卡：甲\n章節：長節\n\n」共 11 字元，內文每段最多 289 字元，每段與前一段重疊 20 字元
        # 內文起點 0、269（289 - 20），第二段 269 到 500 結束 → 2 個 chunk
        self.assertEqual(len(chunks), 2)
        for item in chunks:
            self.assertLessEqual(item["tokens"], 300)
            self.assertTrue(item["content"].startswith("卡：甲\n章節：長節\n\n"))
        first = chunks[0]["content"].split("\n\n", 1)[1]
        second = chunks[1]["content"].split("\n\n", 1)[1]
        self.assertEqual(first, text[:289])
        self.assertEqual(second, text[269:])

    def test_no_chunk_exceeds_the_limit_for_a_very_long_section(self):
        content = document("卡：甲", "# 長節", body("內文", 2500))

        chunks = chunk(content, size=400, overlap=40)

        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(c["tokens"] <= 400 for c in chunks))


class ShortSectionTest(unittest.TestCase):
    def test_short_section_merges_into_next_and_header_lists_both_names(self):
        content = document(
            "卡：甲",
            "# 短節",
            body("短內文", 30),
            "# 長節",
            body("長內文", 200),
        )

        chunks = chunk(content)

        self.assertEqual(len(chunks), 1)
        text = chunks[0]["content"]
        self.assertTrue(text.startswith("卡：甲\n章節：短節、長節\n\n短內文"))
        self.assertIn("長內文", text)

    def test_short_last_section_merges_into_previous(self):
        content = document(
            "卡：甲",
            "# 長節",
            body("長內文", 200),
            "# 尾節",
            body("尾內文", 20),
        )

        chunks = chunk(content)

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0]["content"].startswith("卡：甲\n章節：長節、尾節\n\n長內文"))
        self.assertIn("尾內文", chunks[0]["content"])

    def test_section_of_100_tokens_is_not_short_but_99_is(self):
        # 節的 token 數 = 標題行（「# 甲節」4 字元）+ 空行 2 字元 + 內文
        at_limit = document("卡：甲", "# 甲節", body("甲", 94), "# 乙節", body("乙", 120))
        below_limit = document("卡：甲", "# 甲節", body("甲", 93), "# 乙節", body("乙", 120))

        self.assertEqual(len(chunk(at_limit)), 2)
        self.assertEqual(len(chunk(below_limit)), 1)

    def test_merged_group_over_the_limit_is_split_again(self):
        content = document(
            "卡：甲",
            "# 短節",
            body("短內文", 30),
            "# 長節",
            body("長內文", 700),
        )

        chunks = chunk(content, size=400, overlap=40)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(c["tokens"] <= 400 for c in chunks))
        self.assertTrue(all("章節：短節、長節" in c["content"] for c in chunks))


class HeaderTest(unittest.TestCase):
    def test_long_header_is_rewritten_except_in_the_first_chunk(self):
        cards = [f"第{i:03d}號卡" for i in range(40)]  # 每張 5 字元 + 頓號，清單約 240 字元，超過 150
        header = "信用卡：" + "、".join(cards)
        content = document(header, "# 甲節", body("甲", 200), "# 乙節", body("乙", 200))

        chunks = chunk(content)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0]["content"].startswith(header + "\n章節：甲節"))
        self.assertTrue(chunks[1]["content"].startswith("信用卡：適用 40 張卡（清單見本文件第一段）\n章節：乙節"))
        self.assertNotIn("第000號卡", chunks[1]["content"])

    def test_header_within_150_tokens_is_kept_in_every_chunk(self):
        header = "信用卡：" + "、".join(f"卡{i}" for i in range(20))  # 約 70 字元
        content = document(header, "# 甲節", body("甲", 200), "# 乙節", body("乙", 200))

        chunks = chunk(content)

        self.assertTrue(all(c["content"].startswith(header) for c in chunks))


class NoHeadingTest(unittest.TestCase):
    def test_document_without_headings_is_split_by_tokens_and_every_chunk_has_header(self):
        content = document("卡：甲", body("無標題內文", 900))

        chunks = chunk(content, size=400, overlap=40)

        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(c["content"].startswith("卡：甲\n\n") for c in chunks))
        self.assertTrue(all("章節：" not in c["content"] for c in chunks))
        self.assertTrue(all(c["tokens"] <= 400 for c in chunks))

    def test_text_before_the_first_heading_is_its_own_section_without_a_name(self):
        content = document("卡：甲", body("前言", 150), "# 甲節", body("甲內文", 150))

        chunks = chunk(content)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0]["content"].startswith("卡：甲\n\n前言"))
        self.assertTrue(chunks[1]["content"].startswith("卡：甲\n章節：甲節\n\n甲內文"))

    def test_empty_document_yields_no_chunks(self):
        self.assertEqual(chunk(document("卡：甲")), [])


def count_tokens(text: str) -> int:
    return len(CharTokenizer().encode(text))


def joined_text(content_list: list[dict]) -> str:
    """RAG-Anything 把 content list 的文字項目以空行串成文件內容（raganything/utils.py 的 separate_content）。"""
    return "\n\n".join(item["text"] for item in content_list if item.get("type") == "text" and item["text"].strip())


class RewriteContentListTest(unittest.TestCase):
    def sample(self) -> list[dict]:
        return [
            {"type": "text", "text": "前言", "page_idx": 0},
            {"type": "text", "text": "回饋方案", "text_level": 2, "page_idx": 0},
            {"type": "text", "text": body("內文", 150), "page_idx": 0},
            {"type": "table", "table_body": "<table></table>", "table_caption": ["表一"], "page_idx": 0},
            {"type": "image", "img_path": "a.png", "image_caption": [], "page_idx": 1},
            {"type": "equation", "text": "x=1"},
        ]

    def test_header_block_comes_first_and_levelled_text_becomes_markdown_heading(self):
        result = rewrite_content_list(self.sample(), "信用卡：甲卡", count_tokens)

        self.assertEqual(result[0], {"type": "text", "text": f"{MARKER_START}\n信用卡：甲卡\n{MARKER_END}"})
        self.assertEqual(result[2]["text"], "## 回饋方案")
        self.assertEqual(result[1]["text"], "前言")
        self.assertEqual(result[3]["text"], body("內文", 150))

    def test_table_and_image_captions_get_the_card_label(self):
        result = rewrite_content_list(self.sample(), "信用卡：甲卡", count_tokens)

        table = next(item for item in result if item["type"] == "table")
        image = next(item for item in result if item["type"] == "image")
        self.assertEqual(table["table_caption"], ["卡片標籤：信用卡：甲卡", "表一"])
        self.assertEqual(image["image_caption"], ["卡片標籤：信用卡：甲卡"])
        self.assertEqual(result[-1], {"type": "equation", "text": "x=1"})

    def test_long_header_is_shortened_in_captions(self):
        header = "信用卡：" + "、".join(f"第{i:03d}號卡" for i in range(40))

        result = rewrite_content_list(self.sample(), header, count_tokens)

        table = next(item for item in result if item["type"] == "table")
        self.assertEqual(table["table_caption"][0], "卡片標籤：信用卡：適用 40 張卡（清單見本文件第一段）")

    def test_input_is_not_modified(self):
        original = self.sample()
        snapshot = [dict(item) for item in original]

        rewrite_content_list(original, "信用卡：甲卡", count_tokens)

        self.assertEqual(original, snapshot)

    def test_header_containing_the_marker_is_rejected(self):
        with self.assertRaises(ValueError):
            rewrite_content_list(self.sample(), f"卡 {MARKER_END} 卡", count_tokens)

    def test_rewritten_list_feeds_the_chunker(self):
        rewritten = rewrite_content_list(self.sample(), "信用卡：甲卡", count_tokens)

        chunks = chunk(joined_text(rewritten))

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0]["content"].startswith("信用卡：甲卡\n章節：回饋方案\n\n"))
        self.assertIn("前言", chunks[0]["content"])


if __name__ == "__main__":
    unittest.main()
