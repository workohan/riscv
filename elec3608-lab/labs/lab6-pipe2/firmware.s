.section .text
.global main
.global _start
_start:

addi x10, zero, 0
addi x9, zero, 1
addi x8, zero, 9

loop:
add x10, x10, x9
bge x8, x9, loop
addi x9, x9, 1

nop
ebreak
