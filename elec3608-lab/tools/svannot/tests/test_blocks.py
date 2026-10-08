"""Block scanner tests: extents, nesting, and no phantom blocks."""
from __future__ import annotations

import unittest

from annot.blocks import describe, scan_blocks
from annot.lexer import scan

from . import common


def kinds(fi) -> list[str]:
    return [b.kind for b in fi.block_scan.all_blocks()]


class TestGoodFixture(unittest.TestCase):
    def setUp(self):
        self.fi = common.index("good.sv")

    def test_block_kinds_and_nesting(self):
        self.assertEqual(kinds(self.fi),
                         ["module", "always_comb", "always_ff", "function",
                          "assign", "always_comb"])

    def test_module_name_and_span(self):
        m = self.fi.block_scan.outermost_module()
        self.assertIsNotNone(m)
        self.assertEqual(m.name, "nerv")
        self.assertEqual((m.start_line, m.end_line), (3, 48))

    def test_every_block_is_inside_the_module(self):
        m = self.fi.block_scan.outermost_module()
        for b in self.fi.block_scan.all_blocks():
            if b is m:
                continue
            self.assertIs(b.parent, m, f"{b.label} should be a child of the module")

    def test_no_scanner_warnings(self):
        self.assertEqual(self.fi.block_scan.warnings, [])


class TestNesting(unittest.TestCase):
    """nested_blocks.sv is built so that guessing where a block ends fails."""

    def setUp(self):
        self.fi = common.index("nested_blocks.sv")
        self.blocks = [b for b in self.fi.block_scan.all_blocks()
                       if b.kind != "module"]

    def _first(self, kind):
        hits = [b for b in self.blocks if b.kind == kind]
        self.assertTrue(hits, f"no {kind} block found")
        return hits[0]

    def test_always_comb_survives_nested_begin_end_and_case(self):
        b = self._first("always_comb")
        # starts at the `always_comb begin` on 1-based line 12 and must find the
        # matching `end` on line 26, past if/else, begin/end and case/endcase.
        self.assertEqual((b.start_line + 1, b.end_line + 1), (12, 26))

    def test_function_extent(self):
        f = [b for b in self.fi.block_scan.all_blocks() if b.kind == "function"][0]
        self.assertEqual(f.name, "nested_fn")
        self.assertEqual((f.start_line + 1, f.end_line + 1), (29, 37))

    def test_always_ff_with_two_edge_sensitivity(self):
        f = [b for b in self.fi.block_scan.all_blocks() if b.kind == "always_ff"][0]
        self.assertEqual((f.start_line + 1, f.end_line + 1), (40, 43))

    def test_single_statement_always_comb(self):
        # `always_comb c = a & b;` has no begin/end -- extent is to the `;`.
        combos = [b for b in self.fi.block_scan.all_blocks()
                  if b.kind == "always_comb"]
        single = [b for b in combos if b.end_line == b.start_line]
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0].start_line + 1, 46)

    def test_innermost_at(self):
        # line 20 (1-based) is inside the case, inside the always_comb
        b = self.fi.block_scan.innermost_at(19)
        self.assertEqual(b.kind, "always_comb")

    def test_containers_are_flagged(self):
        m = self.fi.block_scan.outermost_module()
        self.assertTrue(m.is_container)
        comb = [b for b in self.fi.block_scan.all_blocks()
                if b.kind == "always_comb"][0]
        self.assertFalse(comb.is_container)


class TestNoPhantomBlocks(unittest.TestCase):
    def test_keywords_in_strings_and_comments_do_not_create_blocks(self):
        fi = common.index("comment_edge_cases.sv")
        # Only the module, the initial block and the one always_comb may exist.
        self.assertEqual(sorted(kinds(fi)),
                         ["always_comb", "initial", "module"])
        initial = [b for b in fi.block_scan.all_blocks()
                   if b.kind == "initial"][0]
        comb = [b for b in fi.block_scan.all_blocks()
                if b.kind == "always_comb"][0]
        # the `end` inside the block comment must not have closed the initial
        self.assertTrue(initial.end_line < comb.start_line)
        self.assertEqual((comb.start_line + 1, comb.end_line + 1), (18, 20))


class TestScannerEdges(unittest.TestCase):
    def test_unterminated_module_warns(self):
        s = scan("module m;\n logic a;\n")
        r = scan_blocks(s.masked, s.lines)
        self.assertEqual(len(r.warnings), 1)
        self.assertIn("unterminated", r.warnings[0])

    def test_describe(self):
        self.assertEqual(describe("always_comb"), "combinational block")
        self.assertEqual(describe("mystery"), "mystery")

    def test_block_label_and_path(self):
        fi = common.index("good.sv")
        b = [x for x in fi.block_scan.all_blocks() if x.kind == "function"][0]
        self.assertEqual(b.label, "function decode_insn")
        self.assertEqual(b.path(), "module nerv/function decode_insn")


if __name__ == "__main__":
    unittest.main()
