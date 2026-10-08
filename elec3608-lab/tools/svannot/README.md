# svannot — annotation-driven symbols for SystemVerilog

Tools built alongside **ELEC3608 Assignment 1 (`labs/ass1-2026`)**.

Three things live here:

| Directory | What it is | TODO item |
|---|---|---|
| `annot/` | The annotation language server (LSP) | 1 |
| `lint/` | Verilator lint + signal-contract checks | 2 |
| `docs/` | Design research and the README defect report | 3 (research) |

**No dependencies.** Everything is Python standard library — no `pygls`, no
`pytest`, no virtualenv. Zed launches `python3` directly, so there is nothing to
install and nothing to clean up.

---

## The annotation language

Annotations live **only in comments**, which is why no SystemVerilog parser is
needed for any of this.

```systemverilog
// @mux:pcmux    selects npc from reset, pc+4 and @br_target; driven by [pc]
always_comb begin
    npc = pc + 32'd4;
end

// see @pcmux for the redirect logic
```

| Form | Meaning | Rule |
|---|---|---|
| `@<category>:<name> [description]` | **definition** | must be the first token of the comment; category is required |
| `@<name>` | **reference** | anywhere else in any comment |
| `[<identifier>]` | **hardware reference** (optional) | checked against identifiers in the file; only honoured inside comments that contain an `@` |

- `category` matches `[a-z][a-z0-9_]*` — `mux`, `comb`, `seq`, `reg`, `alu`,
  `decoder`, `ctrl`, `wire`, `func`, `module`, `instance`, `const`, anything you
  like.
- `name` matches `[A-Za-z_]\w*` and must be unique across the workspace.
- Because a definition requires the colon, a bare `@name` at the start of a
  comment is unambiguously a *reference*.

The category ends up in the outline label — `mux:pcmux`, not just `pcmux` —
because LSP symbol kinds are a fixed enum and would otherwise flatten a mux and
an ALU into the same "function".

**Where the annotation attaches.** A definition binds to its enclosing block if
it has one; otherwise to the next block starting within 3 lines; otherwise to
the module. So both of these work:

```systemverilog
// @seq:pc_reg     comment above the block           // @seq:pc_reg   or inside it
always_ff @(posedge clk) begin                       always_ff @(posedge clk) begin
    pc <= npc;                                           // @seq:pc_reg
end                                                  end
```

---

## Quick start

```bash
cd elec3608-lab/tools/svannot

python3 -m unittest discover -s tests -t .      # 106 tests, no install needed
python3 -m annot --check ../labs/ass1-2026      # summarise annotations + diagnostics
python3 -m annot --dump-json some_file.sv       # machine-readable symbols
python3 -m annot --stdio                        # the language server (Zed does this)
```

`--check` is the debugging entry point when the outline looks wrong: it prints
which annotation bound to which block, and every diagnostic.

```
=== good.sv ===
  L16   mux:pcmux              -> always_comb L19-22
        selects npc from reset, pc+4 and @br_target. driven by [pc] and [ppc].
  [warn] L24:57 undefined-reference: `@npc_mux` is not defined in any indexed file
```

---

## Zed setup

### Prerequisite: Rust via **rustup**, not the distro package

Zed compiles extensions to `wasm32-wasip2`. It will install that target for you
**only if Rust came from rustup**. A distribution `rustc` (Fedora's `rust`
package, Homebrew, Nix) has no `rustup` and no wasm32-wasip2 std, and the install
fails with:

```
failed to compile Rust extension
Caused by:
    the `wasm32-wasip2` target is not installed, and `rustup` is not available
    to install it.
```

Fedora cannot fix this through packages either: it ships
`rust-std-static-wasm32-unknown-unknown`, but **not** `wasm32-wasip2`. So:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
rustup target add wasm32-wasip2          # Zed would also do this itself
rustup target list --installed           # confirm wasm32-wasip2 is listed
```

**Then check Zed can see the toolchain.** rustup edits shell profiles, but a
Zed launched from the desktop may not inherit them. If the install still reports
"rustup is not available", make the tools visible to GUI apps:

```bash
sudo ln -sf ~/.cargo/bin/{cargo,rustc,rustup} /usr/local/bin/
```

and restart Zed. (Launching Zed from a terminal with `zed --foreground` also
inherits your shell PATH, and shows INFO-level logs while you retry.)

### Alternative: no Rust at all

If you would rather not install a toolchain, `zed-settings-no-extension.json`
reaches the same language server by overriding the binary of a server the
Verilog extension already registers — nothing to compile:

```bash
# use the contents of zed-settings-no-extension.json instead of the other snippet
```

This is **unverified**: if Zed asks the extension for a binary before honouring
`binary.path`, it may try to download the real `svls`. If the outline stays
empty after a restart, fall back to the rustup route above.

### The three steps

1. **Install the Verilog extension** (Extensions panel → "Verilog"). It supplies
   the `Verilog`/`SystemVerilog` languages and the tree-sitter grammar used for
   syntax highlighting. `svannot` only adds a language server.

2. **Install this as a dev extension**: command palette →
   `zed: install dev extension` → select `tools/svannot/zed`.

3. **Add the settings** from `zed-settings-snippet.json` to `settings.json`
   (`zed: open settings`):

   ```json
   {
     "languages": {
       "SystemVerilog": { "document_symbols": "on", "language_servers": ["svannot"] },
       "Verilog":       { "document_symbols": "on", "language_servers": ["svannot"] }
     },
     "lsp": {
       "svannot": {
         "binary": {
           "path": "/home/workohan/Desktop/ELEC3608/elec3608-lab/tools/svannot/run.sh",
           "arguments": ["--stdio"]
         }
       }
     }
   }
   ```

   Two things matter here:

   - **`"document_symbols": "on"`** is required. Zed's outline panel uses
     tree-sitter by default; this setting switches it to LSP symbols. Without it
     the outline will not show the annotations at all, even though everything
     else works.
   - **`"language_servers": ["svannot"]`** stops the four servers the Verilog
     extension registers (`verible`, `veridian`, `slang`, `svls`) from also
     starting. Drop it if you want them as well.
   - **Workspace root matters.** Zed resolves paths relative to whatever you
     opened. If you open `Desktop/ELEC3608`, the script is at
     `elec3608-lab/tools/svannot/run.sh`; if you open `elec3608-lab`, it is at
     `tools/svannot/run.sh`. The extension probes both, so normally you need to
     do nothing — but the `lsp.svannot.binary.path` entry above is the
     authoritative override if the probe ever misses. A `svannot-lsp` symlink
     on `$PATH` also works. If none of those resolve, the extension reports
     every path it tried in `zed: open log`.

4. Open a `.sv` file. `cmd-shift-b` opens the outline panel.

### Acceptance checklist

- [ ] The outline shows a `module:…` root with `category:name` children.
- [ ] `f12` on a `@name` reference jumps to its definition comment.
- [ ] `shift-f12` lists every reference, including the definition.
- [ ] Hover on a reference shows the description and where it is defined.
- [ ] Typing `@` offers completion of every known name, plus a template.
- [ ] An undefined reference gets a warning squiggle; the Diagnostics panel
      lists it.
- [ ] `project symbols: toggle` finds annotations across the workspace.

---

## What the server provides

| Method | Behaviour |
|---|---|
| `textDocument/documentSymbol` | hierarchical tree: module → components, nested by Verilog block |
| `textDocument/definition` | `@name` → its definition; `[signal]` → the signal's declaration |
| `textDocument/references` | every `@name` occurrence, workspace-wide |
| `textDocument/hover` | description, bound block, definition site |
| `textDocument/completion` | after `@`: all known names + a `@category:name` template |
| `workspace/symbol` | every annotation, for `project symbols: toggle` |
| `textDocument/publishDiagnostics` | the rules below |

### Diagnostics

| Code | Severity | Trigger |
|---|---|---|
| `undefined-reference` | Warning | `@name` defined nowhere in the workspace |
| `duplicate-definition` | Error | same name defined twice (same file or across files) |
| `missing-category` | Information | a comment starts with `@name` and it is defined nowhere — probably a definition that forgot its category |
| `bad-annotation` | Warning | malformed, e.g. `@:foo`, `@  spaced`, or an invalid category (with a suggested fix) |
| `unknown-identifier` | Warning | `[foo]` where no such identifier exists in the file |
| `parse-warning` | Information | the block scanner lost sync; binding fell back to module scope |
| `unannotated-block` | Hint | a component block with no annotation *(off by default)* |

### Configuration

The client may send `initializationOptions`:

```json
{
  "unannotatedBlocks": true,
  "unknownIdentifiers": false,
  "undefinedReferences": true,
  "duplicateDefinitions": true
}
```

`unannotatedBlocks` is the useful one once you are annotating systematically:
it turns every un-annotated `always_*`/`function`/`assign` into a hint, which
enforces the "every component has its own block, and every block is annotated"
discipline.

---

## Lint harness

`labs/ass1-2026/Makefile` gains three targets (the Makefile is **not** part of
the Canvas submission — README §Submission asks for a PDF and two `.sv` files —
so this does not affect marking):

```bash
make lint            # verilator --lint-only -Wall on the processor
make lint-contract   # lint the design *with* testbench.sv
make lint-names      # the signal-contract check, no Verilator needed
```

`make lint-contract` is the valuable one: `testbench.sv` reaches into the DUT by
exact name — `dut.regfile[r]`, `dut.pc`, `dut.csr_mepc`, `dut.csr_mie`,
`dut.csr_mtvec`, `dut.csr_mip`, `dut.csr_mcause`, `dut.csr_mstatus`,
`dut.csr_mscratch` — and **none of these are documented in the README or defined
in the skeleton**. Wrong names make the testbench fail to elaborate and the
entire suite breaks with an error pointing at `testbench.sv` rather than at your
design.

The previous recipe passed `-Wno-lint`, so none of this was ever checked.

`lint/lint.sh` does the same three steps for use outside the Makefile.

---

## Docs

| File | Contents |
|---|---|
| `docs/research.md` | Zicsr encodings and suppression rules, the CSR map, trap vs interrupt semantics, the interrupt timing budget, the undocumented signal contract, the harness mechanics, and a report checklist |
| `docs/semantics-contract.md` | the test suite distilled into rules R1–R19, the golden final state for each firmware, and the coverage gaps |
| `docs/readme-defects.md` | every README defect with line numbers, split into marks-affecting, toolchain, and cosmetic |

Three findings worth knowing before you write any RTL:

1. **`mstatus` GIE is bit 3, not bit 0.** README line 49 says position 0; all
   three interrupt tests enable bit 3 (`addi x1, x0, 0x8`, commented "enable MIE
   bit"). Implement it per the README and `firmware04`/`firmware07` can never
   take an interrupt.
2. **`trap` is the halt output, not the exception signal.** `ebreak` asserts it
   and stops without redirecting; an illegal instruction redirects to `mtvec`
   with `mcause=2` and keeps simulating.
3. **`firmware06`'s expectation is wrong** — its `ebreak` is at `0x20`, so "PC
   after ebreak" is `0x24`, not `0x0020`. That one-token fix has been applied.

---

## Layout

```
tools/svannot/
├── run.sh                       launcher Zed calls (sets PYTHONPATH)
├── zed-settings-snippet.json    paste into Zed's settings.json
├── annot/
│   ├── __main__.py              CLI: --stdio | --check | --dump-json
│   ├── lsp.py                   Content-Length JSON-RPC framing + message loop
│   ├── server.py                request/notification handlers
│   ├── lexer.py                 comment- and string-aware scanner
│   ├── blocks.py                SystemVerilog block scanner
│   ├── grammar.py               the annotation language
│   ├── index.py                 per-file and workspace symbol index
│   └── diagnostics.py           the seven rules
├── tests/                       106 unittest cases + fixtures
├── zed/                         extension.toml, Cargo.toml, src/lib.rs
├── lint/                        lint.sh, check_contract.py
└── docs/                        research.md, semantics-contract.md, readme-defects.md
```

---

## Design notes

**Why no SystemVerilog parser?** Annotations live in comments, so the only thing
that needs to understand Verilog is *block extent* — where an `always_comb`
ends. `blocks.py` does that by walking `begin`/`end`, `case`/`endcase`,
`fork`/`join` and sensitivity lists, on text where comments and strings have
already been blanked. That is a few hundred lines instead of a parser
dependency, and it is enough because nothing here consumes the AST.

If it ever proves too fragile, the upgrade path is
`tree-sitter-systemverilog` — the same grammar Zed uses for highlighting.

**Why hand-rolled LSP instead of pygls?** The request surface is seven methods,
and the framing is about a hundred lines. `pygls` would add a dependency, a
version to pin, and a v1/v2 API migration to track — for a tool that has to run
under whatever `python3` Zed happens to spawn.

**Offsets.** Positions use LSP's line/character convention. Multi-byte characters
before a token on the same line would shift the column; SystemVerilog sources
are ASCII in practice, and bytes-per-line are counted consistently on both sides.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `failed to compile Rust extension` / "the `wasm32-wasip2` target is not installed, and `rustup` is not available" | Rust is a distro package, not rustup. See **Prerequisite** above — Fedora has no wasm32-wasip2 std package, so rustup is the only fix |
| Same error, but rustup *is* installed | Zed (launched from the GUI) cannot see `~/.cargo/bin`; symlink the tools into `/usr/local/bin` or launch Zed from a terminal |
| `failed to spawn command … run.sh: No such file or directory` | The path is wrong for your workspace root. The extension probes the usual layouts; if it still misses, set `lsp.svannot.binary.path` to the **absolute** path of `run.sh`, or symlink `run.sh` to `svannot-lsp` somewhere on `$PATH`. `zed: open log` lists every path that was tried |
| Outline shows tree-sitter symbols, not annotations | `"document_symbols": "on"` is missing for that language |
| No diagnostics, no navigation at all | The dev extension is not installed, or the server failed to start — check `zed: open log` |
| Server starts but exits immediately | `run.sh` is not executable (`chmod +x tools/svannot/run.sh`) |
| Everything shows as undefined | Only some files were indexed; annotations resolve workspace-wide, so open the repository root rather than a subdirectory |
| An annotation lands under the wrong block | Run `python3 -m annot --check <file>` to see the binding; usually the block scanner could not find the end, which also emits `parse-warning` |
