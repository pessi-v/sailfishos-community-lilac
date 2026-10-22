#!/usr/bin/env python3
"""Stop gcc_mss_cfg_ahb_clk from aborting modem PIL bring-up.

Ported from the first port's own patch-clk-gcc-mss-cfg-ahb-halt-skip-414.py.
Our kernel already carries the sibling
fix for gcc_mss_q6_bimc_axi_clk (BRANCH_HALT_SKIP) -- confirmed by diff against the build tree. This is the second MSS
clock in the same chain, hit later: once qcrild + per_mgr vote the modem
subsystem up, PIL's own MBA-load path enables this clock as part of powering up
the modem, and modem is by definition not yet powered at that exact point, so the
halt-bit poll fails:

    gcc_mss_cfg_ahb_clk: status stuck at 'off'
    WARNING drivers/clk/qcom/clk-branch.c:116 clk_branch_toggle
    Call trace: clk_branch_toggle -> clk_branch2_enable -> clk_core_enable -> clk_enable
      -> pil_mss_enable_clks -> pil_mss_reset -> pil_mss_reset_load_mba
      -> pil_msa_mss_reset_mba_load_auth_mdt -> pil_boot -> modem_powerup
    pil-q6v5-mss 4080000.qcom,mss: MBA boot failed(rc:-16)

Unlike gcc_mss_q6_bimc_axi_clk this clock is not CLK_IS_CRITICAL and doesn't abort
the whole GCC controller -- it aborts just this one clk_enable() call inside
pil_mss_enable_clks(), which pil_mss_reset() propagates up as -EBUSY (-16).
Same root shape though: a halt-bit poll on a not-yet-powered modem-domain clock.
Standard Qualcomm treatment: BRANCH_HALT_SKIP (write the enable, skip the
unreliable readback poll).

Confirmed against our own oldlenny source (drivers/clk/qcom/gcc-msm8998.c,
gcc_mss_cfg_ahb_clk at .halt_reg = 0x8A000) that it already has an EXPLICIT
`.halt_check = BRANCH_HALT,` line -- so this patch replaces that line's value
in-place rather than inserting a new field. Idempotent. Run from the 4.14 kernel
root, or pass argv[1].
"""
import re
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/clk/qcom/gcc-msm8998.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
marker = 'lilac-v2: skip halt poll -- modem off during PIL MBA load'
if marker in s:
    print('already patched')
    sys.exit(0)

pattern = re.compile(
    r'(static struct clk_branch gcc_mss_cfg_ahb_clk = \{\n'
    r'\t\.halt_reg = 0x[0-9A-Fa-f]+,\n'
    r'\t)\.halt_check = BRANCH_HALT,\n'
)
m = pattern.search(s)
if not m:
    sys.exit('gcc_mss_cfg_ahb_clk anchor not found -- re-derive against current source')

repl = f'{m.group(1)}.halt_check = BRANCH_HALT_SKIP, /* {marker} */\n'
s = s[:m.start()] + repl + s[m.end():]
p.write_text(s)
print(f'patched {p}: gcc_mss_cfg_ahb_clk halt_check = BRANCH_HALT -> BRANCH_HALT_SKIP')
