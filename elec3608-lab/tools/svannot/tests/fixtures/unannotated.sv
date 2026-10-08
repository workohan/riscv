// Fixture: one annotated block and one that was forgotten, for the optional
// `unannotated-blocks` hint.
module unannotated;
    logic a;
    logic b;

    // @comb:annotated_one    this one is annotated
    always_comb begin
        a = 1'b0;
    end

    always_comb begin
        b = 1'b1;
    end

    // @seq:annotated_two    so is this one
    always_ff @(posedge clk) begin
        a <= b;
    end
endmodule
