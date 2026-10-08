"""Comment- and string-aware scanner for SystemVerilog source.

The annotation language lives entirely inside comments, but the *block*
structure has to be read from the code.  Both jobs need the same primitive:
a pass over the source that knows where comments and string literals are, so
that a word like ``end`` inside a comment or a ``"`` inside a string cannot
confuse anything downstream.

Produces:

* ``comments`` -- every comment with its offset range and inner text
* ``masked``   -- the source with comments and string bodies replaced by
                  spaces (newlines preserved), so offsets and line numbers in
                  the masked text still match the original

No third-party dependencies.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass


@dataclass(frozen=True)
class Comment:
    """A single ``//`` or ``/* */`` comment."""

    start: int          # offset of the opening delimiter
    end: int            # offset just past the closing delimiter
    text: str           # inner text, delimiters stripped
    kind: str           # "line" or "block"
    start_line: int     # 0-based
    end_line: int       # 0-based, inclusive
    start_col: int      # 0-based

    @property
    def is_line(self) -> bool:
        return self.kind == "line"


class LineIndex:
    """Offset <-> (line, column) conversion. Lines and columns are 0-based."""

    def __init__(self, src: str) -> None:
        self._starts = [0]
        for i, ch in enumerate(src):
            if ch == "\n":
                self._starts.append(i + 1)

    def line_col(self, offset: int) -> tuple[int, int]:
        line = bisect.bisect_right(self._starts, offset) - 1
        return line, offset - self._starts[line]

    def line_start(self, line: int) -> int:
        return self._starts[line]

    def offset(self, line: int, character: int) -> int:
        """Inverse of :meth:`line_col`, clamped to the file."""
        if line < 0:
            return 0
        if line >= len(self._starts):
            return self._starts[-1]
        return self._starts[line] + max(0, character)

    @property
    def line_count(self) -> int:
        return len(self._starts)


@dataclass
class Scan:
    src: str
    masked: str
    comments: list[Comment]
    lines: LineIndex

    def block_at(self, offset: int) -> Comment | None:
        """The comment containing ``offset``, if any."""
        for c in self.comments:
            if c.start <= offset < c.end:
                return c
        return None


def scan(src: str) -> Scan:
    """Scan ``src`` for comments and string literals."""
    lines = LineIndex(src)
    comments: list[Comment] = []
    # Work on a mutable list so masking never shifts offsets.
    out = list(src)
    n = len(src)
    i = 0

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]

        # ---- line comment ----
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            if j == -1:
                j = n
            sl, sc = lines.line_col(i)
            el, _ = lines.line_col(max(i, j - 1))
            comments.append(Comment(i, j, src[i + 2:j], "line", sl, el, sc))
            blank(i, j)
            i = j
            continue

        # ---- block comment ----
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            close = src.find("*/", i + 2)
            if close == -1:                      # unterminated: run to EOF
                end = n
                text = src[i + 2:]
            else:
                end = close + 2
                text = src[i + 2:close]
            sl, sc = lines.line_col(i)
            el, _ = lines.line_col(max(i, end - 1))
            comments.append(Comment(i, end, text, "block", sl, el, sc))
            blank(i, end)
            i = end
            continue

        # ---- string literal ----
        if c == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    j += 1
                    break
                j += 1
            blank(i, j)
            i = j
            continue

        i += 1

    return Scan(src, "".join(out), comments, lines)


def comment_body_lines(comment: Comment) -> list[str]:
    """The comment's text split into lines, with leading ``*`` decorations and
    whitespace stripped from each line.

    Block comments are conventionally written as::

        /*
         * @mux:pcmux  selects the next pc
         *             see @br_target
         */

    so every continuation line tends to start with ``*``.  Stripping that makes
    the annotation text readable in hover and completion output.
    """
    raw = comment.text.split("\n")
    cleaned: list[str] = []
    for idx, line in enumerate(raw):
        s = line.strip()
        if idx > 0 and s.startswith("*"):
            s = s[1:].strip()
        cleaned.append(s)
    return cleaned
