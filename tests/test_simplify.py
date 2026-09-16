"""Tests for Traditional -> Simplified conversion and gap repair.

The point is the *gap*: an engine that reports success while silently leaving
thousands of Traditional characters behind produces a mixed-script document,
which reads worse than either script alone.

Standard library only::

    python -m unittest discover -s tests -v
"""

import unittest

from gutenberg_reader.simplify import (
    REFERENCE_PAIRS,
    SIMPLIFY_PATCH,
    SIMPLIFY_PATCH_EXCLUDED,
    SIMPLIFY_PATCH_UNCHANGED,
    SIMPLIFY_PATCH_WRONG_VARIANT,
    audit_gaps,
    residual_traditional,
    to_simplified,
)


class TestPatchTable(unittest.TestCase):
    def test_patch_applies_even_with_no_engine(self):
        """A Windows-only API failing must not mean zero conversion.

        爲 is the biggest measured gap (2,052 occurrences in 聊齋志異) and the
        patch table has to cover it regardless of which engine ran.
        """
        conv = to_simplified("爲於後")
        for expected in ("为", "于", "后"):
            self.assertIn(expected, conv.text)
        self.assertNotIn("爲", conv.text)

    def test_every_patch_entry_converts(self):
        for trad, simp in sorted(SIMPLIFY_PATCH.items()):
            with self.subTest(trad=trad):
                conv = to_simplified(f"x{trad}y")
                self.assertIn(simp, conv.text)
                self.assertNotIn(trad, conv.text)

    def test_untouched_forms_are_repaired(self):
        """Failure mode 1: the engine leaves the Traditional form in place."""
        for trad, simp in sorted(SIMPLIFY_PATCH_UNCHANGED.items()):
            with self.subTest(trad=trad):
                conv = to_simplified(f"x{trad}y")
                self.assertIn(simp, conv.text)
                self.assertGreaterEqual(conv.patched, 1)

    def test_wrong_variant_output_is_repaired(self):
        """Failure mode 2: the engine converts, but to the wrong variant.

        A patch table that maps only Traditional sources cannot fix these — by
        the time the patch runs the source character is gone, so the remap has
        to target the engine's output.  This test is what caught the mistake.
        """
        self.assertIn("锺", SIMPLIFY_PATCH_WRONG_VARIANT)
        self.assertIn("麽", SIMPLIFY_PATCH_WRONG_VARIANT)
        for wrong, right in sorted(SIMPLIFY_PATCH_WRONG_VARIANT.items()):
            with self.subTest(wrong=wrong):
                conv = to_simplified(f"x{wrong}y")
                self.assertIn(right, conv.text)
                self.assertNotIn(wrong, conv.text)

    def test_wrong_variant_repair_survives_the_engine(self):
        """End to end: feed the Traditional source, expect the modern form.

        The engine turns 鍾 into 锺; the patch must still land on 钟.
        """
        conv = to_simplified("鍾")
        self.assertIn("钟", conv.text)
        self.assertNotIn("鍾", conv.text)
        self.assertNotIn("锺", conv.text)

    def test_patch_can_be_disabled(self):
        conv = to_simplified("爲", apply_patch=False)
        self.assertEqual(conv.patched, 0)

    def test_excluded_forms_are_deliberately_untouched(self):
        """藉 is a valid Simplified character in 慰藉/狼藉 — only 藉口 -> 借口
        should convert — so a blanket mapping would introduce errors.  祗 is a
        subtle variant with negligible frequency."""
        self.assertIn("藉", SIMPLIFY_PATCH_EXCLUDED)
        self.assertIn("祗", SIMPLIFY_PATCH_EXCLUDED)
        self.assertNotIn("藉", SIMPLIFY_PATCH)
        self.assertNotIn("祗", SIMPLIFY_PATCH)

        conv = to_simplified("慰藉狼藉")
        self.assertIn("藉", conv.text)

    def test_patch_table_is_documented_without_duplicates(self):
        self.assertEqual(len(SIMPLIFY_PATCH), len(set(SIMPLIFY_PATCH)))
        for trad, simp in SIMPLIFY_PATCH.items():
            self.assertEqual(len(trad), 1)
            self.assertEqual(len(simp), 1)
            self.assertNotEqual(trad, simp)


class TestConversionResult(unittest.TestCase):
    def test_reports_counts_consistently(self):
        conv = to_simplified("爲於後")
        self.assertEqual(conv.patched, 3)
        self.assertGreaterEqual(conv.total_changed, 3)

    def test_reports_an_engine_name(self):
        conv = to_simplified("爲")
        self.assertIn(conv.engine, ("windows", "opencc", "none"))

    def test_engine_changed_count_excludes_patch(self):
        """engine_changed measures the engine alone; patched measures repairs."""
        conv = to_simplified("爲爲爲")
        self.assertEqual(conv.patched, 3)
        # 爲 is not in any engine's working range, so the engine did nothing here
        if conv.engine == "windows":
            self.assertEqual(conv.engine_changed, 0)

    def test_plain_text_passes_through(self):
        conv = to_simplified("hello 世界")
        self.assertEqual(conv.text, "hello 世界")
        self.assertEqual(conv.patched, 0)


class TestAuditGaps(unittest.TestCase):
    """The procedure that produced SIMPLIFY_PATCH."""

    def test_returns_highest_frequency_first(self):
        text = "爲" * 10 + "後" * 3
        gaps = audit_gaps(text)
        counts = [c for _, _, c in gaps]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_finds_known_engine_gaps(self):
        gaps = audit_gaps("爲後於")
        forms = {f for f, _, _ in gaps}
        self.assertIn("爲", forms)

    def test_ignores_forms_absent_from_the_text(self):
        """Which gaps matter is a function of what the book contains."""
        self.assertEqual(audit_gaps("完全沒有繁體字的文字"), [])

    def test_reference_table_is_well_formed(self):
        self.assertGreater(len(REFERENCE_PAIRS), 100)
        for trad, simp in REFERENCE_PAIRS:
            self.assertEqual(len(trad), 1, trad)
            self.assertEqual(len(simp), 1, simp)
            self.assertNotEqual(trad, simp)


class TestResidualTraditional(unittest.TestCase):
    def test_empty_after_conversion(self):
        """A cheap quality gate on the final text."""
        conv = to_simplified("爲於後衆蹟牀")
        self.assertEqual(residual_traditional(conv.text), {})

    def test_detects_unconverted_text(self):
        residual = residual_traditional("爲於後")
        self.assertEqual(set(residual), {"爲", "於", "後"})

    def test_counts_occurrences(self):
        residual = residual_traditional("爲爲爲於")
        self.assertEqual(residual["爲"], 3)
        self.assertEqual(residual["於"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
