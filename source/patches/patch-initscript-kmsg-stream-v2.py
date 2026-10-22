#!/usr/bin/env python3
"""Make the existing sdlog_kmsg_stream() diagnosable -- it has been silently
producing zero output across multiple real boots.

`sdlog_kmsg_stream()` (added to this ramdisk's own `init` script in an earlier
session) backgrounds `cat /proc/kmsg >>
live-kmsg.log` right after the SD card mounts, specifically so it survives
`switch_root` with no dependency on systemd reaching any target (an
already-open fd keeps writing to the same block device regardless of what the
mount namespace looks like afterward). Confirmed via `sdlog_mark`'s own
checkpoints that this function *is* being reached on a real boot (the
"sdlog-mounted" checkpoint, printed immediately before it, appears fresh in
`sfos-v2/boot.log` every boot) -- but `sfos-v2/live-kmsg.log` itself has not
been touched by ANY boot this whole session (checked directly from the
LineageOS side: its mtime predates every `fastboot boot` attempt logged
anywhere in this repo's own history). Not one byte, not even an error message
from a failed `cat /proc/kmsg` open (which the existing `2>&1` redirect should
have captured). Root cause not yet identified -- this patch does not guess at
one; it makes the function self-diagnosing so the *next* boot's own SD-card
evidence answers it directly: writes an explicit, synced start marker before
ever touching /proc/kmsg, explicitly tests `[ -r /proc/kmsg ]` and logs the
result, and captures `cat`'s own exit code once it returns (which it should
never do while still streaming, so seeing that line at all is itself a
finding). Writes to a new file (`live-kmsg-v2.log`) rather than the old
`live-kmsg.log`, so a genuinely fresh, empty-until-touched file makes "did
this boot write anything at all" unambiguous at a glance, without needing to
compare timestamps against a stale leftover from months earlier.

Idempotent. Requires patch-initscript-sdlog.py already applied (this
function's own callsite, inside sdlog_init(), predates this patch). Run
against an already-unpacked ramdisk's init script -- pass its path as
argv[1], or it defaults to `init` in the current directory.
"""
import sys
import pathlib

p = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('init')
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'sdlog_kmsg_stream() entered' in s or 'live-kmsg-v2.log' in s:
    print('already patched')
    sys.exit(0)

old = '''sdlog_kmsg_stream() {
    # Continuous kmsg + sync capture, started before switch_root so it does
    # not depend on systemd reaching any target in the real rootfs. An
    # already-open fd keeps writing to the same underlying block device
    # (/dev/mmcblk0p2) regardless of what the mount namespace looks like
    # after switch_root -- same reasoning as the checkpoint log above, just
    # continuous instead of one-shot.
    ( cat /proc/kmsg >> /sdlog/sfos-v2/live-kmsg.log 2>&1 ) &
    ( while true; do sync; sleep 1; done ) &
}'''

new = '''sdlog_kmsg_stream() {
    # Continuous kmsg + sync capture, started before switch_root so it does
    # not depend on systemd reaching any target in the real rootfs. An
    # already-open fd keeps writing to the same underlying block device
    # (/dev/mmcblk0p2) regardless of what the mount namespace looks like
    # after switch_root -- same reasoning as the checkpoint log above, just
    # continuous instead of one-shot.
    #
    # v2 diag: the previous version of this function produced NO output at
    # all across several real boots (live-kmsg.log never touched, not even
    # an error line, despite sdlog_mark's own "sdlog-mounted" checkpoint --
    # printed immediately before this function is called -- showing up fresh
    # every boot). Root cause not yet known. This version writes an explicit
    # start marker (synced immediately) before ever touching /proc/kmsg, and
    # tests readability explicitly first, so the NEXT boot's own SD-card
    # evidence says definitively whether this function is even reached,
    # whether /proc/kmsg opens at all, and if not, the exact error -- rather
    # than staying a silent no-op a second time. New filename
    # (live-kmsg-v2.log) so "untouched" is unambiguous without comparing
    # timestamps against the old file's stale leftover content.
    KLOG=/sdlog/sfos-v2/live-kmsg-v2.log
    : > $KLOG
    echo "=== sdlog_kmsg_stream entered, $(date) ===" >> $KLOG
    sync
    if [ -r /proc/kmsg ]; then
        echo "/proc/kmsg readable, starting cat" >> $KLOG
    else
        echo "/proc/kmsg NOT readable (test -r failed)" >> $KLOG
    fi
    sync
    ( cat /proc/kmsg >> $KLOG 2>>$KLOG ; echo "cat /proc/kmsg exited rc=$?" >> $KLOG ; sync ) &
    ( while true; do sync; sleep 1; done ) &
}'''

if old not in s:
    sys.exit('sdlog_kmsg_stream() body anchor not found -- init script may have changed')

p.write_text(s.replace(old, new))
print(f'patched {p}: sdlog_kmsg_stream() made self-diagnosing')
