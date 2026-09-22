.section .text
.global main
.global _start
_start:

addi x10, zero, 1
addi x9, zero, 1
beq x10, x9, jump_here
addi x8, zero, 8
addi x6, zero, 6

jump_here:
addi x7, zero, 7

nop
ebreak
