// Fixture: words that look like keywords but sit inside strings or comments.
// None of `end`, `endmodule`, `endcase`, `begin` below may create a block, and
// an annotation-looking token inside a string literal must not be parsed.
module comment_edge_cases;
    logic a;

    initial begin
        $display("this string contains // and /* and end and endmodule");
        $display("a quote \" then more text, then begin and @fake_annotation");
    end

    /* a block comment containing the words
     * end endmodule endcase begin function endfunction generate endgenerate
     * which must not create any blocks
     */

    // @comb:real_block    the only real block below
    always_comb begin
        a = 1'b0;   // trailing reference inside the block: @real_block
    end

endmodule
