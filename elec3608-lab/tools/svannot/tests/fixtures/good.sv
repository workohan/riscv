`default_nettype none

// @module:nerv   pipelined RV32I processor used by the lab-6 delay-slot work
module nerv #(
    parameter [31:0] RESET_ADDR = 32'h0000_0000
) (
    input  clock,
    input  reset,
    output [31:0] imem_addr
);

    logic [31:0] pc;
    logic [31:0] npc;
    logic [31:0] br_target;

    /* @mux:pcmux    selects npc from reset, pc+4 and @br_target.
     *               driven by [pc] and [ppc].
     */
    always_comb begin
        npc = pc + 32'd4;
        if (reset) npc = RESET_ADDR;
    end

    // @seq:pc_reg    the fetch pointer; see @pcmux and @npc_mux
    always_ff @(posedge clock) begin
        if (reset) begin
            pc <= RESET_ADDR;
        end else begin
            pc <= npc;
        end
    end

    // @func:decode_insn  splits the fetched instruction into fields
    function automatic [6:0] decode_insn(input [31:0] insn);
        decode_insn = insn[6:0];
    endfunction

    // @wire:br_target   branch destination computed in @pcmux
    assign br_target = pc + 32'h8;

    // @alu:adder   the pc+4 adder, feeding @pcmux
    always_comb begin
        imem_addr = pc;
    end

    // a comment that is only a reference: see @pcmux for the redirect
    // and one that points nowhere: @does_not_exist

endmodule
