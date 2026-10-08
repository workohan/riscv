#  NERV -- Naive Educational RISC-V Processor
#
#  Copyright (C) 2020  N. Engelhardt <nak@yosyshq.com>
#  Copyright (C) 2020  Claire Xenia Wolf <claire@yosyshq.com>
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

TOOLCHAIN_PREFIX?=riscv64-unknown-elf-
VERILATOR = verilator
RDOCKER = docker run --platform linux/amd64 -it -e DISPLAY=host.docker.internal:0 -v `pwd`:/config phwl/elec3608-cad:latest
FIRMWAREFILE=firmware01_read_mtvec.hex

# all tests
ALLFIRMWARE=firmware00_baseline.hex \
	firmware01_read_mtvec.hex \
	firmware02_write_mtvec.hex \
	firmware03_write_scratch.hex \
	firmware04_intr.hex \
	firmware05_intr_disabled.hex \
	firmware06_intr_disabled2.hex \
	firmware07_mret.hex \
	firmware08_illegal.hex \
	firmware09_illegal_mret.hex \

all:	$(FIRMWAREFILE) test_verilator # nerv.asc

# logging file name
LOGFILE=`basename $(FIRMWAREFILE) .hex`.log
ASMFILE=`basename $(FIRMWAREFILE) .hex`.s
RESULTFILE=results.log

allresults:
	$(foreach ff, $(ALLFIRMWARE),  make result FIRMWAREFILE=$(ff);)
	@echo "---------------------------------------------------"
	@echo "Results..."
	@cat $(RESULTFILE)

result : all
	@python checkregs.py $(LOGFILE) $(ASMFILE) | tee --append $(RESULTFILE)

test_verilator: testbench_verilator
	@./obj_dir/Vtestbench +vcd > $(LOGFILE)

%.asc: %.json
	nextpnr-ice40 --hx8k --pcf $*.pcf --json $*.json --asc $*.asc --pcf-allow-unconstrained -l $*-pnr.log

%.json: %.sv
	yosys -s $*.yosys -l $*-yosys.log

testbench_verilator: $(FIRMWAREFILE) testbench.sv nerv-interrupt.sv testbench.cpp
	$(VERILATOR) --cc --exe -Wno-lint -trace --top-module testbench \
	-Gfirmwarefile=\"$(FIRMWAREFILE)\" \
	testbench.sv nerv-interrupt.sv testbench.cpp
	$(MAKE) -C obj_dir -f Vtestbench.mk

# ---------------------------------------------------------------------------
# Linting.  Local addition -- the course Makefile is NOT part of the Canvas
# submission (README "Submission": a .pdf report plus two .sv files), so this
# does not affect marking.
#
#   make lint           lint the processor design on its own.
#                       The recipe above passes -Wno-lint, so none of this
#                       was previously checked.
#   make lint-contract  elaborate the design *together with* testbench.sv.
#                       This is the check that the internal signal names the
#                       testbench pokes at actually exist (regfile, csr_*,
#                       pc -- see testbench.sv:138-148).  It will fail loudly
#                       until they do, which is the point: without them the
#                       whole test suite fails to elaborate.
#   make lint-names     the same contract check without needing Verilator.
# ---------------------------------------------------------------------------
SVANNOT = ../../tools/svannot
DUTFILES = nerv-interrupt.sv $(wildcard singlecycle-interrupt.sv)
LINTFLAGS = --lint-only -Wall -Wno-DECLFILENAME

lint:
	$(VERILATOR) $(LINTFLAGS) --top-module nerv $(DUTFILES)
	@echo "lint: ok"

lint-contract:
	$(VERILATOR) $(LINTFLAGS) --top-module testbench testbench.sv $(DUTFILES)
	@echo "lint-contract: ok"

lint-names:
	@python3 $(SVANNOT)/lint/check_contract.py nerv-interrupt.sv

.PHONY: all allresults result test_verilator testbench_verilator show rundocker \
        clean lint lint-contract lint-names

%.elf: %.s
	$(TOOLCHAIN_PREFIX)gcc -march=rv32i -mabi=ilp32 -Os -Wall -Wextra -Wl,-Bstatic,-T,sections.lds,--strip-debug -ffreestanding -nostdlib -o $@ $^

%.hex: %.elf
	$(TOOLCHAIN_PREFIX)objcopy -O verilog $< $@

show:
	gtkwave testbench.vcd testbench.gtkw >> gtkwave.log 2>&1 &

rundocker:
	$(RDOCKER)

clean:
	rm -rf *.elf *.hex testbench testbench.vcd gtkwave.log
	rm -rf disasm.o disasm.s checks/ cexdata/ obj_dir
	rm -rf *.log *.asc *.json
