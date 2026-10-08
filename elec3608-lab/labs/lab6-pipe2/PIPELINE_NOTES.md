# Pipelined NERV — Stages, Control Signals and the Branch Delay Slot

Reference notes for `nerv.sv` (Lab 6, Part 3). Everything here is verified
against an actual Verilator run (`make test_verilator`), not just by inspection.

Contents:

1. [`npc`, `ppc`, `pc`](#1-the-three-pc-signals-npc-ppc-pc)
2. [`IF` — Instruction Fetch](#if--instruction-fetch)
3. [`IF/ID` — the instruction register](#ifid--the-instruction-register)
4. [`ID` — Decode / Register Fetch / control transfer](#id--decode--register-fetch--control-transfer)
5. [`ID/EX` — the operand/control register](#idex--the-operandcontrol-register)
6. [`EX / MA / WB`](#ex--ma--wb--execute-memory-write-back)
7. [Control signals](#7-control-signals)
8. [Branch logic and why there is no bubble](#8-branch-logic-and-why-there-is-no-bubble)
9. [Expected result for `firmware.s`](#9-expected-result-for-firmwares)
10. [The three bugs that were fixed](#10-the-three-bugs-that-were-fixed)
11. [Known limitations](#11-known-limitations)

---

## 1. The three PC signals: `npc`, `ppc`, `pc`

| Signal | Kind | Meaning |
|--------|------|---------|
| `npc` | combinational | **Next** fetch pointer: `pc + 4`, or a branch/jump target. |
| `pc`  | register | The **fetch pointer**. Presented to the instruction memory, so it names the instruction being fetched *now* — not the one being decoded. |
| `ppc` | register | One-cycle-delayed copy of `pc` (`ppc <= pc`). While an instruction is in **ID**, `ppc` is **that instruction's own address**. |

Every non-stalled clock edge:

```systemverilog
ppc <= pc;      // shift the old fetch pointer down
pc  <= npc;     // take the new one
```

### Why `ppc` is the base for a branch offset

`ir` (IF/ID) is **not** aligned with `pc`; it is one fetch behind. So when the
branch instruction is in ID:

* `pc` has already advanced to the **branch delay slot** address, and
* `ppc` still holds **the branch instruction's own address**.

RISC-V branch offsets are relative to the branch instruction itself, hence
`ppc + imm` is the target. Using `pc + imm` lands 4 bytes too far.

---

## IF — Instruction Fetch

| Signal | Role |
|--------|------|
| `pc` | fetch pointer, driven out on `imem_addr` |
| `npc` | next fetch pointer (combinational) |
| `imem_addr` | `= (trap \|\| mem_rd_enable_q) ? imem_addr_q : npc` |
| `imem_data` | instruction word returned by the (synchronous) memory |
| `imem_addr_q` | registered `imem_addr`; holds the address steady during a data read / after a trap |
| `reset`, `reset_q`, `trapped` | force `npc = RESET_ADDR`; freeze `pc` |

* `pc` is a register, `npc` is pure combinational logic.
* On reset `pc <= RESET_ADDR - 4`, so the first real fetch after the reset
  cycle is `RESET_ADDR`.
* While `mem_rd_enable_q` is set (a load completing) the pointer is held at
  `pc`, so no fetch is lost.

## IF/ID — the instruction register

| Signal | Latched from | Role |
|--------|--------------|------|
| `ir` | `imem_data` | the fetched instruction; the ID stage's input |

`ir` is the IF/ID boundary. It is written every cycle, held during a load
stall, and forced to `32'h00000013` (NOP) on reset.

## ID — Decode / Register Fetch / control transfer

| Signal | Role |
|--------|------|
| `id_insn` (= `ir`) | instruction being decoded |
| `id_insn_funct7/rs2/rs1/funct3/rd/opcode` | **explicitly declared** field split of `id_insn` |
| `id_imm_b`, `id_imm_b_sext` | B-type (branch) immediate |
| `id_imm_i`, `id_imm_i_sext` | I-type immediate (JALR) |
| `id_imm_j`, `id_imm_j_sext` | J-type immediate (JAL) |
| `id_rs1_value`, `id_rs2_value` | register-file operands read from the live `ir` |
| `br_a`, `br_b` | those operands **after the EX→ID bypass** |
| `ppc` | the ID instruction's own address (branch offset base) |
| `npc` | control-transfer target is written here |
| `next_wr`, `next_rd`, `insn_rd` | read to implement the bypass |

The ID stage is combinational. It performs decode, the register-file read, and
the **control-transfer decision** for branches and jumps (see §8).

### The EX→ID operand bypass

A branch in ID may depend on the result of the instruction immediately ahead of
it, which is in EX *this cycle* and whose write-back only lands on the clock
edge. Reading the register file alone would return a stale value.

```systemverilog
br_a = id_rs1_value;
br_b = id_rs2_value;
if (next_wr && !mem_rd_enable_q && (insn_rd != 5'd0)) begin
    if (insn_rd == id_insn_rs1) br_a = next_rd;   // EX ALU result
    if (insn_rd == id_insn_rs2) br_b = next_rd;
end
```

`next_rd`/`next_wr` do not depend on `br_a`/`br_b`, so this is not a
combinational loop. This bypass is what makes the supplied `firmware.s` work:
its `beq` compares `x9`, written by the *immediately preceding* `addi`.

## ID/EX — the operand/control register

| Signal | Latched from | Role |
|--------|--------------|------|
| `ex_insn` | `ir` | the instruction now in EX |
| `ex_pc1` | `pc` | `pc` delayed one fetch |
| `ex_pc` | `ex_pc1` | `pc` delayed two fetches = **address of the instruction in EX** |

All are held together during a load stall and forced to NOP/0 on reset, so the
instruction and the address describing it never drift apart.

Does an instruction take two fetch cycles to reach EX? Yes: `imem_data` is
registered and `ir` adds a second register. `ex_pc` compensates for exactly
that, which is why it is a two-deep delay rather than one.

## EX / MA / WB — Execute, Memory, Write-Back

| Signal | Role |
|--------|------|
| `insn` (= `ex_insn`) | instruction being executed |
| `insn_funct7/rs2/rs1/funct3/rd/opcode` | field split of `insn` |
| `imm_i/s/b/j`, `imm_*_sext` | immediate generation |
| `rs1_value`, `rs2_value` | register-file operands, read via the EX instruction's fields |
| `ex_pc` | this instruction's address — used for the AUIPC base and the JAL/JALR link |
| `next_wr`, `next_rd` | register-file write enable and write data |
| `illinsn` | illegal instruction or misaligned target -> sets `trapped` |
| `mem_rd_*` / `mem_wr_*` | data-memory load / store request |
| `mem_rd_enable_q`, `mem_rd_reg_q`, `mem_rd_func_q` | delayed load request (completes the synchronous read one cycle later); also the stall condition |
| `mem_rdata` | load result (byte/half/word, signed or unsigned) |
| `regfile[rd]` | write-back destination |

Because `insn` is `ex_insn`, the whole execute block — ALU, memory request,
trap checks, and the **branch-encoding legality check** — works on registered
operands. Note the branch *decision* is **not** made here (see §8).

---

## 7. Control signals

| Signal | Width | Meaning |
|--------|-------|---------|
| `npc` | 32 | Next fetch address: `pc + 4`, overridden by a taken branch/jump (resolved in ID). |
| `next_wr` | 1 | This EX instruction writes a GPR. |
| `next_rd` | 32 | Value written (ALU result, LUI/AUIPC constant, JAL/JALR link). |
| `illinsn` | 1 | Illegal instruction or misaligned branch/jump target; sets `trapped`. |
| `trapped`, `trapped_q`, `trap` | 1 | Sticky trap flag; stops `pc` and write-back. `trap` is the output. |
| `mem_rd_enable` | 1 | Load issued to data memory. |
| `mem_rd_addr` | 32 | Load address (`rs1 + imm_i`, word aligned). |
| `mem_rd_reg` | 5 | Load destination register. |
| `mem_rd_func` | 5 | Load size/sign selector `{addr[1:0], funct3}`. |
| `mem_rd_enable_q` | 1 | Registered load request (2nd half of the read); also the stall. |
| `mem_rd_reg_q`, `mem_rd_func_q` | 5 | Registered load destination / selector. |
| `mem_wr_enable` | 1 | Store issued. |
| `mem_wr_addr` | 32 | Store address (`rs1 + imm_s`, word aligned). |
| `mem_wr_data` | 32 | Store data (`rs2`, pre-shifted into the byte lane). |
| `mem_wr_strb` | 4 | Byte strobes, shifted by `addr[1:0]`. |
| `dmem_valid` | 1 | `mem_wr_enable \|\| mem_rd_enable`. |
| `dmem_addr` | 32 | Store address if storing, else load address. |
| `dmem_wstrb`, `dmem_wdata` | 4, 32 | Store strobes / data. |
| `dmem_rdata` | 32 | Loaded data. |
| `reset`, `reset_q` | 1 | Reset, and its delayed copy (suppresses the first post-reset edge). |
| `trap` | 1 | Output: processor has trapped. |

---

## 8. Branch logic and why there is no bubble

### The logic (ID stage)

```systemverilog
if (id_insn_opcode == OPCODE_BRANCH)
    case (id_insn_funct3)
        3'b000: if (br_a == br_b)          npc = ppc + id_imm_b_sext;  // BEQ
        3'b001: if (br_a != br_b)          npc = ppc + id_imm_b_sext;  // BNE
        3'b100: if ($signed(br_a) <  $signed(br_b)) npc = ppc + id_imm_b_sext;
        3'b101: if ($signed(br_a) >= $signed(br_b)) npc = ppc + id_imm_b_sext;
        3'b110: if (br_a <  br_b)          npc = ppc + id_imm_b_sext;
        3'b111: if (br_a >= br_b)          npc = ppc + id_imm_b_sext;
    endcase

if (id_insn_opcode == OPCODE_JAL)  npc = ppc + id_imm_j_sext;
if (id_insn_opcode == OPCODE_JALR) npc = (br_a + id_imm_i_sext) & ~32'b1;
```

JAL/JALR links are produced in EX as `next_rd = ex_pc + 8` — `ex_pc` is the
jump's own address there, so `+8` is the instruction past the delay slot, which
is where a return must resume.

### Why exactly one delay slot

Branch at `0x0c`, delay slot at `0x10`, target `0x28` (verified trace):

| cycle | `pc` (fetching) | ID (`ir`) | what happens |
|-------|-----------------|-----------|--------------|
| 4 | `0x0c` | `0x08` addi x9 | branch being fetched |
| 5 | `0x10` | `0x0c` **beq** | ID resolves: `ppc=0x0c`, `a=b=1` -> `npc = 0x28`. The delay slot `0x10` is in the fetch stage. |
| 6 | `0x28` | `0x10` addi x8 | target being fetched; **delay slot is in ID** |
| 7 | `0x2c` | `0x28` addi x7 | **delay slot in EX** (x8 becomes 1); target in ID |
| 8 | `0x30` | `0x2c` addi x6 | target retires (x7 = 7) |

The redirect at cycle 5 changes what is fetched *next*. The delay-slot
instruction had already been fetched, so it is latched into `ir` and retires
normally. Execution then continues at the target.

### No bubble, no flush

* **No bubble (stall):** the delay slot is never lost, so there is no hole to
  fill. The redirect and the delay-slot latch happen on the same edge.
* **No flush:** the instruction fetched after the delay slot is never latched
  into `ir`, because `pc` is redirected before that fetch completes.
* A taken branch costs **zero extra cycles**: exactly one delay-slot
  instruction executes.

This is the MIPS-I / RISC-V scheme the lab sheet asks for: the instruction
after a branch always executes, so it should hold useful work — here
`addi x8, x8, 1`.

### Why the decision must be in ID, not EX

The decode block is keyed on `insn`, and `insn = ex_insn`. If the branch were
resolved there it would be one stage too late: by then the instruction *after*
the delay slot (`0x14`) has already been fetched and reaches `ir`, so it also
retires. The branch would appear to have **two** delay slots, and the target
would be computed from `ppc = 0x10` instead of `0x0c`, landing at `0x2c`
instead of `0x28`. Keying on `id_insn` = `ir` fixes both.

---

## 9. Expected result for `firmware.s`

`firmware.s` performs **no stores**, so it prints **nothing** of its own — there
is no serial/console output. The observable result is the register file when the
`ebreak` traps:

| Register | Value | Why |
|----------|-------|-----|
| `x8`  | **1** | `addi x8,zero,0`, then the **delay slot** `addi x8,x8,1` runs exactly once |
| `x9`  | 1 | `addi x9,zero,1` |
| `x10` | 1 | `addi x10,zero,1` |
| `x7`  | **7** | `jump_here: addi x7,zero,7` — reached because the branch target is correct |
| `x6`  | 6 | `addi x6,zero,6` |
| `trap`| 1 | `ebreak` |

Verified run (`make test_verilator`, `./obj_dir/Vtestbench +vcd`):

```
cyc=5  pc=0x00000010 | ID: ppc=0x0000000c ir=0x00950e63 BRANCH  a=1 b=1 -> npc=0x00000028 | EX: ex_pc=0x00000008 ex_insn=0x00100493
cyc=6  pc=0x00000028 | ID: ppc=0x00000010 ir=0x00140413 ALU-imm | EX: ex_pc=0x0000000c ex_insn=0x00950e63
cyc=7  pc=0x0000002c | ID: ppc=0x00000028 ir=0x00700393 ALU-imm | EX: ex_pc=0x00000010 ex_insn=0x00140413
cyc=8  pc=0x00000030 | ID: ppc=0x0000002c ir=0x00600313 ALU-imm | EX: ex_pc=0x00000028 ex_insn=0x00700393
cyc=9  pc=0x00000034 | ID: ppc=0x00000030 ir=0x00000013 ALU-imm | EX: ex_pc=0x0000002c ex_insn=0x00600313
Simulated 32 cycles
regfile[10]=         1
```

Final register-file contents, read straight out of `testbench.vcd`:

```
x6 = 6    x7 = 7    x8 = 1    x9 = 1    x10 = 1    trap = 1
```

Fetch stream: `0x00, 0x04, 0x08, 0x0c, 0x10, 0x28, 0x2c, 0x30, 0x34`. The
intervening instructions `0x14`–`0x24` are **never fetched** — that is the
single delay slot working correctly.

`nerv.sv` carries a `TRACE` switch (`localparam bit TRACE = 1'b1;`); set it to
`1'b0` to silence the per-cycle line.

---

## 10. The three bugs that were fixed

1. **Wrong offset base.** The six branch cases used a mix of `pc` and `ppc`.
   Only `ppc` is correct: when the branch is in ID, `ppc` is its own address.
   Using `pc` (the delay-slot address) put every taken branch one instruction
   past its target.

2. **The decision was made in the wrong stage.** The decode block is driven by
   `insn`, which is assigned `ex_insn`, so the comparisons and `npc` update
   happened in EX. That is one stage too late: the instruction after the delay
   slot is already in flight, giving two delay slots. The comparison and
   redirect now live in an ID-stage block keyed on `id_insn` (= `ir`).

3. **`id_insn_*` fields were implicit 1-bit nets.** The concatenation
   `assign {id_insn_funct7, id_insn_rs2, ...} = id_insn;` had no declarations,
   so each name became a 1-bit wire. `id_insn_opcode` therefore only ever
   carried **bit 0** of the opcode, and a test like
   `id_insn_opcode == OPCODE_BRANCH` could never match. The fields are now
   declared at their proper widths (`[6:0]`, `[4:0]`, `[2:0]`, ...).

   This is also why an earlier attempt to change only the base appeared to do
   nothing: the branch was not being resolved from `ir` at all.

Bugs 1 and 3 are silent in Verilator because the build uses `-Wno-lint`; the
give-away is in the waveform, where `id_insn_opcode` is listed as a 1-bit
signal.

---

## 11. Known limitations

* **Load-use hazard has no interlock.** The bypass only forwards the EX ALU
  result; a branch in ID depending on a load in EX still reads a stale value,
  and would need a stall or a load-data bypass. The lab sheet defers hazard
  handling to the assignment, and `firmware.s` does not hit this case.
* **Register-file write-back is not visible to the ID read** without the
  bypass described in §4. Any future consumer added to ID needs the same
  treatment.
* **`firmware.s` must obey the delay-slot rule.** The instruction after a
  branch is always executed. In the supplied file that slot holds a useful
  `addi x8,x8,1`; if it were filled with something that must not run on the
  fall-through path the program would have to be rearranged.
* **The IF/ID alignment relies on the registered instruction memory** of
  `testbench.sv`. A purely combinational memory would shift the alignment by
  one cycle and `ppc + imm` would no longer be the right base.
