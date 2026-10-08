/*
 *  ELEC3608 Lab 6, Part 3 — firmware rewritten for the branch delay slot.
 *
 *  The pipelined processor executes the instruction AFTER a taken branch
 *  (and after a not-taken branch), i.e. the branch delay slot.  The loop
 *  below therefore puts the loop increment in the delay slot of `bge`,
 *  where it does useful work instead of being a `nop`.
 *
 *  Result: x10 = 1 + 2 + ... + 10 = 55
 */

.section .text
.global main
.global _start
_start:

    addi x10, zero, 0        # x10 = running sum
    addi x9,  zero, 1        # x9  = i  (the counter)
    addi x8,  zero, 9        # x8  = loop bound -- see the NOTE below

    # NOTE ON THE BOUND (why 9 and not 10)
    #
    # Moving the increment into the delay slot moves it AFTER the branch
    # test, so the branch compares the value of i from BEFORE the increment.
    # The loop therefore runs one pass longer than the bound suggests:
    #
    #     this ordering   (add ; bge ; addi)  ->  adds i = 1 .. x8+1
    #                                              sum = (x8+1)(x8+2)/2
    #                                              x8 = 9  ->  55
    #
    #     original order  (add ; addi ; bge)  ->  adds i = 1 .. x8
    #                                              sum = x8(x8+1)/2
    #                                              x8 = 10  ->  55
    #
    # So the bound drops by one purely because of where the increment sits.

loop:
    add  x10, x10, x9        # sum += i
    bge  x8,  x9,  loop      # repeat while x8 >= i
    addi x9,  x9,  1         # DELAY SLOT: i++   (always executed)

    ebreak                   # x10 = 55, x9 = 11, x8 = 9
