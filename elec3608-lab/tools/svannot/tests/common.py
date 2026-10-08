"""Shared helpers for the svannot tests."""
from __future__ import annotations

from pathlib import Path

from annot.index import WorkspaceIndex, build_file_index, path_to_uri

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> Path:
    return FIXTURES / name


def load(name: str) -> str:
    return fixture(name).read_text()


def index(name: str):
    """Build a single-file index for a fixture."""
    return build_file_index(str(fixture(name)), load(name))


def workspace(*names: str) -> WorkspaceIndex:
    """Build a workspace index over the named fixtures only."""
    ws = WorkspaceIndex()
    for n in names:
        ws.index_path(str(fixture(n)))
    return ws


def full_workspace() -> WorkspaceIndex:
    ws = WorkspaceIndex()
    ws.index_directory(str(FIXTURES))
    return ws


def uri(name: str) -> str:
    return path_to_uri(fixture(name))


def diag_codes(fi, ws) -> list[str]:
    from annot.diagnostics import Options, compute
    return [d.code for d in compute(fi, ws, Options())]
