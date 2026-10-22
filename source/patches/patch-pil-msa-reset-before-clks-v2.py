#!/usr/bin/env python3
"""Deassert the MSS reset BEFORE enabling its clocks.

Ported from the first port's own patch-pil-msa-reset-before-clks-414.py:
the root cause of the modem MBA-load
failure, found there by diffing pil_mss_reset() against a working 4.4 kernel for
this exact SoC. Confirmed our own oldlenny source has the same broken ordering
(drivers/soc/qcom/pil-msa.c, pil_mss_reset()) and is otherwise unmodified.

Working order (4.4):
    pil_mss_power_up()
    pil_mss_restart_reg(drv, 0)   <-- deassert MSS reset FIRST
    pil_mss_enable_clks()         <-- then enable clocks

Broken order (this 4.14 tree, before this patch):
    pil_mss_power_up()
    pil_mss_enable_clks()         <-- clocks enabled while MSS is STILL IN RESET
    pil_mss_assert_resets(); udelay(200); pil_mss_deassert_resets()

gcc_mss_snoc_axi_clk and gcc_mss_mnoc_bimc_axi_clk are the AXI *bridge* clocks
between the MSS island and the SoC NoC fabric. Their CBCR halt bit only clears
once the MSS side of the bridge is out of reset and can complete the clock
handshake. With the broken order the MSS is still held in reset at that moment,
so the bridge never acks and the halt bit stays at 'off' forever:

    gcc_mss_snoc_axi_clk: status stuck at 'off'
    pil-q6v5-mss 4080000.qcom,mss: MBA boot failed(rc:-16)

Why 4.14's newer assert/deassert sequence doesn't compensate on this board:
pil_mss_assert_resets()/pil_mss_deassert_resets() are built around PDC-sync and
alt-reset hardware, both gated on drv->pdc_sync / drv->alt_reset, which come from
DT resources named "pdc_sync" and "alt_reset". lilac's msm8998.dtsi qcom,mss node
declares neither (reg-names = qdsp6_base, halt_q6, halt_modem, halt_nc, rmb_base,
restart_reg), so on msm8998 that whole newer mechanism is a no-op and all that
survives of the forward-port is the broken clock/reset ordering.

NB this is NOT the same mistake as blindly extending BRANCH_HALT_SKIP further down
this clock chain (which the first port tried and hit a fatal SError -- a real,
still-gated bus). This restores the exact ordering of the kernel that demonstrably
works on this hardware, so the halt check still runs and still means something --
it should now simply pass.

Transforms pil_mss_reset() to the working 4.4 ordering:
  1. deassert reset (pil_mss_restart_reg(drv, 0)) before pil_mss_enable_clks()
     (on failure goto err_clks, which does power_down+return -- correct here,
     since only power_up needs undoing at that point)
  2. drop the later assert/deassert cycle, which 4.4 does not do at all
  3. re-assert the reset on the failure path (4.4 does this; the broken ordering
     dropped it along with the early deassert -- without this a failed attempt
     leaves the MSS out of reset, which would skew any subsequent retry)
  4. drop the now-unused err_restart label (its body still runs, reached by
     fall-through from err_q6v5_reset)
Idempotent. Run from the 4.14 kernel root, or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/soc/qcom/pil-msa.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
marker = 'lilac-v2: deassert MSS reset'
if marker in s:
    print('already patched')
    sys.exit(0)

# 1. Deassert the reset before enabling clocks (4.4 order).
anchor1 = '''\tret = pil_mss_enable_clks(drv);
\tif (ret)
\t\tgoto err_clks;
'''
repl1 = '''\t/*
\t * lilac-v2: deassert the MSS reset BEFORE enabling clocks, matching the
\t * working 4.4 kernel. The MSS<->NoC AXI bridge clocks (gcc_mss_snoc_axi_clk,
\t * gcc_mss_mnoc_bimc_axi_clk) cannot complete their halt handshake while the
\t * MSS is held in reset, so enabling them first leaves them stuck at 'off'
\t * forever and fails the MBA load with -EBUSY.
\t */
\tret = pil_mss_restart_reg(drv, 0);
\tif (ret)
\t\tgoto err_clks;

\tret = pil_mss_enable_clks(drv);
\tif (ret)
\t\tgoto err_clks;
'''
if anchor1 not in s:
    sys.exit('pil_mss_enable_clks anchor not found -- re-derive against current source')
s = s.replace(anchor1, repl1, 1)

# 2. Drop the later assert/deassert cycle (4.4 has no equivalent).
anchor2 = '''\t/* Assert reset to subsystem */
\tpil_mss_assert_resets(drv);
\t/* Wait 6 32kHz sleep cycles for reset */
\tudelay(200);
\tret = pil_mss_deassert_resets(drv);
\tif (ret)
\t\tgoto err_restart;
'''
repl2 = '''\t/*
\t * lilac-v2: 4.4 does no assert/deassert cycle here -- the reset was already
\t * deasserted above, before the clocks. The 4.14 cycle exists for
\t * PDC-sync/alt-reset capable SoCs; msm8998's DT declares neither, so it is
\t * a no-op here apart from re-imposing the broken ordering.
\t */
'''
if anchor2 not in s:
    sys.exit('assert/deassert anchor not found -- re-derive against current source')
s = s.replace(anchor2, repl2, 1)

# 3+4. Re-assert reset on the failure path (4.4 does this), and drop the now-unused
# err_restart label. Its body still runs via fall-through from err_q6v5_reset.
anchor3 = '''err_q6v5_reset:
\tmodem_log_rmb_regs(drv->rmb_base);
err_restart:
\tpil_mss_disable_clks(drv);
\tif (drv->ahb_clk_vote)
\t\tclk_disable_unprepare(drv->ahb_clk);
err_clks:
\tpil_mss_power_down(drv);
'''
repl3 = '''err_q6v5_reset:
\tmodem_log_rmb_regs(drv->rmb_base);
\tpil_mss_disable_clks(drv);
\tif (drv->ahb_clk_vote)
\t\tclk_disable_unprepare(drv->ahb_clk);
err_clks:
\t/* lilac-v2: re-assert the reset we deasserted above, as 4.4 does */
\tpil_mss_restart_reg(drv, 1);
\tpil_mss_power_down(drv);
'''
if anchor3 not in s:
    sys.exit('error-path anchor not found -- re-derive against current source')
s = s.replace(anchor3, repl3, 1)

p.write_text(s)
print(f'patched {p}: deassert MSS reset before enabling clocks (4.4 ordering)')
