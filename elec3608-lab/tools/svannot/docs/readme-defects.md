# `labs/ass1-2026/README.md` — defect report

Line numbers refer to the README as committed. Defects are split by whether they
can cost marks, break the toolchain, or are cosmetic.

---

## A. Substantive — will cost marks if followed literally

### A1. `mstatus` global interrupt enable is at bit 3, not bit 0

**Line 49:** "The `MSTATUS` register will contain only a single global interrupt
enable (GIE) bit at position 0."

Every interrupt test enables it at **bit 3**:

| File | Line | Code | Comment |
|---|---|---|---|
| `firmware04_intr.s` | 17-18 | `addi x1, x0, 0x8` / `csrrs x0, mstatus, x1` | `/* enable MIE bit */` |
| `firmware06_intr_disabled2.s` | 17-18 | same | `/* enable MIE bit */` |
| `firmware07_mret.s` | 17-18 | same | `/* enable MIE bit */` |

`0x8` is bit 3 — the real `mstatus.MIE` position — and the tests name it `MIE`,
not `GIE`.

**Impact:** implementing bit 0 makes the interrupt permanently masked, so
`firmware04` (`mcause = 0x8000000B`, `pc = 0x1018`) and `firmware07`
(`x30 = 10`, `pc = 0x30`) cannot pass. `firmware05`/`06` pass either way, so they
do not reveal the problem.

**Fix:** change line 49 to "bit at position 3", or implement bit 3 and note the
divergence.

### A2. README contradicts itself on `mtvec` access

- **Line 53:** "The `MTVEC` register will be **write only** and hard wired to the
  address 0x1000. Writes are ignored."
- **Line 128:** "We will use a hard-coded value of `0x1000`, so `mtvec` will be
  **read-only**".

"Write only" and "writes are ignored" cannot both hold. The tests settle it:
`firmware01_read_mtvec.s` **reads** mtvec and expects `x1 = 0x1000`, and
`firmware02_write_mtvec.s` writes junk through it and expects `mtvec` to still
read `0x1000`. So it is **read-only**: reads return `0x1000`, writes are ignored.

**Fix:** delete "write only" from line 53.

### A3. `mstatus` is listed as read-only, then treated as writable

- **Line 21:** "`mstatus` Machine status **(read only)**"
- **Line 49:** describes *setting* the GIE bit.
- `firmware04`/`06`/`07` all write it with `csrrs x0, mstatus, x1`.

**Fix:** drop "(read only)" from line 21.

### A4. `firmware06`'s `pc` expectation is off by one instruction

`firmware06_intr_disabled2.s` has 9 instructions in its main program, placing
`ebreak` at `0x20`, so the PC after it is `0x24`. The file expects:

```
expect h0:pc = 0x0020 (PC after ebreak)
```

Five other tests follow the "PC **after** ebreak" rule and are self-consistent:

| File | insns | `ebreak` at | PC after | expected | ok |
|---|---|---|---|---|---|
| `firmware05_intr_disabled.s` | 10 | `0x24` | `0x28` | `0x28` | ✓ |
| `firmware06_intr_disabled2.s` | 9 | `0x20` | `0x24` | `0x20` | ✗ |
| `firmware07_mret.s` | 12 | `0x2c` | `0x30` | `0x30` | ✓ |
| `firmware09_illegal_mret.s` | 9 | `0x20` | `0x24` | `0x24` | ✓ |
| `firmware04_intr.s` (handler) | 6 | `0x1014` | `0x1018` | `0x1018` | ✓ |
| `firmware08_illegal.s` (handler) | 2 | `0x1004` | `0x1008` | `0x1008` | ✓ |

**Impact:** chasing a phantom bug in your processor when the test is wrong.

**Fix:** `expect h0:pc = 0x0024`. This toolkit applies that one-token fix.

---

## B. Interface / toolchain

### B1. Wrong make variable in the documented command

**Line 35:** "use the command `make result FIRMWARE=filename.hex`".

The Makefile defines `FIRMWAREFILE`, and its `result` target depends on
`$(FIRMWAREFILE)`. `make result FIRMWARE=x.hex` silently builds the default
firmware instead of `x.hex`.

**Fix:** document `make result FIRMWAREFILE=filename.hex`.

### B2. The DUT signal-name contract is never documented

`testbench.sv` lines 138-148 reference `dut.regfile[r]`, `dut.pc`,
`dut.csr_mepc`, `dut.csr_mie`, `dut.csr_mtvec`, `dut.csr_mip`,
`dut.csr_mcause`, `dut.csr_mstatus`, `dut.csr_mscratch`.

None appear in the README or the skeleton. Wrong names make the testbench fail to
elaborate, breaking the whole suite with an error pointing at `testbench.sv`
rather than at the design.

**Fix:** add a short "required internal signal names" section to the README, or
at minimum note the requirement in "Code format" (line 41-44, which currently
only says to connect the CSR bits and the `intr` port).

### B3. Submission section says "two separate files" but lists three

**Line 75:** "submitted online as two separate files (a .pdf and  two .sv files)"
— double space, and that is three files.

**Fix:** "as three files (a .pdf report and two .sv design files)".

### B4. `mip` bit 11 is named `MEIE`, which is the `mie` name

**Line 55:** "The `MIP` register will contain a single bit at position 11
**(MEIE)**".

In the ISA, bit 11 of `mie` is `MEIE` (enable) and bit 11 of `mip` is `MEIP`
(pending). Using `MEIE` for both is confusing in a design where the two bits have
different roles.

**Fix:** call the `mip` bit `MEIP`.

### B5. `testsuites` should be "test suites"

**Line 37.** Minor, but it is prose in a spec.

---

## C. Wording and typos

| Line | Text | Should be |
|---|---|---|
| 9 | "located in the Privleged Instructions specifications" | "Privileged" |
| 26 | "restore the state of the processor to whatever instruction was executing when the exception occurred" | imprecise: for a **trap**, `mepc` is the *next* instruction (line 119 says so correctly) |
| 30 | "external platform interrupt interrupt (intr=1,cause=11)" | "external platform interrupt" |
| 34 | "The machine marked parts will consider correctness and performance." | garbled — probably "The marked parts will be assessed for correctness and performance." |
| 44 | "you must connect the external interrupt port input to test that an unexpected interrupt continues code as expected" | awkward |
| 59 | "has been deemed "illegal", and use to stop the simulation" | "used to" |
| 68 | "you could following a similar style for your report" | "could follow" |
| 69 | "assume that the reader is familiar computer architecture in general" | "familiar with computer architecture" |
| 77 | "System Verilog files" | "SystemVerilog files" |
| 80 | "unless chaged by Jump or Branch instructions" | "changed" |
| 85 | "a trap generally occurs at the Execute (EX) or Memory (MEM) phases" | the labs call this stage MA, not MEM |
| 95 | "exceptions invoke a _priviliged_ instruction mode" | "privileged" |
| 99 | "Unlike `JALR/JALR`" | "Unlike `JAL/JALR`" |
| 99 | "the compliler didn't know" | "compiler" |
| 106 | "CSRs with different levels of priviliged" → "priviliged" | "privilege" (the sentence reads "…what makes them priviliged or not…") |
| 128 | "The `mtvec` register contains the value of the `PC` is to take when the exception occurs." | garbled — "contains the value the `PC` is to take" |
| 137 | "sets the `mstatus` bit back to user mode" | "clears the global interrupt enable" (and see §A1 — there is no privilege switching) |

---

## D. Test-program comments that contradict the tests

Not README defects, but they will mislead you while debugging.

| File | Issue |
|---|---|
| `firmware04_intr.s`, `firmware07_mret.s` | `expect h0:mcause = 0x8000000B (int=1,cause=16)` — cause is **11**, not 16 (`0xB`). README line 30 and the hardware both say 11. |
| `firmware04_intr.s` handler | address comments skip a word: `nop` `0x1000`, `addi` `0x1004`, `addi` `0x1008`, `bne` labelled `0x1010`, `nop` `0x1014`, `ebreak` `0x1018`. Real addresses are `0x1000, 0x1004, 0x1008, 0x100c, 0x1010, 0x1014`. |
| `firmware05_intr_disabled.s` | `ebreak; /* addr 0x0028 */` — the instruction is at `0x24`; `0x28` is the PC *after* it (which is what the expectation checks). |
| `firmware08_illegal.s` | `expect h0:mepc = 0x14 (return address after )` — trailing truncated parenthetical. |
| `firmware02_write_mtvec.s` | comment says "No read due to zero bits of x0" but the instruction is `csrrw x1, mtvec, x1` — `rd` is `x1`, so it *does* read. |
| `firmware01`/`04`/`05`/`06` | "see Unprivileged ISR pg 49" — page reference is to a specific spec revision and will drift; cite the section instead. |

---

## E. Harness defects worth knowing

These are in the Makefile / scripts rather than the README.

1. `make clean` runs `rm -rf *.log`, which **deletes `results.log`** — the
   accumulated `make allresults` output.
2. `make show` opens `testbench.gtkw`, which does not exist in this repository,
   so the target fails.
3. `all: … # nerv.asc` — the FPGA flow is commented out and `nerv.yosys` is
   absent, so `make nerv.asc` cannot work. Not needed for this assignment.
4. The testbench's `intr` pulse time (`ton_intr=35`, `toff_intr=36`) is a fixed
   cycle count, so test programs are timing-sensitive. Override with `-G` when
   writing directed tests.
5. `checkregs.py` reports `Total failures = 0 of 0 tests` when a `.s` file has no
   `expect` comments — a green result that checks nothing.
