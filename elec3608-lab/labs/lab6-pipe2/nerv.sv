/*
 *  NERV -- Naive Educational RISC-V Processor
 *
 *  Copyright (C) 2020  Claire Xenia Wolf <claire@yosyshq.com>
 *
 *  Permission to use, copy, modify, and/or distribute this software for any
 *  purpose with or without fee is hereby granted, provided that the above
 *  copyright notice and this permission notice appear in all copies.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 *  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 *  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 *  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 *  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 *  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 *  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 *
 */

module nerv #(
    parameter [31:0] RESET_ADDR = 32'h0000_0000,
    parameter integer NUMREGS = 32
) (
    input  clock,
    input  reset,
    output trap,

    // we have 2 external memories
    // one is instruction memory
    output [31:0] imem_addr,
    input  [31:0] imem_data,

    // the other is data memory
    output        dmem_valid,
    output [31:0] dmem_addr,
    output [ 3:0] dmem_wstrb,
    output [31:0] dmem_wdata,
    input  [31:0] dmem_rdata
);
    logic mem_wr_enable;
    logic [31:0] mem_wr_addr;
    logic [31:0] mem_wr_data;
    logic [3:0] mem_wr_strb;

    logic mem_rd_enable;
    logic [31:0] mem_rd_addr;
    logic [4:0] mem_rd_reg;
    logic [4:0] mem_rd_func;

    logic mem_rd_enable_q;
    logic [4:0] mem_rd_reg_q;
    logic [4:0] mem_rd_func_q;

    logic [31:0] ppc;
    logic [31:0] ir;

    // delayed copies of mem_rd
    always @(posedge clock) begin
        mem_rd_enable_q <= mem_rd_enable;
        mem_rd_reg_q <= mem_rd_reg;
        mem_rd_func_q <= mem_rd_func;
        if (reset) begin
            mem_rd_enable_q <= 0;
        end
    end

    // memory signals
    assign dmem_valid = mem_wr_enable || mem_rd_enable;
    assign dmem_addr  = mem_wr_enable ? mem_wr_addr : mem_rd_enable ? mem_rd_addr : 32'hx;
    assign dmem_wstrb = mem_wr_enable ? mem_wr_strb : mem_rd_enable ? 4'h0 : 4'hx;
    assign dmem_wdata = mem_wr_enable ? mem_wr_data : 32'hx;

    // registers, instruction reg, program counter, next pc
    logic [31:0] regfile[0:NUMREGS-1];
    logic [31:0] npc;
    logic [31:0] pc;

    logic [31:0] imem_addr_q;


    always @(posedge clock) begin
        imem_addr_q <= imem_addr;
    end

    // instruction memory pointer
    assign imem_addr = (trap || mem_rd_enable_q) ? imem_addr_q : npc;


    // ---------------------------------------------------------------
    // IF/ID and ID/EX pipeline registers.
    //
    //   ir     : IF/ID  - the fetched instruction word (ID stage)
    //   ex_insn: ID/EX  - the instruction being executed (EX stage)
    //   ex_pc  : ID/EX  - the address that instruction was fetched from
    //
    // An instruction takes TWO fetch cycles to travel from `pc` into
    // `ex_insn`, because the instruction memory returns its data one
    // cycle after its address is presented, and `ir` adds one more:
    //
    //   edge N   : pc = A          address A presented to imem
    //   edge N+1 : imem_data = insn(A)   -> latched into ir
    //   edge N+2 : ir = insn(A)          -> latched into ex_insn
    //
    // `ex_pc` therefore has to be delayed by the same two registers
    // (pc -> ex_pc1 -> ex_pc) so that it still remembers A at the moment
    // insn(A) reaches EX.  It is used for the trace output; branch
    // offsets are resolved in ID against `ppc` (see the branch case).
    // ---------------------------------------------------------------
    logic [31:0] ex_insn;
    logic [31:0] ex_pc1;     // pc delayed by one fetch cycle
    logic [31:0] ex_pc;      // pc delayed by two fetch cycles == address in EX
    always @(posedge clock) begin
        // ir <= imem_data;  // label: ir is set here, represents the instruction for the id stage
        // ex_insn <= ir; // label: the instruction for the execute stage
        if (reset) begin
                   ir <= 32'h00000013;       // NOP
                   ex_insn <= 32'h00000013;  // NOP
                   ex_pc1 <= 32'h00000000;
                   ex_pc <= 32'h00000000;
               end else if (mem_rd_enable_q) begin
                   // Stall: do not update ex_insn so it replays after memory load
               end else begin
                   ir <= imem_data;
                   ex_insn <= ir;
                   ex_pc1 <= pc;
                   ex_pc <= ex_pc1;
               end

    end


    // ---------------------------------------------------------------
    // ID stage: decode of the instruction in IR.
    //
    // This stage does instruction decode, the register-file read, and
    // the next-PC decision (branches and jumps).  Resolving control
    // transfers here is what gives the design its single delay slot:
    // by the time the branch is in IR, the instruction after it has
    // already been fetched, so redirecting npc now leaves that
    // instruction in flight.  It arrives in IR on the next edge and
    // retires normally - no bubble and no flush is required.
    // ---------------------------------------------------------------
    wire [31:0] id_insn;
    assign id_insn = ir; // label: just an alias

    // split R-type instruction - see section 2.2 of RiscV spec
    //
    // NOTE: these MUST be explicitly declared.  Without the declarations
    // below they become implicit 1-bit nets, so e.g. `id_insn_opcode` would
    // only ever carry bit 0 of the real opcode and the ID-stage control
    // transfer test would never match OPCODE_BRANCH.
    wire [ 6:0] id_insn_funct7;
    wire [ 4:0] id_insn_rs2;
    wire [ 4:0] id_insn_rs1;
    wire [ 2:0] id_insn_funct3;
    wire [ 4:0] id_insn_rd;
    wire [ 6:0] id_insn_opcode;
    assign {id_insn_funct7, id_insn_rs2, id_insn_rs1, id_insn_funct3, id_insn_rd, id_insn_opcode} = id_insn; // label: split for id

    // B - conditionals
    wire [12:0] id_imm_b;
    assign {id_imm_b[12], id_imm_b[10:5]} = id_insn_funct7,
        {id_imm_b[4:1], id_imm_b[11]} = id_insn_rd,
        id_imm_b[0] = 1'b0;

    wire [31:0] id_imm_b_sext = $signed(id_imm_b);

    // I - short immediates and loads
    wire [11:0] id_imm_i;
    assign id_imm_i = id_insn[31:20];
    wire [31:0] id_imm_i_sext = $signed(id_imm_i);

    // J - unconditional jumps
    wire [20:0] id_imm_j;
    assign {id_imm_j[20], id_imm_j[10:1], id_imm_j[11], id_imm_j[19:12], id_imm_j[0]} =
        {id_insn[31:12], 1'b0};
    wire [31:0] id_imm_j_sext = $signed(id_imm_j);


    // rs1 and rs2 sourced from the ID-stage instruction, i.e. the operands
    // used by the control-transfer comparison in the ID stage.
    wire [31:0] id_rs1_value = !id_insn_rs1 ? 0 : regfile[id_insn_rs1];
    wire [31:0] id_rs2_value = !id_insn_rs2 ? 0 : regfile[id_insn_rs2];

    // EX -> ID operand bypass.  A branch/jump in ID may depend on the result
    // of the instruction immediately ahead of it, which is in EX this cycle
    // and whose write-back only lands on this clock edge.  `next_wr`/`next_rd`
    // are exactly that result, computed from `insn` (= ex_insn) in the block
    // below; they do not depend on br_a/br_b, so there is no combinational loop.
    logic [31:0] br_a, br_b;
    // ----------

    // ---------- FOR EX
    logic [31:0] insn;
    assign insn = ex_insn; // label: move instruction decoding to stage 2 for simplicity

    // rs1 and rs2 are source for the instruction
    wire [31:0] rs1_value = !insn_rs1 ? 0 : regfile[insn_rs1];
    wire [31:0] rs2_value = !insn_rs2 ? 0 : regfile[insn_rs2];

    // components of the instruction
    wire [ 6:0] insn_funct7;
    wire [ 4:0] insn_rs2;
    wire [ 4:0] insn_rs1;
    wire [ 2:0] insn_funct3;
    wire [ 4:0] insn_rd;
    wire [ 6:0] insn_opcode;

    // split R-type instruction - see section 2.2 of RiscV spec
    assign {insn_funct7, insn_rs2, insn_rs1, insn_funct3, insn_rd, insn_opcode} = insn;

    // setup for I, S, B & J type instructions
    // I - short immediates and loads
    wire [11:0] imm_i;
    assign imm_i = insn[31:20];

    // S - stores
    wire [11:0] imm_s;
    assign imm_s[11:5] = insn_funct7, imm_s[4:0] = insn_rd;

    // B - conditionals
    wire [12:0] imm_b;
    assign {imm_b[12], imm_b[10:5]} = insn_funct7,
        {imm_b[4:1], imm_b[11]} = insn_rd,
        imm_b[0] = 1'b0;

    // J - unconditional jumps
    wire [20:0] imm_j;
    assign {imm_j[20], imm_j[10:1], imm_j[11], imm_j[19:12], imm_j[0]} = {insn[31:12], 1'b0};

    wire [31:0] imm_i_sext = $signed(imm_i);
    wire [31:0] imm_s_sext = $signed(imm_s);
    wire [31:0] imm_b_sext = $signed(imm_b);
    wire [31:0] imm_j_sext = $signed(imm_j);
    // -----------

    // opcodes - see section 19 of RiscV spec
    localparam OPCODE_LOAD = 7'b00_000_11;
    localparam OPCODE_STORE = 7'b01_000_11;
    localparam OPCODE_MADD = 7'b10_000_11;
    localparam OPCODE_BRANCH = 7'b11_000_11;

    localparam OPCODE_LOAD_FP = 7'b00_001_11;
    localparam OPCODE_STORE_FP = 7'b01_001_11;
    localparam OPCODE_MSUB = 7'b10_001_11;
    localparam OPCODE_JALR = 7'b11_001_11;

    localparam OPCODE_CUSTOM_0 = 7'b00_010_11;
    localparam OPCODE_CUSTOM_1 = 7'b01_010_11;
    localparam OPCODE_NMSUB = 7'b10_010_11;
    localparam OPCODE_RESERVED_0 = 7'b11_010_11;

    localparam OPCODE_MISC_MEM = 7'b00_011_11;
    localparam OPCODE_AMO = 7'b01_011_11;
    localparam OPCODE_NMADD = 7'b10_011_11;
    localparam OPCODE_JAL = 7'b11_011_11;

    localparam OPCODE_OP_IMM = 7'b00_100_11;
    localparam OPCODE_OP = 7'b01_100_11;
    localparam OPCODE_OP_FP = 7'b10_100_11;
    localparam OPCODE_SYSTEM = 7'b11_100_11;

    localparam OPCODE_AUIPC = 7'b00_101_11;
    localparam OPCODE_LUI = 7'b01_101_11;
    localparam OPCODE_RESERVED_1 = 7'b10_101_11;
    localparam OPCODE_RESERVED_2 = 7'b11_101_11;

    localparam OPCODE_OP_IMM_32 = 7'b00_110_11;
    localparam OPCODE_OP_32 = 7'b01_110_11;
    localparam OPCODE_CUSTOM_2 = 7'b10_110_11;
    localparam OPCODE_CUSTOM_3 = 7'b11_110_11;

    // next write, next destination (rd), illegal instruction registers
    logic next_wr;
    logic [31:0] next_rd;
    logic illinsn;

    logic trapped;
    logic trapped_q;
    assign trap = trapped;

    always_comb begin
        // advance pc
        npc = pc + 4;

        // defaults for read, write
        next_wr = 0;
        next_rd = 0;
        illinsn = 0;

        mem_wr_enable = 0;
        mem_wr_addr = 'hx;
        mem_wr_data = 'hx;
        mem_wr_strb = 'hx;

        mem_rd_enable = 0;
        mem_rd_addr = 'hx;
        mem_rd_reg = 'hx;
        mem_rd_func = 'hx;

        // act on opcodes
        case (insn_opcode)
            // Load Upper Immediate
            OPCODE_LUI: begin
                next_wr = 1;
                next_rd = insn[31:12] << 12;
            end
            // Add Upper Immediate to Program Counter
            OPCODE_AUIPC: begin
                next_wr = 1;
                // `ex_pc` is this instruction's own address
                next_rd = (insn[31:12] << 12) + ex_pc;
            end
            // Jump And Link (unconditional jump)
            //
            // The fetch redirect happens in the ID block below, so the jump
            // gets the same single delay slot as a branch.  Here we only
            // produce the link value: the jump is in EX now, so `ex_pc` is
            // its own address and the return address is past the delay slot.
            OPCODE_JAL: begin
                next_wr = 1;
                next_rd = ex_pc + 8;
            end
            // Jump And Link Register (indirect jump)
            OPCODE_JALR: begin
                case (insn_funct3)
                    3'b000  /* JALR */: begin
                        next_wr = 1;
                        next_rd = ex_pc + 8;
                    end
                    default: illinsn = 1;
                endcase
            end
            // branch instructions: Branch If Equal, Branch Not Equal, Branch
            // Less Than, Branch Greater or Equal, Branch Less Than Unsigned,
            // Branch Greater or Equal Unsigned
            //
            // The comparison and the npc redirect are done in the ID block
            // below, keyed on `id_insn` (= `ir`), because a taken branch has
            // to be signalled from the second pipeline stage to get a single
            // delay slot.  Resolving it here, from `insn` (= `ex_insn`), is
            // one stage too late: the instruction after the delay slot has
            // already been fetched and would also retire, giving two delay
            // slots.  This case therefore only validates the encoding.
            OPCODE_BRANCH: begin
                case (insn_funct3)
                    3'b000, 3'b001, 3'b100, 3'b101, 3'b110, 3'b111: ;
                    default: illinsn = 1;
                endcase
            end
            // load from memory into rd: Load Byte, Load Halfword, Load Word, Load Byte Unsigned, Load Halfword Unsigned
            OPCODE_LOAD: begin
                mem_rd_addr = rs1_value + imm_i_sext;
                casez ({
                    insn_funct3, mem_rd_addr[1:0]
                })
                    5'b 000_zz /* LB  */,
					5'b 001_z0 /* LH  */,
					5'b 010_00 /* LW  */,
					5'b 100_zz /* LBU */,
					5'b 101_z0 /* LHU */: begin
                        mem_rd_enable = 1;
                        mem_rd_reg = insn_rd;
                        mem_rd_func = {mem_rd_addr[1:0], insn_funct3};
                        mem_rd_addr = {mem_rd_addr[31:2], 2'b00};
                    end
                    default: illinsn = 1;
                endcase
            end
            // store to memory instructions: Store Byte, Store Halfword, Store Word
            OPCODE_STORE: begin
                mem_wr_addr = rs1_value + imm_s_sext;
                casez ({
                    insn_funct3, mem_wr_addr[1:0]
                })
                    5'b000_zz  /* SB */, 5'b001_z0  /* SH */, 5'b010_00  /* SW */: begin
                        mem_wr_enable = 1;
                        mem_wr_data   = rs2_value;
                        mem_wr_strb   = 4'b1111;
                        case (insn_funct3)
                            3'b000  /* SB  */: begin
                                mem_wr_strb = 4'b0001;
                            end
                            3'b001  /* SH  */: begin
                                mem_wr_strb = 4'b0011;
                            end
                            3'b010  /* SW  */: begin
                                mem_wr_strb = 4'b1111;
                            end
                        endcase
                        mem_wr_data = mem_wr_data << (8 * mem_wr_addr[1:0]);
                        mem_wr_strb = mem_wr_strb << mem_wr_addr[1:0];
                        mem_wr_addr = {mem_wr_addr[31:2], 2'b00};
                    end
                    default: illinsn = 1;
                endcase
            end
            // immediate ALU instructions: Add Immediate, Set Less Than Immediate, Set Less Than Immediate Unsigned, XOR Immediate,
            // OR Immediate, And Immediate, Shift Left Logical Immediate, Shift Right Logical Immediate, Shift Right Arithmetic Immediate
            OPCODE_OP_IMM: begin
                casez ({
                    insn_funct7, insn_funct3
                })
                    10'bzzzzzzz_000  /* ADDI  */: begin
                        next_wr = 1;
                        next_rd = rs1_value + imm_i_sext;
                    end
                    10'bzzzzzzz_010  /* SLTI  */: begin
                        next_wr = 1;
                        next_rd = $signed(rs1_value) < $signed(imm_i_sext);
                    end
                    10'bzzzzzzz_011  /* SLTIU */: begin
                        next_wr = 1;
                        next_rd = rs1_value < imm_i_sext;
                    end
                    10'bzzzzzzz_100  /* XORI  */: begin
                        next_wr = 1;
                        next_rd = rs1_value ^ imm_i_sext;
                    end
                    10'bzzzzzzz_110  /* ORI   */: begin
                        next_wr = 1;
                        next_rd = rs1_value | imm_i_sext;
                    end
                    10'bzzzzzzz_111  /* ANDI  */: begin
                        next_wr = 1;
                        next_rd = rs1_value & imm_i_sext;
                    end
                    10'b0000000_001  /* SLLI  */: begin
                        next_wr = 1;
                        next_rd = rs1_value << insn[24:20];
                    end
                    10'b0000000_101  /* SRLI  */: begin
                        next_wr = 1;
                        next_rd = rs1_value >> insn[24:20];
                    end
                    10'b0100000_101  /* SRAI  */: begin
                        next_wr = 1;
                        next_rd = $signed(rs1_value) >>> insn[24:20];
                    end
                    default: illinsn = 1;
                endcase
            end
            OPCODE_OP: begin
                // ALU instructions: Add, Subtract, Shift Left Logical, Set Left Than, Set Less Than Unsigned, XOR, Shift Right Logical,
                // Shift Right Arithmetic, OR, AND
                case ({
                    insn_funct7, insn_funct3
                })
                    10'b0000000_000  /* ADD  */: begin
                        next_wr = 1;
                        next_rd = rs1_value + rs2_value;
                    end
                    10'b0100000_000  /* SUB  */: begin
                        next_wr = 1;
                        next_rd = rs1_value - rs2_value;
                    end
                    10'b0000000_001  /* SLL  */: begin
                        next_wr = 1;
                        next_rd = rs1_value << rs2_value[4:0];
                    end
                    10'b0000000_010  /* SLT  */: begin
                        next_wr = 1;
                        next_rd = $signed(rs1_value) < $signed(rs2_value);
                    end
                    10'b0000000_011  /* SLTU */: begin
                        next_wr = 1;
                        next_rd = rs1_value < rs2_value;
                    end
                    10'b0000000_100  /* XOR  */: begin
                        next_wr = 1;
                        next_rd = rs1_value ^ rs2_value;
                    end
                    10'b0000000_101  /* SRL  */: begin
                        next_wr = 1;
                        next_rd = rs1_value >> rs2_value[4:0];
                    end
                    10'b0100000_101  /* SRA  */: begin
                        next_wr = 1;
                        next_rd = $signed(rs1_value) >>> rs2_value[4:0];
                    end
                    10'b0000000_110  /* OR   */: begin
                        next_wr = 1;
                        next_rd = rs1_value | rs2_value;
                    end
                    10'b0000000_111  /* AND  */: begin
                        next_wr = 1;
                        next_rd = rs1_value & rs2_value;
                    end
                    default: illinsn = 1;
                endcase
            end
            default: illinsn = 1;
        endcase

        // ---------------------------------------------------------------
        // ID STAGE: control-transfer resolution (branches and jumps)
        //
        // Keyed on `id_insn` = `ir`, the instruction in the second (ID)
        // stage, so the fetch is redirected while the branch is still in
        // ID.  By then the delay-slot instruction has already been
        // fetched, so it survives the redirect and retires: exactly ONE
        // delay slot, with no bubble and no flush.
        //
        // The offset base is `ppc`.  When an instruction is in ID, `pc` has
        // already advanced to the delay-slot address and `ppc` holds the
        // instruction's own address - and a RISC-V branch offset is
        // relative to the branch instruction itself.
        // ---------------------------------------------------------------
        br_a = id_rs1_value;
        br_b = id_rs2_value;
        if (next_wr && !mem_rd_enable_q && (insn_rd != 5'd0)) begin
            if (insn_rd == id_insn_rs1) br_a = next_rd;
            if (insn_rd == id_insn_rs2) br_b = next_rd;
        end

        if (id_insn_opcode == OPCODE_BRANCH) begin
            case (id_insn_funct3)
                3'b000  /* BEQ  */: if (br_a == br_b) npc = ppc + id_imm_b_sext;
                3'b001  /* BNE  */: if (br_a != br_b) npc = ppc + id_imm_b_sext;
                3'b100  /* BLT  */: if ($signed(br_a) <  $signed(br_b)) npc = ppc + id_imm_b_sext;
                3'b101  /* BGE  */: if ($signed(br_a) >= $signed(br_b)) npc = ppc + id_imm_b_sext;
                3'b110  /* BLTU */: if (br_a <  br_b) npc = ppc + id_imm_b_sext;
                3'b111  /* BGEU */: if (br_a >= br_b) npc = ppc + id_imm_b_sext;
                default: illinsn = 1;
            endcase
            if (npc & 32'b11) begin
                illinsn = 1;
                npc = npc & ~32'b11;
            end
        end

        // JAL / JALR: no condition, redirect immediately
        if (id_insn_opcode == OPCODE_JAL) begin
            npc = ppc + id_imm_j_sext;
            if (npc & 32'b11) begin
                illinsn = 1;
                npc = npc & ~32'b11;
            end
        end
        if (id_insn_opcode == OPCODE_JALR) begin
            case (id_insn_funct3)
                3'b000  /* JALR */: begin
                    npc = (br_a + id_imm_i_sext) & ~32'b1;
                    if (npc & 32'b11) begin
                        illinsn = 1;
                        npc = npc & ~32'b11;
                    end
                end
                default: illinsn = 1;
            endcase
        end

        // if last cycle was a memory read, then this cycle is the 2nd part of it and imem_data will not be a valid instruction
        if (mem_rd_enable_q) begin
            npc = pc;
            next_wr = 0;
            illinsn = 0;
            mem_rd_enable = 0;
            mem_wr_enable = 0;
        end

        // reset
        if (reset || reset_q) begin
            npc = RESET_ADDR;
            next_wr = 0;
            illinsn = 0;
            mem_rd_enable = 0;
            mem_wr_enable = 0;
        end
    end

    logic reset_q;
    logic [31:0] mem_rdata;

    // mem read functions: Lower and Upper Bytes, signed and unsigned
    always_comb begin
        mem_rdata = dmem_rdata >> (8 * mem_rd_func_q[4:3]);
        case (mem_rd_func_q[2:0])
            3'b000  /* LB  */: begin
                mem_rdata = $signed(mem_rdata[7:0]);
            end
            3'b001  /* LH  */: begin
                mem_rdata = $signed(mem_rdata[15:0]);
            end
            3'b100  /* LBU */: begin
                mem_rdata = mem_rdata[7:0];
            end
            3'b101  /* LHU */: begin
                mem_rdata = mem_rdata[15:0];
            end
        endcase
    end

    // ---------------------------------------------------------------
    // Optional execution trace, for lab-book / GTKWave cross-checking.
    // It prints, once per clock, the instruction that is in EX and the
    // address it was actually fetched from (ex_pc).  Set TRACE = 0 to
    // silence it (the `if` is constant so synthesis drops it entirely).
    // ---------------------------------------------------------------
    localparam bit TRACE = 1'b1;

    logic [31:0] trace_cycles;
    always @(posedge clock) begin
        if (reset) trace_cycles <= 0;
        else       trace_cycles <= trace_cycles + 32'd1;
    end

    function automatic [8*24-1:0] mnemo(input [31:0] i);
        begin
            case (i[6:0])
                7'b0110011: mnemo = "ALU-reg";
                7'b0010011: mnemo = "ALU-imm";
                7'b0000011: mnemo = "LOAD";
                7'b0100011: mnemo = "STORE";
                7'b1100011: mnemo = "BRANCH";
                7'b1101111: mnemo = "JAL";
                7'b1100111: mnemo = "JALR";
                7'b0110111: mnemo = "LUI";
                7'b0010111: mnemo = "AUIPC";
                7'b1110011: mnemo = "SYSTEM/ebreak";
                7'b0000000: mnemo = "nop?";
                default:    mnemo = "?";
            endcase
        end
    endfunction

    always @(posedge clock) begin
        if (TRACE && !reset && !reset_q) begin
            $write("cyc=%0d  pc=0x%08x | ID: ppc=0x%08x ir=0x%08x %0s",
                   trace_cycles, pc, ppc, ir, mnemo(ir));
            if (ir[6:0] == 7'b1100011)
                $write("  a=%0d b=%0d -> npc=0x%08x", br_a, br_b, npc);
            $write(" | EX: ex_pc=0x%08x ex_insn=0x%08x", ex_pc, ex_insn);
            $display("");
        end
    end

    // every cycle
    always @(posedge clock) begin
        reset_q   <= reset;
        trapped_q <= trapped;

        // increment pc if possible
        if (!trapped && !reset && !reset_q) begin
            if (illinsn) trapped <= 1;
            ppc <= pc;  // label: ppc is set to the previous pc value
            pc  <= npc;
            // update registers from memory or rd (destination)
            if (mem_rd_enable_q || next_wr)
                regfile[mem_rd_enable_q ? mem_rd_reg_q : insn_rd] <= mem_rd_enable_q ? mem_rdata : next_rd;
        end
        if (trapped) $display("regfile[10]=%d", regfile[10]);

        // reset
        if (reset || reset_q) begin
            pc <= RESET_ADDR - (reset ? 4 : 0);
            trapped <= 0;
        end
    end

endmodule
