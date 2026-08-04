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
    output result_eq_zero
);

    // Compute result
    always_comb begin
        case (alu_function)
            `ALU_ADD: result = op_a + op_b;
            `ALU_SUB: result = op_a - op_b;

            `ALU_XOR: result = op_a ^ op_b;  // am i supposed to be using signs for this stuff?
            `ALU_OR:  result = op_a | op_b;
            `ALU_AND: result = op_a & op_b;

            // TODO: handle edgecases where you're shifting by >31 bits
            // only use the last few bits?
            `ALU_SLL: result = op_a << op_b;
            `ALU_SRL: result = op_a >> op_b;
            ALU_SRA: result = op_a + op_b;
            /* SRL impl:
            wire msb = op_a[bits-1]; // to know what it should be
            wire (?) no_bits_to_shift = op_b[5:0] // from earlier

            // now conv to one hot encoding; i.e. 6 = 11111....
            wire (?) ONES = 31b'6 (should actually be set to the no. bits) // this is the 111... to use
            wire temp_pad = ONES << (32 - no_bits_to_shift) // results in array like {1}s + {0}s
            wire actual_padding = temp_pad & msb; // to get 0s or 1s based on msb

            result = (op_a >> op_b) + actual_padding;
            */


            // ALU_SLT:
            // ALU_SLTU:
            default:  result = `ZERO;
        endcase

        result_eq_zero = (result == `ZERO) ? 1'b1 : 1'b0;  // simple comparision to set zero

        // gates: you can implement this by &&ing all the bits together and then inverting the result
        //
    end

endmodule
