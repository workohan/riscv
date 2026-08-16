// a simple alu
//
`include "constants.svh"

`default_nettype none

//
module alu (
    input [4:0] alu_function,
    input [31:0] op_a,
    input [31:0] op_b,
    output logic [31:0] result,
    output logic result_eq_zero
);

    // Compute result
    always_comb begin
        case (alu_function)
            `ALU_ADD: result = op_a + op_b;
            `ALU_SUB: result = op_a - op_b;

            `ALU_XOR: result = op_a ^ op_b;
            `ALU_OR:  result = op_a | op_b;
            `ALU_AND: result = op_a & op_b;

            `ALU_SLL: result = op_a << op_b[4:0];
            `ALU_SRL: result = op_a >> op_b[4:0];
            `ALU_SRA: result = $signed(op_a) >>> op_b[4:0];

            `ALU_SLT: result = ($signed(op_a) < $signed(op_b)) ? 32'd1 : 32'd0;
            `ALU_SLTU: result = (op_a < op_b) ? 32'd1 : 32'd0;
            default:  result = `ZERO;
        endcase

        result_eq_zero = (result == `ZERO) ? 1'b1 : 1'b0;  // simple comparision to set zero

    end

endmodule
