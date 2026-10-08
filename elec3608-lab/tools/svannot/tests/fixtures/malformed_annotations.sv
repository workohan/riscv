// Fixture: malformed annotations that must be reported rather than ignored.
module malformed_annotations;
    logic a;

    // @:noname    a category with no name
    always_comb begin
        a = 1'b0;
    end

    // @Bad_Category:thing    categories must be lowercase
    always_comb begin
        a = 1'b1;
    end

    // a stray at-sign: @ followed by a space
    // @ and another: @  fine
    always_comb begin
        a = 1'b0;
    end
endmodule
