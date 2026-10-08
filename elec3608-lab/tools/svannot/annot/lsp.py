"""Minimal LSP / JSON-RPC transport over stdio.

Deliberately dependency-free: Zed spawns ``python3 -m annot`` and there should
be nothing to install first.  `pygls` would work, but it brings a dependency
plus a v1/v2 API to track, and the request surface this server needs is small --
around a hundred lines of framing.

Handles the LSP base protocol: ``Content-Length``-framed UTF-8 JSON-RPC 2.0.
"""
from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class LspError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def read_message(stream: BinaryIO) -> dict | None:
    """Read one framed message.  Returns None at clean EOF."""
    length: int | None = None
    while True:
        line = stream.readline()
        if not line:
            return None                                   # EOF
        line = line.strip()
        if not line:
            break                                          # end of headers
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError:
                raise LspError(PARSE_ERROR, "bad Content-Length header")
    if length is None:
        raise LspError(PARSE_ERROR, "missing Content-Length header")
    body = stream.read(length)
    if len(body) < length:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LspError(PARSE_ERROR, f"invalid JSON body: {exc}")


def write_message(stream: BinaryIO, msg: dict) -> None:
    body = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def make_response(msg_id: Any, result: Any) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "result": result}


def make_error(msg_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "error": err}


def make_notification(method: str, params: Any) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}


def serve(server, stdin: BinaryIO | None = None,
          stdout: BinaryIO | None = None) -> int:
    """Run the message loop until ``exit`` or EOF.

    ``server`` must expose ``handle_request(method, params) -> result`` and
    ``handle_notification(method, params) -> bool`` (False means "stop").
    """
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    while True:
        try:
            msg = read_message(stdin)
        except LspError as exc:
            write_message(stdout, make_error(None, exc.code, exc.message))
            continue
        if msg is None:
            return 0

        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method is None and msg_id is not None:
            continue                                       # a response; ignore

        try:
            if msg_id is None:
                keep_going = server.handle_notification(method, params)
                for out in server.drain():
                    write_message(stdout, out)
                if not keep_going:
                    return 0
            else:
                result = server.handle_request(method, params)
                write_message(stdout, make_response(msg_id, result))
                for out in server.drain():
                    write_message(stdout, out)
        except LspError as exc:
            if msg_id is not None:
                write_message(stdout, make_error(msg_id, exc.code, exc.message, exc.data))
        except Exception as exc:                            # never kill the server
            if msg_id is not None:
                write_message(stdout, make_error(
                    msg_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))


class MemoryTransport:
    """Test helper: collect outbound messages instead of writing them."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def __call__(self, msg: dict) -> None:
        self.sent.append(msg)

    def clear(self) -> None:
        self.sent.clear()
