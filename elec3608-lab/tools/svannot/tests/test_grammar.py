"""Annotation grammar tests."""
from __future__ import annotations

import unittest

from annot.grammar import DEF_LINE_RE, parse

from . import common


class TestDefinitions(unittest.TestCase):
    def setUp(self):
        self.fi = common.index("good.sv")
        self.names = {d.name: d for d in self.fi.annotations.definitions}

    def test_all_definitions_found(self):
        self.assertEqual(sorted(self.names),
                         ["adder", "br_target", "decode_insn", "nerv",
                          "pc_reg", "pcmux"])

    def test_category_is_required_and_captured(self):
        self.assertEqual(self.names["pcmux"].category, "mux")
        self.assertEqual(self.names["pc_reg"].category, "seq")
        self.assertEqual(self.names["nerv"].category, "module")

    def test_line_numbers_are_one_based_when_displayed(self):
        self.assertEqual(self.names["pcmux"].line + 1, 16)
        self.assertEqual(self.names["br_target"].line + 1, 38)

    def test_definition_offset_points_at_the_at_sign(self):
        d = self.names["pcmux"]
        self.assertEqual(self.fi.text[d.offset], "@")
        self.assertEqual(self.fi.text[d.offset:d.end_offset], "@mux:pcmux")

    def test_description_continues_across_block_comment_lines(self):
        # `/* @mux:pcmux ... \n * driven by [pc] and [ppc]. */`
        desc = self.names["pcmux"].description
        self.assertIn("selects npc from reset", desc)
        self.assertIn("driven by [pc] and [ppc]", desc)
        self.assertNotIn("*", desc)

    def test_block_comment_definition_is_found(self):
        # pcmux is defined in a /* */ comment, the rest in // comments
        self.assertEqual(self.names["pcmux"].comment.kind, "block")


class TestReferences(unittest.TestCase):
    def setUp(self):
        self.fi = common.index("good.sv")
        self.refs = self.fi.annotations.references

    def test_reference_names(self):
        names = sorted(r.name for r in self.refs)
        self.assertEqual(names, ["br_target", "does_not_exist", "npc_mux",
                                 "pcmux", "pcmux", "pcmux", "pcmux"])

    def test_definition_token_is_not_also_a_reference(self):
        # The `@pcmux` that *defines* the component must not self-reference.
        # (Other @names on the same line -- e.g. `@br_target` in the
        # description -- are legitimate references.)
        d = [x for x in self.fi.annotations.definitions if x.name == "pcmux"][0]
        same_offset = [r for r in self.refs if r.offset == d.offset]
        self.assertEqual(same_offset, [])

    def test_trailing_reference_on_a_code_line(self):
        fi = common.index("comment_edge_cases.sv")
        refs = [r for r in fi.annotations.references if r.name == "real_block"]
        self.assertEqual(len(refs), 1)
        # the reference sits on the same line as a statement, inside the block
        line_text = fi.text.split("\n")[refs[0].line]
        self.assertIn("a = 1'b0;", line_text)

    def test_references_never_come_from_strings(self):
        fi = common.index("comment_edge_cases.sv")
        names = {r.name for r in fi.annotations.references}
        self.assertNotIn("fake_annotation", names)


class TestHardwareRefs(unittest.TestCase):
    def test_bracket_refs_collected_and_classified(self):
        fi = common.index("good.sv")
        by_name = {h.name: h for h in fi.annotations.hardware}
        self.assertIn("pc", by_name)
        self.assertIn("ppc", by_name)
        self.assertIn("pc", fi.identifiers)
        self.assertNotIn("ppc", fi.identifiers)

    def test_brackets_ignored_without_an_annotation(self):
        # A comment with no '@' must not yield hardware refs, so prose like
        # `[see below]` is not mistaken for a signal.
        fi = common.index("comment_edge_cases.sv")
        plain = [h for h in fi.annotations.hardware if h.name == "see"]
        self.assertEqual(plain, [])


class TestBareAtStart(unittest.TestCase):
    def test_bare_token_at_comment_start_is_not_a_definition(self):
        fi = common.index("missing_category.sv")
        self.assertEqual([d.name for d in fi.annotations.definitions], ["proper"])
        self.assertEqual([r.name for r in fi.annotations.bare_at_start],
                         ["forgot_the_category"])

    def test_bare_token_is_not_double_counted_as_a_reference(self):
        fi = common.index("missing_category.sv")
        self.assertEqual([r.name for r in fi.annotations.references], [])

    def test_bare_token_mid_comment_is_a_reference(self):
        fi = common.index("good.sv")
        # "...see @pcmux and @npc_mux" -- neither is at the comment start
        refs = {r.name for r in fi.annotations.references}
        self.assertIn("npc_mux", refs)


class TestMalformed(unittest.TestCase):
    def setUp(self):
        self.fi = common.index("malformed_annotations.sv")
        self.msgs = [m.message for m in self.fi.annotations.malformed]

    def test_all_malformed_forms_reported(self):
        self.assertEqual(len(self.msgs), 5)

    def test_empty_category(self):
        self.assertTrue(any("@` must be followed by a name" in m
                            for m in self.msgs))

    def test_bad_category_suggests_a_fix(self):
        hit = [m for m in self.msgs if "Bad_Category" in m]
        self.assertEqual(len(hit), 1)
        self.assertIn("@bad_category:thing", hit[0])

    def test_no_definitions_from_malformed_input(self):
        self.assertEqual(self.fi.annotations.definitions, [])


class TestFalsePositives(unittest.TestCase):
    """Prose that looks like an annotation but is not."""

    def parse_src(self, src: str):
        from annot.grammar import parse
        from annot.lexer import scan
        return parse(scan(src))

    def test_email_address_is_not_a_reference(self):
        # Every file in this repository has a copyright header with an email
        # in it; treating that as @yosyshq made every file report a bogus
        # undefined reference.
        got = self.parse_src(
            "/*\n * Copyright (C) 2020 Claire Xenia Wolf <claire@yosyshq.com>\n */\n")
        self.assertEqual(got.references, [])
        self.assertEqual(got.malformed, [])

    def test_real_reference_next_to_an_email_still_found(self):
        got = self.parse_src(
            "// mail claire@yosyshq.com about @pcmux and more\n")
        self.assertEqual([r.name for r in got.references], ["pcmux"])

    def test_annotation_after_bracket_or_paren(self):
        got = self.parse_src("// see (@pcmux) and [@npc_mux]\n")
        self.assertEqual(sorted(r.name for r in got.references),
                         ["npc_mux", "pcmux"])

    def test_plain_indexing_is_not_a_hardware_ref(self):
        got = self.parse_src("// @comb:thing  reads arr[i] and bus[31:0]\n")
        self.assertEqual([h.name for h in got.hardware], [])

    def test_real_hardware_ref_still_found(self):
        got = self.parse_src("// @comb:thing  uses [pc] and [reset_q]\n")
        self.assertEqual(sorted(h.name for h in got.hardware), ["pc", "reset_q"])

    def test_definition_still_found_after_a_leading_star(self):
        got = self.parse_src("/*\n * @seq:pc_reg  the counter\n */\n")
        self.assertEqual([d.name for d in got.definitions], ["pc_reg"])


class TestGrammarRegexes(unittest.TestCase):
    def test_category_must_be_lowercase(self):
        self.assertIsNotNone(DEF_LINE_RE.match("@mux:pcmux  text"))
        self.assertIsNone(DEF_LINE_RE.match("@Mux:pcmux  text"))
        self.assertIsNone(DEF_LINE_RE.match("@1mux:pcmux  text"))

    def test_name_charset(self):
        self.assertIsNotNone(DEF_LINE_RE.match("@wire:_under_ok  x"))
        self.assertIsNone(DEF_LINE_RE.match("@wire:9bad  x"))

    def test_no_space_required_around_colon(self):
        m = DEF_LINE_RE.match("@mux:pcmux")
        self.assertEqual(m.group("name"), "pcmux")
        self.assertEqual(m.group("rest"), "")


if __name__ == "__main__":
    unittest.main()
