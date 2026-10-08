#!/usr/bin/env python3
"""Lab-book datapath figures for the pipelined nerv processor.

Style follows the course figures pipefig.png / NERV.png:
  * vertical pipeline-register bars with a clock triangle
  * pink stage-separator bars + purple italic stage names
  * blue functional-unit boxes with their port names listed inside
  * trapezoid MUXes and a chevron ALU
  * purple signal-name labels along the wires

Emits SVG (editable) and PNG (paste-ready) from ONE geometry description.

Figures
  datapath_full     - complete datapath: every functional unit and pipeline
                      register, with all control signals drawn
  control_signals   - reference table of every signal, grouped by path
  delayslot_timing  - verified cycle trace showing ONE delay slot

Signal names match nerv.sv exactly.

Usage:  python3 make_diagrams.py [outdir]
"""
import os
import sys
import math
from PIL import Image, ImageDraw, ImageFont

SANS = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"
SANSB = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
SANSI = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Oblique.ttf"
SANSBI = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-BoldOblique.ttf"
MONO = "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf"
MONOB = "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Bold.ttf"

# ---- palette (pipefig-like) ----
UNIT = ("#3b6ea5", "#20456b")      # blue functional unit
UNITX = ("#e8f0f8", "#20456b")     # pale unit
REG = ("#fdf2f8", "#9d174d")       # pipeline register bar
BAR = "#f5d0e0"                    # stage separator
HL = ("#fde68a", "#b45309")        # the branch/delay-slot modification
MEM = ("#3b6ea5", "#20456b")
INK = "#111827"
WIRE = "#1f2937"
PURPLE = "#7c1d6f"
CTRL = "#2563eb"
BR = "#b45309"
WB = "#15803d"
BYP = "#7c3aed"
GREY = "#9ca3af"


class Canvas:
    def __init__(self, w, h, scale=2):
        self.w, self.h, self.s = w, h, scale
        self.ops = []
        self._img = None
        self._drw = None

    # ---------------- primitives ----------------
    def rect(self, x, y, w, h, fill="none", stroke=INK, sw=1.5, rx=6, dash=None):
        self.ops.append(("rect", x, y, w, h, fill, stroke, sw, rx, dash))

    def poly(self, pts, fill="none", stroke=INK, sw=1.5):
        self.ops.append(("poly", list(pts), fill, stroke, sw))

    def line(self, pts, color=WIRE, sw=1.5, dash=None, arw=False, arw_start=False):
        self.ops.append(("line", list(pts), color, sw, dash, arw, arw_start))

    def dot(self, x, y, r=3, fill=INK):
        self.ops.append(("dot", x, y, r, fill))

    def text(self, x, y, s, size=13, anchor="l", color=INK, bold=False,
             mono=False, ital=False):
        self.ops.append(("text", x, y, s, size, anchor, color, bold, mono, ital))

    def text_rot(self, x, y, s, size=13, color=INK, bold=False, mono=False, ital=False):
        self.ops.append(("rot", x, y, s, size, color, bold, mono, ital))

    # ---------------- helpers ----------------
    def _font(self, size, bold=False, mono=False, ital=False):
        if mono:
            path = MONOB if bold else MONO
        elif bold and ital:
            path = SANSBI
        elif bold:
            path = SANSB
        elif ital:
            path = SANSI
        else:
            path = SANS
        return ImageFont.truetype(path, int(round(size * self.s)))

    def render_png(self, path):
        s = self.s
        img = Image.new("RGB", (int(self.w * s), int(self.h * s)), "white")
        d = ImageDraw.Draw(img)
        self._img, self._drw = img, d
        for op in self.ops:
            k = op[0]
            if k == "rect":
                _, x, y, w, h, fill, stroke, sw, rx, dash = op
                bx = [x * s, y * s, (x + w) * s, (y + h) * s]
                if fill != "none":
                    d.rounded_rectangle(bx, radius=rx * s, fill=fill)
                if stroke == "none":
                    pass
                elif dash is None:
                    d.rounded_rectangle(bx, radius=rx * s, outline=stroke,
                                        width=max(1, int(sw * s)))
                else:
                    for seg in self._dash_segments(
                            [(bx[0], bx[1]), (bx[2], bx[1]), (bx[2], bx[3]),
                             (bx[0], bx[3]), (bx[0], bx[1])], dash * s):
                        d.line(seg, fill=stroke, width=max(1, int(sw * s)))
            elif k == "poly":
                _, pts, fill, stroke, sw = op
                P = [(a * s, b * s) for a, b in pts]
                if fill != "none":
                    d.polygon(P, fill=fill)
                if stroke != "none":
                    d.line(P + [P[0]], fill=stroke, width=max(1, int(sw * s)))
            elif k == "text":
                _, x, y, tx, size, anchor, color, bold, mono, ital = op
                f = self._font(size, bold, mono, ital)
                a = {"l": "lm", "m": "mm", "r": "rm", "lt": "la", "ct": "ma"}[anchor]
                d.text((x * s, y * s), tx, font=f, fill=color, anchor=a)
            elif k == "rot":
                _, x, y, tx, size, color, bold, mono, ital = op
                f = self._font(size, bold, mono, ital)
                bb = f.getbbox(tx)
                pad = 6
                tmp = Image.new("RGBA", (bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad),
                                (0, 0, 0, 0))
                ImageDraw.Draw(tmp).text((pad - bb[0], pad - bb[1]), tx, font=f, fill=color)
                tmp = tmp.rotate(90, expand=True)
                img.paste(tmp, (int(x * s) - tmp.width // 2, int(y * s) - tmp.height // 2), tmp)
            elif k == "line":
                _, pts, color, sw, dash, arw, arw_start = op
                P = [(a * s, b * s) for a, b in pts]
                if dash is None:
                    d.line(P, fill=color, width=max(1, int(sw * s)), joint="curve")
                else:
                    for seg in self._dash_segments(P, dash * s):
                        d.line(seg, fill=color, width=max(1, int(sw * s)))
                if arw:
                    self._arrow(d, P[-2], P[-1], color)
                if arw_start:
                    self._arrow(d, P[1], P[0], color)
            elif k == "dot":
                _, x, y, r, fill = op
                d.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], fill=fill)
        self._img = self._drw = None
        img.save(path)

    def _arrow(self, d, p0, p1, color):
        s = self.s
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        L, Wd = 10 * s, 4.5 * s
        t = (p1[0], p1[1])
        b1 = (t[0] - L * math.cos(ang) + Wd * math.sin(ang),
              t[1] - L * math.sin(ang) - Wd * math.cos(ang))
        b2 = (t[0] - L * math.cos(ang) - Wd * math.sin(ang),
              t[1] - L * math.sin(ang) + Wd * math.cos(ang))
        d.polygon([t, b1, b2], fill=color)

    def _dash_segments(self, P, dash):
        out = []
        for i in range(len(P) - 1):
            (x0, y0), (x1, y1) = P[i], P[i + 1]
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy)
            if L == 0:
                continue
            ux, uy = dx / L, dy / L
            t = 0.0
            while t < L:
                e = min(t + dash, L)
                out.append([(x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e)])
                t = e + dash
        return out

    def render_svg(self, path):
        esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
             f'viewBox="0 0 {self.w} {self.h}">',
             '<defs><marker id="arw" markerWidth="10" markerHeight="10" refX="8" refY="3" '
             'orient="auto"><path d="M0,0 L8,3 L0,6 z" fill="context-stroke"/></marker></defs>',
             f'<rect width="{self.w}" height="{self.h}" fill="white"/>']
        for op in self.ops:
            k = op[0]
            if k == "rect":
                _, x, y, w, h, fill, stroke, sw, rx, dash = op
                da = f' stroke-dasharray="{dash}"' if dash else ""
                o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                         f'stroke="{stroke}" stroke-width="{sw}"{da}/>')
            elif k == "poly":
                _, pts, fill, stroke, sw = op
                p = " ".join(f"{a},{b}" for a, b in pts)
                o.append(f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" '
                         f'stroke-width="{sw}"/>')
            elif k == "text":
                _, x, y, tx, size, anchor, color, bold, mono, ital = op
                ta = {"l": "start", "m": "middle", "r": "end", "lt": "start", "ct": "middle"}[anchor]
                fam = "Liberation Mono, monospace" if mono else "DejaVu Sans, sans-serif"
                st = (' font-weight="bold"' if bold else '') + (' font-style="italic"' if ital else '')
                o.append(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{ta}" fill="{color}" '
                         f'font-family="{fam}"{st} dominant-baseline="central">{esc(tx)}</text>')
            elif k == "rot":
                _, x, y, tx, size, color, bold, mono, ital = op
                fam = "Liberation Mono, monospace" if mono else "DejaVu Sans, sans-serif"
                st = (' font-weight="bold"' if bold else '') + (' font-style="italic"' if ital else '')
                o.append(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="middle" fill="{color}" '
                         f'font-family="{fam}"{st} transform="rotate(-90 {x} {y})" '
                         f'dominant-baseline="central">{esc(tx)}</text>')
            elif k == "line":
                _, pts, color, sw, dash, arw, arw_start = op
                p = " ".join(f"{a},{b}" for a, b in pts)
                da = f' stroke-dasharray="{dash}"' if dash else ""
                me = ' marker-end="url(#arw)"' if arw else ""
                ms = ' marker-start="url(#arw)"' if arw_start else ""
                o.append(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{sw}"'
                         f'{da}{me}{ms} stroke-linejoin="round"/>')
            elif k == "dot":
                _, x, y, r, fill = op
                o.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>')
        o.append("</svg>")
        open(path, "w").write("\n".join(o))


# ---------------- composite shapes (pipefig vocabulary) ----------------
def vreg(c, x, y, w, h, name, sub=None):
    """Vertical pipeline-register bar with a clock triangle at the bottom."""
    c.rect(x, y, w, h, fill=REG[0], stroke=REG[1], sw=2, rx=8)
    cx = x + w / 2
    c.text_rot(cx - 4, y + h / 2, name, size=15, bold=True, color=REG[1], mono=True)
    if sub:
        c.text(cx, y + h + 14, sub, size=10, anchor="m", color=GREY, mono=True)
    # clock triangle
    tx, ty = cx, y + h - 12
    c.poly([(tx - 6, ty - 7), (tx + 6, ty - 7), (tx, ty + 3)], fill=REG[1], stroke=REG[1], sw=1)


def tmux(c, x, y, w, h, label=None):
    """Trapezoid multiplexer, output (narrow end) on the right."""
    c.poly([(x, y), (x + w, y + h * 0.26), (x + w, y + h * 0.74), (x, y + h)],
           fill=("#ede9fe"), stroke="#6d28d9", sw=2)
    if label:
        c.text(x + w * 0.34, y + h / 2, label, size=11, anchor="m", bold=True, color="#4c1d95")


def chevron(c, x, y, w, h, label="ALU"):
    c.poly([(x, y), (x + w - h * 0.42, y), (x + w, y + h / 2),
            (x + w - h * 0.42, y + h), (x, y + h)], fill=UNITX[0], stroke=UNIT[1], sw=2)
    c.text(x + w * 0.40, y + h / 2, label, size=14, anchor="m", bold=True, color=UNIT[1])


def unit(c, x, y, w, h, title, ports=None, pal=MEM):
    c.rect(x, y, w, h, fill=pal[0], stroke=pal[1], sw=2, rx=8)
    cx = x + w / 2
    c.text(cx, y + 20, title, size=14, anchor="m", bold=True, color="white")
    if ports:
        for i, p in enumerate(ports):
            c.text(cx, y + 44 + i * 16, p, size=11, anchor="m", color="#e5eef7", mono=True)


def sig(c, x, y, s, color=PURPLE, size=11, anchor="m", mono=True):
    c.text(x, y, s, size=size, anchor=anchor, color=color, mono=mono)


# =========================================================================
# Figure: full datapath, pipefig style
# =========================================================================
def figure_datapath(svg, png):
    W, H = 2560, 1180
    c = Canvas(W, H)
    c.text(W / 2, 34, "Pipelined nerv — complete datapath with control signals",
           size=26, anchor="m", bold=True)
    c.text(W / 2, 66, "signal names are those of nerv.sv", size=13, anchor="m", color=GREY)

    # ---- stage bars + names ----
    for bx in (660, 1430):
        c.rect(bx, 190, 20, 700, fill=BAR, stroke="none", rx=10)
    c.text(340, 920, "I-Fetch (IF)", size=17, anchor="m", ital=True, color=PURPLE, bold=True)
    c.text(1045, 920, "Decode, Reg. Fetch (ID)", size=17, anchor="m", ital=True,
           color=PURPLE, bold=True)
    c.text(2000, 920, "Execute / Memory / Write-Back", size=17, anchor="m", ital=True,
           color=PURPLE, bold=True)

    # ================= IF =================
    tmux(c, 70, 380, 130, 120, "npc\nMUX")
    c.text(20, 350, "reset", size=11, anchor="l", color=CTRL, mono=True)
    c.line([(22, 372), (68, 372)], color=CTRL, sw=1.8, dash=5, arw=True)
    c.line([(22, 485), (68, 485)], color=BR, sw=3, arw=True)
    sig(c, 24, 466, "target", color=BR, anchor="l")

    c.rect(180, 190, 110, 56, fill=UNITX[0], stroke=UNIT[1], sw=2, rx=8)
    c.text(235, 218, "+ 4", size=14, anchor="m", bold=True, color=UNIT[1])
    c.line([(235, 246), (235, 376)], color=WIRE, sw=1.8, arw=True)
    sig(c, 246, 300, "pc+4", anchor="l")

    vreg(c, 300, 360, 70, 170, "pc")
    c.line([(205, 440), (298, 440)], color=WIRE, sw=2, arw=True)
    sig(c, 250, 424, "npc")
    c.line([(335, 360), (335, 260), (292, 260)], color=WIRE, sw=1.6, arw=True)
    sig(c, 348, 330, "pc", anchor="l")

    unit(c, 430, 350, 200, 200, "Inst. Memory", ["imem_addr   (in)", "imem_data   (out)"])
    c.line([(370, 445), (428, 445)], color=WIRE, sw=2, arw=True)
    sig(c, 399, 429, "imem_addr", size=10)

    vreg(c, 300, 620, 70, 170, "ppc", "ppc <= pc")
    c.line([(335, 530), (335, 618)], color=WIRE, sw=1.8, arw=True)

    # ================= IF/ID =================
    vreg(c, 686, 350, 70, 170, "ir", "IF/ID")
    c.line([(632, 435), (684, 435)], color=WIRE, sw=2, arw=True)
    sig(c, 658, 419, "imem_data", size=10)

    # ================= ID =================
    unit(c, 810, 265, 270, 300, "GPRs", [
        "we    next_wr",
        "— ID read —",
        "rs1   id_insn_rs1", "rs2   id_insn_rs2",
        "rd1   id_rs1_value", "rd2   id_rs2_value",
        "— EX read —",
        "rs1   insn_rs1", "rs2   insn_rs2",
        "rd1   rs1_value", "rd2   rs2_value",
        "— write —",
        "wa    insn_rd", "wd    next_rd"])

    c.rect(810, 585, 200, 90, fill=UNITX[0], stroke=UNIT[1], sw=2, rx=8)
    c.text(910, 610, "Imm gen", size=14, anchor="m", bold=True, color=UNIT[1])
    c.text(910, 635, "id_imm_b / i / j", size=11, anchor="m", color=UNIT[1], mono=True)
    c.text(910, 655, "-> _sext", size=11, anchor="m", color=UNIT[1], mono=True)

    # control-transfer unit (the modification)
    c.rect(1090, 380, 290, 290, fill=HL[0], stroke=HL[1], sw=2.5, rx=10)
    c.text(1235, 406, "Control transfer", size=15, anchor="m", bold=True, color="#7c2d12")
    c.text(1235, 430, "branch compare + target adder", size=11, anchor="m", color="#7c2d12")
    c.text(1235, 458, "in:  id_insn, br_a / br_b,", size=11, anchor="m", color="#7c2d12", mono=True)
    c.text(1235, 476, "     id_imm_*, ppc", size=11, anchor="m", color="#7c2d12", mono=True)
    c.text(1235, 502, "out: npc, illinsn", size=11, anchor="m", color="#7c2d12", mono=True)
    c.text(1235, 532, "BEQ BNE BLT BGE", size=10, anchor="m", color="#7c2d12", mono=True)
    c.text(1235, 550, "BLTU BGEU JAL JALR", size=10, anchor="m", color="#7c2d12", mono=True)
    c.text(1235, 578, "target = ppc + id_imm_sext", size=10, anchor="m", color="#7c2d12", mono=True)
    c.text(1235, 604, "taken -> npc", size=10, anchor="m", color="#7c2d12", mono=True)

    # ir -> ID units
    c.line([(756, 400), (808, 400)], color=WIRE, sw=2, arw=True)
    sig(c, 782, 384, "id_insn", size=10)
    c.line([(756, 435), (790, 435), (790, 630), (808, 630)], color=WIRE, sw=1.6, arw=True)
    c.line([(756, 470), (772, 470), (772, 545), (1088, 545)], color=WIRE, sw=1.7, arw=True)
    sig(c, 930, 530, "id_insn (decode)", size=10)

    # GPR -> control transfer
    c.line([(1080, 420), (1088, 420)], color=WIRE, sw=2, arw=True)

    # imm -> control transfer
    c.line([(1010, 630), (1050, 630), (1050, 645), (1088, 645)], color=WIRE, sw=1.8, arw=True)

    # ppc -> control transfer  (the offset base)
    c.line([(370, 705), (1235, 705), (1235, 672)], color=BR, sw=2.6, arw=True)
    sig(c, 800, 692, "ppc   (offset base)", color=BR, size=12)

    # EX -> ID bypass
    c.line([(1990, 330), (1990, 200), (1200, 200), (1200, 378)], color=BYP, sw=2.4, arw=True)
    sig(c, 1590, 182, "next_rd   (EX → ID operand bypass)", color=BYP, size=13)

    # control transfer -> npc MUX
    c.line([(1090, 600), (1040, 600), (1040, 1050), (40, 1050), (40, 485), (68, 485)],
           color=BR, sw=3, arw=True)
    sig(c, 620, 1068, "npc = ppc + imm   (taken branch / jump)", color=BR, size=13)

    # ================= ID/EX =================
    vreg(c, 1456, 350, 70, 180, "ex_insn", "ID/EX")
    c.line([(1385, 435), (1454, 435)], color=WIRE, sw=2, arw=True)
    sig(c, 1417, 419, "ir", size=10)
    vreg(c, 1456, 570, 70, 180, "ex_pc", "ex_pc1 / ex_pc")
    c.line([(1385, 660), (1454, 660)], color=BR, sw=1.8, arw=True)
    sig(c, 1470, 800, "held while mem_rd_enable_q  (load stall)", size=10, color=GREY)

    # ================= EX / MA / WB =================
    c.rect(1590, 280, 250, 170, fill=UNITX[0], stroke=UNIT[1], sw=2, rx=8)
    c.text(1715, 306, "EX control", size=15, anchor="m", bold=True, color=UNIT[1])
    c.text(1715, 332, "decode insn", size=11, anchor="m", color=UNIT[1], mono=True)
    c.text(1715, 356, "out:  next_wr  next_rd", size=10, anchor="m", color=UNIT[1], mono=True)
    c.text(1715, 376, "mem_rd_enable  mem_rd_reg", size=10, anchor="m", color=UNIT[1], mono=True)
    c.text(1715, 394, "mem_rd_func  mem_wr_enable", size=10, anchor="m", color=UNIT[1], mono=True)
    c.text(1715, 412, "mem_wr_strb   illinsn", size=10, anchor="m", color=UNIT[1], mono=True)
    c.text(1715, 432, "WB mux select", size=10, anchor="m", color=UNIT[1], mono=True)
    c.line([(1526, 420), (1588, 420)], color=WIRE, sw=2, arw=True)
    sig(c, 1557, 404, "insn", size=10)

    chevron(c, 1900, 330, 180, 200, "ALU")
    c.line([(1840, 340), (1878, 340), (1878, 365), (1898, 365)], color=CTRL, sw=1.6,
           dash=6, arw=True)
    sig(c, 1908, 348, "alu op", size=10, color=CTRL, anchor="l")

    # GPR operand read for the EX stage (address fields come from ex_insn)
    c.line([(1080, 300), (1120, 300), (1120, 262), (1950, 262), (1950, 328)],
           color=WIRE, sw=1.8, arw=True)
    sig(c, 1520, 248, "rs1_value / rs2_value   (GPR read, ex_insn fields)",
        color=PURPLE, size=11)

    unit(c, 2140, 310, 210, 200, "Data Memory",
         ["dmem_addr", "dmem_wstrb", "dmem_wdata", "dmem_rdata"])
    c.line([(2080, 390), (2138, 390)], color=WIRE, sw=1.8, arw=True)
    sig(c, 2109, 374, "alu_out", size=10)

    tmux(c, 2400, 360, 120, 110, "WB\nMUX")
    c.line([(2350, 440), (2398, 440)], color=WIRE, sw=1.8, arw=True)
    sig(c, 2374, 424, "mem_rdata", size=10)
    # ALU result to the WB mux, routed under the data memory
    c.line([(1990, 530), (1990, 560), (2440, 560), (2440, 472)], color=WIRE, sw=1.8, arw=True)

    # WB -> GPRs
    c.line([(2520, 415), (2540, 415), (2540, 960), (940, 960), (940, 567)],
           color=WB, sw=2.4, arw=True)
    sig(c, 1740, 978, "next_rd / mem_rdata  →  GPRs wd", color=WB, size=13)

    # memory control signals
    c.line([(1840, 450), (2100, 450), (2100, 490), (2138, 490)], color=CTRL, sw=1.6,
           dash=6, arw=True)
    sig(c, 2010, 506, "mem_rd_enable / mem_wr_enable / mem_wr_strb", color=CTRL, size=11)

    # trap
    c.rect(2140, 590, 210, 90, fill="#fee2e2", stroke="#b91c1c", sw=2, rx=8)
    c.text(2245, 616, "trap", size=14, anchor="m", bold=True, color="#7f1d1d")
    c.text(2245, 642, "illinsn -> trapped", size=10, anchor="m", color="#7f1d1d", mono=True)
    c.text(2245, 662, "trap = trapped", size=10, anchor="m", color="#7f1d1d", mono=True)
    c.line([(1660, 450), (1660, 580), (2200, 580), (2200, 588)], color="#b91c1c", sw=1.8,
           dash=6, arw=True)
    sig(c, 1930, 566, "illinsn", color="#b91c1c", size=11)

    # legend
    lx, ly = 70, 1100
    for lbl, fill, stroke in [("pipeline register", REG[0], REG[1]),
                              ("functional unit", UNIT[0], UNIT[1]),
                              ("control-transfer path", HL[0], HL[1]),
                              ("control signal", "none", CTRL),
                              ("write-back", "none", WB),
                              ("EX→ID bypass", "none", BYP)]:
        c.rect(lx, ly - 7, 18, 13, fill=fill, stroke=stroke, sw=1.6, rx=3)
        c.text(lx + 24, ly, lbl, size=11, anchor="l", color="#374151")
        lx += 34 + len(lbl) * 6.4

    c.render_png(png)
    c.render_svg(svg)


# =========================================================================
# Figure: control-signal reference table
# =========================================================================
CONTROL_ROWS = [
    ("next-PC  / fetch", [
        ("npc", "32", "ID control-transfer (or pc+4)", "next fetch address -> pc"),
        ("imem_addr", "32", "npc (held via imem_addr_q)", "instruction memory address"),
        ("imem_data", "32", "instruction memory", "fetched instruction word"),
        ("imem_addr_q", "32", "registered imem_addr", "address held during load / trap"),
    ]),
    ("pipeline registers", [
        ("pc", "32", "npc", "fetch pointer (drives imem_addr)"),
        ("ppc", "32", "pc", "ID instruction's own address = branch offset base"),
        ("ir", "32", "imem_data", "IF/ID instruction register"),
        ("ex_insn", "32", "ir", "ID/EX instruction register"),
        ("ex_pc1", "32", "pc", "pc delayed one fetch"),
        ("ex_pc", "32", "ex_pc1", "pc delayed two fetches = EX instruction address"),
    ]),
    ("register file", [
        ("regfile[0:31]", "32", "-", "general-purpose registers (x0 hard-wired 0)"),
        ("id_rs1_value", "32", "regfile, id_insn_rs1", "ID operand read for branch compare"),
        ("id_rs2_value", "32", "regfile, id_insn_rs2", "ID operand read for branch compare"),
        ("br_a", "32", "id_rs1_value or next_rd", "bypassed operand A"),
        ("br_b", "32", "id_rs2_value or next_rd", "bypassed operand B"),
        ("rs1_value", "32", "regfile, insn_rs1", "EX operand read"),
        ("rs2_value", "32", "regfile, insn_rs2", "EX operand read"),
        ("next_wr", "1", "EX control", "GPR write enable"),
        ("next_rd", "32", "EX control", "GPR write data (also the EX→ID bypass)"),
    ]),
    ("load path", [
        ("mem_rd_enable", "1", "EX control", "issue a load this cycle"),
        ("mem_rd_addr", "32", "rs1_value + imm_i_sext", "load address (word aligned)"),
        ("mem_rd_reg", "5", "EX control (insn_rd)", "load destination register"),
        ("mem_rd_func", "5", "{addr[1:0], insn_funct3}", "load size / sign select"),
        ("mem_rd_enable_q", "1", "mem_rd_enable (reg)", "2nd half of read; also the stall"),
        ("mem_rd_reg_q", "5", "mem_rd_reg (reg)", "load destination, delayed"),
        ("mem_rd_func_q", "5", "mem_rd_func (reg)", "load selector, delayed"),
        ("mem_rdata", "32", "dmem_rdata", "load result after size/sign extraction"),
    ]),
    ("store path", [
        ("mem_wr_enable", "1", "EX control", "issue a store this cycle"),
        ("mem_wr_addr", "32", "rs1_value + imm_s_sext", "store address (word aligned)"),
        ("mem_wr_data", "32", "rs2_value", "store data, shifted into byte lane"),
        ("mem_wr_strb", "4", "EX control + addr[1:0]", "byte write strobes"),
    ]),
    ("data memory port", [
        ("dmem_valid", "1", "mem_wr_enable | mem_rd_enable", "memory request valid"),
        ("dmem_addr", "32", "mem_wr_addr | mem_rd_addr", "memory address"),
        ("dmem_wstrb", "4", "mem_wr_strb | 4'h0", "memory write strobes"),
        ("dmem_wdata", "32", "mem_wr_data", "memory write data"),
        ("dmem_rdata", "32", "data memory", "memory read data"),
    ]),
    ("trap / reset", [
        ("illinsn", "1", "EX control (bad opcode) | ID misaligned", "illegal instruction / misaligned target"),
        ("trapped", "1", "sticky on illinsn", "processor has trapped"),
        ("trapped_q", "1", "trapped (reg)", "delayed trap"),
        ("trap", "1", "trapped", "trap output"),
        ("reset_q", "1", "reset (reg)", "delayed reset"),
    ]),
    ("decode / immediates", [
        ("insn_opcode", "7", "ex_insn[6:0]", "EX opcode -> control case"),
        ("insn_funct3", "3", "ex_insn[14:12]", "EX ALU / branch / mem select"),
        ("insn_funct7", "7", "ex_insn[31:25]", "EX ALU / shift select"),
        ("insn_rs1 / insn_rs2", "5", "ex_insn", "EX source register numbers"),
        ("insn_rd", "5", "ex_insn[11:7]", "EX destination register"),
        ("imm_i / imm_s / imm_b / imm_j", "-", "ex_insn", "EX immediates (I, S, B, J)"),
        ("imm_*_sext", "32", "sign-extended", "EX immediate to ALU / memory"),
        ("id_insn_opcode", "7", "ir[6:0]", "ID opcode -> control transfer"),
        ("id_insn_rs1 / rs2 / rd / funct7", "5/5/5/7", "ir", "ID register and funct fields"),
        ("id_insn_funct3", "3", "ir[14:12]", "ID branch type select"),
        ("id_imm_b / id_imm_i / id_imm_j", "-", "ir", "ID immediates"),
        ("id_imm_*_sext", "32", "sign-extended", "ID target arithmetic"),
    ]),
]


def figure_control(svg, png):
    W = 1700
    row_h = 21
    nrows = sum(len(r) for _, r in CONTROL_ROWS) + len(CONTROL_ROWS)
    H = 150 + nrows * row_h + 60
    c = Canvas(W, H)
    c.text(W / 2, 34, "nerv.sv — every signal, grouped by path", size=24, anchor="m", bold=True)
    c.text(W / 2, 64, "control signals are highlighted; width / driver / meaning",
           size=13, anchor="m", color=GREY)

    cx = [50, 380, 470, 660, 900]
    hdr = ["signal", "w", "driven by", "meaning"]
    c.text(cx[0], 104, hdr[0], size=13, bold=True, color="#374151")
    c.text(cx[2], 104, hdr[1], size=13, bold=True, color="#374151")
    c.text(cx[3], 104, hdr[2], size=13, bold=True, color="#374151")
    c.text(cx[4], 104, hdr[3], size=13, bold=True, color="#374151")
    c.line([(40, 118), (W - 40, 118)], color="#cbd5e1", sw=1.5)

    y = 134
    ctrl_words = ("next_wr", "mem_rd_enable", "mem_wr_enable", "mem_wr_strb", "npc",
                  "illinsn", "trap", "dmem_valid", "mem_rd_enable_q", "reset_q")
    for group, rows in CONTROL_ROWS:
        c.rect(40, y - 13, W - 80, 22, fill="#eef2f7", stroke="none", rx=4)
        c.text(50, y - 2, group, size=12, bold=True, color="#334155")
        y += row_h + 6
        for name, width, driver, meaning in rows:
            is_ctrl = any(k in name for k in ctrl_words)
            if is_ctrl:
                c.rect(40, y - 10, W - 80, 19, fill="#eff6ff", stroke="none", rx=3)
            col = "#1d4ed8" if is_ctrl else INK
            c.text(cx[0], y, name, size=11.5, anchor="l", mono=True,
                   color=col, bold=is_ctrl)
            c.text(cx[2] + 40, y, width, size=11.5, anchor="m", color="#475569")
            c.text(cx[3], y, driver, size=11, anchor="l", color="#475569")
            c.text(cx[4], y, meaning, size=11, anchor="l", color="#374151")
            y += row_h
        y += 4

    c.render_png(png)
    c.render_svg(svg)


# =========================================================================
# Figure: delay-slot timing
# =========================================================================
def figure_timing(svg, png):
    rows = [
        ("5", "0x00000010", "0x0000000c", "00950e63  beq x10,x9,+28",
         "0x00000008", "00100493  addi x9,x0,1",
         "BEQ in ID  →  npc = ppc + 28 = 0x28", "redirect"),
        ("6", "0x00000028", "0x00000010", "00140413  addi x8,x8,1",
         "0x0000000c", "00950e63  beq x10,x9,+28",
         "delay slot in ID; target 0x28 fetched", "slot"),
        ("7", "0x0000002c", "0x00000028", "00700393  addi x7,x0,7",
         "0x00000010", "00140413  addi x8,x8,1",
         "delay slot retires  →  x8 = 1", "slot"),
        ("8", "0x00000030", "0x0000002c", "00600313  addi x6,x0,6",
         "0x00000028", "00700393  addi x7,x0,7",
         "target retires  →  x7 = 7", "target"),
    ]
    W, H = 1660, 470
    c = Canvas(W, H)
    c.text(W / 2, 26, "One delay slot — verified cycle trace (firmware.s)",
           size=20, anchor="m", bold=True)
    c.text(W / 2, 52,
           "branches resolve in ID with offset base ppc; the delay slot at 0x10 executes exactly once",
           size=12, anchor="m", color=GREY)
    colx = [46, 210, 540, 900, 1230]
    for x, h in zip(colx, ["cycle", "pc  (fetching)", "ID:  ir  @ ppc",
                           "EX:  ex_insn  @ ex_pc", "effect"]):
        c.text(x, 92, h, size=13, anchor="l", bold=True, color="#334155")
    c.line([(30, 108), (W - 30, 108)], color="#cbd5e1", sw=1.5)
    fill_of = {"redirect": HL, "slot": (REG[0], REG[1]), "target": ("#dcfce7", "#15803d")}
    y = 130
    for (cyc, pc, ppc, ir, epc, ex, note, kind) in rows:
        pal = fill_of[kind]
        c.rect(30, y, W - 60, 68, fill=pal[0], stroke=pal[1], sw=1.5, rx=6)
        c.text(colx[0] + 4, y + 34, cyc, size=17, anchor="l", bold=True)
        c.text(colx[1], y + 24, pc, size=13, anchor="l", mono=True)
        c.text(colx[2], y + 24, ir[:8], size=13, anchor="l", mono=True)
        c.text(colx[2], y + 45, "ppc = " + ppc, size=11, anchor="l", mono=True, color="#475569")
        c.text(colx[3], y + 24, ex[:8], size=13, anchor="l", mono=True)
        c.text(colx[3], y + 45, "ex_pc = " + epc, size=11, anchor="l", mono=True, color="#475569")
        c.text(colx[4], y + 34, note, size=11, anchor="l", color="#334155")
        y += 76
    c.text(W / 2, H - 18,
           "fetch stream:  0x00  0x04  0x08  0x0c  0x10  →  0x28  0x2c  0x30  0x34     "
           "(0x14–0x24 are never fetched)",
           size=12, anchor="m", mono=True, color="#475569")
    c.render_png(png)
    c.render_svg(svg)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "diagrams"
    os.makedirs(out, exist_ok=True)
    figure_datapath(os.path.join(out, "datapath_full.svg"),
                    os.path.join(out, "datapath_full.png"))
    figure_control(os.path.join(out, "control_signals.svg"),
                   os.path.join(out, "control_signals.png"))
    figure_timing(os.path.join(out, "delayslot_timing.svg"),
                  os.path.join(out, "delayslot_timing.png"))
    print("wrote figures to", out)
