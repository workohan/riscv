.section .text
.global main
.global _start
_start:

addi x8, zero, 0
addi x10, zero, 1
addi x9, zero, 1
beq x10, x9, jump_here
addi x8, x8, 1
addi x8, x8, 1
addi x8, x8, 1
addi x8, x8, 1
addi x8, x8, 1
addi x8, x8, 1

jump_here:
addi x7, zero, 7

nop
ebreak
