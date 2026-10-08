"""LSP request handlers for the annotation language.

Transport-agnostic: :class:`AnnotServer` exposes ``handle_request`` and
``handle_notification`` and collects outbound notifications in an outbox, so the
whole thing is testable without an editor or a socket.  ``annot/lsp.py`` supplies
the stdio framing.

Capabilities provided
---------------------
* ``textDocument/documentSymbol`` -- the annotated component tree (this is what
  feeds Zed's outline panel once ``document_symbols`` is set to ``"on"``)
* ``textDocument/definition``      -- ``@name`` -> its definition, ``[sig]`` ->
  the signal's declaration
* ``textDocument/references``
* ``textDocument/hover``
* ``textDocument/completion``      -- after ``@``
* ``workspace/symbol``             -- every annotation in the workspace
* ``textDocument/publishDiagnostics``
"""
from __future__ import annotations

import os
from typing import Any

from . import diagnostics as diag
from .blocks import describe
from .diagnostics import Diagnostic, Options
from .index import (BoundDefinition, FileIndex, WorkspaceIndex, path_to_uri,
                    uri_to_path)
from .lsp import INVALID_PARAMS, LspError, make_notification

SERVER_NAME = "svannot"
SERVER_VERSION = "0.1.0"

# LSP SymbolKind values we use.
KIND_FILE, KIND_MODULE, KIND_NAMESPACE, KIND_PACKAGE = 1, 2, 3, 4
KIND_FIELD, KIND_INTERFACE, KIND_FUNCTION = 8, 11, 12
KIND_VARIABLE, KIND_CONSTANT, KIND_OBJECT, KIND_KEY = 13, 14, 19, 20

CATEGORY_KINDS = {
    "module": KIND_MODULE,
    "interface": KIND_INTERFACE,
    "package": KIND_PACKAGE,
    "mux": KIND_FUNCTION, "comb": KIND_FUNCTION, "alu": KIND_FUNCTION,
    "decoder": KIND_FUNCTION, "ctrl": KIND_FUNCTION, "func": KIND_FUNCTION,
    "function": KIND_FUNCTION, "method": KIND_FUNCTION,
    "seq": KIND_VARIABLE, "reg": KIND_VARIABLE, "ff": KIND_VARIABLE,
    "state": KIND_VARIABLE, "var": KIND_VARIABLE, "variable": KIND_VARIABLE,
    "wire": KIND_FIELD, "signal": KIND_FIELD, "field": KIND_FIELD,
    "port": KIND_FIELD,
    "instance": KIND_OBJECT, "obj": KIND_OBJECT,
    "const": KIND_CONSTANT, "param": KIND_CONSTANT,
    "parameter": KIND_CONSTANT, "localparam": KIND_CONSTANT,
}

CONTAINER_KINDS = {
    "module": KIND_MODULE, "interface": KIND_INTERFACE,
    "package": KIND_PACKAGE, "program": KIND_NAMESPACE,
    "generate": KIND_NAMESPACE, "class": KIND_NAMESPACE,
    "checker": KIND_NAMESPACE,
}


def symbol_kind(category: str, block_kind: str | None = None) -> int:
    k = CATEGORY_KINDS.get(category.lower())
    if k is not None:
        return k
    if block_kind:
        k = CONTAINER_KINDS.get(block_kind)
        if k is not None:
            return k
    return KIND_VARIABLE


class AnnotServer:
    def __init__(self) -> None:
        self.ws = WorkspaceIndex()
        self.options = Options()
        self.overlays: dict[str, str] = {}      # uri -> in-memory buffer
        self.outbox: list[dict] = []
        self.root_path: str | None = None
        self.exiting = False

    # ------------------------------------------------------------------
    # outbound plumbing
    # ------------------------------------------------------------------
    def emit(self, method: str, params: Any) -> None:
        self.outbox.append(make_notification(method, params))

    def drain(self) -> list[dict]:
        out, self.outbox = self.outbox, []
        return out

    # ------------------------------------------------------------------
    # document helpers
    # ------------------------------------------------------------------
    def file_for(self, uri: str) -> FileIndex | None:
        return self.ws.files.get(uri_to_path(uri))

    def _require_file(self, params: dict) -> FileIndex:
        try:
            uri = params["textDocument"]["uri"]
        except (KeyError, TypeError):
            raise LspError(INVALID_PARAMS, "missing textDocument.uri")
        fi = self.file_for(uri)
        if fi is None:
            path = uri_to_path(uri)
            text = self.overlays.get(uri)
            if text is None:
                try:
                    text = open(path, errors="replace").read()
                except OSError:
                    raise LspError(INVALID_PARAMS, f"cannot read {path}")
            fi = self.ws.index_path(path, text)
        return fi

    def _offset(self, fi: FileIndex, params: dict) -> int:
        pos = params.get("position") or {}
        return fi.scan.lines.offset(int(pos.get("line", 0)),
                                    int(pos.get("character", 0)))

    def _location(self, path: str, start: int, end: int) -> dict:
        fi = self.ws.files.get(path)
        uri = path_to_uri(path)
        if fi is None:
            return {"uri": uri, "range": {"start": {"line": 0, "character": 0},
                                          "end": {"line": 0, "character": 0}}}
        sl, sc = fi.scan.lines.line_col(start)
        el, ec = fi.scan.lines.line_col(end)
        return {"uri": uri, "range": {"start": {"line": sl, "character": sc},
                                      "end": {"line": el, "character": ec}}}

    def _block_range(self, fi: FileIndex, blk) -> dict:
        sl, el = blk.start_line, blk.end_line
        end_col = len(fi.text.split("\n")[el]) if el < fi.scan.lines.line_count else 0
        return {"start": {"line": sl, "character": 0},
                "end": {"line": el, "character": end_col}}

    def publish(self, fi: FileIndex) -> None:
        d: list[Diagnostic] = diag.compute(fi, self.ws, self.options)
        self.emit("textDocument/publishDiagnostics", {
            "uri": path_to_uri(fi.path),
            "diagnostics": [x.to_lsp() for x in d],
        })

    def reindex(self, uri: str, text: str | None = None) -> FileIndex:
        path = uri_to_path(uri)
        if text is None:
            text = self.overlays.get(uri)
        if text is None:
            text = open(path, errors="replace").read()
        fi = self.ws.index_path(path, text)
        self.publish(fi)
        return fi

    # ------------------------------------------------------------------
    # requests
    # ------------------------------------------------------------------
    def handle_request(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if method == "shutdown":
            return None
        handler = {
            "textDocument/documentSymbol": self._document_symbol,
            "textDocument/definition": self._definition,
            "textDocument/references": self._references,
            "textDocument/hover": self._hover,
            "textDocument/completion": self._completion,
            "workspace/symbol": self._workspace_symbol,
        }.get(method)
        if handler is None:
            raise LspError(-32601, f"method not supported: {method}")
        return handler(params)

    def _initialize(self, params: dict) -> dict:
        opts = params.get("initializationOptions") or {}
        if isinstance(opts, dict):
            self.options = Options(
                unannotated_blocks=bool(opts.get("unannotatedBlocks", False)),
                unknown_identifiers=bool(opts.get("unknownIdentifiers", True)),
                undefined_references=bool(opts.get("undefinedReferences", True)),
                duplicate_definitions=bool(opts.get("duplicateDefinitions", True)),
            )
        root = None
        folders = params.get("workspaceFolders") or []
        if folders and isinstance(folders, list):
            root = uri_to_path(folders[0].get("uri", ""))
        elif params.get("rootUri"):
            root = uri_to_path(params["rootUri"])
        elif params.get("rootPath"):
            root = params["rootPath"]
        if root and os.path.isdir(root):
            self.root_path = root
            self.ws.index_directory(root)
        return {
            "capabilities": {
                "textDocumentSync": {"openClose": True, "change": 1},   # Full
                "documentSymbolProvider": True,
                "definitionProvider": True,
                "referencesProvider": True,
                "hoverProvider": True,
                "completionProvider": {"triggerCharacters": ["@", "["]},
                "workspaceSymbolProvider": True,
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    # ---- symbols -----------------------------------------------------
    def _document_symbol(self, params: dict) -> list[dict]:
        fi = self._require_file(params)
        return self._symbols(fi)

    def _symbols(self, fi: FileIndex) -> list[dict]:
        blocks = fi.block_scan.all_blocks()
        by_block: dict[int, list[BoundDefinition]] = {}
        for bd in fi.bound:
            if bd.block is not None:
                by_block.setdefault(id(bd.block), []).append(bd)

        symbolised = {id(b) for b in blocks if b.is_container} | set(by_block)
        node: dict[int, dict] = {}
        for b in blocks:
            if id(b) not in symbolised:
                continue
            defs = by_block.get(id(b))
            if defs:
                # one symbol per annotation bound to this block
                for bd in defs:
                    node[id(b)] = _definition_symbol(self, fi, b, bd)
                    break
                # (a block with several annotations keeps the first as the
                #  node; extras are attached as children below)
                extras = defs[1:]
            else:
                node[id(b)] = _container_symbol(self, fi, b)
                extras = []
            if extras:
                for bd in extras:
                    node[id(b)]["children"].append(
                        _definition_symbol(self, fi, b, bd))

        roots: list[dict] = []
        for b in blocks:
            if id(b) not in node:
                continue
            anc = b.parent
            while anc is not None and id(anc) not in node:
                anc = anc.parent
            if anc is None:
                roots.append(node[id(b)])
            else:
                node[id(anc)]["children"].append(node[id(b)])

        # definitions that bound to no block at all
        for bd in fi.bound:
            if bd.block is None:
                roots.append(_definition_symbol(self, fi, None, bd))
        return roots

    # ---- navigation --------------------------------------------------
    def _name_at(self, fi: FileIndex, off: int) -> tuple[str | None, dict | None]:
        """Return (name, origin) where origin describes what was under the cursor."""
        d = fi.definition_at(off)
        if d:
            return d.name, {"kind": "definition", "definition": d}
        r = fi.reference_at(off)
        if r:
            return r.name, {"kind": "reference", "reference": r}
        return None, None

    def _definition(self, params: dict) -> Any:
        fi = self._require_file(params)
        off = self._offset(fi, params)
        name, origin = self._name_at(fi, off)
        if name:
            loc = self.ws.resolve(name, prefer_path=fi.path)
            if loc is None:
                return None
            return [self._location(loc.path, loc.definition.offset,
                                   loc.definition.end_offset)]
        hw = fi.hardware_at(off)
        if hw:
            decl = fi.declaration_of(hw.name)
            if decl is not None:
                return [self._location(fi.path, decl, decl + len(hw.name))]
            loc = self.ws.resolve(hw.name, prefer_path=fi.path)
            if loc is not None:
                return [self._location(loc.path, loc.definition.offset,
                                       loc.definition.end_offset)]
        return None

    def _references(self, params: dict) -> list[dict]:
        fi = self._require_file(params)
        off = self._offset(fi, params)
        ctx = params.get("context") or {}
        include_def = bool(ctx.get("includeDeclaration", True))
        name, _ = self._name_at(fi, off)
        if not name:
            name = fi.identifier_at(off)
        if not name:
            return []
        out: list[dict] = []
        if include_def:
            for loc in self.ws.definitions_named(name):
                out.append(self._location(loc.path, loc.definition.offset,
                                          loc.definition.end_offset))
        for path, ref in self.ws.references_to(name):
            out.append(self._location(path, ref.offset, ref.end_offset))
        return out

    def _hover(self, params: dict) -> Any:
        fi = self._require_file(params)
        off = self._offset(fi, params)
        name, origin = self._name_at(fi, off)
        if name and origin:
            loc = self.ws.resolve(name, prefer_path=fi.path)
            if origin["kind"] == "definition":
                d = origin["definition"]
                bound = fi.by_name.get(d.name)
                block = bound.block.label if bound and bound.block else "(no block)"
                md = (f"**`@{d.label}`**\n\n{d.description or '_(no description)_'}\n\n"
                      f"*bound to* `{block}`")
            elif loc is None:
                md = f"**`@{name}`**\n\n_undefined — no `@category:{name}` found_"
            else:
                d = loc.definition
                where = os.path.relpath(loc.path, self.root_path) \
                    if self.root_path else loc.path
                md = (f"**`@{d.label}`**\n\n{d.description or '_(no description)_'}\n\n"
                      f"*defined in* `{where}` line {d.line + 1}")
            return {"contents": {"kind": "markdown", "value": md}}
        hw = fi.hardware_at(off)
        if hw:
            known = hw.name in fi.identifiers
            md = f"**`[{hw.name}]`**\n\n" + (
                "signal declared in this file" if known
                else "_no such signal declared in this file_")
            return {"contents": {"kind": "markdown", "value": md}}
        return None

    def _completion(self, params: dict) -> dict:
        items: list[dict] = []
        for loc in self.ws.all_definitions():
            d = loc.definition
            items.append({
                "label": d.name,
                "kind": symbol_kind(d.category, None),
                "detail": f"{d.category}  ({os.path.basename(loc.path)})",
                "documentation": {"kind": "markdown",
                                  "value": d.description or "_(no description)_"},
                "filterText": d.name,
                "sortText": d.name,
            })
        items.append({
            "label": "@category:name  (new annotation)",
            "kind": 15,                                   # Snippet
            "detail": "definition template",
            "insertText": "@${1|mux,comb,seq,reg,alu,decoder,ctrl,wire,func,module,instance,const|}:${2:name} ${3:description}",
            "insertTextFormat": 2,
            "sortText": "zzzz",
        })
        return {"isIncomplete": False, "items": items}

    def _workspace_symbol(self, params: dict) -> list[dict]:
        query = (params.get("query") or "").lower()
        out: list[dict] = []
        for loc in self.ws.all_definitions():
            d = loc.definition
            if query and query not in d.name.lower() and query not in d.category.lower():
                continue
            out.append({
                "name": d.label,
                "kind": symbol_kind(d.category, None),
                "location": self._location(loc.path, d.offset, d.end_offset),
                "containerName": os.path.basename(loc.path),
            })
        return out

    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------
    def handle_notification(self, method: str, params: dict) -> bool:
        if method == "initialized":
            return True
        if method == "exit":
            return False
        if method == "textDocument/didOpen":
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            if uri:
                self.overlays[uri] = td.get("text", "")
                self.reindex(uri)
            return True
        if method == "textDocument/didChange":
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            changes = params.get("contentChanges") or []
            if uri and changes:
                # Full sync: the last change carries the whole document.
                self.overlays[uri] = changes[-1].get("text", "")
                self.reindex(uri)
            return True
        if method == "textDocument/didSave":
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            if uri:
                self.overlays.pop(uri, None)
                self.reindex(uri)
            return True
        if method == "textDocument/didClose":
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            if uri:
                self.overlays.pop(uri, None)
                self.emit("textDocument/publishDiagnostics",
                          {"uri": uri, "diagnostics": []})
            return True
        return True


# ---------------------------------------------------------------------------
# symbol construction
# ---------------------------------------------------------------------------
def _container_symbol(server: AnnotServer, fi: FileIndex, blk) -> dict:
    name = f"{blk.kind} {blk.name}" if blk.name else blk.kind
    rng = server._block_range(fi, blk)
    return {
        "name": name,
        "detail": describe(blk.kind),
        "kind": CONTAINER_KINDS.get(blk.kind, KIND_NAMESPACE),
        "range": rng,
        "selectionRange": rng,
        "children": [],
    }


def _definition_symbol(server: AnnotServer, fi: FileIndex, blk,
                       bd: BoundDefinition) -> dict:
    d = bd.definition
    if blk is not None:
        rng = server._block_range(fi, blk)
    else:
        sl, sc = fi.scan.lines.line_col(d.offset)
        rng = {"start": {"line": sl, "character": sc},
               "end": {"line": sl, "character": sc + len(d.label) + 1}}
    sel = server._location(fi.path, d.offset, d.end_offset)["range"]
    # selectionRange must be inside range; a comment above the block is not.
    if (sel["start"]["line"] < rng["start"]["line"]
            or sel["start"]["line"] > rng["end"]["line"]):
        rng = {"start": dict(sel["start"]),
               "end": {"line": max(sel["end"]["line"], rng["end"]["line"]),
                       "character": rng["end"]["character"]}}
    return {
        "name": d.label,
        "detail": (d.description or describe(blk.kind if blk else ""))[:200],
        "kind": symbol_kind(d.category, blk.kind if blk else None),
        "range": rng,
        "selectionRange": sel,
        "children": [],
    }
