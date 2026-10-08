"""The annotation language.

Annotations live **only in comments**, which is what keeps this tool free of any
SystemVerilog parsing obligation for its core feature.

Grammar
-------

::

    // @mux:pcmux    selects npc from reset, pc+4 and @br_target; driven by [pc]
    always_comb begin ... end

    // see @pcmux for the redirect logic

===========================  ==================================================
``@<category>:<name> text``  **definition**.  Must be the first token of the
                             comment.  Category is required.
``@<name>``                  **reference**, anywhere else in any comment.
``[<identifier>]``           optional **hardware reference**; checked against
                             the Verilog identifiers in the file.  Only
                             honoured inside comments that contain an ``@``,
                             so prose like ``[see below]`` is ignored.
===========================  ==================================================

Because a definition requires the colon, a bare ``@name`` at the start of a
comment is unambiguously a *reference*.  A bare ``@name`` at the start that is
nowhere defined is reported as ``missing-category`` -- that is almost always
someone writing a definition out of habit.

Categories are lowercase identifiers, e.g. ``mux``, ``seq``, ``comb``, ``alu``,
``decoder``, ``reg``, ``wire``, ``module``, ``func``, ``instance``, ``const``.
They are free-form; the outline maps the common ones to LSP symbol kinds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .lexer import Comment, Scan, comment_body_lines

# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------
# @category:name  <description>
DEF_RE = re.compile(r"@([a-z][a-z0-9_]*):([A-Za-z_]\w*)(?![A-Za-z0-9_])")

# @name  (reference, or a definition that forgot its category)
REF_RE = re.compile(r"@([A-Za-z_]\w*)")

# [identifier]  (hardware reference)
HW_RE = re.compile(r"\[([A-Za-z_]\w*)\]")

CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# A whole first line that is exactly a definition, used to grab the description.
DEF_LINE_RE = re.compile(
    r"^@(?P<category>[a-z][a-z0-9_]*):(?P<name>[A-Za-z_]\w*)(?![A-Za-z0-9_])\s*(?P<rest>.*)$"
)
BARE_LINE_RE = re.compile(r"^@(?P<name>[A-Za-z_]\w*)(?![A-Za-z0-9_:])\s*(?P<rest>.*)$")


def _is_annotation_at(text: str, idx: int) -> bool:
    """True if the ``@`` at ``idx`` introduces an annotation.

    Guards against email addresses and the like: in ``claire@yosyshq.com`` the
    ``@`` is preceded by a word character, so it is not an annotation.  Every
    file in this repository carries a copyright header with an email address in
    it, so without this check every file reports a bogus undefined reference.
    """
    if idx <= 0:
        return True
    prev = text[idx - 1]
    return not (prev.isalnum() or prev == "_")


def _is_bracket_ref_at(text: str, idx: int) -> bool:
    """Same idea for ``[identifier]``: ``arr[i]`` is indexing, not a reference."""
    if idx <= 0:
        return True
    prev = text[idx - 1]
    return not (prev.isalnum() or prev == "_" or prev == "]")


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Definition:
    name: str
    category: str
    description: str
    comment: Comment
    offset: int                 # offset of the "@" of the annotation token
    end_offset: int             # just past "<category>:<name>"
    line: int                   # 0-based
    col: int                    # 0-based
    comment_line: int           # index of the annotation line inside the comment

    @property
    def key(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        return f"{self.category}:{self.name}"


@dataclass(frozen=True)
class Reference:
    name: str
    comment: Comment
    offset: int
    end_offset: int
    line: int
    col: int


@dataclass(frozen=True)
class HardwareRef:
    name: str
    comment: Comment
    offset: int
    end_offset: int
    line: int
    col: int


@dataclass(frozen=True)
class Malformed:
    text: str
    comment: Comment
    offset: int
    line: int
    col: int
    message: str


@dataclass
class AnnotationSet:
    definitions: list[Definition] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    hardware: list[HardwareRef] = field(default_factory=list)
    malformed: list[Malformed] = field(default_factory=list)
    # bare "@name" at the start of a comment: a reference, unless the name is
    # nowhere defined -- then it is probably a definition missing its category.
    bare_at_start: list[Reference] = field(default_factory=list)

    def definition_named(self, name: str) -> Definition | None:
        for d in self.definitions:
            if d.name == name:
                return d
        return None

    @property
    def names(self) -> list[str]:
        return [d.name for d in self.definitions]


# ---------------------------------------------------------------------------
# offset helpers
# ---------------------------------------------------------------------------
def _line_offsets(comment: Comment) -> list[int]:
    """Absolute offset of the start of each line of the comment's inner text."""
    base = comment.start + 2
    offs: list[int] = []
    pos = base
    for ln in comment.text.split("\n"):
        offs.append(pos)
        pos += len(ln) + 1
    return offs


def _abs_offset(comment: Comment, text_index: int) -> int:
    """Map an index within ``comment.text`` to an absolute source offset."""
    offs = _line_offsets(comment)
    remaining = text_index
    for line_no, raw in enumerate(comment.text.split("\n")):
        if remaining <= len(raw):
            return offs[line_no] + remaining
        remaining -= len(raw) + 1
    return offs[-1]


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def parse_comment(comment: Comment, lines) -> tuple[
        Definition | None, list[Reference], list[HardwareRef],
        list[Malformed], Reference | None]:
    """Parse one comment.  Returns (definition, refs, hw, malformed, bare_at_start)."""
    body_lines = comment_body_lines(comment)
    raw_lines = comment.text.split("\n")

    # First non-empty line is the only place a definition may appear.
    first_idx: int | None = None
    for k, s in enumerate(body_lines):
        if s:
            first_idx = k
            break

    definition: Definition | None = None
    bare: Reference | None = None
    occupied: list[tuple[int, int]] = []       # (start, end) within comment.text
    malformed: list[Malformed] = []

    if first_idx is not None:
        cleaned = body_lines[first_idx]
        raw_line = raw_lines[first_idx] if first_idx < len(raw_lines) else ""
        # Offset of this line's start, in comment.text coordinates.
        line_text_start = sum(len(l) + 1 for l in raw_lines[:first_idx])

        m = DEF_LINE_RE.match(cleaned)
        if m:
            name = m.group("name")
            category = m.group("category")
            # Rest of the description may continue on later comment lines.
            rest = [m.group("rest").strip()]
            for cont in body_lines[first_idx + 1:]:
                if cont:
                    rest.append(cont)
            description = " ".join(x for x in rest if x).strip()

            # locate the "@" of the definition inside the raw line
            at_in_line = raw_line.find("@" + category + ":" + name)
            if at_in_line < 0:
                at_in_line = raw_line.find("@")
            text_index = line_text_start + max(at_in_line, 0)
            offset = _abs_offset(comment, text_index)
            end_offset = offset + 1 + len(category) + 1 + len(name)
            line, col = lines.line_col(offset)
            definition = Definition(name, category, description, comment,
                                    offset, end_offset, line, col, first_idx)
            occupied.append((offset, end_offset))
        else:
            # A colon form that failed to match is almost always a bad category
            # (uppercase, digits first, punctuation) -- say so specifically
            # rather than letting it fall through as a bare reference.
            mc = re.match(r"^@(?P<cat>[^:\s]+):(?P<name>[A-Za-z_]\w*)", cleaned)
            mb = BARE_LINE_RE.match(cleaned)
            if mc:
                at_in_line = raw_line.find("@")
                offset = _abs_offset(comment, line_text_start + max(at_in_line, 0))
                line, col = lines.line_col(offset)
                end = offset + 1 + len(mc.group("cat")) + 1 + len(mc.group("name"))
                malformed.append(Malformed(
                    cleaned, comment, offset, line, col,
                    f"category `{mc.group('cat')}` must match [a-z][a-z0-9_]*; "
                    f"try `@{mc.group('cat').lower()}:{mc.group('name')}`"))
                occupied.append((offset, end))
            elif mb:
                at_in_line = raw_line.find("@" + mb.group("name"))
                text_index = line_text_start + max(at_in_line, 0)
                offset = _abs_offset(comment, text_index)
                name = mb.group("name")
                end_offset = offset + 1 + len(name)
                line, col = lines.line_col(offset)
                bare = Reference(name, comment, offset, end_offset, line, col)
                occupied.append((offset, end_offset))

    # ---- references: every other @name in the comment ----
    refs: list[Reference] = []
    for m in REF_RE.finditer(comment.text):
        if not _is_annotation_at(comment.text, m.start()):
            continue
        start, end = m.start(), m.end()
        abs_start = _abs_offset(comment, start)
        abs_end = _abs_offset(comment, end)
        if any(abs_start < o_end and o_start < abs_end for o_start, o_end in occupied):
            continue
        line, col = lines.line_col(abs_start)
        refs.append(Reference(m.group(1), comment, abs_start, abs_end, line, col))

    # ---- hardware references, only where an @ annotation is present ----
    hw: list[HardwareRef] = []
    if comment.text.find("@") >= 0:
        for m in HW_RE.finditer(comment.text):
            if not _is_bracket_ref_at(comment.text, m.start()):
                continue
            abs_start = _abs_offset(comment, m.start())
            abs_end = _abs_offset(comment, m.end())
            line, col = lines.line_col(abs_start)
            hw.append(HardwareRef(m.group(1), comment, abs_start, abs_end, line, col))

    # ---- malformed: an '@' that starts nothing recognisable ----
    for m in re.finditer(r"@", comment.text):
        if not _is_annotation_at(comment.text, m.start()):
            continue
        nxt = comment.text[m.end():m.end() + 1]
        if nxt and (nxt.isalpha() or nxt == "_"):
            continue                      # handled as @name or @cat:name
        abs_off = _abs_offset(comment, m.start())
        line, col = lines.line_col(abs_off)
        snippet = comment_body_lines(comment)[0][:48] if body_lines else ""
        malformed.append(Malformed(
            snippet, comment, abs_off, line, col,
            "`@` must be followed by a name, or `category:name` for a definition",
        ))

    # A definition whose category is not lowercase is caught above; anything
    # still bare at the start of a comment is a reference (or a definition that
    # forgot its category entirely, reported as `missing-category`).
    return definition, refs, hw, malformed, bare


def parse(scan_result: Scan) -> AnnotationSet:
    """Parse every comment in a scanned file."""
    out = AnnotationSet()
    for comment in scan_result.comments:
        d, refs, hw, bad, bare = parse_comment(comment, scan_result.lines)
        if d:
            out.definitions.append(d)
        out.references.extend(refs)
        out.hardware.extend(hw)
        out.malformed.extend(bad)
        if bare:
            out.bare_at_start.append(bare)
    return out
