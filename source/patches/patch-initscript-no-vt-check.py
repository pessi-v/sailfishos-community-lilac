#!/usr/bin/env python3
"""Drop CONFIG_VT from init-script's own check_kernel_config() requirement list.

ROOT CAUSE of the 2026-09-15 boot failures (found via the sdlog checkpoint
instrumentation, patches/patch-initscript-sdlog*.py): hybris-boot's
init-script has its OWN hard-coded "must be =y" kernel config check,
separate from and in addition to the build-time `mer_verify_kernel_config`
audit (which patches/patch-dhd-tolerate-vt.py already excuses for this
exact, deliberate gap -- see that patch and patches/patch-defconfig-
sailfish-reqs.py for why CONFIG_VT is intentionally left off: the first
port found VT=y crashes this hardware's display before the initramfs can
even log anything).

This SECOND, RUNTIME check lists CONFIG_VT as mandatory too. Since it's
missing, `/diagnosis.log` gets written, `DBG_REASON` becomes non-empty, and
the init-script diverts into `run_debug_session` instead of ever reaching
`switch_root` -- confirmed via the sdlog checkpoints: "after-mount_stowaways"
is reached and logged every time, but no further checkpoint (including one
added immediately before switch_root) ever appears. That debug session then
tries to bring up a USB gadget network interface for telnet access; ours
fails (this port's boot cmdline doesn't set `androidboot.configfs=true`/
`androidboot.usbcontroller=...`, unlike the first port's), which
run_debug_session's own fallback handles with `sleep 60; reboot -f` --
exactly matching the ~60-90s silent return to LineageOS observed on both
2026-09-15 boot attempts.

Idempotent. Run against hybris-boot's init-script directly (i.e. inside an
already-unpacked ramdisk, or against `hybris/hybris-boot/init-script` in
the source tree before an Android-side rebuild) -- pass its path as
argv[1], or it defaults to `init-script` in the current directory.
"""
import sys
import pathlib

p = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('init-script')
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()

old = 'for x in CONFIG_CGROUPS CONFIG_AUTOFS4_FS CONFIG_DEVTMPFS_MOUNT CONFIG_DEVTMPFS CONFIG_UNIX CONFIG_INOTIFY_USER CONFIG_SYSVIPC CONFIG_NET CONFIG_PROC_FS CONFIG_SIGNALFD CONFIG_SYSFS CONFIG_TMPFS_POSIX_ACL CONFIG_VT; do'
new = 'for x in CONFIG_CGROUPS CONFIG_AUTOFS4_FS CONFIG_DEVTMPFS_MOUNT CONFIG_DEVTMPFS CONFIG_UNIX CONFIG_INOTIFY_USER CONFIG_SYSVIPC CONFIG_NET CONFIG_PROC_FS CONFIG_SIGNALFD CONFIG_SYSFS CONFIG_TMPFS_POSIX_ACL; do # CONFIG_VT deliberately excluded, see patch-initscript-no-vt-check.py'

if new in s:
    print('already patched')
    sys.exit(0)
if old not in s:
    sys.exit('expected check_kernel_config for-loop not found -- init-script may have changed')

p.write_text(s.replace(old, new))
print(f'patched {p}: CONFIG_VT no longer required by check_kernel_config()')
