#!/usr/bin/env python3
"""Cycle-level model of nerv.sv, used as an independent cross-check of the
branch / delay-slot behaviour.

This mirrors the RTL structure:

  * registers: pc, ppc, ir, ex_insn, ex_pc1, ex_pc, imem_data, regfile[]
  * imem_addr is combinational and equals npc
  * the control-transfer decision is made in the ID stage from `ir`, with the
    offset base `ppc`, plus the EX->ID operand bypass
  * write-back lands on the clock edge and is visible to the next cycle

It is NOT part of the build.  The authoritative check is the real simulation:

    make test_verilator && ./obj_dir/Vtestbench +vcd
"""
import sys

# firmware.hex: 14 instructions
WORDS = ("13 04 00 00 13 05 10 00 93 04 10 00 63 0E 95 00 "
         "13 04 14 00 13 04 14 00 13 04 14 00 13 04 14 00 "
         "13 04 14 00 13 04 14 00 93 03 70 00 13 03 60 00 "
         "13 00 00 00 73 00 10 00").split()
_B = bytes(int(x, 16) for x in WORDS)
MEM = {a: int.from_bytes(_B[a:a + 4], "little") for a in range(0, len(_B), 4)}
NOP = 0x13


def imm_i(i):
    v = (i >> 20) & 0xfff
    return v - 4096 if v & 0x800 else v


def imm_b(i):
    v = (((i >> 31) & 1) << 12 | ((i >> 7) & 1) << 11 |
         ((i >> 30) & 0x3f) << 5 | ((i >> 8) & 0xf) << 1)
    return v - 8192 if v & 0x1000 else v


def run(cycles=14, show=True):
    pc, ppc, ir, ex_insn = -4, 0, NOP, NOP
    imem_data = 0
    ex_pc1 = ex_pc = 0
    rf = [0] * 32
    log = []

    for n in range(cycles):
        # ---- EX write-back (visible to this cycle's combinational logic) ----
        eop, ef3 = ex_insn & 0x7f, (ex_insn >> 12) & 7
        erd, ers1 = (ex_insn >> 7) & 0x1f, (ex_insn >> 15) & 0x1f
        next_wr = 0
        next_rd = 0
        if eop == 0x13 and ef3 == 0 and erd != 0:
            next_wr = 1
            next_rd = ((0 if ers1 == 0 else rf[ers1]) + imm_i(ex_insn)) & 0xffffffff

        # ---- ID stage: control transfer, keyed on `ir` ----
        iop, if3 = ir & 0x7f, (ir >> 12) & 7
        irs1, irs2 = (ir >> 15) & 0x1f, (ir >> 20) & 0x1f
        br_a = 0 if irs1 == 0 else rf[irs1]
        br_b = 0 if irs2 == 0 else rf[irs2]
        if next_wr and erd != 0:                    # EX -> ID bypass
            if erd == irs1:
                br_a = next_rd
            if erd == irs2:
                br_b = next_rd

        npc = pc + 4
        if iop == 0x63 and if3 == 0 and br_a == br_b:
            npc = (ppc + imm_b(ir)) & 0xffffffff    # base is ppc, not pc

        log.append((n, pc & 0xffffffff, ppc & 0xffffffff, ir, ex_pc, ex_insn,
                    npc & 0xffffffff, rf[6], rf[7], rf[8], rf[9], rf[10]))

        # ---- clock edge ----
        if next_wr:
            rf[erd] = next_rd
        new_data = MEM.get(npc & 0xffffffff, 0)
        old_pc = pc
        pc, ppc, ir, ex_insn = npc, pc, imem_data, ir
        ex_pc1, ex_pc = old_pc & 0xffffffff, ex_pc1
        imem_data = new_data

    if show:
        print(f"{'cyc':>3} {'pc':>6} {'ppc':>6} {'ir':>10} {'ex_pc':>6}"
              f" {'ex_insn':>10} {'npc':>6}  x6 x7 x8 x9 x10")
        for r in log:
            print(f"{r[0]:>3} 0x{r[1]:04x} 0x{r[2]:04x} 0x{r[3]:08x}"
                  f" 0x{r[4] & 0xffffffff:04x} 0x{r[5]:08x} 0x{r[6]:04x}"
                  f"  {r[7]}  {r[8]}  {r[9]}  {r[10]}  {r[11]}")
    return log


if __name__ == "__main__":
    log = run()
    fin = log[-1]
    print()
    print(f"FINAL: x6={fin[7]} x7={fin[8]} x8={fin[9]} x9={fin[10]} x10={fin[11]}")
    print("expected: x6=6 x7=7 x8=1 x9=1 x10=1")
    ok = (fin[7], fin[8], fin[9], fin[10], fin[11]) == (6, 7, 1, 1, 1)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
