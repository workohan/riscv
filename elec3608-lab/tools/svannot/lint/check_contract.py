#!/usr/bin/env python3
"""Check nerv-interrupt.sv against the contract testbench.sv imposes on it.

`labs/ass1-2026/testbench.sv` reaches directly into the DUT hierarchy:

    dut.regfile[r]                      (r = 0..31, so it must be an array)
    dut.pc
    dut.csr_mepc   dut.csr_mie    dut.csr_mtvec   dut.csr_mip
    dut.csr_mcause dut.csr_mstatus dut.csr_mscratch

None of these are mentioned in the README, and the skeleton does not define
them.  If the names are wrong, `verilator` fails while elaborating
*testbench.sv* -- not the design -- and the entire test suite breaks with an
error that points at the wrong file.

This script checks the names without needing Verilator, so it works before the
design compiles.

Usage:
    python3 check_contract.py [nerv-interrupt.sv ...]

Exit status: 0 if every check passes, 1 otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Names testbench.sv requires, with a human-readable description.
REQUIRED_INTERNALS: list[tuple[str, str]] = [
    ("regfile", "32-entry GPR array, indexable as regfile[r]"),
    ("pc", "program counter"),
    ("csr_mepc", "CSR: machine exception PC"),
    ("csr_mie", "CSR: machine interrupt enable"),
    ("csr_mtvec", "CSR: machine trap vector"),
    ("csr_mip", "CSR: machine interrupt pending"),
    ("csr_mcause", "CSR: machine exception cause"),
    ("csr_mstatus", "CSR: machine status"),
    ("csr_mscratch", "CSR: machine scratch"),
]

# Ports the testbench connects by name.
REQUIRED_PORTS = ["clock", "reset", "trap", "intr",
                  "imem_addr", "imem_data",
                  "dmem_valid", "dmem_addr", "dmem_wstrb", "dmem_wdata",
                  "dmem_rdata"]

REQUIRED_PARAM = "MTVEC_ADDR"


def strip_comments_and_strings(src: str) -> str:
    """Remove // and /* */ comments and string literals, preserving newlines."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            i += 2
        elif c == '"':
            i += 1
            while i < n and src[i] != '"':
                if src[i] == "\\":
                    i += 1
                i += 1
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def find_module(src: str, name: str = "nerv"):
    """Return (header_text, body_text) for `module <name> ... endmodule`."""
    m = re.search(rf"\bmodule\s+{re.escape(name)}\b", src)
    if not m:
        return None
    start = m.start()
    end = src.find("endmodule", start)
    header_end = src.find(";", src.find(")", start)) if "(" in src[start:start + 400] else -1
    header = src[start:header_end + 1] if header_end > 0 else src[start:start + 400]
    body = src[start:end if end > 0 else len(src)]
    return header, body


def check_file(path: Path) -> bool:
    raw = path.read_text(errors="replace")
    src = strip_comments_and_strings(raw)

    print(f"\n=== {path} ===")
    ok = True

    mod = find_module(src, "nerv")
    if not mod:
        print("  FAIL  no `module nerv` found in this file")
        return False
    header, body = mod

    # --- parameter the testbench overrides ---
    if re.search(rf"\bparameter\b[^;]*\b{REQUIRED_PARAM}\b", header, re.S):
        print(f"  ok    parameter {REQUIRED_PARAM} declared")
    else:
        print(f"  FAIL  parameter {REQUIRED_PARAM} missing "
              f"(testbench.sv does #(.{REQUIRED_PARAM}(...)))")
        ok = False

    # --- ports connected by name ---
    missing_ports = [p for p in REQUIRED_PORTS
                     if not re.search(rf"\b{re.escape(p)}\b", header)]
    if missing_ports:
        print(f"  FAIL  port(s) missing from the nerv port list: "
              f"{', '.join(missing_ports)}")
        ok = False
    else:
        print(f"  ok    all {len(REQUIRED_PORTS)} testbench ports present")

    # --- internals the testbench pokes at ---
    print("  --- internals referenced as dut.<name> ---")
    for name, desc in REQUIRED_INTERNALS:
        # `regfile` must be an array (indexed by the testbench as regfile[r])
        if name == "regfile":
            if re.search(r"\bregfile\s*\[", body):
                print(f"  ok    {name:14} array  ({desc})")
            else:
                print(f"  FAIL  {name:14} not declared as an array ({desc})")
                ok = False
            continue

        decl = re.search(
            rf"\b(?:logic|reg|wire)\b[^;=\n]*\b{re.escape(name)}\b\s*(?:;|,|=|\[)",
            body)
        assign = re.search(rf"\bassign\s+{re.escape(name)}\b", body)
        if decl or assign:
            print(f"  ok    {name:14} {desc}")
        else:
            print(f"  FAIL  {name:14} not declared ({desc})")
            ok = False

    if re.search(r"`default_nettype\s+none", raw):
        print("  ok    `default_nettype none is set "
              "(typos become hard errors, not implicit wires)")
    else:
        print("  note  `default_nettype none is NOT set; a typo here would "
              "create a silent implicit wire")

    return ok


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]]
    if not paths:
        here = Path(__file__).resolve().parent.parent.parent.parent / "labs" / "ass1-2026"
        paths = [here / "nerv-interrupt.sv"]
    paths = [p for p in paths if p.exists()]
    if not paths:
        print("check_contract: no input files found", file=sys.stderr)
        return 1

    results = [check_file(p) for p in paths]
    print()
    if all(results):
        print("check_contract: PASS - every name testbench.sv needs is present")
        return 0
    print("check_contract: FAIL - see the FAIL lines above; "
          "the testbench will not elaborate until these exist")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
