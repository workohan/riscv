Make sure to categorise things properly otherwise it will be really hard to understand!!

# Make things
1. lsp for this thing
  * only works in comments
  * annotate comments with @<identifier> so that i can look up and annotate specific verilog components
    * Assumes that each component has its own "block", ie. an always_comb block for a multiplexer
  * Shows outline + tree of symbols in the zed outline panel
  * Can reference from other comments, like "... links to @pcmux ..."
  * Format
    * Annotate component "@instruction_decode takes instruction from ir and splits into various segments"
    * Link component "TODO: figure out how to link @exception_registers and @regfile so that we can work with them
    * (optional) Refer to verilog hardware with appropriate names: "@instruction_decode takes instruction from [ir] (or some other way to annotate) ..."
    * (optional) Draw.io sync; i download my diagram as an XML or something and somehow "annotate" each thing that is supposed to be a component / wire in my verilog. as such, i can read that file and get warnings that things that are defined have not been defined yet (this is super unecessary i can easily do this by hand).
2. Set up linting and warnings etc for the project
  * Needs to be checked in the makefile i think
  * Also will need testcases etc. Fuzzing? 
3. Make the actual design
  * NOTE: check ed to doulbe check what typos are present in the readme
  * Research things etc to determine what needs to be considered
  * Start with 2 stage pipeline or single cycle? May be easier to pipeline the single cycle and than just have a solid pipelined processor first try
