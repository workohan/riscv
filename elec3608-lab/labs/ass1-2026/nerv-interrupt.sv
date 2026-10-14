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
`default_nettype none
// CSR numbers per Privileged ISA sec 2.2.4 table 7
localparam CSR_MSTATUS = 12'h300;
localparam CSR_MIE = 12'h304;
localparam CSR_MTVEC = 12'h305;
localparam CSR_MSCRATCH = 12'h340;
localparam CSR_MEPC = 12'h341;
localparam CSR_MCAUSE = 12'h342;
localparam CSR_MIP = 12'h344;

module nerv #(  // THE ACTUAL CPU
    parameter [31:0] RESET_ADDR = 32'h0000_0000,
    parameter integer NUMREGS = 32,
    parameter integer MTVEC_ADDR = 32'h0000_1000  // Interrupt/trap vector address
) (
    input  clock,
    input  reset,
    output trap,   // todo: what does this contain?
    input  intr,   // interrupt request

    // we have 2 external memories
    // one is instruction memory
    output [31:0] imem_addr,  // sent to external imem to get [imem_data]
    input  [31:0] imem_data,  // got from external imem via [imem_addr]

    // the other is data memory
    // todo: sync read and write or what?
    output dmem_valid,  // todo: what
    output [31:0] dmem_addr,  // address to write to; since in stage 2 must be delayed appropriately
    output [3:0] dmem_wstrb,  // todo: what
    output [31:0] dmem_wdata,  // i guess data to write to dmem
    input [31:0] dmem_rdata  //
);

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

// ===========================================================
localparam OPCODE_SYSTEM = 7'b11_100_11; // FOR ZICSR

// Zicsr (Unprivileged ISA 5.1.1) -- all on OPCODE_SYSTEM, selected by funct3
localparam FUNCT3_CSRRW  = 3'b001;
localparam FUNCT3_CSRRS  = 3'b010;
localparam FUNCT3_CSRRC  = 3'b011;
localparam FUNCT3_CSRRWI = 3'b101;
localparam FUNCT3_CSRRSI = 3'b110;
localparam FUNCT3_CSRRCI = 3'b111;

// OPCODE_SYSTEM with funct3 == 000: privileged, selected by insn[31:20]
localparam [11:0] SYSTEM_ECALL  = 12'h000;
localparam [11:0] SYSTEM_EBREAK = 12'h001;
localparam [11:0] SYSTEM_MRET   = 12'h302;
// ===========================================================

localparam OPCODE_AUIPC = 7'b00_101_11;
localparam OPCODE_LUI = 7'b01_101_11;
localparam OPCODE_RESERVED_1 = 7'b10_101_11;
localparam OPCODE_RESERVED_2 = 7'b11_101_11;

localparam OPCODE_OP_IMM_32 = 7'b00_110_11;
localparam OPCODE_OP_32 = 7'b01_110_11;
localparam OPCODE_CUSTOM_2 = 7'b10_110_11;
localparam OPCODE_CUSTOM_3 = 7'b11_110_11;

    /* @csr:intr_handler parses the 1 cycle [intr] activation and handles
    execution*/
    // [intr] comes in
    // """signals""" go out to tell everything to stop what its doing rn
    // I think this just means tell whatever is in ID to stop


    // ==============================================
    // @stage:pipeline_control the one hazard that reaches the PC and both
    // pipeline registers: dmem has a SYNCHRONOUS read, so a load occupies
    // @exec on the cycle it issues and completes on the next one.
    // During that second cycle the fetch and both pipeline registers are
    // frozen, so the instruction behind the load replays instead of latching
    // a stale operand / committing a stale result.

    // TODO: the load-use stall (source register still in @exec) hangs
    //       off [stall] as well.
    logic        mem_rd_enable_q;  // set by @exec, consumed here
    logic [ 4:0] mem_rd_reg_q;
    logic [ 4:0] mem_rd_func_q;
    wire         stall = mem_rd_enable_q; // will cause stall if i need to write to regfile, todo:

    // ==============================================
    // @stage:pc_stuff everything relating to manipulating the program counter.

    logic [31:0] npc;  // value that pc will be upated to; this is the address
                       // presented on [imem_addr] this cycle
    logic [31:0] pc;   // the pc that belongs to [imem_data], i.e. the address of
                       // the instruction that arrives in [ir] next cycle

    logic [31:0] imem_addr_q;
    always @(posedge clock) begin
        imem_addr_q <= imem_addr;
    end

    // instruction memory pointer.  [pc] is loaded from [npc], so holding [npc]
    // holds the whole fetch pipeline.
    // TODO: also hold while `trap` is asserted, once trap is driven.
    assign imem_addr = stall ? imem_addr_q : npc;

    always @(posedge clock) begin
        if (reset) pc <= RESET_ADDR;
        else       pc <= npc;
    end

    // ==============================================
    // @stage:insd after @pc_stuff, actual stage 1 of pipeline

    logic [31:0] ir;  // in: imem_data, outputs the ith instruction
    wire  [31:0] s1_inst;  // equal to [ir], just an alias
    logic [31:0] s1_pc;    // the pc that belongs to [s1_inst] (the old cpu's [ppc])
    always @(posedge clock) begin
        if (reset) begin
            ir    <= 32'h0000_0013;  // sends a nop
            s1_pc <= RESET_ADDR;
        end else if (stall) begin
            // @dmem read completing: hold the instruction in ID
            // TODO:
        end else begin
            ir    <= imem_data;
            s1_pc <= pc;   // pairs with [ir]: see the invariant note below
        end
    end
    assign s1_inst = ir;


    // @memory:regfile the cpu's registers
    logic [31:0] regfile[0:NUMREGS-1];
    logic regfile_csr_w_en = 0;


    // ==============================================
    // @stage:exec after @insd, stage 2 of the pipeline

    // Cross-stage signals.  These live OUTSIDE both REGION_* macros so that the
    // ID and EX regions stay independent of each other:
    //   [ex_next_wr] / [ex_next_rd] : produced by @exec below, read by the
    //                                 @insd operand bypass
    //   [npc_misaligned]            : produced by @insd below, carried
    //                                 through the ID/EX register into @exec
    logic        ex_next_wr;   // the EX instruction writes [ex_next_rd] this edge
    logic [31:0] ex_next_rd;   // ... into register s2_inst[11:7]
    logic        npc_misaligned;

    // ID/EX pipeline register.  Latches [s1_inst] plus everything that has to
    // travel with it: its own pc (for AUIPC and the JAL/JALR link value) and
    // the bad-jump-target flag raised in @insd.
    logic [31:0] s2_inst;
    logic [31:0] s2_pc;
    logic        ex_misaligned;
    always @(posedge clock) begin
        if (reset) begin
            s2_inst       <= 32'h0000_0013;  // NOP
            s2_pc         <= RESET_ADDR;
            ex_misaligned <= 1'b0;
        end else if (stall) begin
            // replay this instruction once the load result has landed
        end else begin
            s2_inst       <= s1_inst;
            s2_pc         <= s1_pc;
            ex_misaligned <= npc_misaligned;
        end
    end
    // @unpipe:s1_to_s2 change always block to assign s2_inst <= s1_inst; and change to wire
    // (same for s2_pc and ex_misaligned; once s1 and s2 are the same stage the
    //  EX -> ID bypass above is dead and can go)

    // ==============================================
    // @insd OPERAND FETCH + NEXT-PC DECISION  <-- the branching logic
    //
    // Control transfers are resolved HERE, on the instruction sitting in [ir],
    // This allows us to achieve one delay slot branching :)
    //
    // NOTE: this block sits below the @exec *declarations* because the
    // operand bypass reads [s2_inst] / [ex_next_wr] / [ex_next_rd].  Declare
    // before use keeps every tool happy.
    // ==============================================
    `define REGION_ID_BRANCH_LOGIC
    `ifdef REGION_ID_BRANCH_LOGIC
        wire [ 6:0] s1_inst_funct7;
        wire [ 4:0] s1_inst_rs2;
        wire [ 4:0] s1_inst_rs1;
        wire [ 2:0] s1_inst_funct3;
        wire [ 4:0] s1_inst_rd;
        wire [ 6:0] s1_inst_opcode;
        assign {s1_inst_funct7, s1_inst_rs2, s1_inst_rs1, s1_inst_funct3, s1_inst_rd, s1_inst_opcode} = s1_inst;

        // I - short immediates
        wire [11:0] s1_imm_i;
        assign s1_imm_i = s1_inst[31:20];

        // B - conditionals
        wire [12:0] s1_imm_b;
        assign {s1_imm_b[12], s1_imm_b[10:5]} = s1_inst_funct7,
               {s1_imm_b[4:1], s1_imm_b[11]} = s1_inst_rd,
               s1_imm_b[0] = 1'b0;

        // J - unconditional jumps
        wire [20:0] s1_imm_j;
        assign {s1_imm_j[20], s1_imm_j[10:1], s1_imm_j[11], s1_imm_j[19:12], s1_imm_j[0]} = {s1_inst[31:12], 1'b0};

        wire [31:0] s1_imm_i_sext = $signed(s1_imm_i);
        wire [31:0] s1_imm_b_sext = $signed(s1_imm_b);
        wire [31:0] s1_imm_j_sext = $signed(s1_imm_j);

        // csr:s1_csr_decode
        wire [11:0] s1_zicsr_src_dest; // passed into csrfile
        wire [4:0] s1_zicsr_rs1; // reg val
        wire [2:0] s1_zicsr_funct3; // subinstruction
        wire [4:0] s1_zicsr_rd; // to write to
        wire [6:0] _s1_zicsr_opcode; // unused

        assign {s1_zicsr_src_dest, s1_zicsr_rs1, s1_zicsr_funct3, s1_zicsr_rd, _s1_zicsr_opcode} = s1_inst;

        logic[31:0] s2_zicsr_rs1_val; // the actual value of rs1 taken from regfile
        always @(posedge clock) begin
            assign s2_zicsr_rs1_val = regfile[s1_zicsr_rs1];
        end

        // ------------------------------------------------------------------

        // [ex_next_wr] / [ex_next_rd] are declared above (cross-stage block).
        // Neither depends on br_a / br_b or on npc, so the bypass below cannot
        // form a combinational loop.
        // todo: what

        // ---- operands for the comparison ---------------------------------
        wire [31:0] s1_rs1_value = !s1_inst_rs1 ? 0 : regfile[s1_inst_rs1];
        wire [31:0] s1_rs2_value = !s1_inst_rs2 ? 0 : regfile[s1_inst_rs2];

        // EX -> ID operand bypass.  A branch / JALR sitting in ID can depend on
        // the result of the instruction immediately ahead of it, which is in
        // EX right now and whose write-back only lands on this clock edge.
        // Without this the branch compares stale operands.
        logic [31:0] br_a, br_b;
        always_comb begin
            br_a = s1_rs1_value;
            br_b = s1_rs2_value;
            if (ex_next_wr && !stall && (s2_inst[11:7] != 5'd0)) begin
                if (s2_inst[11:7] == s1_inst_rs1) br_a = ex_next_rd;
                if (s2_inst[11:7] == s1_inst_rs2) br_b = ex_next_rd;
            end
        end

        // ---- next-PC -----------------------------------------------------
        // [npc_misaligned] is declared above (cross-stage block).
        // @insd:delay_slot_branch branching in stage 1
        always_comb begin
            // sequential by default.  [pc] is the address already sitting in
            // [imem_data], so the next address to present is [pc] + 4.
            npc = pc + 4;
            npc_misaligned = 1'b0;

            case (s1_inst_opcode)
                OPCODE_JAL: begin
                    npc = s1_pc + s1_imm_j_sext;
                    npc_misaligned = (npc[1:0] != 2'b00);
                end
                OPCODE_JALR: begin
                    case (s1_inst_funct3)
                        3'b000 /* JALR */: npc = (br_a + s1_imm_i_sext) & ~32'b1;
                        default: ;  // bogus funct3: leave the fetch sequential,
                                    // @exec flags it as illegal
                    endcase
                    npc_misaligned = (npc[1:0] != 2'b00);
                end
                OPCODE_BRANCH: begin
                    case (s1_inst_funct3)
                        3'b000 /* BEQ  */: if (br_a == br_b) npc = s1_pc + s1_imm_b_sext;
                        3'b001 /* BNE  */: if (br_a != br_b) npc = s1_pc + s1_imm_b_sext;
                        3'b100 /* BLT  */: if ($signed(br_a) <  $signed(br_b)) npc = s1_pc + s1_imm_b_sext;
                        3'b101 /* BGE  */: if ($signed(br_a) >= $signed(br_b)) npc = s1_pc + s1_imm_b_sext;
                        3'b110 /* BLTU */: if (br_a <  br_b) npc = s1_pc + s1_imm_b_sext;
                        3'b111 /* BGEU */: if (br_a >= br_b) npc = s1_pc + s1_imm_b_sext;
                        default: ;
                    endcase
                    // only the taken case can be mis-aligned: the fall-through
                    // is [pc] + 4, which is always word aligned
                    npc_misaligned = (npc[1:0] != 2'b00);
                end
                default: ;
            endcase

            // a target that is not word aligned is an illegal instruction
            // address.  Park the fetch on the aligned word and let
            // @exec turn [npc_misaligned] into the trap.
            if (npc_misaligned) npc = {npc[31:2], 2'b00};

            // @dmem read completing: hold the whole fetch pipeline
            if (stall) begin
                npc = pc;
                npc_misaligned = 1'b0;
            end

            if (reset) begin
                npc = RESET_ADDR;
                npc_misaligned = 1'b0;
            end
        end
    `endif

    // @decode:alu_sigs happens in @exec
    `define REGION_ALU_LOGIC
    `ifdef REGION_ALU_LOGIC
        wire [ 6:0] s2_inst_funct7;
        wire [ 4:0] s2_inst_rs2;
        wire [ 4:0] s2_inst_rs1;
        wire [ 2:0] s2_inst_funct3;
        wire [ 4:0] s2_inst_rd;
        wire [ 6:0] s2_inst_opcode;
        assign {s2_inst_funct7, s2_inst_rs2, s2_inst_rs1, s2_inst_funct3, s2_inst_rd, s2_inst_opcode} = s2_inst;


        // setup for I, S, B & J type instructions
        // I - short immediates and loads
        wire [11:0] imm_i;
        assign imm_i = s2_inst[31:20];

        // S - stores
        wire [11:0] imm_s;
        assign imm_s[11:5] = s2_inst_funct7, imm_s[4:0] = s2_inst_rd;

        // B - conditionals
        wire [12:0] imm_b;
        assign {imm_b[12], imm_b[10:5]} = s2_inst_funct7,
            {imm_b[4:1], imm_b[11]} = s2_inst_rd,
            imm_b[0] = 1'b0;

        // J - unconditional jumps
        wire [20:0] imm_j;
        assign {imm_j[20], imm_j[10:1], imm_j[11], imm_j[19:12], imm_j[0]} = {s2_inst[31:12], 1'b0};

        wire [31:0] imm_i_sext = $signed(imm_i);
        wire [31:0] imm_s_sext = $signed(imm_s);
        wire [31:0] imm_b_sext = $signed(imm_b);
        wire [31:0] imm_j_sext = $signed(imm_j);

        // @decode:s2_csr_inst decode component  for zicsr instructions
        // need to decode in stage 1 as well
        wire [11:0] zicsr_src_dest; // passed into csrfile
        wire [4:0] zicsr_rs1; // reg val
        wire [2:0] zicsr_funct3; // subinstruction
        wire [4:0] zicsr_rd; // to write to
        wire [6:0] _zicsr_opcode; // unused

        assign {zicsr_src_dest, zicsr_rs1, zicsr_funct3, zicsr_rd, _zicsr_opcode} = s2_inst;
    `endif


    // @memory:csrfile uses [csrfile]
    // ---------------------------------------------------------------
    // Hookup only.  Who drives what:
    //
    //   here  -> csrfile : csr_addr, csr_re, csr_we, csr_wdata,
    //                      csr_mepc, csr_mcause, csr_mtvec, csr_mip
    //
    //   csrfile -> here  : csr_rdata, csr_mstatus, csr_mie, csr_mscratch
    //
    // [csr_mstatus] is driven BY the csrfile: its rw_mstatus_bits port is
    // assigned inside that module.  Never assign it here - two drivers make
    // every read x.  Trap entry and mret change it through the we/wdata port.
    //
    // The seven csr_m* / csr_mscratch names are also what testbench.sv:138-148
    // reads hierarchically, so do not rename them.
    // ---------------------------------------------------------------

    // access port, driven by @exec (CSR instruction, or trap entry / mret)
    logic [11:0] csr_addr  = 12'h000;  // CSR number, instruction[31:20]
    logic [31:0] csr_re    = 32'h0;    // bit-addressable READ mask  (0 = no read)
    logic [31:0] csr_we    = 32'h0;    // bit-addressable WRITE mask (0 = no write)
    logic [31:0] csr_wdata = 32'h0;    // bits to write where [csr_we] is set
    wire  [31:0] csr_rdata;            // combinational read-back, same cycle

    // read-only CSRs: storage lives here in the processor
    logic [31:0] csr_mepc;             // trap: return address
    logic [31:0] csr_mcause;           // trap: cause code
    logic [31:0] csr_mip;              // sticky: external interrupt pending
    wire  [31:0] csr_mtvec = MTVEC_ADDR;  // hard-wired trap vector

    // read/write CSRs: storage lives in the [csrfile]
    wire  [31:0] csr_mstatus;          // driven by csrfile (see note above)
    wire  [31:0] csr_mie;              // driven by csrfile
    wire  [31:0] csr_mscratch;         // driven by csrfile

    // reset only.  The update logic (trap entry, mret, latching [intr]) is
    // TODO - this just keeps the three registers out of x and gives them their
    // architectural reset values.
    always @(posedge clock) begin
        if (reset) begin
            csr_mepc   <= 32'h0;
            csr_mcause <= 32'h0;
            csr_mip    <= 32'h0;
        end
    end

    csrfile csr_file (
        .clock  (clock),
        .reset  (reset),
        .addr   (csr_addr),           // instruction[31:20]
        .re     (csr_re),             // read mask
        .we     (csr_we),             // write mask
        .rdata  (csr_rdata),          // combinational
        .wdata  (csr_wdata),

        .ro_mepc_bits    (csr_mepc),      // in:  storage is ours
        .rw_mstatus_bits (csr_mstatus),   // out: storage is the csrfile's
        .rw_mie_bits     (csr_mie),       // out
        .ro_mtvec_bits   (csr_mtvec),     // in:  constant
        .ro_mip_bits     (csr_mip),       // in:  storage is ours
        .ro_mcause_bits  (csr_mcause),    // in:  storage is ours
        .rw_mscratch_bits(csr_mscratch)   // out
    );


    // @memory:dmem and its associated signals. note that dmem stuff is external
    // @decode:dmem_sigs done in @exec for convinience
    // the dmem_* output wiring lives at the bottom of the module

    `define ALU_IMPLEMENT
    `ifdef ALU_IMPLEMENT
    logic        ex_illinst;   // illegal instruction / bad jump target

    logic        mem_wr_enable_ex;
    logic [31:0] mem_wr_addr_ex;
    logic [31:0] mem_wr_data_ex;
    logic [ 3:0] mem_wr_strb_ex;

    logic        mem_rd_enable_ex;
    logic [31:0] mem_rd_addr_ex;
    logic [ 4:0] mem_rd_reg_ex;
    logic [ 4:0] mem_rd_func_ex;

    // todo: unused?
    wire [31:0] rs1_value = !s2_inst_rs1 ? 0 : regfile[s2_inst_rs1]; // alu in 1
    wire [31:0] rs2_value = !s2_inst_rs2 ? 0 : regfile[s2_inst_rs2]; // alu in 2
    always_comb begin

        ex_next_wr = 0;
        ex_next_rd = 0;
        ex_illinst = 0; // for catching exceptions

        // reading
        mem_wr_enable_ex = 0;
        mem_wr_addr_ex = 'hx;
        mem_wr_data_ex = 'hx;
        mem_wr_strb_ex = 'hx;

        // writing
        mem_rd_enable_ex = 0;
        mem_rd_addr_ex = 'hx;
        mem_rd_reg_ex = 'hx;
        mem_rd_func_ex = 'hx;

        case (s2_inst_opcode)
            // ---- control transfers ---------------------------------------
            // The redirect itself already happened in @insd (that is
            // where the delay slot comes from).  These arms only produce the
            // architectural side effects of the instruction.

            // Add Upper Immediate to Program Counter.  [s2_pc] is this
            // instruction's own address.
            OPCODE_AUIPC: begin
                ex_next_wr = 1;
                ex_next_rd = (s2_inst[31:12] << 12) + s2_pc;
            end

            OPCODE_JAL: begin
                ex_next_wr = 1;
                ex_next_rd = s2_pc + 8; // since its the addr after delay slot
            end

            OPCODE_JALR: begin
                case (s2_inst_funct3)
                    3'b000  /* JALR */: begin
                        ex_next_wr = 1;
                        ex_next_rd = s2_pc + 8; // ibid
                    end
                    default: ex_illinst = 1;
                endcase
            end

            // @delay_slot_branch since we do branching there we treat branch instructions
            // that make it till here as "illegal"
            OPCODE_BRANCH: begin
                case (s2_inst_funct3)
                    3'b000, 3'b001, 3'b100, 3'b101, 3'b110, 3'b111: ;
                    default: ex_illinst = 1;
                endcase
            end


            // TODO: move other stuff here as well
            // LUI, LOAD, STORE, OP_IMM, OP, SYSTEM (Zicsr + MRET + EBREAK).
            // Everything you lift from nerv_part4.sv goes here.

            // @csr:instructions
            OPCODE_SYSTEM: begin
                // assign {zicsr_src_dest, zicsr_rs1, zicsr_funct3, zicsr_rd, _zicsr_opcode} = s2_inst;
                // 1. decode the intputs
                // 2. use inputs to do some calcs
                // 3. set the inputs to the input values to the csrfile
                // 4. link csr file back to regfile (will need a mux or something)

                case (zicsr_funct3)
                /*
                    csrrw:
                    cycle 1: get rs value from regfile
                    cycle 2: write to csr and also write output of csr to regfile
                    * special handling for rd=x0; no csr read takes place

                    csrrs: (what would rs be used for?)
                    same as rw but we also use the bitmask

                    csrrc: read and clear
                */

                // TODO: rd = 0 handling
                // TODO: add immediates
                // TODO: what does "zero extend by XLEN mean??"
                3'b000: /*CSRRW */ begin
                    // swap registers
                    csr_re = 32'hFFFF_FFFF;
                    csr_we = 32'hFFFF_FFFF;
                    csr_wdata = s2_zicsr_rs1_val;
                    csr_addr = zicsr_src_dest;

                end

                3'b001: /*CSRRS */ begin
                    // read and set bits
                    csr_re = 32'hFFFF_FFFF; // read entire reg
                    csr_we = s2_zicsr_rs1_val; // only set provided bits
                    csr_wdata = 32'hFFFF_FFFF; // forces setting
                    csr_addr = zicsr_src_dest; // as usual
                end

                3'b010: /*CSRRC */ begin
                    // read and clear bits
                    csr_re = 32'hFFFF_FFFF; // read entire reg
                    csr_we = s2_zicsr_rs1_val; // only clear provided bits
                    csr_wdata = 32'b0; // forces clearing
                    csr_addr = zicsr_src_dest; // as usual
                end



                endcase

            end

            default:; // TODO: err?  (this default is also where the
                      //        illegal-instruction trap has to come from -
                      //        `fence` in firmware08/09 lands here)
        endcase

        // a jump / branch target that was not word aligned, detected in
        // @insd and carried through the pipeline
        // also invalid values for ALU operations would be good.
        ex_illinst = ex_illinst | ex_misaligned;

        // todo: what
        // @dmem read completing.  This cycle's EX instruction is a
        // REPLAY: the operands it is holding are the ones latched before the
        // load result landed, so nothing it produces may be committed - in
        // particular a STORE must not be issued with a stale address/data.
        if (stall) begin
            ex_next_wr      = 0;
            ex_illinst      = 0;
            mem_rd_enable_ex = 0;
            mem_wr_enable_ex = 0;
        end

        // NOTE: the write-back mux must still give the load priority over
        // ex_next_wr on this cycle (see the nerv_part4.sv retire block), and
        // the reset override belongs here too.

    end
    `endif

    // ==============================================
    // @dmem latency.  The read is synchronous, so the load result and
    // the address it came from are both needed one cycle later.  [stall] (up in
    // @pipeline_control) is the cycle in which this is valid.
    always @(posedge clock) begin
        mem_rd_enable_q <= mem_rd_enable_ex;
        mem_rd_reg_q    <= mem_rd_reg_ex;
        mem_rd_func_q   <= mem_rd_func_ex;
        if (reset) begin
            mem_rd_enable_q <= 0;
        end
    end

    // @dmem output wiring, lifted as-is from nerv_part4.sv.  The
    // addresses are word-aligned by the STORE/LOAD arms in @exec.
    assign dmem_valid = mem_wr_enable_ex || mem_rd_enable_ex;
    assign dmem_addr  = mem_wr_enable_ex ? mem_wr_addr_ex : mem_rd_enable_ex ? mem_rd_addr_ex : 32'hx;
    assign dmem_wstrb = mem_wr_enable_ex ? mem_wr_strb_ex : mem_rd_enable_ex ? 4'h0 : 4'hx;
    assign dmem_wdata = mem_wr_enable_ex ? mem_wr_data_ex : 32'hx;

    // @memory:regfile_writes behaviour of regfile writes
    always @(posedge clock) begin
        if (regfile_csr_w_en) begin
            regfile[zicsr_rd] = csr_rdata;
        end
    end

endmodule


// CSR file.  Slightly different than register file since it's bit addressable
// this skeleton provides bit addressable read & write.
// Some CSRs are marked read-only, some write only, and some read/write
// It's intended that you connect the addr, re, we, wdata and rdata to the
// instruction decoder logic, while the "bits" ports connect to internal "wire" or "logic" signals
module csrfile (
    input wire clock,  // clock input
    input wire reset,  // reset signal
    input wire [11:0] addr,  // CSR address (CSR ID number)
    input wire [31:0] re,  // bit-addressable write enable
    input wire [31:0] we,  // bit-addressable read enable
    output wire [31:0] rdata,  // CSR bits  for read out (use w/ re lines)
    input wire [31:0] wdata,  // CSR bits for write input (use w/ we lines)

    // raw bits
    input wire [31:0] ro_mepc_bits,  // actual internal bits of MEPC register
    inout wire [31:0] rw_mstatus_bits,  // ... etc
    output wire [31:0] rw_mie_bits,
    input wire [31:0] ro_mtvec_bits,
    input wire [31:0] ro_mip_bits,
    input wire [31:0] ro_mcause_bits,
    output wire [31:0] rw_mscratch_bits
);
    // TODO:
    /*
    * ```mepc``` Machine exception PC
    * ```mstatus``` Machine status
    * ```mie``` Machine interrupt enable
    * ```mtvec``` Machine trap vector
    * ```mip```  Machine interrupt pending
    * ```mcause``` Machine exception cause
    */


    /*
    @csr:MEPC ================================================
    for _EXCEPTION_, holds location of the return address (which means, some valid
    [imem_addr]) |
    for _INTERRUPT_ indicates the instruction that was aborted (would be in @insd)
    for the 2 stage pipeline, assuming inst in @exec always gets executed. NOTE:
    aborted instruction MUST BE RERUN |
    for _TRAP_ indicates the next instruction [pc]+4 / [npc]
    */
    // simple iout that can be assigned to



    /*
    @csr:MSTATUS ================================================
     apparenlty only holds 1 bit? (GIE: global interupt enable)
        | 1 = interrupts are processed
        | 0 = ignore interrupts
        | ignore writes to  all other bits (use a mask)
        | Only enable when @MIE is also set |
    Takes priority over @MIE |
    NOTE: apparenlty supposed to be bit 3, according to the specs and
    some testcases

    */
    // create mask for bit 3

    /*
    @csr:MIE ================================================
     holds 1 bit like @MSTATUS, at index 11
        | 1 = interrupts are processed
        | 0 = ignore interrupts
        | ignore writes to  all other bits (use a mask)
        | only enable when @MSTATUS is set
    TODO: confusion between this and @MSTATUS since they seem to describe
    the same thing
    */


    /*
    @csr:MTVEC ================================================
    README has typo, its read only |
    hard wired to the address 0x1000
    | ignore writes
    | "good practice" to make this a system verilog constant or param
    */


    /*
    @csr:MIP ================================================
    Only hold single bit at 11, like @MIE indicating if there is
    an external interrupt pending ([intr] set for at least one cycle) |
    Read only, cleared once the mret instruction is executed |
    all other bits always read zero
    */


    /*
    @csr:MSCRATCH ================================================
    Free 32-bit CSR, only csr that's read and write it seems |
    can be manipulated with the appropriate csr instructions
    */

    // internal flipflops
    // these will hold logic that is for read-write and write only registers
    // the rest of the CSRs are read-only, and so the actual FF is contained
    // inside the processor logic, not here.
    logic [31:0] mie_bits;
    logic [31:0] mscratch_bits;
    logic [31:0] mstatus_bits;


    genvar i;

    // combinational read
    assign rdata = (addr == CSR_MEPC) 		? ro_mepc_bits 		& re :
					(addr == CSR_MSTATUS) 	? rw_mstatus_bits	& re :
					(addr == CSR_MIE) 		? rw_mie_bits 		& re :
					(addr == CSR_MTVEC) 	? ro_mtvec_bits 	& re :
					(addr == CSR_MIP) 		? ro_mip_bits 		& re :
					(addr == CSR_MCAUSE) 	? ro_mcause_bits 	& re:
					(addr == CSR_MSCRATCH) 	? rw_mscratch_bits 	& re:
					32'hx;


    // map the internal FFs into ports that can be used by your processor's controller
    assign rw_mie_bits = mie_bits;
    assign rw_mscratch_bits = mscratch_bits;
    assign rw_mstatus_bits = mstatus_bits;

    // construct  bitwise those CSRs that are read-write
    // the rest not listed here are read-only, and thus controlled
    // outside this module
    localparam [31:0] MSTATUS_MASK = 32'h0000_0088;  // MPIE(7) | GIE(3)
    localparam [31:0] MIE_MASK     = 32'h0000_0800;  // MEIE(11)

    generate
        for (i = 0; i < 32; i++) begin : gen_write_bits

            always @(posedge clock) begin
                if (reset == 1) begin
                    mie_bits[i] <= 0;
                    mscratch_bits[i] <= 0;
                end else if (addr == CSR_MIE     && we[i] && MIE_MASK[i])     mie_bits[i]     <= wdata[i];
                else if (addr == CSR_MSCRATCH&& we[i])                     mscratch_bits[i]<= wdata[i];
                else if (addr == CSR_MSTATUS && we[i] && MSTATUS_MASK[i]) mstatus_bits[i] <= wdata[i];
            end
        end : gen_write_bits
    endgenerate


endmodule
