#!/usr/bin/env python3
"""Retry UFS device detection with a full device reset.

MITIGATION, NOT A ROOT CAUSE FIX. Roughly half of all boots fail to enumerate
UFS (10.128/10.129): the link starts fine at gear-1 SLOWAUTO, then the very first
device interaction times out and never recovers --

    ufshcd_query_flag: Sending flag query for idn 1 failed, err = -110   (x3)
    ufshcd_complete_dev_init: reading fDeviceInit flag failed with error -110

-- leaving no LUNs, no /vendor, no modem/IPA firmware, and eventually an IPA
panic. Static diffing against the working 4.4 tree found no discriminator:
ufshcd_complete_dev_init is byte-identical, the device-reset support and
hba->pctrl assignment match, and the ufshc@1da4000 DT node matches down to the
dev-reset pinctrl states. The failure is a timing/state margin, not a visible
code difference, and the ref-clk-gating-wait hypothesis was tested and disproved.

WHAT THIS DOES
ufshcd_async_scan() currently calls ufshcd_probe_hba() exactly once and DISCARDS
the return value, so a failed detection is simply the end of the story -- the
controller is left with no device and the boot is unusable. This retries via
ufshcd_detect_device(), which is already the driver's own recovery path (used by
two other call sites) and does exactly the right things in the right order:

    ufshcd_vops_full_reset()            - full controller/PHY reset
    ufshcd_reset_device()               - HARDWARE reset of the UFS device over
                                          the dev-reset-assert/deassert pinctrl
                                          lines the DT already declares
    ufshcd_host_reset_and_restore()     - host reset, then re-run probe_hba

The hardware device reset is the part that matters: a device that has gone silent
after link-up is precisely what a reset pulse is for, and nothing on the current
path ever issues one.

Each attempt takes its own pm_runtime reference: ufshcd_probe_hba() always drops
one on exit in this context, so the first failed probe already spent the one
ufshcd_init() took, and re-entering it without a fresh get would underflow the
usage count. See the comment in the generated code.

NB 4.4 does not retry here either -- its async_scan is identical -- so this is a
new mitigation, not restoration of lost behaviour. 4.4 simply succeeds reliably.
Expect this to convert a ~50% failure rate into near-certain success WITHOUT
explaining why the device goes silent; the root cause remains open.

Bounded at 3 attempts so a genuinely dead device still fails rather than looping,
and each attempt is loud in dmesg so the retry rate stays measurable -- if this
lands, the interesting number becomes "how often did it need a retry", which is
the same signal, just no longer fatal.
Idempotent. Run from the 4.14 kernel root, or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/scsi/ufs/ufshcd.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
marker = 'lilac 10.130'
if marker in s:
    print('already patched')
    sys.exit(0)

anchor = '''\tufshcd_hold_all(hba);
\tufshcd_probe_hba(hba);
\tufshcd_release_all(hba);
'''
if anchor not in s:
    sys.exit('ufshcd_async_scan anchor not found -- re-derive against current source')

repl = '''\tufshcd_hold_all(hba);
\tret = ufshcd_probe_hba(hba);
\t/*
\t * lilac 10.130: device detection fails on roughly half of all boots --
\t * link comes up, then fDeviceInit times out and the device answers
\t * nothing. Upstream discards this failure, which leaves the controller
\t * with no device and the boot unusable. Retry through the driver's own
\t * recovery path, which crucially issues a HARDWARE reset to the device
\t * (dev-reset pinctrl) before re-probing -- nothing else on this path
\t * ever does. Mitigation only; root cause still unknown.
\t *
\t * The pm_runtime_get_sync() is required, not decorative:
\t * ufshcd_probe_hba() ends with pm_runtime_put_sync() on BOTH its success
\t * and failure paths whenever it runs outside error handling and power
\t * management (i.e. exactly here), so the failed probe above has already
\t * consumed the reference ufshcd_init() took before async_schedule().
\t * ufshcd_detect_device() re-enters probe_hba via
\t * ufshcd_host_reset_and_restore() and would put a second time, so each
\t * attempt must bring its own reference or the usage count underflows and
\t * the controller can be runtime-suspended in the middle of recovery.
\t * ufshcd_card_detect_handler() takes the reference the same way, for the
\t * same reason.
\t */
\tfor (retries = 0; ret && retries < UFSHCD_LILAC_DETECT_RETRIES; retries++) {
\t\tdev_err(hba->dev,
\t\t\t"%s: device detection failed (%d), retry %d/%d with full device reset\\n",
\t\t\t__func__, ret, retries + 1, UFSHCD_LILAC_DETECT_RETRIES);
\t\tpm_runtime_get_sync(hba->dev);
\t\tret = ufshcd_detect_device(hba);
\t}
\tif (ret)
\t\tdev_err(hba->dev, "%s: device detection failed after %d retries (%d)\\n",
\t\t\t__func__, UFSHCD_LILAC_DETECT_RETRIES, ret);
\telse if (retries)
\t\tdev_err(hba->dev, "%s: device detected after %d retry(ies)\\n",
\t\t\t__func__, retries);
\tufshcd_release_all(hba);
'''
s = s.replace(anchor, repl, 1)

# locals for the new code
decl_anchor = '''static void ufshcd_async_scan(void *data, async_cookie_t cookie)
{
\tstruct ufs_hba *hba = (struct ufs_hba *)data;
'''
if decl_anchor not in s:
    sys.exit('async_scan declaration anchor not found -- re-derive')
s = s.replace(decl_anchor, decl_anchor + '\tint ret, retries;\n', 1)

# the retry bound, next to the driver's other tunables
const_anchor = '#define UFSHCD_REF_CLK_GATING_WAIT_US 100 /* microsecs */\n'
if const_anchor not in s:
    sys.exit('constant anchor not found -- re-derive')
s = s.replace(
    const_anchor,
    const_anchor + '\n/* lilac 10.130: attempts at UFS device detection before giving up */\n'
                   '#define UFSHCD_LILAC_DETECT_RETRIES 3\n',
    1)

p.write_text(s)
print(f'patched {p}: retry ufshcd_probe_hba via ufshcd_detect_device (max '
      f'UFSHCD_LILAC_DETECT_RETRIES)')
