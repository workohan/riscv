Make sure to categorise things properly otherwise it will be really hard to understand!!

# Making actual design

## Design decisions

- NOTE: apparenlty this relates to how we idenitifed and handled trap instructions?

1. Interrupts
2. Exceptions
3. Add pipelining (seems we need both single and pipelined processor?

### CSR Lore reference to

- https://docs.riscv.org/reference/isa/v20260120/priv/priv-csrs.html: registers and input decode
- https://docs.riscv.org/reference/isa/v20260120/unpriv/zicsr.html: Table 7 has the num id of each csr. everything has highest privellege M
-

### Interupts and Exceptions

- Traps are trigged by instruction (and only happen during execute / mem stage)
- Interrupts are trigged from outside, can happen whenever
- TODO: how do we differentiate them for MEPC handling

### Conditions for exceptions

- Divide by zero
- "illegal instruction" -> am i supposed to know what? like bit shift 33 or something todo
  - In readme it says that they usually happen during ex or mem, but for illegal instructions we could technically detect them during ID. => okay?

## How to move to different execution

- todo: how to know what value to jump to for pc. or is it given --> nvm we always jump to 1000 i just remmebered

## How to return to previous execution

- Note: since we're interrupting something (and we assume thats in ID since what are we even going to stop for EX. writebacks?) the return address is going to be the instruction in ID, so the previous program counter value i.e. ppc.
- todo: ... what do i actaully "stop"? for single cycle there is nothing to stop, you just start executing excep / intr code next cycle. for 2 stage TODO QUESTION: do you stop what is in id from progressing to ex? for intr it seems so + exceptions detected during the execute stage. 
  - Trying to get intr / except code into the cpu as fast as possible (i.e. next cycle). but that might not be possible since we need to do addition (???) to get the jump address. 

## Questions

1. what are the 6 instructions that they want implemented?
2. why is there ebreak in mtvec section?
3. When we interrupt something and there is an instruction in EX, do we stop that as well?
4. https://edstem.org/au/courses/39073/discussion/3620175 --> ebreak handling is still opaque. worse yet, seems like we have to choose something:
   "This is an example of something you should discuss in your report. Make a decision on how, as an engineer, you'd like to handle this situation. Should you flag this test as erroneous? Should you accomodate the tests and possibly make your design incosistent? Should the test be rewritten and how? Ultimately, I'll read your report first, and if you have a clear reason for deviating from the test files that makes logical sense, and your design operates correctly under that thinking, I should still be able to give you the mark.
   For 1.) This example code is using a delay slot. If you are able to code your design without needing a delay slot, as with 2.), document your thinking, and how you believe the test should be ignored, modified, or if you decide to accomodate it.
   "
5. what happens if the code to execute after interrupt / execution is empty? -- edgecase

## Assorted todos

1. Disable some of the linting / warnings since many are useless and i have like 3 lsps running right now.
2. Any way to "interact" with svannot once its running (setting up an api or something, unix domain sockets?) so that i can ask it queries and get it to tell me like "what are some errors" "what are some warnings" query the list of known identifiers and categories so that I can search things easier
3. May require some kind of a cli / repl. Don't wanna use web since, well... heavy.
4. Could write in OCaml!! or use reedline or something
