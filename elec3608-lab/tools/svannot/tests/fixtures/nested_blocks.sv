// Fixture: block-extent torture.  Every construct below contains nested
// begin/end, case/endcase, and if/else with and without begin blocks -- all of
// which the scanner has to walk to find where the enclosing block ends.
module nested_blocks (
    input logic clk,
    input logic rst_n
);
    logic [31:0] a, b, c;
    logic [31:0] sel;

    // @alu:inner_adder    nested inside if/else and begin/end
    always_comb begin
        if (sel[0]) begin
            a = b + c;
        end else begin
            a = b - c;
        end
        case (sel[1:0])
            2'b00:   a = 32'd0;
            2'b01:   begin
                         a = 32'd1;
                     end
            default: a = 32'd2;
        endcase
        if (sel[2]) a = 32'd3;
    end

    // @func:nested_fn    a function containing begin/end
    function automatic [31:0] nested_fn(input [31:0] x);
        begin
            if (x[0]) begin
                nested_fn = x;
            end else begin
                nested_fn = ~x;
            end
        end
    endfunction

    // @seq:with_reset    always_ff with a two-edge sensitivity list
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) b <= 32'd0;
        else        b <= a;
    end

    // @comb:single_stmt    an always_comb with no begin/end at all
    always_comb c = a & b;

endmodule
