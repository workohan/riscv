// Fixture: second half of the cross-file duplicate pair (see duplicate_cross.sv).
module duplicate_other;
    logic a;

    // @seq:cross_file    also defined in duplicate_cross.sv
    always_ff @(posedge clk) begin
        a <= 1'b1;
    end
endmodule
