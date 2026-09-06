/*
 *  Single cycle RV32 processor supporting R-type and I-type instructions
 *  Parts derived from NERV
 *  Copyright (C) 2022  Philip Leong <philip.leong@sydney.edu.au>

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

`include "constants.svh"

`default_nettype none

module rv3608c (
    input clock,
    input reset,
    output trap,
    output logic [31:0] x10,

    // Instruction memory
    output [31:0] imem_addr,
    input  [31:0] imem_data
);
    assign imem_addr = pc;
    assign insn = imem_data;

    // Data memory
    logic [31:0] dmem[0:1023];
    logic dmem_wr_enable;
    logic [31:0] dmem_wr_addr;
    logic [31:0] dmem_wr_data;

    logic [31:0] dmem_rd_addr;
    logic [31:0] dmem_rd_data;

    // Debugging
    logic [4:0] d_rd;
    logic [31:0] d_x0, d_x1, d_x2, d_x3, d_x4;
    logic [6:0] d_opcode;

    logic illegalinsn;
    logic trapped;
    assign trap = trapped;

    logic [31:0] regfile[0:`NUMREGS-1];
    logic [31:0] pc;
    logic [31:0] insn;

    logic [6:0] insn_funct7;
    logic [4:0] insn_rs2;
    logic [4:0] insn_rs1;
    logic [2:0] insn_funct3;
    logic [4:0] insn_rd;
    logic [6:0] insn_opcode;
    assign {insn_funct7, insn_rs2, insn_rs1, insn_funct3, insn_rd, insn_opcode} = insn;

    wire  [31:0] rs1_value = regfile[insn_rs1];
    wire  [31:0] rs2_value = regfile[insn_rs2];

    // --- IMMEDIATES ---
    // I-type
    logic [11:0] imm_i;
    assign imm_i = insn[31:20];
    wire  [31:0] imm_i_sext = {{20{imm_i[11]}}, imm_i};
    wire  [31:0] imm_shift = 32'(signed'({1'b0, insn[24:20]}));
    logic [31:0] imm_val;
    assign imm_val = ({insn_funct7, insn_funct3} == `OPCODE_SLLI ||
                       {insn_funct7, insn_funct3} == `OPCODE_SRLI ||
                       {insn_funct7, insn_funct3} == `OPCODE_SRAI) ? imm_shift : imm_i_sext;

    // S-type (Added for SW)
    wire  [11:0] imm_s = {insn[31:25], insn[11:7]};
    wire  [31:0] imm_s_sext = 32'(signed'(imm_s));

    // B-type and J-type
    logic [12:0] imm_b;
    assign {imm_b[12], imm_b[10:5]} = insn_funct7,
        {imm_b[4:1], imm_b[11]} = insn_rd,
        imm_b[0] = 1'b0;
    logic [20:0] imm_j;
    assign {imm_j[20], imm_j[10:1], imm_j[11], imm_j[19:12], imm_j[0]} = {insn[31:12], 1'b0};

    wire [31:0] imm_b_sext = 32'(signed'(imm_b));
    wire [31:0] imm_j_sext = 32'(signed'(imm_j));

    // --- ALU WIRING ---
    logic alu_eq_zero;
    logic [31:0] alu_result;
    wire [31:0] alu_op_a = rs1_value;

    // FIXED ALU B-MUX: Routes S-type imm for stores, I-type imm for loads/arithmetic, rs2 for branches/R-type
    wire   [31:0] alu_op_b = (insn_opcode == `OPCODE_STORE) ? imm_s_sext :
                              (insn_opcode == `OPCODE_OP_IMM || insn_opcode == `OPCODE_LOAD) ? imm_val :
                              rs2_value;
    logic [4:0] alu_op;

    // --- DMEM WIRING ---
    assign dmem_rd_addr = alu_result;
    assign dmem_rd_data = dmem[dmem_rd_addr[11:2]];  // Word-aligned read
    assign dmem_wr_addr = alu_result;
    assign dmem_wr_data = rs2_value;

    // --- ALU OP DECODER ---
    always_comb begin
        alu_op = `ALU_ADD;
        case (insn_opcode)
            `OPCODE_OP_IMM: begin
                casez ({
                    insn_funct7, insn_funct3
                })
                    10'bzzzzzzz_000: alu_op = `ALU_ADD;
                    10'bzzzzzzz_010: alu_op = `ALU_SLT;
                    10'bzzzzzzz_011: alu_op = `ALU_SLTU;
                    10'bzzzzzzz_100: alu_op = `ALU_XOR;
                    10'bzzzzzzz_110: alu_op = `ALU_OR;
                    10'bzzzzzzz_111: alu_op = `ALU_AND;
                    10'b0000000_001: alu_op = `ALU_SLL;
                    10'b0000000_101: alu_op = `ALU_SRL;
                    10'b0100000_101: alu_op = `ALU_SRA;
                    default: alu_op = `ALU_ADD;
                endcase
            end
            `OPCODE_OP: begin
                casez ({
                    insn_funct7, insn_funct3
                })
                    10'b0000000_000: alu_op = `ALU_ADD;
                    10'b0100000_000: alu_op = `ALU_SUB;
                    10'b0000000_001: alu_op = `ALU_SLL;
                    10'b0000000_010: alu_op = `ALU_SLT;
                    10'b0000000_011: alu_op = `ALU_SLTU;
                    10'b0000000_100: alu_op = `ALU_XOR;
                    10'b0000000_101: alu_op = `ALU_SRL;
                    10'b0100000_101: alu_op = `ALU_SRA;
                    10'b0000000_110: alu_op = `ALU_OR;
                    10'b0000000_111: alu_op = `ALU_AND;
                    default: alu_op = `ALU_ADD;
                endcase
            end
            `OPCODE_BRANCH: begin
                case (insn_funct3)
                    3'b000, 3'b001: alu_op = `ALU_SUB;  // BEQ, BNE
                    3'b100, 3'b101: alu_op = `ALU_SLT;  // BLT, BGE
                    3'b110, 3'b111: alu_op = `ALU_SLTU;  // BLTU, BGEU
                    default: alu_op = `ALU_ADD;
                endcase
            end
            `OPCODE_LOAD, `OPCODE_STORE: alu_op = `ALU_ADD;
            `OPCODE_JAL, `OPCODE_JALR: alu_op = `ALU_ADD;
            7'b1110011  /* EBREAK */: alu_op = `ALU_ADD;
            default: alu_op = `ALU_ADD;
        endcase
    end

    alu alu_1 (
        .alu_function(alu_op),
        .op_a(alu_op_a),
        .op_b(alu_op_b),
        .result(alu_result),
        .result_eq_zero(alu_eq_zero)
    );

    // --- CONTROL SIGNALS ---
    logic regwrite;
    logic [31:0] npc;
    logic [31:0] rfilewdata;

    always_comb begin
        illegalinsn = 0;
        regwrite = 0;
        dmem_wr_enable = 0;  // FIXED: Prevent latches
        npc = pc + 4;
        rfilewdata = alu_result;

        case (insn_opcode)
            0: ;  // NOP
            `OPCODE_OP_IMM, `OPCODE_OP: regwrite = 1;

            `OPCODE_JAL: begin
                regwrite = 1;
                rfilewdata = pc + 4;
                npc = pc + imm_j_sext;
            end
            `OPCODE_JALR: begin
                regwrite = 1;
                rfilewdata = pc + 4;
                npc = (rs1_value + imm_i_sext) & ~32'b1;
            end

            `OPCODE_BRANCH: begin
                case (insn_funct3)
                    3'b000  /* BEQ  */: begin
                        if (alu_eq_zero) npc = pc + imm_b_sext;
                    end
                    3'b001  /* BNE  */: begin
                        if (!alu_eq_zero) npc = pc + imm_b_sext;
                    end
                    3'b100  /* BLT  */: begin
                        if (alu_result != 0) npc = pc + imm_b_sext;
                    end
                    3'b101  /* BGE  */: begin
                        if (alu_result == 0) npc = pc + imm_b_sext;
                    end
                    3'b110  /* BLTU */: begin
                        if (alu_result != 0) npc = pc + imm_b_sext;
                    end
                    3'b111  /* BGEU */: begin
                        if (alu_result == 0) npc = pc + imm_b_sext;
                    end
                    default: illegalinsn = 1;
                endcase
            end

            `OPCODE_LOAD: begin
                regwrite   = 1;
                rfilewdata = dmem_rd_data;
                $display("lw from 0x%08x = 0x%08x", dmem_rd_addr, dmem_rd_data);
            end
            `OPCODE_STORE: begin
                dmem_wr_enable = 1;  // Assert write enable
                $display("sw 0x%08x to = 0x%08x", rs2_value, dmem_wr_addr);
            end

            7'b1110011  /* EBREAK */: illegalinsn = 1;
            default: illegalinsn = 1;
        endcase

        if ((npc & 32'b11) != 0) begin
            illegalinsn = 1;
            npc = pc & ~32'b11;
        end
    end

    // --- SEQUENTIAL CLOCK BLOCK ---
    always_ff @(posedge clock) begin
        if (!trapped && !reset) begin
            if (illegalinsn) trapped <= 1;
            pc <= npc;

            if (regwrite && insn_rd > 0) begin
                regfile[insn_rd] <= rfilewdata;
            end
            // Keep x10 up to date for testbench
            x10 <= regfile[10];

            if (dmem_wr_enable) begin
                dmem[dmem_wr_addr[11:2]] <= dmem_wr_data;
            end
        end

        if (reset) begin
            pc <= 0;
            trapped <= 0;
        end

        d_x0 = regfile[0];
        d_x1 = regfile[1];
        d_x2 = regfile[2];
        d_x3 = regfile[3];
        d_x4 = regfile[4];
        d_rd = insn_rd;
        d_opcode <= insn_opcode;
    end
endmodule
