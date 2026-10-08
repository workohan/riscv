# ass1-2026 — behaviour contract derived from the test suite

`docs/research.md` explains *why* the design must behave this way. This file is
the checkable version: one row per test, the behaviour it exercises, and the
final architectural state it demands. Use it as a debugging checklist — when a
test fails, this tells you which rule you broke.

---

## 1. Golden state per test

`pc` is the value of `dut.pc` when `trap` halts the simulation, i.e. **after** the
`ebreak` that ended the run (except where a handler ended it).

| Test | Exercises | Expected final state |
|---|---|---|
| `firmware00_baseline` | plain RV32I loop, `ebreak` halt | `x0=0`, `x1=52`, `x2=11`, `x3=9` |
| `firmware01_read_mtvec` | `csrrw` read with `rs1=x0` (no write) | `x0=0`, `x1=0x1000` |
| `firmware02_write_mtvec` | write to a read-only CSR is ignored | `x0=0`, `x1=0x1000`, `mtvec=0x1000` |
| `firmware03_write_scratch` | read-modify of a free R/W CSR | `x1=0x123`, `x2=0x0`, `x3=0x123`, `mscratch=0x123` |
| `firmware04_intr` | interrupt enabled and taken | `pc=0x1018`, `x4=0x0`, `mcause=0x8000000B`, `mip=0x800` |
| `firmware05_intr_disabled` | GIE **off**, MEIE on → not taken, but pending latched | `pc=0x0028`, `x4=0x0`, `mcause=0x00`, `mip=0x800` |
| `firmware06_intr_disabled2` | GIE on, MEIE **off** → not taken, but pending latched | `pc=0x0024` *(file says `0x0020` — see `readme-defects.md` §A4)*, `x4=0x0`, `mcause=0x0`, `mip=0x800` |
| `firmware07_mret` | interrupt taken, `mret` returns | `pc=0x30`, `x4=0x0`, `x30=10`, `mcause=0x8000000B`, `mip=0x000` |
| `firmware08_illegal` | illegal instruction traps to `mtvec` | `pc=0x1008`, `mcause=0x00000002`, `mepc=0x14` |
| `firmware09_illegal_mret` | illegal traps, `mret` resumes **after** it | `pc=0x24`, `x1=25`, `mcause=0x00000002`, `mepc=0x14` |

Coverage gaps in the supplied suite, worth filling with your own tests:

- No test reads `mstatus` or `mie` back after writing them.
- `csrrwi`/`csrrsi`/`csrrci` (the immediate forms) are never used — only
  `csrrw` and `csrrs`. The README awards marks for all six.
- No test exercises `csrrc` (clear bits).
- No test reads `mepc` or `mcause` with a *CSR instruction* (they are only
  inspected by the testbench's end-of-run dump).
- Nothing checks behaviour when `GIE` is set but `intr` arrives during trap
  handling.
- `firmware00` is the only test of the base ISA, so regressions in plain ALU /
  branch / load-store behaviour can hide.

---

## 2. Rules, each traced to the test that proves it

| # | Rule | Proved by |
|---|---|---|
| R1 | `csrrw rd, csr, x0` reads the CSR and writes nothing | `firmware01` |
| R2 | Writes to `mtvec` are ignored, and reads always return `0x1000` | `firmware02` |
| R3 | `mscratch` is a full 32-bit read/write CSR | `firmware03` |
| R4 | `csrrw` returns the **old** CSR value in `rd` | `firmware03` (`x2 = 0x0` on the first read) |
| R5 | An interrupt is taken only when `mstatus[3]` **and** `mie[11]` are set | `firmware04` vs `firmware05` vs `firmware06` |
| R6 | `mip[11]` latches on the `intr` pulse **even when masked** | `firmware05`, `firmware06` |
| R7 | Taking an interrupt sets `mcause = 0x8000000B` | `firmware04`, `firmware07` |
| R8 | Taking an interrupt saves the **aborted** instruction's PC in `mepc` | `firmware07` (the countdown loop completes after `mret`; `x4 = 0`) |
| R9 | `pc` takes the `mtvec` value on a taken interrupt | `firmware04` (`pc = 0x1018` inside the handler) |
| R10 | `mret` returns to `mepc` | `firmware07` |
| R11 | `mret` clears `mip[11]` | `firmware07` (`mip = 0x000`) |
| R12 | `mret` does **not** clear `mcause` | `firmware07` (`mcause = 0x8000000B` afterwards) |
| R13 | An illegal instruction sets `mcause = 2` and `mepc = pc + 4` | `firmware08`, `firmware09` |
| R14 | An illegal instruction redirects to `mtvec` and simulation **continues** | `firmware08` (the handler runs) |
| R15 | After `mret`, execution resumes at the instruction **after** the illegal one | `firmware09` (`x1 = 25`, set by the instruction following `fence`) |
| R16 | `ebreak` halts by asserting `trap`, without redirecting and without touching `mcause`/`mepc` | `firmware00` (no handler) and `firmware08` (`mcause` still 2 at the end) |
| R17 | `pc` has advanced past the `ebreak` when it halts | every `pc` expectation in the suite |
| R18 | The `fence` instruction must be treated as **illegal** | `firmware08` |
| R19 | The testbench can index `regfile` and read `csr_*`/`pc` by name | `testbench.sv:138-148` (see `research.md` §8) |

---

## 3. The four outcomes, side by side

```
                        mepc            mcause          pc            trap out
ebreak                  unchanged       unchanged       pc + 4        ASSERTED (halt)
illegal instruction     pc + 4          0x00000002      mtvec         not asserted
interrupt               pc (aborted)    0x8000000B      mtvec         not asserted
mret                    unchanged       unchanged       mepc          not asserted
                                        (not cleared)   mip[11] <- 0
```

The distinction that matters most: **`mcause`/`mepc` describe the *last
exception*, and only an exception writes them.** `ebreak` and `mret` must leave
them alone, which is what lets `firmware08` end with `mcause = 2` after a
handler `ebreak`, and `firmware07` end with `mcause = 0x8000000B` after an
`mret`.

---

## 4. How to run it

```bash
# inside the lab container
make result FIRMWAREFILE=firmware04_intr.hex     # note: FIRMWAREFILE
make allresults                                   # everything, appends results.log
```

`checkregs.py` prints `Total failures = N of M tests`. **If `M` is 0, the `.s`
file has no `expect` comments and the run checked nothing** — always confirm `M`
is non-zero.

Capture the cycle count from the same log (`Simulated %0d cycles`) for the
report's performance section.
