from ctypes import c_int32, c_uint32
import pyverilator

from ctypes import c_int32, c_uint32
import pyverilator

ALU_ADD    = 1   # 5'b00001
ALU_SUB    = 2   # 5'b00010
ALU_SLL    = 3   # 5'b00011
ALU_SRL    = 4   # 5'b00100
ALU_SRA    = 5   # 5'b00101
ALU_SEQ    = 6   # 5'b00110
ALU_SLT    = 7   # 5'b00111
ALU_SLTU   = 8   # 5'b01000
ALU_XOR    = 9   # 5'b01001
ALU_OR     = 10  # 5'b01010
ALU_AND    = 11  # 5'b01011

ALUSYM = {
    ALU_ADD: "+",
    ALU_SUB: "-",
    ALU_SLL: "<<",
    ALU_SRL: ">>",
    ALU_SRA: ">>>",
    ALU_SEQ: "==",
    ALU_SLT: "< (s)",
    ALU_SLTU:"< (u)",
    ALU_XOR: "^",
    ALU_OR:  "|",
    ALU_AND: "&"
}

def uint32(v):
    """Force value to behave as a 32-bit unsigned integer."""
    return c_uint32(v).value

def int32(v):
    """Force value to behave as a 32-bit signed integer."""
    return c_int32(v).value

def alu(alu_function, a, b):
    # Ensure inputs act as strictly 32-bit boundaries
    u_a = uint32(a)
    u_b = uint32(b)
    i_a = int32(a)
    i_b = int32(b)

    # RISC-V 32-bit spec: shifts only use the lowest 5 bits of rs2
    shamt = u_b & 0x1F

    if alu_function == ALU_ADD:
        r = u_a + u_b
    elif alu_function == ALU_SUB:
        r = u_a - u_b
    elif alu_function == ALU_XOR:
        r = u_a ^ u_b
    elif alu_function == ALU_OR:
        r = u_a | u_b
    elif alu_function == ALU_AND:
        r = u_a & u_b
    elif alu_function == ALU_SLL:
        r = u_a << shamt
    elif alu_function == ALU_SRL:
        r = u_a >> shamt  # Unsigned in python acts as logical shift right
    elif alu_function == ALU_SRA:
        r = i_a >> shamt  # Signed in python acts as arithmetic shift right
    elif alu_function == ALU_SLT:
        r = 1 if (i_a < i_b) else 0  # Signed comparison
    elif alu_function == ALU_SLTU:
        r = 1 if (u_a < u_b) else 0  # Unsigned comparison
    else:
        r = 0

    r = uint32(r) # Truncate back to 32 bits
    zero = 1 if (r == 0) else 0
    return (r, zero)

def test_alu(tb, alu_function, a, b):
    tb.io.alu_function = alu_function
    tb.io.op_a = a
    tb.io.op_b = b

    (cresult, ceq) = alu(alu_function, a, b)  # python (computer) result
    vresult = uint32(tb.io.result)            # verilog result
    veq = uint32(tb.io.result_eq_zero)

    ok = cresult == vresult and ceq == veq
    print(
        "{:08x} {:5} {:08x} \tresult={:08x},{} (cresult={:08x},{}) [{}]".format(
            a, ALUSYM[alu_function], b, vresult, veq, cresult, ceq, "PASS" if ok else "FAIL"
        )
    )
    return ok


# ----------------------------
# Initialization
# ----------------------------
tb = pyverilator.PyVerilator.build("alu.sv")
# tb.start_vcd_trace("addsub.vcd")

# ----------------------------
# 1. ADD / SUB
# ----------------------------
print("--- ADD / SUB ---")
test_alu(tb, ALU_ADD, 1, 2)
test_alu(tb, ALU_ADD, 0xFFFFFFFF, 2)
test_alu(tb, ALU_ADD, 0x7FFFFFFF, 0xFF)
test_alu(tb, ALU_SUB, 0xDEADBEEF, 0xDEADBEEF)
test_alu(tb, ALU_SUB, 0xDEADBEEF, 2)
test_alu(tb, ALU_SUB, 0xE1E10, 0xDEADBEEF)

# ----------------------------
# 2. Bitwise Logic (XOR, OR, AND)
# ----------------------------
print("--- LOGIC ---")
test_alu(tb, ALU_XOR, 0x00000000, 0x000000e1) # Alternating bits
test_alu(tb, ALU_XOR, 0xFFFFFFFF, 0x00000000)
test_alu(tb, ALU_XOR, 0x12345678, 0x12345678) # Same value -> 0

test_alu(tb, ALU_OR,  0xAAAAAAAA, 0x55555555) # Yields FFFFFFFF
test_alu(tb, ALU_OR,  0x00000000, 0x00000000)

test_alu(tb, ALU_AND, 0xFFFFFFFF, 0x55555555) # Yields 55555555
test_alu(tb, ALU_AND, 0x00000000, 0xFFFFFFFF)

# ----------------------------
# 3. Shifts (SLL, SRL, SRA)
# ----------------------------
print("--- SHIFTS ---")
# Logical Left
test_alu(tb, ALU_SLL, 0x00000001, 0)
test_alu(tb, ALU_SLL, 0x00000001, 15)
test_alu(tb, ALU_SLL, 0x00000001, 31)
test_alu(tb, ALU_SLL, 0x00000001, 32) # Edgecase (>31): 32 & 0x1F = 0, should shift by 0!
test_alu(tb, ALU_SLL, 0x00000001, 33) # Edgecase (>31): 33 & 0x1F = 1, should shift by 1!

# Logical Right
test_alu(tb, ALU_SRL, 0x80000000, 0)
test_alu(tb, ALU_SRL, 0x80000000, 31) # Shifts 1 to the end (Result: 0x00000001)
test_alu(tb, ALU_SRL, 0x80000000, 32) # Edgecase (>31): Result should be 0x80000000
test_alu(tb, ALU_SRL, 0xFFFFFFFF, 15) # Result: 0x0001FFFF

# Arithmetic Right
test_alu(tb, ALU_SRA, 0x80000000, 0)  # MSB 1, shift 0
test_alu(tb, ALU_SRA, 0x80000000, 15) # MSB 1, shift 15 -> 0xFFFF0000
test_alu(tb, ALU_SRA, 0x80000000, 31) # MSB 1, shift 31 -> 0xFFFFFFFF
test_alu(tb, ALU_SRA, 0x80000000, 32) # MSB 1, shift 0 (Mask edgecase) -> 0x80000000
test_alu(tb, ALU_SRA, 0x7FFFFFFF, 31) # MSB 0, shift 31 -> 0x00000000

# ----------------------------
# 4. Set Less Than (SLT, SLTU)
# ----------------------------
print("--- SLT / SLTU ---")
# SLT evaluates Signed integers
test_alu(tb, ALU_SLT, 0xFFFFFFFF, 1)
test_alu(tb, ALU_SLT, 2, 1)
test_alu(tb, ALU_SLT, 0xFFFFFFFF, 1)  # -1 < 1 -> True (1)
test_alu(tb, ALU_SLT, 1, 0xFFFFFFFF)  # 1 < -1 -> False (0)
test_alu(tb, ALU_SLT, 0x80000000, 0x7FFFFFFF) # Most negative < Most positive -> True (1)
test_alu(tb, ALU_SLT, 0x7FFFFFFF, 0x80000000) # Most positive < Most negative -> False (0)

# SLTU evaluates Unsigned integers
test_alu(tb, ALU_SLTU, 1, 2)
test_alu(tb, ALU_SLTU, 2, 1)
test_alu(tb, ALU_SLTU, 0xFFFFFFFF, 1) # Unsigned Max < 1 -> False (0)
test_alu(tb, ALU_SLTU, 1, 0xFFFFFFFF) # 1 < Unsigned Max -> True (1)
test_alu(tb, ALU_SLTU, 0x80000000, 0x7FFFFFFF) # 2147483648 < 2147483647 -> False (0)
test_alu(tb, ALU_SLTU, 0x7FFFFFFF, 0x80000000) # 2147483647 < 2147483648 -> True (1)

# tb.stop_vcd_trace()
