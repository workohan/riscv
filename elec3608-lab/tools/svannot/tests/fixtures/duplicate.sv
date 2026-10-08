// Fixture: the same annotation name defined twice -- must be reported.
module duplicate;
    logic a;
    logic b;

    // @comb:shared    first definition
    always_comb begin
        a = 1'b0;
    end

    // @comb:shared    second definition of the same name
    always_comb begin
        b = 1'b0;
    end

    // a reference to the ambiguous name: @shared
endmodule
