"""Lightweight SystemVerilog block scanner.

Annotations only ever live in comments, so a full SystemVerilog parser is not
needed -- but an annotation has to know *which* block it describes, and that
requires block extents.

This scanner finds the constructs that correspond to "a component" in the sense
the project uses the word: ``module``, ``always_comb`` / ``always_ff`` /
``always_latch`` / ``always``, ``function``, ``task``, ``generate``,
``interface``, ``package``, ``initial`` / ``final``, and ``assign``.

It works on the *masked* text from :mod:`annot.lexer`, so keywords appearing in
comments or strings are already blanked out and cannot create phantom blocks.

Deliberately not a parser: it does not build an AST and does not resolve
hierarchy.  If it ever loses sync it says so (see :attr:`ScanResult.warnings`)
and callers fall back to module scope.

Upgrade path if this proves too fragile: parse with
``tree-sitter-systemverilog`` (the grammar Zed itself uses).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Keywords that open a construct terminated by a matching keyword.
PAIRED: dict[str, str] = {
    "module": "endmodule",
    "interface": "endinterface",
    "package": "endpackage",
    "program": "endprogram",
    "function": "endfunction",
    "task": "endtask",
    "generate": "endgenerate",
    "specify": "endspecify",
    "checker": "endchecker",
    "class": "endclass",
}

# Procedural blocks whose extent is a single statement.
PROCEDURAL = ("always_comb", "always_ff", "always_latch", "always", "initial", "final")

# Tokens that open/close a nesting level when matching begin..end.
_OPENERS = {"begin", "case", "casex", "casez", "fork"}
_CLOSERS = {"end", "endcase", "join", "join_any", "join_none"}

_IDENT = re.compile(r"[A-Za-z_]\w*")

# Words that may sit between a construct keyword and the real name.
_LIFETIME = {"automatic", "static"}


@dataclass
class Block:
    kind: str                       # "module", "always_comb", "function", ...
    name: str | None
    start: int                      # offset of the keyword
    end: int                        # offset just past the construct
    start_line: int
    end_line: int
    parent: "Block | None" = None
    children: list["Block"] = field(default_factory=list)

    # ---- convenience ----
    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)

    @property
    def is_container(self) -> bool:
        """True for constructs that *hold* components rather than being one.

        A comment inside a module is technically "inside" the module, but the
        module is not what it is annotating -- so binding prefers a real
        component and only falls back to the container.
        """
        return self.kind in ("module", "interface", "package", "program",
                             "generate", "class", "checker")

    def contains_line(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line

    def path(self) -> str:
        """Human-readable nesting path, e.g. ``nerv/always_comb#3``."""
        parts: list[str] = []
        node: Block | None = self
        while node is not None:
            parts.append(node.label)
            node = node.parent
        return "/".join(reversed(parts))

    @property
    def label(self) -> str:
        if self.name:
            return f"{self.kind} {self.name}"
        return self.kind


@dataclass
class ScanResult:
    blocks: list[Block]                     # top level (usually one module)
    warnings: list[str] = field(default_factory=list)

    def all_blocks(self) -> list[Block]:
        out: list[Block] = []

        def walk(b: Block) -> None:
            out.append(b)
            for c in b.children:
                walk(c)

        for b in self.blocks:
            walk(b)
        return out

    def innermost_at(self, line: int) -> Block | None:
        """Deepest block whose line span contains ``line``."""
        best: Block | None = None
        for b in self.all_blocks():
            if b.contains_line(line):
                if best is None or (b.end - b.start) <= (best.end - best.start):
                    best = b
        return best

    def enclosing_at(self, line: int) -> list[Block]:
        """Blocks containing ``line``, innermost first."""
        hits = [b for b in self.all_blocks() if b.contains_line(line)]
        hits.sort(key=lambda b: b.end - b.start)
        return hits

    def next_block_starting_after(self, line: int, within: int = 3) -> Block | None:
        """The first block that starts on ``line`` or up to ``within`` lines
        later -- used to attach a comment written *above* a block."""
        cands = [b for b in self.all_blocks() if line < b.start_line <= line + within]
        if not cands:
            return None
        cands.sort(key=lambda b: b.start_line)
        return cands[0]

    def outermost_module(self) -> Block | None:
        for b in self.blocks:
            if b.kind == "module":
                return b
        return None


# --------------------------------------------------------------------------
# helpers over the masked text
# --------------------------------------------------------------------------
def _skip_ws(s: str, i: int) -> int:
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    return i


def _iter_idents(s: str, start: int, end: int | None = None):
    """Yield (token, offset) for identifier-like tokens."""
    stop = len(s) if end is None else end
    for m in _IDENT.finditer(s, start, stop):
        yield m.group(0), m.start(), m.end()


def _match_block_end(s: str, i: int) -> int:
    """``s[i:]`` begins at ``begin``/``case``/``fork``. Return the offset just
    past its matching closer."""
    depth = 0
    for tok, _start, end in _iter_idents(s, i):
        if tok in _OPENERS:
            depth += 1
        elif tok in _CLOSERS:
            depth -= 1
            if depth <= 0:
                return end
    return len(s)


def _match_paired(s: str, i: int, opener: str, closer: str) -> int:
    """Nesting-aware match for ``module``/``endmodule`` style pairs."""
    depth = 0
    for tok, _start, end in _iter_idents(s, i):
        if tok == opener:
            depth += 1
        elif tok == closer:
            depth -= 1
            if depth <= 0:
                return end
    return len(s)


def _statement_end(s: str, i: int) -> int:
    """Offset just past the next ``;`` at bracket depth zero."""
    depth = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == ";" and depth == 0:
            return i + 1
        i += 1
    return n


def _skip_sensitivity(s: str, i: int) -> int:
    """Skip an ``@(...)`` or ``@*`` sensitivity list."""
    i = _skip_ws(s, i)
    if i < len(s) and s[i] == "@":
        i += 1
        i = _skip_ws(s, i)
        if i < len(s) and s[i] == "(":
            depth = 0
            while i < len(s):
                if s[i] == "(":
                    depth += 1
                elif s[i] == ")":
                    depth -= 1
                    if depth == 0:
                        return i + 1
                i += 1
        elif i < len(s) and s[i] == "*":
            return i + 1
    return i


def _name_after(s: str, i: int) -> tuple[str | None, int]:
    """First identifier at/after ``i``, skipping lifetime qualifiers."""
    i = _skip_ws(s, i)
    while True:
        m = _IDENT.match(s, i)
        if not m:
            return None, i
        if m.group(0) in _LIFETIME:
            i = _skip_ws(s, m.end())
            continue
        return m.group(0), m.end()


def _function_name(s: str, i: int) -> str | None:
    """``function automatic [31:0] foo(...)`` -- the identifier before ``(``."""
    end = _statement_end(s, i)
    head = s[i:end]
    paren = head.find("(")
    if paren == -1:
        return None
    before = head[:paren]
    names = _IDENT.findall(before)
    return names[-1] if names else None


# --------------------------------------------------------------------------
# main scan
# --------------------------------------------------------------------------
def scan_blocks(masked: str, lines) -> ScanResult:
    """Find every block in ``masked``.

    ``lines`` is a :class:`annot.lexer.LineIndex` for offset -> line mapping.
    """
    warnings: list[str] = []
    found: list[Block] = []

    tokens = list(_iter_idents(masked, 0))
    idx = 0
    while idx < len(tokens):
        tok, start, end = tokens[idx]

        if tok in PAIRED:
            closer = PAIRED[tok]
            stop = _match_paired(masked, start, tok, closer)
            if stop >= len(masked):
                warnings.append(f"unterminated `{tok}` near line {lines.line_col(start)[0] + 1}")
            name: str | None = None
            if tok in ("module", "interface", "package", "program"):
                name, _ = _name_after(masked, end)
            elif tok in ("function", "task"):
                name = _function_name(masked, end)
            sl, _ = lines.line_col(start)
            el, _ = lines.line_col(max(start, stop - 1))
            found.append(Block(tok, name, start, stop, sl, el))
            idx += 1
            continue

        if tok in PROCEDURAL:
            pos = _skip_sensitivity(masked, end)
            pos = _skip_ws(masked, pos)
            if masked.startswith("begin", pos):
                stop = _match_block_end(masked, pos)
            else:
                stop = _statement_end(masked, pos)
            sl, _ = lines.line_col(start)
            el, _ = lines.line_col(max(start, stop - 1))
            found.append(Block(tok, None, start, stop, sl, el))
            idx += 1
            continue

        if tok == "assign":
            stop = _statement_end(masked, end)
            sl, _ = lines.line_col(start)
            el, _ = lines.line_col(max(start, stop - 1))
            found.append(Block("assign", None, start, stop, sl, el))
            idx += 1
            continue

        idx += 1

    # ---- nest by containment ----
    found.sort(key=lambda b: (b.start, -b.end))
    top: list[Block] = []
    stack: list[Block] = []
    for b in found:
        while stack and not (stack[-1].start <= b.start and b.end <= stack[-1].end):
            stack.pop()
        if stack:
            b.parent = stack[-1]
            stack[-1].children.append(b)
        else:
            top.append(b)
        stack.append(b)

    for b in found:
        if b.kind == "always" and b.name is None and b.end - b.start < 4:
            warnings.append(f"degenerate `always` near line {b.start_line + 1}")

    return ScanResult(top, warnings)


# --------------------------------------------------------------------------
# category fallback
# --------------------------------------------------------------------------
BLOCK_DESCRIPTION: dict[str, str] = {
    "module": "module",
    "interface": "interface",
    "package": "package",
    "program": "program",
    "function": "function",
    "task": "task",
    "generate": "generate region",
    "specify": "specify block",
    "checker": "checker",
    "class": "class",
    "always_comb": "combinational block",
    "always_ff": "sequential block",
    "always_latch": "latch block",
    "always": "procedural block",
    "initial": "initial block",
    "final": "final block",
    "assign": "continuous assignment",
}


def describe(kind: str) -> str:
    return BLOCK_DESCRIPTION.get(kind, kind)
