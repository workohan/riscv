"""Lexer tests: comment and string handling, masking, line mapping."""
from __future__ import annotations

import unittest

from annot.lexer import LineIndex, comment_body_lines, scan

from . import common


class TestLineIndex(unittest.TestCase):
    def test_line_col_roundtrip(self):
        idx = LineIndex("abc\ndefg\nhi")
        self.assertEqual(idx.line_col(0), (0, 0))
        self.assertEqual(idx.line_col(2), (0, 2))
        self.assertEqual(idx.line_col(4), (1, 0))
        self.assertEqual(idx.line_col(9), (2, 0))
        self.assertEqual(idx.offset(1, 2), 6)
        self.assertEqual(idx.line_count, 3)

    def test_offset_clamps(self):
        idx = LineIndex("a\nb")
        self.assertEqual(idx.offset(-5, 0), 0)
        self.assertEqual(idx.offset(99, 0), idx.line_start(1))


class TestScan(unittest.TestCase):
    def test_line_comment(self):
        s = scan("logic a; // hello\nlogic b;")
        self.assertEqual(len(s.comments), 1)
        self.assertEqual(s.comments[0].text, " hello")
        self.assertTrue(s.comments[0].is_line)
        self.assertEqual(s.comments[0].start_line, 0)

    def test_block_comment_spans_lines(self):
        s = scan("/* one\n   two */\ncode")
        self.assertEqual(len(s.comments), 1)
        c = s.comments[0]
        self.assertEqual(c.kind, "block")
        self.assertEqual((c.start_line, c.end_line), (0, 1))

    def test_masking_preserves_length_and_lines(self):
        src = 'logic a; // c\nlogic b; /* d\ne */ logic c;'
        s = scan(src)
        self.assertEqual(len(s.masked), len(src))
        self.assertEqual(s.masked.count("\n"), src.count("\n"))

    def test_string_hides_comment_markers(self):
        # `//` and `/*` inside a string must not start a comment.
        s = scan('$display("a // b /* c");')
        self.assertEqual(s.comments, [])
        self.assertNotIn("//", s.masked)
        self.assertNotIn("/*", s.masked)

    def test_comment_hides_string_markers(self):
        # A quote inside a comment must not swallow the following lines.
        s = scan('// he said "hi\nlogic a;\n')
        self.assertEqual(len(s.comments), 1)
        self.assertIn("logic a;", s.masked)

    def test_escaped_quote_inside_string(self):
        s = scan(r'$display("a \" b"); logic c; // real' + "\n")
        self.assertEqual(len(s.comments), 1)
        self.assertEqual(s.comments[0].text, " real")

    def test_unterminated_block_comment(self):
        s = scan("code\n/* never closed\nmore")
        self.assertEqual(len(s.comments), 1)
        self.assertEqual(s.comments[0].end, len("code\n/* never closed\nmore"))

    def test_block_at(self):
        src = "a /* x */ b"
        s = scan(src)
        self.assertIsNotNone(s.block_at(4))
        self.assertIsNone(s.block_at(0))

    def test_comment_body_lines_strips_stars(self):
        s = scan("/*\n * @mux:a  first\n *          second\n */\n")
        cleaned = comment_body_lines(s.comments[0])
        self.assertEqual(cleaned[0], "")
        self.assertEqual(cleaned[1], "@mux:a  first")
        self.assertEqual(cleaned[2], "second")
        self.assertEqual(cleaned[3], "")

    def test_fixture_no_phantom_comments(self):
        # comment_edge_cases.sv has `//` inside a string on line 8 (1-based).
        s = scan(common.load("comment_edge_cases.sv"))
        string_lines = [c.start_line for c in s.comments]
        self.assertNotIn(7, string_lines)   # 0-based line of the $display


if __name__ == "__main__":
    unittest.main()
