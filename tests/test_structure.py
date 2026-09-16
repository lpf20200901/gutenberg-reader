"""Tests for paragraph-boundary detection and heading classification.

Every case here is drawn from a real Project Gutenberg book that broke an
earlier version of the parser.  The docstrings say which one.

Written against the standard library only, so the suite runs with no install::

    python -m unittest discover -s tests -v

(It also runs under pytest if you happen to have it, since pytest collects
unittest.TestCase classes.)
"""

import unittest

from gutenberg_reader.structure import (
    Block,
    classify_heading,
    detect_mode,
    parse,
    stats,
    strip_boilerplate,
)

PG_TEXT = """The Project Gutenberg eBook of something

Title: A Book

*** START OF THE PROJECT GUTENBERG EBOOK A BOOK ***

Real content here.

*** END OF THE PROJECT GUTENBERG EBOOK A BOOK ***

Licence text.
"""


class TestStripBoilerplate(unittest.TestCase):
    def test_removes_header_and_footer(self):
        body = strip_boilerplate(PG_TEXT)
        self.assertIn("Real content here.", body)
        self.assertNotIn("Licence text.", body)
        self.assertNotIn("START OF THE PROJECT GUTENBERG", body)

    def test_is_a_noop_without_markers(self):
        self.assertEqual(strip_boilerplate("just text"), "just text")


class TestDetectMode(unittest.TestCase):
    """The three paragraph conventions found across nine real books."""

    def test_indent(self):
        """醒世恒言: 3,250 indented lines but only 118 blank lines."""
        text = "\n".join(
            "\u3000\u3000" + f"这是第{i}段的内容，用来凑够长度以便统计。" for i in range(120)
        )
        self.assertEqual(detect_mode(text), "indent")

    def test_blank(self):
        """聊齋志異: paragraphs separated by blank lines."""
        text = "\n\n".join(f"    第{i}段的正文内容。" for i in range(120))
        self.assertEqual(detect_mode(text), "blank")

    def test_unwrap(self):
        """二刻拍案惊奇 #24162: ~28 chars per line, blank after every line."""
        line = "嘗記博物志云漢劉褒畫雲漢圖見者覺熱又畫"       # ends mid-sentence
        text = "\n\n".join(line for _ in range(120))
        self.assertEqual(detect_mode(text), "unwrap")

    def test_entry_numbers_do_not_mislead_unwrap_detection(self):
        """世說新語: bare "1." lines never end a sentence, so counting them
        would classify the book as hard-wrapped."""
        chunks = []
        for i in range(120):
            chunks.append(f"{i + 1}.")
            chunks.append("陳仲舉言為士則行為世範登車攬轡有澄清天下之志。")
        self.assertEqual(detect_mode("\n\n".join(chunks)), "blank")


class TestClassifyHeading(unittest.TestCase):
    """The layout zoo: every heading form observed in a real book."""

    def test_simple_heading_forms(self):
        cases = [
            ("〈考城隍〉", [Block("h2", "考城隍")]),        # 聊齋志異
            ("卷一", [Block("h1", "卷一")]),               # 聊齋志異 volume
            ("德行第一", [Block("h1", "德行第一")]),        # 世說新語: ordinal last
            ("第一回", [Block("h2", "第一回")]),
            ("CHAPTER I", [Block("h2", "CHAPTER I")]),
            ("第一卷", [Block("h1", "第一卷")]),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(
                    classify_heading(line, next_phys_blank=True), expected)

    def test_volume_and_title_on_one_line_with_space(self):
        """喻世明言 / 警世通言: 第一卷 + ideographic space + title."""
        got = classify_heading("第一卷\u3000蔣興哥重會珍珠衫", next_phys_blank=False)
        self.assertEqual(got, [Block("h1", "第一卷"), Block("h2", "蔣興哥重會珍珠衫")])

    def test_volume_and_title_run_together(self):
        """初刻拍案惊奇: no space at all between marker and title."""
        got = classify_heading("第一卷轉運漢遇巧洞庭紅\u3000波斯胡指破鼉龍殼",
                              next_phys_blank=False)
        self.assertIsNotNone(got)
        self.assertEqual(got[0], Block("h1", "第一卷"))
        self.assertEqual(got[1].kind, "h2")
        self.assertTrue(got[1].text.startswith("轉運漢遇巧洞庭紅"))

    def test_volume_without_di_prefix(self):
        """二刻拍案惊奇 #26729: 卷一 + title, with no 第."""
        got = classify_heading("卷一 進香客莽看金剛經 出獄僧巧完法會分",
                              next_phys_blank=False)
        self.assertEqual(got[0], Block("h1", "卷一"))
        self.assertEqual(got[1].kind, "h2")

    def test_weak_heading_requires_a_standalone_line(self):
        """The guard that stops wrapped continuation lines being promoted to
        chapter titles."""
        standalone = classify_heading("兩縣令競義婚孤女", next_phys_blank=True)
        inline = classify_heading("兩縣令競義婚孤女", next_phys_blank=False)
        self.assertIsNotNone(standalone)
        self.assertIsNone(inline)

    def test_blocklist_suppresses_in_text_enumeration(self):
        """警世通言 produced four bogus headings (其一/其二/其三/其四) before
        the blocklist existed."""
        for word in ("其一", "其二", "其三", "其四", "又", "詩曰", "話說"):
            with self.subTest(word=word):
                self.assertIsNone(classify_heading(word, next_phys_blank=True))

    def test_ordinary_prose_is_not_a_heading(self):
        line = "陳仲舉言為士則行為世範登車攬轡有澄清天下之志。"
        self.assertIsNone(classify_heading(line, next_phys_blank=True))


class TestParse(unittest.TestCase):
    def test_shishuoxinyu_layout(self):
        """世說新語 puts section title, entry number and text on three
        consecutive lines with NO blank line between them, so a blank-line
        splitter sees one opaque blob."""
        text = (
            "德行第一\n"
            "1.\n"
            "陳仲舉言，為士則行為世範。\n"
            "\n"
            "2.\n"
            "周子居常云：「吾時月不見黃叔度。」\n"
        )
        blocks = parse(text)
        self.assertEqual([b.kind for b in blocks], ["h1", "en", "en"])
        self.assertEqual(blocks[0].text, "德行第一")
        self.assertEqual(blocks[1].number, "1")
        self.assertIn("陳仲舉言", blocks[1].text)
        self.assertEqual(blocks[2].number, "2")

    def test_indent_mode_keeps_paragraphs_apart(self):
        """The bug this module exists for: 初刻拍案惊奇 collapsed from 40
        chapters into 42 paragraphs of ~10,000 characters each."""
        text = (
            "第一卷\n"
            "\u3000\u3000第一段的内容，缩进表示新段落开始。\n"
            "\u3000\u3000第二段的内容，同样有缩进。\n"
            "\u3000\u3000第三段的内容。\n"
        )
        paragraphs = [b for b in parse(text, mode="indent") if b.kind == "p"]
        self.assertEqual(len(paragraphs), 3)
        self.assertTrue(paragraphs[0].text.startswith("第一段"))

    def test_indent_mode_rejoins_wrapped_continuation_lines(self):
        """Continuation lines are not indented and must be rejoined, otherwise
        the text is shredded into ~30-character fragments."""
        text = (
            "第一卷\n"
            "\u3000\u3000這是段首，接下來續行沒有縮進，\n"
            "所以應該被接回同一段，而不是切成兩段。\n"
            "\u3000\u3000第二段的段首也有縮進，這裡是新段落。\n"
        )
        paragraphs = [b for b in parse(text, mode="indent") if b.kind == "p"]
        self.assertEqual(len(paragraphs), 2)
        self.assertIn("所以應該被接回同一段", paragraphs[0].text)

    def test_blank_mode_splits_on_blank_lines(self):
        text = "第一段。\n\n第二段。\n\n第三段。\n"
        paragraphs = [b for b in parse(text, mode="blank") if b.kind == "p"]
        self.assertEqual([p.text for p in paragraphs], ["第一段。", "第二段。", "第三段。"])

    def test_unwrap_mode_joins_until_sentence_end(self):
        text = "這是第一句的一部分，\n然後繼續，\n到這裡才結束。\n接下來是第二句。\n"
        paragraphs = [b for b in parse(text, mode="unwrap") if b.kind == "p"]
        self.assertEqual(paragraphs[0].text, "這是第一句的一部分，然後繼續，到這裡才結束。")
        self.assertEqual(paragraphs[1].text, "接下來是第二句。")

    def test_cjk_paragraphs_are_not_joined_with_spaces(self):
        text = "\u3000\u3000中文段落續行不該插入空格，\n所以拼接後不應出現空白。\n"
        paragraphs = [b for b in parse(text, mode="indent") if b.kind == "p"]
        self.assertNotIn(" ", paragraphs[0].text)

    def test_single_long_line_book_stays_one_paragraph(self):
        """A book whose paragraphs are one long line each, blank-separated."""
        text = "\n\n".join(f"    第{i}段的正文。" for i in range(5))
        paragraphs = [b for b in parse(text, mode="blank") if b.kind == "p"]
        self.assertEqual(len(paragraphs), 5)


class TestStats(unittest.TestCase):
    def test_reports_sane_paragraph_density(self):
        text = "\n".join("\u3000\u3000" + "內容" * 60 for _ in range(30))
        s = stats(parse(text, mode="indent"))
        self.assertEqual(s["counts"].get("p"), 30)
        self.assertGreaterEqual(s["avg_paragraph_chars"], 100)
        self.assertLessEqual(s["avg_paragraph_chars"], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
