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

    // ---------------------------------------------------------------
    // reset / trap
    // ---------------------------------------------------------------
    logic reset_q;
    logic trapped;
    logic trapped_q;
    assign trap = trapped;

    // ---------------------------------------------------------------
    // Data-memory interface.  These are produced by the EXECUTE stage
    // (i.e. from the registered operands) rather than by the live
    // instruction.
    // ---------------------------------------------------------------
    logic        mem_wr_enable_ex;
    logic [31:0] mem_wr_addr_ex;
    logic [31:0] mem_wr_data_ex;
    logic [ 3:0] mem_wr_strb_ex;

    logic        mem_rd_enable_ex;
    logic [31:0] mem_rd_addr_ex;
    logic [ 4:0] mem_rd_reg_ex;
    logic [ 4:0] mem_rd_func_ex;

    logic        mem_rd_enable_q;
    logic [ 4:0] mem_rd_reg_q;
    logic [ 4:0] mem_rd_func_q;

    // delayed copies of mem_rd (the data memory has a synchronous read,
    // so a load completes on the following cycle)
    always @(posedge clock) begin
        mem_rd_enable_q <= mem_rd_enable_ex;
        mem_rd_reg_q    <= mem_rd_reg_ex;
        mem_rd_func_q   <= mem_rd_func_ex;
        if (reset) begin
            mem_rd_enable_q <= 0;
        end
    end

    // memory signals
    assign dmem_valid = mem_wr_enable_ex || mem_rd_enable_ex;
    assign dmem_addr  = mem_wr_enable_ex ? mem_wr_addr_ex : mem_rd_enable_ex ? mem_rd_addr_ex : 32'hx;
    assign dmem_wstrb = mem_wr_enable_ex ? mem_wr_strb_ex : mem_rd_enable_ex ? 4'h0 : 4'hx;
    assign dmem_wdata = mem_wr_enable_ex ? mem_wr_data_ex : 32'hx;

    // registers, instruction reg, program counter, next pc
    logic [31:0] regfile[0:NUMREGS-1];
    wire  [31:0] insn;
    logic [31:0] npc;
    logic [31:0] pc;

    logic [31:0] imem_addr_q;

    always @(posedge clock) begin
        imem_addr_q <= imem_addr;
    end

    // instruction memory pointer
    assign imem_addr = (trap || mem_rd_enable_q) ? imem_addr_q : npc;

    // ===============================================================
    //   IF/ID PIPELINE REGISTERS
    //   PPC : the PC that belongs to the instruction in the IR
    //   IR  : the fetched instruction word
    // ===============================================================
    logic [31:0] ppc;   // PPC - pipeline PC
    logic [31:0] ir;    // IR  - instruction register

    always @(posedge clock) begin
        ppc <= pc;
        ir  <= imem_data;
    end

    assign insn = ir;

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

    // ===============================================================
    // STAGE ID  (Decode / Register Fetch)
    // ===============================================================
    logic npc_misaligned;

    always_comb begin
        // advance pc by default
        npc = ppc + 4;
        npc_misaligned = 0;

        case (insn_opcode)
            // Jump And Link (unconditional jump)
            OPCODE_JAL: begin
                npc = ppc + imm_j_sext;
                npc_misaligned = (npc & 32'b11) != 0;
                if (npc & 32'b11) begin
                    npc = npc & ~32'b11;
                end
            end
            // Jump And Link Register (indirect jump)
            OPCODE_JALR: begin
                case (insn_funct3)
                    3'b000  /* JALR */: begin
                        npc = (rs1_value + imm_i_sext) & ~32'b1;
                        npc_misaligned = (npc & 32'b11) != 0;
                    end
                    default: ;
                endcase
                if (npc & 32'b11) begin
                    npc = npc & ~32'b11;
                end
            end
            // branch instructions: BEQ, BNE, BLT, BGE, BLTU, BGEU
            // label: note how we're using the immediates directly instead of using the immediate registered values
            // ex. ex_imm_i etc. this means that the branch logic is being handled using the values from ID and nothing else
            OPCODE_BRANCH: begin
                case (insn_funct3)
                    3'b000  /* BEQ  */: begin
                        if (rs1_value == rs2_value) npc = ppc + imm_b_sext;
                    end
                    3'b001  /* BNE  */: begin
                        if (rs1_value != rs2_value) npc = ppc + imm_b_sext;
                    end
                    3'b100  /* BLT  */: begin
                        if ($signed(rs1_value) < $signed(rs2_value)) npc = ppc + imm_b_sext;
                    end
                    3'b101  /* BGE  */: begin
                        if ($signed(rs1_value) >= $signed(rs2_value)) npc = ppc + imm_b_sext;
                    end
                    3'b110  /* BLTU */: begin
                        if (rs1_value < rs2_value) npc = ppc + imm_b_sext;
                    end
                    3'b111  /* BGEU */: begin
                        if (rs1_value >= rs2_value) npc = ppc + imm_b_sext;
                    end
                    default: ;
                endcase
                npc_misaligned = (npc & 32'b11) != 0;
                if (npc & 32'b11) begin
                    npc = npc & ~32'b11;
                end
            end
            default: ;
        endcase

        // if last cycle started a data-memory read, this cycle is the 2nd
        // part of it: hold the program counter (and imem_addr) steady
        if (mem_rd_enable_q) begin
            npc = ppc;
            npc_misaligned = 0;
        end

        // reset
        if (reset || reset_q) begin
            npc = RESET_ADDR;
            npc_misaligned = 0;
        end
    end

    // ===============================================================
    // ID/EX PIPELINE REGISTER  ("before the input to the ALU")
    //
    // Everything the execute stage needs is latched here.  In particular
    // the two GPR operands are registered, so the register file and its
    // read muxes leave the same combinational path as the ALU / memory /
    // write-back logic.
    // ===============================================================
    logic [31:0] ex_insn;
    logic [31:0] ex_pc;
    logic [31:0] ex_rs1_value;
    logic [31:0] ex_rs2_value;
    logic        ex_misaligned;

    always @(posedge clock) begin
        ex_insn       <= insn;
        ex_pc         <= ppc;
        ex_rs1_value  <= rs1_value;
        ex_rs2_value  <= rs2_value;
        ex_misaligned <= npc_misaligned;
    end

    // instruction fields, re-derived from the registered instruction
    wire [ 6:0] ex_funct7 = ex_insn[31:25];
    wire [ 2:0] ex_funct3 = ex_insn[14:12];
    wire [ 4:0] ex_rd     = ex_insn[11:7];
    wire [ 6:0] ex_opcode = ex_insn[6:0];

    wire [11:0] ex_imm_i;
    assign ex_imm_i = ex_insn[31:20];

    wire [11:0] ex_imm_s;
    assign ex_imm_s[11:5] = ex_funct7, ex_imm_s[4:0] = ex_rd;

    wire [31:0] ex_imm_i_sext = $signed(ex_imm_i);
    wire [31:0] ex_imm_s_sext = $signed(ex_imm_s);

    // ===============================================================
    // STAGE EX  (Execute + Memory + Write-Back)
    //
    // This is the original combinational execute block, but it now works
    // on the registered operands / instruction.
    // ===============================================================
    logic        ex_next_wr;
    logic [31:0] ex_next_rd;
    logic        ex_illinsn;

    always_comb begin
        // defaults for read, write
        ex_next_wr = 0;
        ex_next_rd = 0;
        ex_illinsn = 0;

        mem_wr_enable_ex = 0;
        mem_wr_addr_ex = 'hx;
        mem_wr_data_ex = 'hx;
        mem_wr_strb_ex = 'hx;

        mem_rd_enable_ex = 0;
        mem_rd_addr_ex = 'hx;
        mem_rd_reg_ex = 'hx;
        mem_rd_func_ex = 'hx;

        // act on opcodes
        case (ex_opcode)
            // Load Upper Immediate
            OPCODE_LUI: begin
                ex_next_wr = 1;
                ex_next_rd = ex_insn[31:12] << 12;
            end
            // Add Upper Immediate to Program Counter
            OPCODE_AUIPC: begin
                ex_next_wr = 1;
                ex_next_rd = (ex_insn[31:12] << 12) + ex_pc;
            end
            // Jump And Link (unconditional jump)
            OPCODE_JAL: begin
                ex_next_wr = 1;
                ex_next_rd = ex_pc + 4;
            end
            // Jump And Link Register (indirect jump)
            OPCODE_JALR: begin
                case (ex_funct3)
                    3'b000  /* JALR */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_pc + 4;
                    end
                    default: ex_illinsn = 1;
                endcase
            end
            // branch instructions (the branch itself was resolved in ID)
            OPCODE_BRANCH: begin
                case (ex_funct3)
                    3'b000, 3'b001, 3'b100, 3'b101, 3'b110, 3'b111: ;
                    default: ex_illinsn = 1;
                endcase
            end
            // load from memory into rd: LB, LH, LW, LBU, LHU
            OPCODE_LOAD: begin
                mem_rd_addr_ex = ex_rs1_value + ex_imm_i_sext;
                casez ({
                    ex_funct3, mem_rd_addr_ex[1:0]
                })
                    5'b 000_zz /* LB  */,
                    5'b 001_z0 /* LH  */,
                    5'b 010_00 /* LW  */,
                    5'b 100_zz /* LBU */,
                    5'b 101_z0 /* LHU */: begin
                        mem_rd_enable_ex = 1;
                        mem_rd_reg_ex = ex_rd;
                        mem_rd_func_ex = {mem_rd_addr_ex[1:0], ex_funct3};
                        mem_rd_addr_ex = {mem_rd_addr_ex[31:2], 2'b00};
                    end
                    default: ex_illinsn = 1;
                endcase
            end
            // store to memory instructions: SB, SH, SW
            OPCODE_STORE: begin
                mem_wr_addr_ex = ex_rs1_value + ex_imm_s_sext;
                casez ({
                    ex_funct3, mem_wr_addr_ex[1:0]
                })
                    5'b000_zz  /* SB */, 5'b001_z0  /* SH */, 5'b010_00  /* SW */: begin
                        mem_wr_enable_ex = 1;
                        mem_wr_data_ex   = ex_rs2_value;
                        mem_wr_strb_ex   = 4'b1111;
                        case (ex_funct3)
                            3'b000  /* SB  */: begin
                                mem_wr_strb_ex = 4'b0001;
                            end
                            3'b001  /* SH  */: begin
                                mem_wr_strb_ex = 4'b0011;
                            end
                            3'b010  /* SW  */: begin
                                mem_wr_strb_ex = 4'b1111;
                            end
                        endcase
                        mem_wr_data_ex = mem_wr_data_ex << (8 * mem_wr_addr_ex[1:0]);
                        mem_wr_strb_ex = mem_wr_strb_ex << mem_wr_addr_ex[1:0];
                        mem_wr_addr_ex = {mem_wr_addr_ex[31:2], 2'b00};
                    end
                    default: ex_illinsn = 1;
                endcase
            end
            // immediate ALU instructions: ADDI, SLTI, SLTIU, XORI, ORI,
            // ANDI, SLLI, SRLI, SRAI
            OPCODE_OP_IMM: begin
                casez ({
                    ex_funct7, ex_funct3
                })
                    10'bzzzzzzz_000  /* ADDI  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value + ex_imm_i_sext;
                    end
                    10'bzzzzzzz_010  /* SLTI  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = $signed(ex_rs1_value) < $signed(ex_imm_i_sext);
                    end
                    10'bzzzzzzz_011  /* SLTIU */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value < ex_imm_i_sext;
                    end
                    10'bzzzzzzz_100  /* XORI  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value ^ ex_imm_i_sext;
                    end
                    10'bzzzzzzz_110  /* ORI   */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value | ex_imm_i_sext;
                    end
                    10'bzzzzzzz_111  /* ANDI  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value & ex_imm_i_sext;
                    end
                    10'b0000000_001  /* SLLI  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value << ex_insn[24:20];
                    end
                    10'b0000000_101  /* SRLI  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value >> ex_insn[24:20];
                    end
                    10'b0100000_101  /* SRAI  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = $signed(ex_rs1_value) >>> ex_insn[24:20];
                    end
                    default: ex_illinsn = 1;
                endcase
            end
            OPCODE_OP: begin
                // ALU instructions: ADD, SUB, SLL, SLT, SLTU, XOR, SRL,
                // SRA, OR, AND
                case ({
                    ex_funct7, ex_funct3
                })
                    10'b0000000_000  /* ADD  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value + ex_rs2_value;
                    end
                    10'b0100000_000  /* SUB  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value - ex_rs2_value;
                    end
                    10'b0000000_001  /* SLL  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value << ex_rs2_value[4:0];
                    end
                    10'b0000000_010  /* SLT  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = $signed(ex_rs1_value) < $signed(ex_rs2_value);
                    end
                    10'b0000000_011  /* SLTU */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value < ex_rs2_value;
                    end
                    10'b0000000_100  /* XOR  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value ^ ex_rs2_value;
                    end
                    10'b0000000_101  /* SRL  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value >> ex_rs2_value[4:0];
                    end
                    10'b0100000_101  /* SRA  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = $signed(ex_rs1_value) >>> ex_rs2_value[4:0];
                    end
                    10'b0000000_110  /* OR   */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value | ex_rs2_value;
                    end
                    10'b0000000_111  /* AND  */: begin
                        ex_next_wr = 1;
                        ex_next_rd = ex_rs1_value & ex_rs2_value;
                    end
                    default: ex_illinsn = 1;
                endcase
            end
            default: ex_illinsn = 1;
        endcase

        // jump / branch target mis-alignment detected in ID
        ex_illinsn = ex_illinsn | ex_misaligned;

        // if last cycle was a memory read, then this cycle is the 2nd part
        // of it and imem_data will not be a valid instruction
        if (mem_rd_enable_q) begin
            ex_next_wr = 0;
            ex_illinsn = 0;
            mem_rd_enable_ex = 0;
            mem_wr_enable_ex = 0;
        end

        // reset
        if (reset || reset_q) begin
            ex_next_wr = 0;
            ex_illinsn = 0;
            mem_rd_enable_ex = 0;
            mem_wr_enable_ex = 0;
        end
    end

    // ---------------------------------------------------------------
    // Write-back / retire
    // ---------------------------------------------------------------
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

    // every cycle
    always @(posedge clock) begin
        reset_q   <= reset;
        trapped_q <= trapped;

        // increment pc if possible
        if (!trapped && !reset && !reset_q) begin
            if (ex_illinsn) trapped <= 1;
            pc <= npc;
            // update registers from memory or rd (destination)
            if (mem_rd_enable_q || ex_next_wr)
                regfile[mem_rd_enable_q ? mem_rd_reg_q : ex_rd] <= mem_rd_enable_q ? mem_rdata : ex_next_rd;
        end
        if (trapped) $display("regfile[10]=%d", regfile[10]);

        // reset
        if (reset || reset_q) begin
            pc <= RESET_ADDR - (reset ? 4 : 0);
            trapped <= 0;
        end
    end

endmodule
