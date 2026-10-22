#!/usr/bin/env python3
"""Stop one modem clock from aborting the whole GCC probe.
Straight port of the first port's own patches/patch-clk-gcc-mss-q6-halt-skip-414.py -- same
bug, same clock, same fix, found here via the same ramoops technique: with the AHB-workaround
and venus smmu-vdd fixes both applied, boot advanced to t=0.846s and hit `msm_vidc: err:
Failed to get clock: sys_noc_axi_clk`, immediately followed by the same NULL-deref shape at
regulator_enable/__enable_regulators as the just-fixed venus panic -- a downstream symptom,
not a new independent bug.

Root cause (confirmed identical here by reading gcc-msm8998.c directly, same anchor, same
offsets): during gcc_msm8998_probe (the Global Clock Controller), the branch
`gcc_mss_q6_bimc_axi_clk` is registered with CLK_IS_CRITICAL, so the clk framework
force-enables it at registration time. clk_branch2_enable then polls the halt bit until the
branch reads 'on' -- but this is a modem (MSS Q6) BIMC-AXI clock and the modem is not powered
this early in boot, so the branch is permanently "status stuck at 'off'", the poll fails, and
because this happens during registration of a CLK_IS_CRITICAL clock, clk_register fails and
aborts the ENTIRE controller: GCC unregisters every clock it owns. Everything downstream that
needs a GCC clock then fails to find it -- Venus's sys_noc_axi_clk here, and (per the first
port's own findings) likely camera flash LED / i2c -517 and others once boot gets that far.

The clock has no `.halt_check`, so it defaults to BRANCH_HALT (poll until on). The standard
Qualcomm treatment for a votable branch feeding a not-yet-powered subsystem is
BRANCH_HALT_SKIP (3) -- write the enable, do not poll the halt bit. The clock stays
CLK_IS_CRITICAL (enabled/voted from boot); only the unreliable readback is skipped, so
registration succeeds and GCC comes up.

Adds `.halt_check = BRANCH_HALT_SKIP,` to gcc_mss_q6_bimc_axi_clk in gcc-msm8998.c.
Idempotent. Run from this kernel's root (kernel/sony/msm-4.14/, one level above
common-kernel/), or pass the tree as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'common-kernel/drivers/clk/qcom/gcc-msm8998.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'lilac: skip halt poll' in s:
    print('already patched')
    sys.exit(0)

anchor = ('static struct clk_branch gcc_mss_q6_bimc_axi_clk = {\n'
          '\t.halt_reg = 0x8A040,\n')
if anchor not in s:
    sys.exit('gcc_mss_q6_bimc_axi_clk anchor not found -- re-derive')

repl = ('static struct clk_branch gcc_mss_q6_bimc_axi_clk = {\n'
        '\t.halt_reg = 0x8A040,\n'
        '\t.halt_check = BRANCH_HALT_SKIP, /* lilac: skip halt poll -- modem off at '
        'GCC probe, was aborting the whole controller */\n')
s = s.replace(anchor, repl, 1)
p.write_text(s)
print(f'patched {p}: gcc_mss_q6_bimc_axi_clk halt_check = BRANCH_HALT_SKIP')
