"""Server tests: LSP framing, handlers, diagnostics, and block binding."""
from __future__ import annotations

import io
import unittest

from annot import diagnostics as diag
from annot.index import WorkspaceIndex, path_to_uri, uri_to_path
from annot.lsp import (LspError, make_notification, make_response, read_message,
                       serve, write_message)
from annot.server import AnnotServer, symbol_kind

from . import common


def booted(*fixtures: str):
    """A server initialised over the fixture directory."""
    s = AnnotServer()
    s.handle_request("initialize", {"rootUri": path_to_uri(str(common.FIXTURES))})
    return s


def pos_of(fi, predicate):
    """First offset matching predicate, as an LSP position."""
    for r in fi.annotations.references:
        if predicate(r):
            return {"line": r.line, "character": r.col}
    raise AssertionError("no matching reference")


class TestLspFraming(unittest.TestCase):
    def test_roundtrip(self):
        buf = io.BytesIO()
        write_message(buf, {"jsonrpc": "2.0", "id": 1, "method": "x"})
        buf.seek(0)
        self.assertEqual(read_message(buf), {"jsonrpc": "2.0", "id": 1, "method": "x"})

    def test_eof_returns_none(self):
        self.assertIsNone(read_message(io.BytesIO(b"")))

    def test_missing_content_length_is_an_error(self):
        with self.assertRaises(LspError):
            read_message(io.BytesIO(b"X: 1\r\n\r\n{}"))

    def test_unicode_payload(self):
        buf = io.BytesIO()
        write_message(buf, {"m": "café — ünïcode"})
        buf.seek(0)
        self.assertEqual(read_message(buf)["m"], "café — ünïcode")

    def test_helpers(self):
        self.assertEqual(make_response(1, None)["id"], 1)
        self.assertEqual(make_notification("m", {})["method"], "m")


class TestLifecycle(unittest.TestCase):
    def test_initialize_capabilities(self):
        s = AnnotServer()
        res = s.handle_request("initialize", {"rootUri": path_to_uri(str(common.FIXTURES))})
        caps = res["capabilities"]
        for key in ("documentSymbolProvider", "definitionProvider",
                    "referencesProvider", "hoverProvider",
                    "workspaceSymbolProvider", "completionProvider"):
            self.assertTrue(caps[key], key)
        self.assertEqual(caps["textDocumentSync"]["change"], 1)   # Full
        self.assertIn("@", caps["completionProvider"]["triggerCharacters"])
        self.assertEqual(res["serverInfo"]["name"], "svannot")

    def test_initialize_creates_no_document_symbols_for_unreadable_root(self):
        s = AnnotServer()
        s.handle_request("initialize", {"rootUri": "file:///does/not/exist"})
        self.assertEqual(s.ws.files, {})

    def test_unknown_request_raises_method_not_found(self):
        with self.assertRaises(LspError):
            AnnotServer().handle_request("textDocument/nonsense", {})

    def test_didopen_indexes_and_publishes(self):
        s = AnnotServer()
        uri = common.uri("good.sv")
        s.handle_notification("textDocument/didOpen", {
            "textDocument": {"uri": uri, "text": common.load("good.sv")}})
        out = s.drain()
        self.assertEqual(out[0]["method"], "textDocument/publishDiagnostics")
        self.assertIn(uri_to_path(uri), s.ws.files)

    def test_didchange_updates_the_buffer(self):
        s = AnnotServer()
        uri = common.uri("good.sv")
        s.handle_notification("textDocument/didOpen", {
            "textDocument": {"uri": uri, "text": "module m;\nendmodule\n"}})
        self.assertIn("module m;", s.ws.files[uri_to_path(uri)].text)
        s.handle_notification("textDocument/didChange", {
            "textDocument": {"uri": uri},
            "contentChanges": [{"text": "// @comb:changed\nmodule m;\nendmodule\n"}]})
        self.assertEqual([d.name for d in
                          s.ws.files[uri_to_path(uri)].annotations.definitions],
                         ["changed"])

    def test_didclose_clears_diagnostics(self):
        s = AnnotServer()
        uri = common.uri("good.sv")
        s.handle_notification("textDocument/didOpen", {
            "textDocument": {"uri": uri, "text": common.load("good.sv")}})
        s.drain()
        s.handle_notification("textDocument/didClose", {"textDocument": {"uri": uri}})
        out = s.drain()
        self.assertEqual(out[-1]["params"]["diagnostics"], [])

    def test_exit_stops_the_loop(self):
        self.assertFalse(AnnotServer().handle_notification("exit", {}))

    def test_serve_returns_on_eof(self):
        self.assertEqual(serve(AnnotServer(), io.BytesIO(b""), io.BytesIO()), 0)


class TestDocumentSymbols(unittest.TestCase):
    def setUp(self):
        self.s = booted("good.sv")
        self.uri = common.uri("good.sv")
        self.syms = self.s.handle_request(
            "textDocument/documentSymbol", {"textDocument": {"uri": self.uri}})

    def test_single_root_module(self):
        self.assertEqual(len(self.syms), 1)
        self.assertEqual(self.syms[0]["name"], "module:nerv")
        self.assertEqual(self.syms[0]["kind"], 2)          # Module

    def test_components_are_nested_under_the_module(self):
        kids = [c["name"] for c in self.syms[0]["children"]]
        self.assertEqual(kids, ["mux:pcmux", "seq:pc_reg", "func:decode_insn",
                                "wire:br_target", "alu:adder"])

    def test_symbol_kinds_follow_the_category(self):
        kids = {c["name"]: c["kind"] for c in self.syms[0]["children"]}
        self.assertEqual(kids["mux:pcmux"], 12)            # Function
        self.assertEqual(kids["seq:pc_reg"], 13)           # Variable
        self.assertEqual(kids["wire:br_target"], 8)        # Field

    def test_detail_carries_the_annotation_text(self):
        pcmux = self.syms[0]["children"][0]
        self.assertIn("selects npc", pcmux["detail"])

    def test_selection_range_is_inside_range(self):
        for c in self.syms[0]["children"]:
            self.assertGreaterEqual(c["selectionRange"]["start"]["line"],
                                    c["range"]["start"]["line"])
            self.assertLessEqual(c["selectionRange"]["start"]["line"],
                                 c["range"]["end"]["line"])

    def test_category_in_name_means_outline_shows_it(self):
        # the outline label carries the category even though LSP kinds are a
        # fixed enum -- this is why the tag is mandatory
        for c in self.syms[0]["children"]:
            self.assertIn(":", c["name"])

    def test_symbol_kind_mapping(self):
        self.assertEqual(symbol_kind("mux"), 12)
        self.assertEqual(symbol_kind("unknowncat"), 13)    # generic fallback
        self.assertEqual(symbol_kind("unknowncat", "module"), 2)


class TestNavigation(unittest.TestCase):
    def setUp(self):
        self.s = booted("good.sv")
        self.uri = common.uri("good.sv")
        self.fi = self.s.ws.files[uri_to_path(self.uri)]

    def test_definition_from_a_reference(self):
        p = pos_of(self.fi, lambda r: r.name == "pcmux" and r.line > 40)
        res = self.s.handle_request("textDocument/definition",
                                    {"textDocument": {"uri": self.uri}, "position": p})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["range"]["start"]["line"] + 1, 16)

    def test_definition_from_the_definition_itself(self):
        d = self.fi.by_name["pcmux"].definition
        res = self.s.handle_request("textDocument/definition", {
            "textDocument": {"uri": self.uri},
            "position": {"line": d.line, "character": d.col + 2}})
        self.assertEqual(res[0]["range"]["start"]["line"] + 1, 16)

    def test_definition_of_an_undefined_reference_is_none(self):
        p = pos_of(self.fi, lambda r: r.name == "does_not_exist")
        res = self.s.handle_request("textDocument/definition",
                                    {"textDocument": {"uri": self.uri}, "position": p})
        self.assertIsNone(res)

    def test_references_include_declaration(self):
        p = pos_of(self.fi, lambda r: r.name == "pcmux")
        res = self.s.handle_request("textDocument/references", {
            "textDocument": {"uri": self.uri}, "position": p,
            "context": {"includeDeclaration": True}})
        self.assertEqual(len(res), 5)      # 1 definition + 4 references

    def test_references_exclude_declaration(self):
        p = pos_of(self.fi, lambda r: r.name == "pcmux")
        res = self.s.handle_request("textDocument/references", {
            "textDocument": {"uri": self.uri}, "position": p,
            "context": {"includeDeclaration": False}})
        self.assertEqual(len(res), 4)

    def test_hover_on_definition(self):
        d = self.fi.by_name["pcmux"].definition
        h = self.s.handle_request("textDocument/hover", {
            "textDocument": {"uri": self.uri},
            "position": {"line": d.line, "character": d.col + 2}})
        md = h["contents"]["value"]
        self.assertIn("@mux:pcmux", md)
        self.assertIn("selects npc", md)
        self.assertIn("always_comb", md)

    def test_hover_on_undefined_reference_says_so(self):
        p = pos_of(self.fi, lambda r: r.name == "does_not_exist")
        h = self.s.handle_request("textDocument/hover",
                                  {"textDocument": {"uri": self.uri}, "position": p})
        self.assertIn("undefined", h["contents"]["value"])

    def test_hover_on_nothing(self):
        h = self.s.handle_request("textDocument/hover", {
            "textDocument": {"uri": self.uri},
            "position": {"line": 0, "character": 0}})
        self.assertIsNone(h)

    def test_definition_of_a_hardware_reference(self):
        fi = self.fi
        hw = [h for h in fi.annotations.hardware if h.name == "pc"][0]
        res = self.s.handle_request("textDocument/definition", {
            "textDocument": {"uri": self.uri},
            "position": {"line": hw.line, "character": hw.col + 1}})
        self.assertIsNotNone(res)

    def test_completion_lists_every_name_and_a_template(self):
        c = self.s.handle_request("textDocument/completion",
                                  {"textDocument": {"uri": self.uri},
                                   "position": {"line": 0, "character": 0}})
        labels = [i["label"] for i in c["items"]]
        for name in ("pcmux", "pc_reg", "decode_insn", "br_target", "adder", "nerv"):
            self.assertIn(name, labels)
        snippets = [i for i in c["items"] if i["kind"] == 15]
        self.assertEqual(len(snippets), 1)
        self.assertIn("@${1|", snippets[0]["insertText"])

    def test_workspace_symbol_filters(self):
        res = self.s.handle_request("workspace/symbol", {"query": "pcmux"})
        self.assertEqual([r["name"] for r in res], ["mux:pcmux"])
        res = self.s.handle_request("workspace/symbol", {"query": "no_such_thing"})
        self.assertEqual(res, [])
        res = self.s.handle_request("workspace/symbol", {"query": ""})
        self.assertGreaterEqual(len(res), 6)


class TestDiagnostics(unittest.TestCase):
    def codes(self, fixture: str, options=None) -> list[str]:
        ws = common.full_workspace()
        fi = ws.files[str(common.fixture(fixture))]
        return [d.code for d in diag.compute(fi, ws, options or diag.Options())]

    def test_no_structure_errors_in_good(self):
        self.assertEqual(self.codes("good.sv").count("duplicate-definition"), 0)
        self.assertEqual(self.codes("good.sv").count("bad-annotation"), 0)

    def test_undefined_reference(self):
        self.assertIn("undefined-reference", self.codes("undefined_ref.sv"))

    def test_duplicate_in_one_file(self):
        self.assertEqual(self.codes("duplicate.sv").count("duplicate-definition"), 2)

    def test_duplicate_across_files(self):
        self.assertIn("duplicate-definition", self.codes("duplicate_cross.sv"))
        self.assertIn("duplicate-definition", self.codes("duplicate_other.sv"))

    def test_missing_category(self):
        self.assertIn("missing-category", self.codes("missing_category.sv"))

    def test_malformed(self):
        self.assertEqual(self.codes("malformed_annotations.sv").count("bad-annotation"), 5)

    def test_unknown_identifier(self):
        self.assertIn("unknown-identifier", self.codes("good.sv"))

    def test_duplicate_disable_switch(self):
        opts = diag.Options(duplicate_definitions=False)
        self.assertNotIn("duplicate-definition", self.codes("duplicate.sv", opts))

    def test_unannotated_blocks_hint_is_off_by_default(self):
        self.assertNotIn("unannotated-block", self.codes("unannotated.sv"))

    def test_unannotated_blocks_hint_when_enabled(self):
        opts = diag.Options(unannotated_blocks=True)
        codes = self.codes("unannotated.sv", opts)
        self.assertEqual(codes.count("unannotated-block"), 1)

    def test_fully_annotated_file_has_no_hint(self):
        opts = diag.Options(unannotated_blocks=True)
        self.assertNotIn("unannotated-block", self.codes("good.sv", opts))

    def test_diagnostic_is_lsp_shaped(self):
        ws = common.full_workspace()
        fi = ws.files[str(common.fixture("good.sv"))]
        d = diag.compute(fi, ws, diag.Options())[0].to_lsp()
        self.assertEqual(set(d), {"range", "severity", "code", "source", "message"})
        self.assertEqual(set(d["range"]), {"start", "end"})
        self.assertEqual(d["source"], "svannot")

    def test_severities(self):
        ws = common.full_workspace()
        fi = ws.files[str(common.fixture("duplicate.sv"))]
        sev = {d.code: d.severity for d in diag.compute(fi, ws, diag.Options())}
        self.assertEqual(sev["duplicate-definition"], diag.ERROR)


class TestBlockBinding(unittest.TestCase):
    def test_each_annotation_binds_to_its_block(self):
        fi = common.index("good.sv")
        got = {bd.definition.name: (bd.block.kind if bd.block else None)
               for bd in fi.bound}
        self.assertEqual(got, {
            "nerv": "module",
            "pcmux": "always_comb",
            "pc_reg": "always_ff",
            "decode_insn": "function",
            "br_target": "assign",
            "adder": "always_comb",
        })

    def test_comment_above_a_block_binds_forward(self):
        # every annotation in good.sv sits above its block, not inside it
        fi = common.index("good.sv")
        for bd in fi.bound:
            if bd.definition.name == "nerv":
                continue
            self.assertIsNotNone(bd.block)
            self.assertGreaterEqual(bd.block.start_line, bd.definition.line)

    def test_annotation_inside_a_block_binds_to_it(self):
        fi = common.index("comment_edge_cases.sv")
        bd = fi.by_name["real_block"]
        self.assertEqual(bd.block.kind, "always_comb")
        self.assertLess(bd.definition.line, bd.block.end_line)

    def test_container_is_not_chosen_when_a_component_is_nearby(self):
        fi = common.index("nested_blocks.sv")
        for bd in fi.bound:
            if bd.definition.category == "module":
                continue
            self.assertFalse(bd.block.is_container,
                             f"{bd.definition.name} bound to a container")

    def test_workspace_resolution_prefers_the_current_file(self):
        ws = WorkspaceIndex()
        ws.index_path(str(common.fixture("duplicate.sv")))
        ws.index_path(str(common.fixture("duplicate_cross.sv")))
        loc = ws.resolve("shared", prefer_path=str(common.fixture("duplicate.sv")))
        self.assertTrue(loc.path.endswith("duplicate.sv"))


if __name__ == "__main__":
    unittest.main()
