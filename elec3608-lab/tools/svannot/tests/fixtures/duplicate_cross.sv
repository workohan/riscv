// Fixture: the same annotation name defined in two separate files, to exercise
// workspace-level duplicate detection.  Paired with duplicate_other.sv.
module duplicate_cross;
    logic a;

    // @seq:cross_file    defined here and again in duplicate_other.sv
    always_ff @(posedge clk) begin
        a <= 1'b0;
    end
endmodule
