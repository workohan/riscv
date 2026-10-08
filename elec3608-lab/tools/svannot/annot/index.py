"""Per-file and workspace symbol index.

Combines the three lower layers:

    lexer    -> where the comments are
    blocks   -> where the Verilog constructs are
    grammar  -> what the annotations say

and answers the questions the LSP handlers need: what is defined here, what does
``@name`` point at, which block does an annotation describe, and what is
undefined.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from . import blocks as blocks_mod
from . import grammar
from .blocks import Block, ScanResult
from .grammar import AnnotationSet, Definition, HardwareRef, Malformed, Reference
from .lexer import Scan, scan

SV_SUFFIXES = (".sv", ".v", ".svh", ".vh")

# Where to attach a comment that sits outside every block.
LOOKAHEAD_LINES = 3

_IDENT = re.compile(r"[A-Za-z_]\w*")

# Words that are not useful as "hardware identifiers" for [bracket] checking.
_SV_KEYWORDS = frozenset("""
module endmodule input output inout wire reg logic bit byte int integer
always always_comb always_ff always_latch assign begin end if else case casez
casex endcase for while repeat forever function endfunction task endtask
generate endgenerate initial final posedge negedge or and not begin end
parameter localparam typedef struct enum packed signed unsigned
default_nettype include define ifdef ifndef endif else elsif
""".split())


# ---------------------------------------------------------------------------
# uri helpers
# ---------------------------------------------------------------------------
def path_to_uri(path: str | Path) -> str:
    p = Path(path).resolve()
    return "file://" + quote(str(p))


def uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme in ("", "file"):
        return unquote(parsed.path if parsed.scheme else uri)
    return unquote(uri)


# ---------------------------------------------------------------------------
# per-file
# ---------------------------------------------------------------------------
@dataclass
class BoundDefinition:
    definition: Definition
    block: Block | None
    module: Block | None

    @property
    def block_kind(self) -> str:
        return self.block.kind if self.block else "(file)"


@dataclass
class FileIndex:
    path: str
    text: str
    scan: Scan
    block_scan: ScanResult
    annotations: AnnotationSet
    bound: list[BoundDefinition] = field(default_factory=list)
    identifiers: set[str] = field(default_factory=set)

    # ---- lookups ----
    @property
    def by_name(self) -> dict[str, BoundDefinition]:
        return {b.definition.name: b for b in self.bound}

    def definition_at(self, offset: int) -> Definition | None:
        for b in self.bound:
            d = b.definition
            if d.offset <= offset < d.end_offset:
                return d
        return None

    def reference_at(self, offset: int):
        for r in self.annotations.references:
            if r.offset <= offset < r.end_offset:
                return r
        for r in self.annotations.bare_at_start:
            if r.offset <= offset < r.end_offset:
                return r
        return None

    def hardware_at(self, offset: int) -> HardwareRef | None:
        for h in self.annotations.hardware:
            if h.offset <= offset < h.end_offset:
                return h
        return None

    def identifier_at(self, offset: int) -> str | None:
        """The Verilog identifier under the cursor in real code (not comments)."""
        if self.scan.block_at(offset) is not None:
            return None
        m = _IDENT.search(self.scan.masked, offset)
        if not m or m.start() != offset:
            # allow the cursor to sit just after the token
            m2 = None
            for cand in _IDENT.finditer(self.scan.masked):
                if cand.start() <= offset <= cand.end():
                    m2 = cand
                    break
            if not m2:
                return None
            m = m2
        return m.group(0)

    def declaration_of(self, name: str) -> int | None:
        """Offset of a plausible declaration of ``name`` in real code."""
        pat = re.compile(
            rf"^\s*(?:input|output|inout|wire|reg|logic|bit|byte|int|integer|"
            rf"parameter|localparam)\b[^;\n]*\b{re.escape(name)}\b",
            re.M)
        m = pat.search(self.scan.masked)
        if m:
            inner = re.search(rf"\b{re.escape(name)}\b", m.group(0))
            if inner:
                return m.start() + inner.start()
        return None


def build_file_index(path: str, text: str) -> FileIndex:
    sc = scan(text)
    bs = blocks_mod.scan_blocks(sc.masked, sc.lines)
    ann = grammar.parse(sc)
    fi = FileIndex(path=path, text=text, scan=sc, block_scan=bs, annotations=ann)
    fi.identifiers = {
        t for t in _IDENT.findall(sc.masked) if t not in _SV_KEYWORDS
    }

    module = bs.outermost_module()
    for d in ann.definitions:
        blk = _bind_block(bs, d.comment.start_line, module)
        fi.bound.append(BoundDefinition(d, blk, module))
    return fi


def _bind_block(bs: ScanResult, line: int, module: Block | None) -> Block | None:
    """Decide which Verilog construct an annotation describes.

    1. the innermost block containing the comment -- but a module/interface is
       not a *component*, so it does not count on its own;
    2. otherwise the next component that starts within ``LOOKAHEAD_LINES``
       (the common style of a comment sitting directly above its block);
    3. otherwise the enclosing module.
    """
    inner = bs.innermost_at(line)
    if inner is not None and not inner.is_container:
        return inner
    ahead = bs.next_block_starting_after(line, LOOKAHEAD_LINES)
    if ahead is not None:
        return ahead
    return inner or module


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------
@dataclass
class DefinitionLocation:
    path: str
    bound: BoundDefinition

    @property
    def definition(self) -> Definition:
        return self.bound.definition


@dataclass
class WorkspaceIndex:
    root: str | None = None
    files: dict[str, FileIndex] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ---- mutation ----
    def put(self, path: str, fi: FileIndex) -> None:
        self.files[path] = fi

    def drop(self, path: str) -> None:
        self.files.pop(path, None)

    def index_path(self, path: str, text: str | None = None) -> FileIndex:
        if text is None:
            try:
                text = Path(path).read_text(errors="replace")
            except OSError as exc:
                self.warnings.append(f"cannot read {path}: {exc}")
                text = ""
        fi = build_file_index(path, text)
        for w in fi.block_scan.warnings:
            self.warnings.append(f"{os.path.basename(path)}: {w}")
        self.put(path, fi)
        return fi

    def index_directory(self, root: str, limit: int = 2000) -> None:
        self.root = str(Path(root).resolve())
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "obj_dir", "node_modules", "__pycache__")]
            for fn in filenames:
                if not fn.endswith(SV_SUFFIXES):
                    continue
                if count >= limit:
                    self.warnings.append(
                        f"stopped indexing at {limit} files; "
                        "raise the limit or narrow the workspace")
                    return
                self.index_path(os.path.join(dirpath, fn))
                count += 1

    # ---- queries ----
    def definitions_named(self, name: str) -> list[DefinitionLocation]:
        out: list[DefinitionLocation] = []
        for path, fi in self.files.items():
            for b in fi.bound:
                if b.definition.name == name:
                    out.append(DefinitionLocation(path, b))
        return out

    def resolve(self, name: str, prefer_path: str | None = None) -> DefinitionLocation | None:
        hits = self.definitions_named(name)
        if not hits:
            return None
        if prefer_path:
            same = [h for h in hits if h.path == prefer_path]
            if same:
                return same[0]
        return hits[0]

    def references_to(self, name: str) -> list[tuple[str, Reference]]:
        out: list[tuple[str, Reference]] = []
        for path, fi in self.files.items():
            for r in fi.annotations.references:
                if r.name == name:
                    out.append((path, r))
            for r in fi.annotations.bare_at_start:
                if r.name == name:
                    out.append((path, r))
        return out

    def all_names(self) -> list[str]:
        names: set[str] = set()
        for fi in self.files.values():
            names.update(fi.annotations.names)
        return sorted(names)

    def all_definitions(self) -> list[DefinitionLocation]:
        out: list[DefinitionLocation] = []
        for path, fi in self.files.items():
            for b in fi.bound:
                out.append(DefinitionLocation(path, b))
        return out

    def duplicate_names(self) -> dict[str, list[DefinitionLocation]]:
        seen: dict[str, list[DefinitionLocation]] = {}
        for loc in self.all_definitions():
            seen.setdefault(loc.definition.name, []).append(loc)
        return {k: v for k, v in seen.items() if len(v) > 1}


__all__ = [
    "Block", "BoundDefinition", "Definition", "DefinitionLocation", "FileIndex",
    "HardwareRef", "Malformed", "Reference", "ScanResult", "WorkspaceIndex",
    "build_file_index", "path_to_uri", "uri_to_path", "SV_SUFFIXES",
]
