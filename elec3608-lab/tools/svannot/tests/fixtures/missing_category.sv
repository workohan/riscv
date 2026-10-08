// Fixture: a comment that looks like a definition but omitted its category.
module missing_category;
    logic a;

    // @forgot_the_category   this was meant to be a definition
    always_comb begin
        a = 1'b0;
    end

    // @comb:proper    a correctly formed definition
    always_comb begin
        a = 1'b1;
    end
endmodule
