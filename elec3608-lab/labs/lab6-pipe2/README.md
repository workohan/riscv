# Pipelined RV32 (Part 2 of 2)

In this lab you will deal with branch instructions for the 2-stage pipelined processor.

## Lab Questions
### Part 1 - Assembly Language (30%) (DONE; double check output)
Using the design and ```firmware.s``` code from the previous lab,
rewrite the sequence of instructions so that it is as compact as
possible and uses a loop.  Verify the operation of your program
using the single cycle processor originally provided.

### Part 2 - Pipelined Processor Datapath (20%) 
A single branch delay slot is the scheme used in the [MIPS-I](https://en.wikipedia.org/wiki/MIPS_architecture) processor. Here is a section from wikipedia:

*All MIPS I control flow instructions are followed by a branch delay slot. Unless the branch delay slot is filled by an instruction performing useful work, an nop is substituted. MIPS I branch instructions compare the contents of a GPR (rs) against zero or another GPR (rt) as signed integers and branch if the specified condition is true.*

Draw a picture of a modified datapath which allows your pipelined
processor to pipeline branches with a single delay slot.

TODO:
* how to represent a nop (or is it there already)
* Currently:
  1. Branch hits execute
  2. Alu computes the result value using ppc (?? or something)
* probably involves the ppc (previous pc). so
  0. All instructions are latched onto ppc, there is branch and then another instruction
  1. Branch instruction hits execute

### Part 3 - Pipelined Processor (50%) 
Modify the Verilog design in Part 2 of the previous lab so that the
branch decision is moved to the second pipeline stage and the
instruction in the branch delay slot is always executed. 

Rewrite the ```firmware.s``` program so that it can execute in your
pipelined processor with delay slot and fill it with a useful
instruction.

Explain in your lab book:
 1. how the scheme works
 2. changes in Verilog that were needed and 
 3. illustrate execution of ```firmware.s``` with a GTKWave screen shot.
