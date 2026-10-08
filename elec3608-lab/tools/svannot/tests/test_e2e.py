"""End-to-end tests: drive the real `python3 -m annot --stdio` process.

This is the strongest check available without an editor -- it exercises the
argument parsing, the JSON-RPC framing, the message loop and the handlers
exactly as Zed will.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from . import common

ROOT = Path(__file__).resolve().parent.parent


def frame(msg: dict) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def read_one(stream) -> dict:
    length = None
    while True:
        line = stream.readline()
        if not line:
            raise AssertionError("server closed the stream unexpectedly")
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1])
    assert length is not None
    return json.loads(stream.read(length).decode("utf-8"))


class TestStdioServer(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "annot", "--stdio"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(frame({"jsonrpc": "2.0", "method": "exit"}))
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (BrokenPipeError, ValueError):
                pass

    def send(self, msg: dict) -> None:
        self.proc.stdin.write(frame(msg))
        self.proc.stdin.flush()

    def test_initialize_handshake(self):
        self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"rootUri": common.fixture(".").as_uri(),
                              "capabilities": {}}})
        res = read_one(self.proc.stdout)
        self.assertEqual(res["id"], 1)
        self.assertTrue(res["result"]["capabilities"]["documentSymbolProvider"])
        self.assertEqual(res["result"]["serverInfo"]["name"], "svannot")

    def test_open_and_get_symbols(self):
        self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"rootUri": common.fixture(".").as_uri(),
                              "capabilities": {}}})
        read_one(self.proc.stdout)

        uri = common.fixture("good.sv").as_uri()
        self.send({"jsonrpc": "2.0", "method": "textDocument/didOpen",
                   "params": {"textDocument": {"uri": uri,
                                               "text": common.load("good.sv")}}})
        # the server pushes diagnostics for the opened buffer
        note = read_one(self.proc.stdout)
        self.assertEqual(note["method"], "textDocument/publishDiagnostics")
        self.assertEqual(note["params"]["uri"], uri)

        self.send({"jsonrpc": "2.0", "id": 2, "method": "textDocument/documentSymbol",
                   "params": {"textDocument": {"uri": uri}}})
        res = read_one(self.proc.stdout)
        self.assertEqual(res["id"], 2)
        root = res["result"][0]
        self.assertEqual(root["name"], "module:nerv")
        names = [c["name"] for c in root["children"]]
        self.assertIn("mux:pcmux", names)

    def test_definition_round_trip(self):
        self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"rootUri": common.fixture(".").as_uri(),
                              "capabilities": {}}})
        read_one(self.proc.stdout)
        uri = common.fixture("good.sv").as_uri()
        self.send({"jsonrpc": "2.0", "method": "textDocument/didOpen",
                   "params": {"textDocument": {"uri": uri,
                                               "text": common.load("good.sv")}}})
        read_one(self.proc.stdout)

        # the @does_not_exist reference on 1-based line 47
        self.send({"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition",
                   "params": {"textDocument": {"uri": uri},
                              "position": {"line": 46, "character": 37}}})
        res = read_one(self.proc.stdout)
        self.assertIsNone(res["result"])          # undefined -> no location

    def test_unknown_method_returns_error_not_crash(self):
        self.send({"jsonrpc": "2.0", "id": 9, "method": "bogus/method", "params": {}})
        res = read_one(self.proc.stdout)
        self.assertIn("error", res)
        self.assertEqual(res["id"], 9)
        # the server must still be alive
        self.assertIsNone(self.proc.poll())


class TestLaunchModes(unittest.TestCase):
    """The server must survive however an editor chooses to launch it.

    Zed may start us with its own extra flags, or without our `--stdio` if a
    host extension supplies the arguments.  Neither may result in a dead
    server, because the failure mode in the editor is silent.
    """

    def _handshake(self, argv):
        proc = subprocess.Popen(
            [sys.executable, "-m", "annot", *argv],
            cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            proc.stdin.write(frame({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                    "params": {"capabilities": {}}}))
            proc.stdin.flush()
            res = read_one(proc.stdout)
            self.assertEqual(res["result"]["serverInfo"]["name"], "svannot")
            proc.stdin.write(frame({"jsonrpc": "2.0", "method": "exit"}))
            proc.stdin.flush()
            proc.wait(timeout=5)
        finally:
            for s in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    s.close()
                except (BrokenPipeError, ValueError):
                    pass

    def test_explicit_stdio(self):
        self._handshake(["--stdio"])

    def test_unknown_editor_flags_are_ignored(self):
        # e.g. the verible wrapper passes --indentation_spaces and --rules_config
        self._handshake(["--stdio", "--indentation_spaces", "4",
                         "--rules_config", "/tmp/nope"])

    def test_no_args_with_piped_stdin_becomes_a_server(self):
        # stdin is a pipe here, not a tty, so the server should start itself
        self._handshake([])


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "annot", *args],
                              cwd=str(ROOT), capture_output=True, text=True)

    def test_check_reports_annotations(self):
        r = self.run_cli("--check", str(common.fixture("good.sv")))
        self.assertIn("mux:pcmux", r.stdout)
        self.assertIn("always_comb", r.stdout)

    def test_check_exit_code_clean_file(self):
        # a file with no annotations at all is not a failure
        r = self.run_cli("--check", str(common.fixture("good.sv")), "--quiet")
        self.assertIn("definition(s)", r.stdout)

    def test_check_flags_errors(self):
        r = self.run_cli("--check", str(common.fixture("duplicate.sv")))
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate-definition", r.stdout)

    def test_dump_json_is_valid_json(self):
        r = self.run_cli("--dump-json", str(common.fixture("good.sv")))
        data = json.loads(r.stdout)
        self.assertEqual(data[0]["definitions"][0]["name"], "nerv")
        self.assertTrue(any(d["name"] == "pcmux" for d in data[0]["definitions"]))

    def test_version(self):
        r = self.run_cli("--version")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout.strip(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
