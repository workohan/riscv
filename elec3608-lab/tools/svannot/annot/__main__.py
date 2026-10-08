"""Entry point: ``python3 -m annot``.

    python3 -m annot --stdio              run the language server (what Zed uses)
    python3 -m annot --check [PATH ...]   index files/dirs and print a summary
    python3 -m annot --dump-json PATH     symbols as JSON, for scripting
    python3 -m annot --version

``--check`` is the debugging entry point when the outline looks wrong: it shows
exactly which annotation bound to which block, and every diagnostic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .diagnostics import Options, compute
from .index import WorkspaceIndex


def _collect(paths: list[str]) -> tuple[WorkspaceIndex, list[str]]:
    ws = WorkspaceIndex()
    files: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            ws.index_directory(str(p))
            files.extend(ws.files.keys())
        elif p.is_file():
            ws.index_path(str(p))
            files.append(str(p))
        else:
            print(f"annot: no such path: {raw}", file=sys.stderr)
    return ws, sorted(set(files))


def cmd_check(paths: list[str], show_diagnostics: bool) -> int:
    ws, files = _collect(paths)
    if not files:
        print("annot: nothing to check")
        return 1
    total_defs = total_refs = 0
    problems = 0
    for path in files:
        fi = ws.files[path]
        defs, refs = fi.bound, fi.annotations.references
        total_defs += len(defs)
        total_refs += len(refs)
        print(f"\n=== {path} ===")
        if not defs:
            print("  (no annotations)")
        for bd in defs:
            d = bd.definition
            blk = bd.block
            where = f"{blk.kind} L{blk.start_line + 1}-{blk.end_line + 1}" if blk \
                else "(unbound)"
            print(f"  L{d.line + 1:<4} {d.label:<24} -> {where}")
            if d.description:
                print(f"        {d.description[:88]}")
        if show_diagnostics:
            ds = compute(fi, ws, Options())
            for x in ds:
                sev = {1: "error", 2: "warn", 3: "info", 4: "hint"}[x.severity]
                print(f"  [{sev}] L{x.line + 1}:{x.col + 1} {x.code}: {x.message}")
            problems += len([x for x in ds if x.severity <= 2])
    dupes = ws.duplicate_names()
    print(f"\nsummary: {len(files)} file(s), {total_defs} definition(s), "
          f"{total_refs} reference(s), {len(dupes)} duplicate name(s), "
          f"{len(ws.warnings)} scanner warning(s)")
    for w in ws.warnings[:10]:
        print(f"  warning: {w}")
    return 1 if problems else 0


def cmd_dump_json(paths: list[str]) -> int:
    ws, files = _collect(paths)
    out = []
    for path in files:
        fi = ws.files[path]
        out.append({
            "path": path,
            "definitions": [{
                "name": bd.definition.name,
                "category": bd.definition.category,
                "line": bd.definition.line + 1,
                "column": bd.definition.col + 1,
                "description": bd.definition.description,
                "block": (f"{bd.block.kind} L{bd.block.start_line + 1}-"
                          f"{bd.block.end_line + 1}") if bd.block else None,
            } for bd in fi.bound],
            "references": [{"name": r.name, "line": r.line + 1, "column": r.col + 1}
                           for r in fi.annotations.references],
            "hardware": [{"name": h.name, "line": h.line + 1,
                          "known": h.name in fi.identifiers}
                         for h in fi.annotations.hardware],
            "diagnostics": [x.to_lsp() for x in compute(fi, ws, Options())],
        })
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="annot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdio", action="store_true",
                    help="run the language server on stdio (used by Zed)")
    ap.add_argument("--check", nargs="*", metavar="PATH",
                    help="index and summarise; defaults to the current directory")
    ap.add_argument("--dump-json", nargs="+", metavar="PATH",
                    help="emit symbols as JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="with --check, omit diagnostics")
    ap.add_argument("--version", action="version",
                    version=f"{__version__}")

    # Tolerate arguments we do not recognise.  Editors launch language servers
    # with their own flags (Zed, or a host extension wrapping us, may add
    # things like `--indentation_spaces 4`), and dying on an unknown flag would
    # leave the editor with a silent dead server.
    args, extra = ap.parse_known_args(argv)

    if args.stdio:
        from .lsp import serve
        from .server import AnnotServer
        return serve(AnnotServer())
    if args.dump_json:
        return cmd_dump_json(args.dump_json)
    if args.check is not None:
        paths = args.check or ["."]
        return cmd_check(paths, show_diagnostics=not args.quiet)

    # No mode was requested.  If stdin is not a terminal we were started by a
    # program rather than a person, so behave as a language server -- this is
    # the safety net for an editor that launches us without our `--stdio`.
    if not sys.stdin.isatty():
        print("annot: no mode given and stdin is not a tty; "
              "running as a language server", file=sys.stderr)
        from .lsp import serve
        from .server import AnnotServer
        return serve(AnnotServer())

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
