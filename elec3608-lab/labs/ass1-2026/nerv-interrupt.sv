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

    /* @csr:intr_handler parses the 1 cycle [intr] activation and handles
    execution*/
    // [intr] comes in
    // """signals""" go out to tell everything to stop what its doing rn
    // I think this just means tell whatever is in ID to stop

    // @stage:pc_stuff everything relating to manipulating the program counter.
    logic [31:0] npc;  // value that pc will be upated to
    logic [31:0] pc;  // points to the the next instruction to load (i+1)

    // @stage:insd after @pc_stuff, actual stage 1 of pipeline

    logic [31:0] ir;  // in: imem_data, outputs the ith instruction
    wire  [31:0] s1_inst;  // equal to [ir], just an alias
    always @(posedge clock) begin
        ir <= imem_data;
    end
    assign s1_inst = ir;

    // @memory:regfile the cpu's registers

    // @memory:csrfile uses [csrfile]
    // instantiate the CSR file
    csrfile csr_file (
    // add your code here
    );

    // @stage:exec after @insd, stage 2 of the pipeline

    // @memory:dmem and its associated signals. note that dmem stuff is external
    // @decode:dmem_sigs done in @exec for convinience
    wire [31:0] s2_inst;  // latches [s1_inst]
    always @(posedge clock) begin
        s2_inst <= s1_inst;
    end

    // @decode:alu_sigs happens in @exec

    /* from old cpu: note that the values must be latched from the other stuff
        assign dmem_valid = mem_wr_enable_ex || mem_rd_enable_ex;
        assign dmem_addr  = mem_wr_enable_ex ? mem_wr_addr_ex : mem_rd_enable_ex ? mem_rd_addr_ex : 32'hx;
        assign dmem_wstrb = mem_wr_enable_ex ? mem_wr_strb_ex : mem_rd_enable_ex ? 4'h0 : 4'hx;
        assign dmem_wdata = mem_wr_enable_ex ? mem_wr_data_ex : 32'hx;
    */

    // [dmem_addr] is delayed by




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
					31'h x;

    // map the internal FFs into ports that can be used by your processor's controller
    assign rw_mie_bits = mie_bits;
    assign rw_mscratch_bits = mscratch_bits;
    assign rw_mstatus_bits = mstatus_bits;

    // construct  bitwise those CSRs that are read-write
    // the rest not listed here are read-only, and thus controlled
    // outside this module
    generate
        for (i = 0; i < 32; i++) begin : gen_write_bits

            always @(posedge clock) begin
                if (reset == 1) begin
                    mie_bits[i] <= 0;
                    mscratch_bits[i] <= 0;
                end else if (addr == CSR_MIE && we[i]) mie_bits[i] <= wdata[i];
                else if (addr == CSR_MSCRATCH && we[i]) mscratch_bits[i] <= wdata[i];
                else if (addr == CSR_MSTATUS && we[i]) mstatus_bits[i] <= wdata[i];
            end
        end : gen_write_bits
    endgenerate


endmodule

// for convinience
module nerv_alu (
    /*
    input [4:0] alu_function,
    input [31:0] op_a,
    input [31:0] op_b,
    output logic [31:0] result,
    output logic result_eq_zero
    */
);
    // todo: should be taken from previous lab stuff?
    logic hi = 0;
endmodule
