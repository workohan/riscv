"""svannot -- annotation-driven symbols for SystemVerilog.

Annotate components in comments::

    // @mux:pcmux    selects npc from reset, pc+4 and @br_target; driven by [pc]
    always_comb begin ... end

and get an outline tree, go-to-definition, find-references, hover and
diagnostics for free -- with no SystemVerilog parser involved, because the
annotations live entirely in comments.

See ``docs/`` for the research this tool was built alongside.
"""

__version__ = "0.1.0"

from .index import WorkspaceIndex, build_file_index, path_to_uri, uri_to_path
from .diagnostics import Diagnostic, Options, compute
from .server import AnnotServer, symbol_kind

__all__ = [
    "WorkspaceIndex", "build_file_index", "path_to_uri", "uri_to_path",
    "Diagnostic", "Options", "compute", "AnnotServer", "symbol_kind",
    "__version__",
]
