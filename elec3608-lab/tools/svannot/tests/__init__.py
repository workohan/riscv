"""Tests for svannot.

Run from the project root::

    python3 -m unittest discover -s tests -t . -v

Only the standard library is used, so there is nothing to install.
"""
import sys
from pathlib import Path

# Make `import annot` work when discovery is started from the project root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
