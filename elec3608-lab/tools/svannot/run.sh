#!/usr/bin/env bash
# Launch the svannot language server.
#
# Zed invokes this via the extension in zed/.  It sets PYTHONPATH so that
# `python3 -m annot` resolves regardless of the working directory Zed picks,
# and needs no virtualenv and no third-party packages.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec env PYTHONPATH="${HERE}${PYTHONPATH:+:${PYTHONPATH}}" \
     python3 -m annot "$@"
