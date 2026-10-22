#!/usr/bin/env python3
"""Instrument hybris-boot's init-script with SD-card checkpoint logging.

Adapted from the first port's `patches/patch-initscript-sdlog.py` (same
technique, same rationale: /init.log lives in the initramfs tmpfs and is
lost on a failed boot's hard reset, so mirror it -- and a dmesg snapshot --
to the microSD at each checkpoint, syncing every time, so whatever the last
checkpoint reached survives even a silent reboot with no panic ever
captured in pstore). The only real change from the first port's version:
this writes to **`sfos-v2`**, this port's own subdirectory, never
`sfos-data`/`sfos-414` (those stay the first port's).

Written for a first, untested boot attempt (2026-09-15): `fastboot boot`
completed, but the phone silently returned to LineageOS with no pstore
dmesg-ramoops captured at all -- meaning either a very early hang/panic
pstore never got a chance to log, or something else entirely. This patch
is how to find out which, the next time.

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
if 'sdlog_init' in s:
    print('already patched')
    sys.exit(0)

anchor_fn = '\nmount_stowaways() {'
if s.count(anchor_fn) != 1:
    sys.exit(f'ANCHOR MISS mount_stowaways def: {s.count(anchor_fn)}')

helpers = '''
# --- SD-card logging (Sailfish lilac-v2 port) ------------------------------
# /init.log lives in the initramfs tmpfs and is lost when a failed boot
# resets. Mirror it, plus a dmesg snapshot, to the microSD's sfos-v2
# subdirectory at each checkpoint so the last one reached survives a hard
# reset even with nothing captured in pstore. Same technique as the first
# port's own patches/patch-initscript-sdlog.py -- deliberately a SEPARATE
# subdir (sfos-v2), never sfos-data/sfos-414.
SDLOG=""
sdlog_init() {
    mkdir -p /sdlog
    if mount -t ext4 /dev/mmcblk0p2 /sdlog 2>/dev/null; then
        mkdir -p /sdlog/sfos-v2
        SDLOG=/sdlog/sfos-v2/boot.log
        : > $SDLOG
        echo "=== hybris-boot init (v2/SODP), $(date) ===" >> $SDLOG
        sdlog_mark "sdlog-mounted"
    fi
}
sdlog_mark() {
    [ -n "$SDLOG" ] || return 0
    {
        echo
        echo "########## CHECKPOINT: $1"
        echo "--- /init.log ---"
        cat /init.log 2>/dev/null
        echo "--- dmesg (tail) ---"
        dmesg 2>/dev/null | tail -n 120
        echo "--- block devices ---"
        ls -l /dev/mmcblk* /dev/sd* 2>/dev/null
        echo "--- mounts ---"
        cat /proc/mounts 2>/dev/null
    } >> $SDLOG 2>&1
    sync
}

mount_stowaways() {'''

s = s.replace(anchor_fn, helpers)

old_flow = '''    do_hotplug_scan

    # Support /dev/block/mmcXXX only in initrd phase
    ln -s . /dev/block
    ln -s /proc/mounts /etc/mtab

    check_kernel_config

    bootsplash

    mount_stowaways
'''
new_flow = '''    do_hotplug_scan

    # Support /dev/block/mmcXXX only in initrd phase
    ln -s . /dev/block
    ln -s /proc/mounts /etc/mtab

    # SD-card logging: start as early as block devices exist.
    sdlog_init

    check_kernel_config
    sdlog_mark "after-check_kernel_config"

    bootsplash
    sdlog_mark "after-bootsplash"

    mount_stowaways
    sdlog_mark "after-mount_stowaways"
'''
if s.count(old_flow) != 1:
    sys.exit(f'ANCHOR MISS main flow: {s.count(old_flow)}')
s = s.replace(old_flow, new_flow)

p.write_text(s)
print(f'patched {p} with sfos-v2 SD logging')
