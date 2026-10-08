# ass1-2026 — design research

What the assignment actually requires, derived from `README.md`, the skeleton
`nerv-interrupt.sv`, the test programs, and `testbench.sv`. Where the README and
the tests disagree, **the tests win** — every discrepancy is called out.

Everything here is evidence-backed; each claim names its source file and line.

---

## 1. Zicsr — the six instructions

Opcode `SYSTEM = 7'b1110011`. The CSR number lives in `insn[31:20]`, the source
operand in `insn[19:15]`.

| Instruction | funct3 | Writes CSR from | Reads CSR into | Notes |
|---|---|---|---|---|
| `csrrw  rd, csr, rs1` | `001` | `rs1` | `rd` | if `rs1 == x0`, the CSR is **not written** |
| `csrrs  rd, csr, rs1` | `010` | `old \| rs1` | `rd` | if `rs1 == x0`, no write and **no read side effects** |
| `csrrc  rd, csr, rs1` | `011` | `old & ~rs1` | `rd` | if `rs1 == x0`, no write |
| `csrrwi rd, csr, uimm` | `101` | `uimm` (5-bit zero-extended) | `rd` | if `uimm == 0`, no write |
| `csrrsi rd, csr, uimm` | `110` | `old \| uimm` | `rd` | if `uimm == 0`, no write |
| `csrrci rd, csr, uimm` | `111` | `old & ~uimm` | `rd` | if `uimm == 0`, no write |

Rules that bite in practice:

- **`rd == x0` still performs the CSR write**, but must not read the CSR. The
  tests rely on this: `csrrs x0, mstatus, x1` (e.g. `firmware04_intr.s:18`) is
  the standard "set bits without a read" idiom.
- **`rs1 == x0` on `csrrw` means no write.** `firmware01_read_mtvec.s` uses
  `csrrw x1, mtvec, x0` purely to read, and its comment notes the zero-register
  trick.
- For `csrrs`/`csrrc` the write must be derived from the **old** CSR value and
  the mask, not from a previously computed `rdata`.
- The skeleton's `csrfile` gives you bit-wise `re`/`we` enables for exactly this
  reason: `rdata = csr & re`, and each bit latches when `we[i]`. Driving `re`
  as all-ones and `we` as the per-bit mask is the intended usage.

Source: README lines 14, 101-106; `nerv-interrupt.sv:67-129`.

---

## 2. CSR map and access rules *for this assignment*

Addresses from the skeleton's own localparams (`nerv-interrupt.sv:20-27`).

| CSR | Address | Spec name | Read | Write | Implemented where |
|---|---|---|---|---|---|
| `mstatus` | `0x300` | `mstatus` | yes | yes (bit 3 only) | `csrfile` internal FF (skeleton) |
| `mie` | `0x304` | `mie` | yes | yes (bit 11 only) | `csrfile` internal FF (skeleton) |
| `mtvec` | `0x305` | `mtvec` | **yes** | ignored | read-only; wire it to `MTVEC_ADDR` |
| `mscratch` | `0x340` | `mscratch` | yes | yes (all 32 bits) | `csrfile` internal FF (skeleton) |
| `mepc` | `0x341` | `mepc` | yes | yes | your processor logic |
| `mcause` | `0x342` | `mcause` | yes | yes | your processor logic |
| `mip` | `0x344` | `mip` | yes | **read-only** | your processor logic |

**mtvec is readable, not write-only.** `firmware01_read_mtvec.s` reads it
(`csrrw x1, mtvec, x0`) and expects `x1 = 0x1000`; `firmware02_write_mtvec.s`
writes a junk value through it and expects both `x1` and `mtvec` to still read
`0x1000`, proving writes are ignored. README line 53 calls it "write only",
which contradicts both.

**Non-CSR hardware registers.** The README's simplified model gives `mstatus`
only one meaningful bit and `mie`/`mip` only bit 11. There is **no `MPIE`** and
no privilege stack — this is *not* spec-conformant RISC-V, and the report should
say so rather than implying full privileged-mode support.

Source: README lines 17-24, 47-57; `nerv-interrupt.sv:20-27`;
`firmware01_read_mtvec.s`, `firmware02_write_mtvec.s`.

---

## 3. `mstatus` GIE is bit 3, not bit 0  ⚠️

**README line 49 says the global interrupt enable is at "position 0". Every test
program sets bit 3.**

| File | Code | Comment |
|---|---|---|
| `firmware04_intr.s:17-18` | `addi x1, x0, 0x8` / `csrrs x0, mstatus, x1` | `/* enable MIE bit */` |
| `firmware06_intr_disabled2.s:17-18` | same | `/* enable MIE bit */` |
| `firmware07_mret.s:17-18` | same | `/* enable MIE bit */` |

`0x8` is bit 3 — the real `mstatus.MIE` position, and the tests even name it
`MIE` rather than `GIE`.

Consequences of following the README:

- `firmware04_intr.s` expects `mcause = 0x8000000B` and `pc = 0x1018`. If GIE
  lives at bit 0 it is never set, the interrupt is permanently masked, the
  handler never runs, and the program ends on its own `ebreak` instead.
- `firmware07_mret.s` expects `x30 = 10` ("proof we got here") and
  `pc = 0x30` — likewise unpassable.

`firmware05`/`firmware06` pass either way (both expect *not taken*), so they do
not disambiguate. **Implement the enable at bit 3.** README line 49 is a defect.

---

## 4. Traps, interrupts and the `trap` output

This is the part most likely to be misread, because `trap` is **not** the
exception signal.

### `trap` is the halt output

`testbench.sv:134-151` ends the simulation when `trap` is high, then dumps the
register file, the seven CSRs and `pc`. So `trap` must be asserted to *stop the
run*.

### `ebreak` halts; it does not trap

`firmware00_baseline.s` ends with a bare `ebreak`, has no `mtvec` handler, and
checks only the register file. `firmware08_illegal.s` puts an `ebreak` in the
handler and expects `pc = 0x1008` — the address *after* that `ebreak`. So:

```
ebreak  ->  assert trap (halt the simulation)
            do NOT redirect to mtvec
            do NOT modify mcause
            do NOT modify mepc
```

The "do not modify `mcause`" part matters: `firmware08` expects
`mcause = 0x00000002` at the end, a value set earlier by the `fence` trap. If
`ebreak` overwrote `mcause` the expectation would break.

### An illegal instruction traps *and keeps running*

`firmware08_illegal.s` executes `fence` at `0x10` and expects
`mcause = 2`, `mepc = 0x14`, and `pc = 0x1008` — i.e. the processor redirected
to `mtvec` (`0x1000`), ran the handler, and halted there. So an illegal
instruction:

```
illegal ->  mepc  <- pc + 4          (the NEXT instruction; the trap is not re-run)
            mcause <- 2              (int = 0)
            pc    <- mtvec (0x1000)
            continue simulating      (trap output NOT asserted)
```

`firmware09_illegal_mret.s` confirms the return path: the handler's `mret` sends
execution back to `mepc = 0x14`, the instruction *after* the illegal one, and
`x1` ends at 25 — the value written by the instruction after `fence`, proving the
illegal instruction was skipped rather than re-run.

### Interrupt

```
interrupt (intr && GIE && MIE.MEIE) ->
            mepc   <- pc            (the ABORTED instruction; it must be re-run)
            mcause <- 0x8000000B    (int = 1, cause = 11)
            mip.MEIP set            (pending, latched from the intr pin)
            pc     <- mtvec
            GIE cleared             (see §5 — inferred, not tested)
```

`firmware04`/`firmware07` both expect `mcause = 0x8000000B`. Note the *comment*
in those files says `(int=1,cause=16)` — **11 is correct** (`0xB`), and README
line 30 also says 11. The firmware comments are wrong.

### `mepc` differs between trap and interrupt

README line 119 states it correctly: **interrupt → the aborted instruction
(must re-run); trap → the next instruction (must be skipped).** The tests pin
both down (`firmware08`/`09`: `mepc = 0x14` after a trap at `0x10`).

### `mip` latches even when masked

`firmware05_intr_disabled.s` (GIE off, MEIE on) and
`firmware06_intr_disabled2.s` (GIE on, MEIE off) both expect `mip = 0x800` while
`mcause = 0`. So the pending bit is set by the `intr` pin **regardless of
masking**, is read-only, and is cleared only by `mret` (`firmware07` expects
`mip = 0x000` afterwards).

Source: README lines 28-30, 55, 118-137; `testbench.sv:132-152`; all firmware.

---

## 5. Under-specified areas — decide these and write them down

The tests do **not** pin these down, so pick a behaviour, document it in the
report, and make the code match.

1. **Does taking an interrupt clear GIE?** Standard RISC-V saves `MIE` into
   `MPIE` and clears `MIE`, preventing nested interrupts. This assignment has no
   `MPIE` field. If you clear GIE on entry you must restore it on `mret`, or
   `firmware07` would still pass (it only takes one interrupt) but the design
   would be self-inconsistent. **Recommendation:** clear bit 3 on trap entry and
   set it again on `mret`, and say so in the report.
2. **Does `mret` clear GIE or set it?** README line 137 says it "sets the
   `mstatus` bit back to user mode", which is garbled. `mret` also must clear
   `mip.MEIP` per README line 55 and `firmware07`.
3. **What `mcause` does `mret` leave behind?** `firmware07` expects
   `0x8000000B` *after* the `mret`, so **do not clear `mcause`**.
4. **Priority when an illegal instruction and a pending interrupt coincide.**
   Not tested. Traps are synchronous and normally take priority over interrupts.
5. **What happens if an illegal instruction is fetched inside the handler?**
   Not tested; avoid an infinite trap loop only if it is cheap to do.
6. **`mtvec` mode.** README line 128 says BASE mode (all traps to one address),
   which is what the tests assume — the handler is at `0x1000` for every cause.

---

## 6. Pipeline considerations

The assignment asks for a **single-cycle and a 2-stage pipelined** version
(README lines 15, 77), so `mepc` and the interrupt interaction must be correct in
both. Specific hazards for the pipelined case:

- **Where to sample `intr`.** It is a 1-cycle-synchronous pulse
  (`testbench.sv:154-166`, and README line 140). Sample it in a single stage to
  avoid double-taking the same interrupt.
- **What is `mepc` for an interrupt?** It must be the PC of the instruction that
  is *aborted*. In a 2-stage pipe the instruction in ID when the interrupt is
  accepted is the one to re-run; the instruction in IF must be squashed and
  re-fetched after `mret`. Getting this wrong shows up as a silently skipped or
  duplicated instruction.
- **`mcause`/`mepc` writes versus the GPR write path.** Trap entry writes CSRs on
  the same edge as normal instructions retire; make sure a trapping instruction
  does not also write back a GPR result.
- **Branch delay slot interaction.** Your lab-6 pipeline executes the
  instruction after a branch unconditionally. If an interrupt is accepted on the
  cycle a delayed branch redirects the PC, decide explicitly whether the delay
  slot still executes. Simplest consistent rule: **the delay slot always
  executes** (that is what "always executed" means), and `mepc` points at the
  instruction after it.
- **Hazards in the pipelined design** must be discussed in the report
  (README line 66). The README hints the marker cares: "Discuss what hazards
  exist in the pipelined design, and how they are tested and mitigated."
- **`ebreak` must not race the halt.** Because `trap` stops the simulation
  immediately, `pc` must already have advanced past the `ebreak` when it is
  asserted — every `pc` expectation in the suite is "PC **after** ebreak".

Source: README lines 15, 66, 77, 85, 140; `testbench.sv:129-166`.

---

## 7. Timing budget — why the test programs look the way they do

Derived from `testbench.cpp` and `testbench.sv`:

- `testbench.cpp` runs `t += 5` per loop iteration, toggling the clock each
  iteration, and clears `reset` only when `t > 200`. That is 41 iterations ≈
  **21 posedges before reset is released.**
- `testbench.sv:154-166` increments `c` on every posedge from time zero and
  raises `intr` when `c >= ton_intr (35)`, dropping it at `toff_intr (36)` — a
  **single-cycle pulse**.
- Therefore the interrupt fires roughly **14 cycles after reset is released**,
  regardless of the program.

That is why every interrupt test spends its first ~8 instructions setting up
`mstatus`/`mie` and then enters a long countdown loop (`addi x4, x4, -1; bne`)
before the trailing `ebreak`: the setup must finish, and the loop must still be
running when the pulse arrives. Practical consequences:

- Do not add instructions to the setup block of those tests.
- Keep the countdown long enough to cover the remaining cycles.
- The parameter values `ton_intr`/`toff_intr` are parameters of `testbench.sv`
  and can be overridden with `-G` if you need the interrupt earlier or later —
  useful for directed tests of your own.

---

## 8. The DUT signal-name contract (undocumented requirement) ⚠️

`testbench.sv:138-148` reaches directly into the DUT hierarchy:

```systemverilog
dut.regfile[r]        for r in 0..31      // indexable array of 32
dut.pc
dut.csr_mepc   dut.csr_mie     dut.csr_mtvec   dut.csr_mip
dut.csr_mcause dut.csr_mstatus dut.csr_mscratch
```

**None of these exist in the skeleton, and the README never mentions them.** If
you name them anything else, Verilator fails to elaborate the testbench and the
*entire* test suite breaks — with an error that points at `testbench.sv`, not at
your design.

Required declarations in `nerv-interrupt.sv`:

```systemverilog
logic [31:0] regfile [0:31];   // must be indexable as regfile[r]
logic [31:0] pc;
logic [31:0] csr_mepc, csr_mie, csr_mtvec, csr_mip,
             csr_mcause, csr_mstatus, csr_mscratch;
```

Because the file starts with `` `default_nettype none ``, any typo here is a
hard error rather than a silent implicit wire — which is helpful, and worth
keeping.

`lint/check_contract.py` in this toolkit checks for these names without needing
Verilator.

---

## 9. How the test harness works

```
make                            # builds one firmware and runs it
make result FIRMWAREFILE=x.hex  # NOTE: FIRMWAREFILE, not FIRMWARE
make allresults                 # runs every firmware in ALLFIRMWARE, appends to results.log
```

- `%.hex` is built from `%.s` with `riscv64-unknown-elf-gcc -march=rv32i …`.
- `test_verilator` compiles `testbench.sv nerv-interrupt.sv testbench.cpp` with
  `-Gfirmwarefile=\"$(FIRMWAREFILE)\"` and runs `./obj_dir/Vtestbench +vcd`,
  redirecting stdout to `<firmware>.log`.
- On `trap`, the testbench prints one line per register and CSR:
  `h0:x%-2d=0x%-0x`, `h0:mepc=…`, `h0:pc=…`.
- `checkregs.py` regex-matches those lines against `expect h0:<name> = <value>`
  comments inside the `.s` file and reports `Total failures = N of M`.

Gotchas:

- The `.s` file must contain the expected values **as comments** or the test
  silently checks nothing (`0 of 0 tests`).
- `make clean` includes `rm -rf *.log`, which **deletes `results.log`.**
- `make show` expects a `testbench.gtkw` that does not exist in this repo.
- Values are compared as integers, so `0x1000` and `4096` are equivalent, but
  trailing text in the expectation is ignored by the regex — keep the value
  first.

Source: `Makefile`, `checkregs.py`, `testbench.cpp`, `testbench.sv`.

---

## 10. Report checklist

README lines 61-71 and the appendix requirements, mapped to what to produce:

| Requirement | Where it is satisfied |
|---|---|
| 4 pages, A4 IEEE format, default fonts | the report itself |
| Sections: Introduction, Background, Architecture, Results, Discussion, Conclusion, References, Appendices | structure |
| Datapath design of all major components: high-level description, dataflow diagram, implementation of subsystems | Architecture section — the diagrams built for lab 6 can be adapted |
| "the SystemVerilog code follows the datapath design, not the other way around" | draw the datapath first, then show the code matching it |
| Performance: cycles per program, with evidence | `Simulated %0d cycles` from `testbench.sv:135`; capture for every firmware |
| Hazards: what exists, how tested, how mitigated | Discussion section |
| Discussion of whether the result is good, and how to improve | Discussion/Conclusion |
| Appendices: code, simulations, log files | `*.log` from each run, VCD screenshots |

Requirements scoring (README lines 14-32): Zicsr = 2 marks (1 single-cycle, 1
pipelined), CSRs = 1, `mret` = 1, PC mux / exceptions = 1, report = 5.

---

## 11. Quick reference — the behaviours to implement

```
RESET            pc <- 0; all CSRs <- 0; mip <- 0
                 mtvec is hard-wired to MTVEC_ADDR (0x1000), writes ignored, reads as 0x1000
                 mstatus: only bit 3 writable, reads as 0 elsewhere
                 mie:     only bit 11 writable, reads as 0 elsewhere
                 mscratch: all 32 bits read/write

CSRRW/CSRRS/CSRRC/CSRRWI/CSRRSI/CSRRCI
                 read old value into rd (unless rd == x0)
                 write per the op and the rs1 == x0 / uimm == 0 suppression rules

EBREAK           assert trap; pc advances; mcause/mepc unchanged

ILLEGAL INSN     mepc <- pc + 4; mcause <- 2; pc <- mtvec; keep running; trap NOT asserted

INTR PULSE       mip.MEIP <- 1, always (even when masked; latched)

INTERRUPT TAKEN  (intr && mstatus[3] && mie[11])
                 mepc <- pc (the aborted instruction); mcause <- 0x8000000B
                 pc <- mtvec; GIE cleared (recommended, document it)

MRET             pc <- mepc; mip.MEIP <- 0; GIE restored if you cleared it
                 mcause left alone
```
