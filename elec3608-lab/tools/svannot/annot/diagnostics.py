"""Diagnostics for annotations.

Each rule produces an LSP-shaped diagnostic (0-based line/character range) so
the publisher layer stays trivial.

Severities follow the LSP: 1 Error, 2 Warning, 3 Information, 4 Hint.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .index import FileIndex, WorkspaceIndex

ERROR, WARNING, INFORMATION, HINT = 1, 2, 3, 4

SOURCE = "svannot"

# Component-ish blocks that are expected to carry an annotation when the
# `unannotated-blocks` hint is enabled.
COMPONENT_KINDS = ("always_comb", "always_ff", "always_latch", "always",
                   "function", "task", "assign", "initial", "final")


@dataclass
class Diagnostic:
    line: int
    col: int
    end_line: int
    end_col: int
    severity: int
    code: str
    message: str

    def to_lsp(self) -> dict:
        return {
            "range": {
                "start": {"line": self.line, "character": self.col},
                "end": {"line": self.end_line, "character": self.end_col},
            },
            "severity": self.severity,
            "code": self.code,
            "source": SOURCE,
            "message": self.message,
        }


@dataclass
class Options:
    """Which rules are enabled.  Mirrors the `initializationOptions` the client
    may send; see server.py."""
    unannotated_blocks: bool = False
    unknown_identifiers: bool = True
    undefined_references: bool = True
    duplicate_definitions: bool = True


def _range(fi: FileIndex, start: int, end: int) -> tuple[int, int, int, int]:
    sl, sc = fi.scan.lines.line_col(start)
    el, ec = fi.scan.lines.line_col(end)
    return sl, sc, el, ec


def compute(fi: FileIndex, ws: WorkspaceIndex,
            options: Options | None = None) -> list[Diagnostic]:
    """All diagnostics for one file."""
    opts = options or Options()
    out: list[Diagnostic] = []

    # ---- 1. malformed annotations -------------------------------------------
    for bad in fi.annotations.malformed:
        out.append(Diagnostic(bad.line, bad.col, bad.line, bad.col + 1,
                              WARNING, "bad-annotation", bad.message))

    # ---- 2. duplicate definitions -------------------------------------------
    if opts.duplicate_definitions:
        dupes = ws.duplicate_names()
        for bd in fi.bound:
            name = bd.definition.name
            all_locs = dupes.get(name, [])
            if len(all_locs) < 2:
                continue
            here = (fi.path, bd.definition.offset)
            others = [loc for loc in all_locs
                      if (loc.path, loc.definition.offset) != here]
            if not others:
                continue
            d = bd.definition
            where = ", ".join(sorted({
                f"{os.path.basename(loc.path)}:{loc.definition.line + 1}"
                for loc in others}))
            out.append(Diagnostic(
                d.line, d.col, d.line, d.col + len(d.label) + 1, ERROR,
                "duplicate-definition",
                f"`@{name}` is also defined at {where}; "
                "references will resolve to only one of them"))

    # ---- 3. undefined references --------------------------------------------
    if opts.undefined_references:
        for r in fi.annotations.references:
            if ws.resolve(r.name, prefer_path=fi.path):
                continue
            sl, sc, el, ec = _range(fi, r.offset, r.end_offset)
            out.append(Diagnostic(
                sl, sc, el, ec, WARNING, "undefined-reference",
                f"`@{r.name}` is not defined in any indexed file"))

    # ---- 4. bare @name at the start of a comment ----------------------------
    #  A bare token at the start is a *reference* by the grammar.  If the name
    #  is nowhere defined it is nearly always a definition missing a category.
    for r in fi.annotations.bare_at_start:
        if ws.resolve(r.name, prefer_path=fi.path):
            continue
        sl, sc, el, ec = _range(fi, r.offset, r.end_offset)
        out.append(Diagnostic(
            sl, sc, el, ec, INFORMATION, "missing-category",
            f"`@{r.name}` is not defined anywhere.  If you meant to define it, "
            f"a category is required, e.g. `@mux:{r.name} ...`"))

    # ---- 5. unknown identifiers in [brackets] -------------------------------
    if opts.unknown_identifiers:
        defined_elsewhere = set(ws.all_names())
        for h in fi.annotations.hardware:
            if h.name in fi.identifiers or h.name in defined_elsewhere:
                continue
            sl, sc, el, ec = _range(fi, h.offset, h.end_offset)
            out.append(Diagnostic(
                sl, sc, el, ec, WARNING, "unknown-identifier",
                f"`[{h.name}]` does not name a signal declared in this file"))

    # ---- 6. scanner could not make sense of the file ------------------------
    for w in fi.block_scan.warnings:
        line = 0
        col = 0
        out.append(Diagnostic(line, col, line, col + 1, INFORMATION,
                              "parse-warning",
                              f"{w}; annotations fall back to module scope"))

    # ---- 7. blocks with no annotation ---------------------------------------
    if opts.unannotated_blocks:
        annotated = {id(bd.block) for bd in fi.bound if bd.block is not None}
        for blk in fi.block_scan.all_blocks():
            if blk.kind not in COMPONENT_KINDS or id(blk) in annotated:
                continue
            out.append(Diagnostic(
                blk.start_line, 0, blk.start_line, 1, HINT, "unannotated-block",
                f"this {blk.label} has no @category:name annotation"))

    out.sort(key=lambda d: (d.line, d.col))
    return out
