#!/usr/bin/env python3
"""Seed a sane default for dev_ref_clk_gating_wait.

Candidate cause of the intermittent UFS enumeration failure that gates the whole
port (10.101-102, 10.128). Failing boots look like this: the link comes up fine
at gear-1 SLOWAUTO, and then EVERY UPIU query descriptor read times out, so the
device descriptor is never read, the power mode never moves to HS gear-3, and no
LUNs enumerate -- no /vendor, no modem firmware, no IPA firmware, and eventually
an IPA panic:

    ufshcd_print_pwr_info:[RX, TX]: gear=[1, 1], lane[1, 1], pwr[SLOWAUTO_MODE...]
    __ufshcd_query_descriptor: opcode 0x01 for idn 4 failed, index 0, err = -110
    ufshcd_read_desc_length: Failed to get descriptor header id 4
    ... same for idn 1, 2, 7, 9

A working boot instead reads the device descriptor ~124ms after that same
SLOWAUTO line and moves straight to gear-3 FAST MODE.

THE REGRESSION
4.4 (works on this hardware) always waited a fixed 1us before gating the device
reference clock:

    /* ... make sure that device ref_clk is active at least 1us after the ... */
    udelay(1);

4.14 replaced that with a device-supplied value:

    udelay(host->hba->dev_ref_clk_gating_wait);

but hba->dev_ref_clk_gating_wait is only assigned in
ufshcd_get_dev_ref_clk_gating_wait(), called from ufshcd_probe_hba() *after* the
device descriptor has been read (ufshcd.c:8922). Until then the field is still 0
from the kzalloc'd hba -- so every ref-clk gate before that point waits udelay(0),
i.e. no delay at all, where 4.4 always waited. Gating the device's reference clock
too soon after hibern8 entry leaves it unable to answer, which is exactly the
observed "link is up, device answers nothing" signature. Being a timing margin,
it fails intermittently, which matches: the same image enumerates UFS on some
boots and not others.

The driver already defines the intended default, UFSHCD_REF_CLK_GATING_WAIT_US
(100us), and even falls back to it if the device reports 0 -- it simply is not
applied before the device is first talked to. This sets it in ufshcd_init(), so
the field is never 0.

Low risk: it only lengthens a delay the code already intends to take, from 0 to
the driver's own documented default, and is overwritten by the real device value
as soon as that can be read.

NB this is a strong hypothesis, not a proven fix -- the failure is intermittent,
so confirming it needs several consecutive successful boots, not one.
Idempotent. Run from the 4.14 kernel root, or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/scsi/ufs/ufshcd.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
marker = 'lilac 10.129'
if marker in s:
    print('already patched')
    sys.exit(0)

anchor = '''\t/* Enable debug prints */
\thba->ufshcd_dbg_print = DEFAULT_UFSHCD_DBG_PRINT_EN;
'''
if anchor not in s:
    sys.exit('ufshcd_init anchor not found -- re-derive against current source')

repl = anchor + '''
\t/*
\t * lilac 10.129: seed the ref-clk gating wait before anything can gate the
\t * device reference clock. It is otherwise 0 until
\t * ufshcd_get_dev_ref_clk_gating_wait() runs, which is only after the device
\t * descriptor has been read -- so the early gates take udelay(0) where 4.4
\t * always took udelay(1), and the device can stop answering UPIU queries.
\t * Overwritten with the device's own value as soon as it can be read.
\t */
\thba->dev_ref_clk_gating_wait = UFSHCD_REF_CLK_GATING_WAIT_US;
'''
s = s.replace(anchor, repl, 1)
p.write_text(s)
print(f'patched {p}: dev_ref_clk_gating_wait defaults to UFSHCD_REF_CLK_GATING_WAIT_US')
