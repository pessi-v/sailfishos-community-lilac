#!/usr/bin/env python3
"""Retry UFS device detection with a full device reset, DEFERRED a few seconds.

Supersedes patches/patch-ufs-retry-device-detect-414.py from the first port, which retried
immediately inside ufshcd_async_scan(). Do not apply both.

PROBLEM
On roughly half of all cold boots the 4.14 UFS driver fails device detection: the link comes
up at gear-1, then the first device interaction times out and never recovers --

    ufshcd_query_flag: Sending flag query for idn 1 failed, err = -110   (x3)
    ufshcd_complete_dev_init: reading fDeviceInit flag failed with error -110

-- leaving no LUNs, no /vendor, no modem, and a userspace that never finishes booting.
ufshcd_async_scan() calls ufshcd_probe_hba() once and discards its return value.

WHAT THIS DOES
When that first probe fails, schedule a work item 3 s later that retries up to
UFSHCD_LILAC_DETECT_RETRIES times through ufshcd_detect_device(), the driver's own recovery
path: full controller/PHY reset, HARDWARE reset of the UFS device (dev-reset pinctrl), host
reset, re-probe. Nothing else on the boot path ever issues the device reset.

WHY DEFERRED, NOT IMMEDIATE (measured, 2026-10-14)
The immediate variant (retry inside async_scan, right after the failed probe) hard-crashed the
phone in the one test it got: black screen, no LED, no USB, no log. Running the same retry from a
work item 25 s later worked (full trace: full_reset 0, reset_device 0, host_reset_and_restore 0,
LUNs enumerated at gear-3 FAST MODE). 3 s works too, and is early enough that the LUNs exist
before systemd-udevd starts (at 25 s the LUNs appeared in the middle of udev's cold-plug and the
by-name rule ran with empty PLATFORM_* variables -- see droid-hal-prepare.sh step -2).
The suspected difference is runtime-PM: the failed probe ends with pm_runtime_put_sync(), and
an immediate pm_runtime_get_sync()+reset races the suspend that put triggers. Not proven.

The pm_runtime_get_sync() per attempt is still required: ufshcd_probe_hba() drops one reference
on every exit outside error handling, and ufshcd_detect_device() re-enters it.

CAVEATS
- Mitigation, not a root-cause fix. The injected-failure tests used a HEALTHY device, so recovery
  of a genuinely silent device is still unproven. Boots with the retry fired showed (in 3 of 3
  tests, all with the injected failure) a rear-camera video recording that never finished and
  ADSP audio-stream-close errors; a boot of the unpatched kernel did not. Cause unknown --
  possibly an artefact of the injection, which skips the real SET_FLAG query. Test this patch
  with NO injection over several cold boots before shipping it.
- Single UFS host assumed (static work + pointer).

Idempotent. Apply to the pristine source. Run from the 4.14 kernel root, or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/scsi/ufs/ufshcd.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
marker = 'lilac 171'
if marker in s:
    print('already patched')
    sys.exit(0)
if 'UFSHCD_LILAC_DETECT_RETRIES' in s:
    sys.exit('the immediate-retry patch (patch-ufs-retry-device-detect-414.py) is applied; '
             'start from pristine source')

# 1. the retry bound, next to the driver's other tunables
const_anchor = '#define UFSHCD_REF_CLK_GATING_WAIT_US 100 /* microsecs */\n'
if const_anchor not in s:
    sys.exit('constant anchor not found -- re-derive')
s = s.replace(
    const_anchor,
    const_anchor + '\n/* lilac 171: attempts at UFS device detection (deferred) before giving up */\n'
                   '#define UFSHCD_LILAC_DETECT_RETRIES 3\n'
                   '#define UFSHCD_LILAC_DETECT_DELAY_SECS 3\n',
    1)

# 2. the deferred worker, placed right before ufshcd_async_scan (ufshcd_detect_device is above)
scan_doc = '/**\n * ufshcd_async_scan - asynchronous execution for probing hba'
if scan_doc not in s:
    sys.exit('ufshcd_async_scan kerneldoc anchor not found -- re-derive')
worker = '''/*
 * lilac 171: deferred device-detection retry. See patches/patch-ufs-retry-device-detect-
 * deferred-414.py for the reasoning (immediate retry crashed the phone, 3 s later works).
 */
static struct ufs_hba *lilac_detect_hba;
static void lilac_detect_retry_fn(struct work_struct *w);
static DECLARE_DELAYED_WORK(lilac_detect_retry_work, lilac_detect_retry_fn);

static void lilac_detect_retry_fn(struct work_struct *w)
{
\tstruct ufs_hba *hba = lilac_detect_hba;
\tint i, err = -EIO;

\tfor (i = 1; err && i <= UFSHCD_LILAC_DETECT_RETRIES; i++) {
\t\tdev_err(hba->dev, "%s: retry %d/%d with full device reset\\n",
\t\t\t__func__, i, UFSHCD_LILAC_DETECT_RETRIES);
\t\tufshcd_hold_all(hba);
\t\t/* ufshcd_probe_hba() drops one runtime-PM reference on every exit here */
\t\tpm_runtime_get_sync(hba->dev);
\t\terr = ufshcd_detect_device(hba);
\t\tufshcd_release_all(hba);
\t}
\tif (err)
\t\tdev_err(hba->dev, "%s: device detection failed after %d retries (%d)\\n",
\t\t\t__func__, UFSHCD_LILAC_DETECT_RETRIES, err);
\telse
\t\tdev_err(hba->dev, "%s: device detected after %d retry(ies)\\n",
\t\t\t__func__, i - 1);
}

'''
s = s.replace(scan_doc, worker + scan_doc, 1)

# 3. schedule it when the one and only probe fails
anchor = '''\tufshcd_hold_all(hba);
\tufshcd_probe_hba(hba);
\tufshcd_release_all(hba);
'''
if anchor not in s:
    sys.exit('ufshcd_async_scan anchor not found -- re-derive against current source')
repl = '''\tufshcd_hold_all(hba);
\tret = ufshcd_probe_hba(hba);
\tif (ret) {
\t\tdev_err(hba->dev,
\t\t\t"%s: device detection failed (%d), retry in %d s\\n",
\t\t\t__func__, ret, UFSHCD_LILAC_DETECT_DELAY_SECS);
\t\tlilac_detect_hba = hba;
\t\tschedule_delayed_work(&lilac_detect_retry_work,
\t\t\t\t      UFSHCD_LILAC_DETECT_DELAY_SECS * HZ);
\t}
\tufshcd_release_all(hba);
'''
s = s.replace(anchor, repl, 1)

decl_anchor = '''static void ufshcd_async_scan(void *data, async_cookie_t cookie)
{
\tstruct ufs_hba *hba = (struct ufs_hba *)data;
'''
if decl_anchor not in s:
    sys.exit('async_scan declaration anchor not found -- re-derive')
s = s.replace(decl_anchor, decl_anchor + '\tint ret;\n', 1)

p.write_text(s)
print(f'patched {p}: deferred ({3} s) UFS device-detection retry, max 3 attempts')
