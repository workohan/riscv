// Fixture: one well-formed definition and one reference that resolves nowhere.
module undefined_ref;
    logic a;

    // @comb:only_def    the one real definition in this file
    always_comb begin
        a = 1'b0;
    end

    // refers to something that was never defined: @nowhere
endmodule
