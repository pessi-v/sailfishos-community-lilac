#!/usr/bin/env python3
"""Extend SD-log checkpointing into the post-switch_root /init-debug path.

Requires patch-initscript-sdlog.py already applied.

2026-09-15, third boot attempt (CONFIG_VT=y test kernel): a NEW checkpoint,
"before-switch_root (init-debug path)", was reached and logged -- the
rootfs's own `/init-debug` flag file exists, so `switch_root` execs into it
instead of straight into systemd. `init-debug` is a re-exec of this SAME
init-script (`[ "$0" = "/init-debug" ]` sets `DONE_SWITCH=yes`, taking the
`else` branch at the bottom of the file: "We're in the real rootfs running
as init-debug"). But `SDLOG`/`sdlog_mark` are only wired into the FIRST
(`DONE_SWITCH=no`, initrd-side) branch -- `sdlog_init` is never called
again in the `else` branch, so every `sdlog_mark` call there is silently a
no-op (`[ -n "$SDLOG" ] || return 0`). That's why logging went dark right
after that checkpoint even though execution kept going.

This patch re-mounts the SD card (idempotent -- `mount` on an
already-mounted device just fails harmlessly under `2>/dev/null`, and
`sdlog_init` unconditionally resets $SDLOG) and adds checkpoints around
`run_debug_session "init-debug in real rootfs"` and immediately before the
final `exec $INIT` -- the two places most likely to be where a USB-gadget-
setup failure (`run_debug_session`'s own `sleep 60; reboot -f` fallback)
or an exec failure would otherwise vanish without a trace.

Idempotent. Run against an init-script that already has patch-
initscript-sdlog.py applied -- pass its path as argv[1], or it defaults to
`init-script` in the current directory.
"""
import sys
import pathlib

p = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('init-script')
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'before-real-init-debug-session' in s:
    print('already patched')
    sys.exit(0)
if 'sdlog_mark' not in s:
    sys.exit('sdlog_mark() not found -- apply patch-initscript-sdlog.py first')

old = '''    do_mount_devprocsys

    HALT_BOOT="n"
    [ -f /init_enter_debug2 ] && HALT_BOOT="y"
    [ -f /init_disable_telnet ] && DISABLE_TELNET="y"
    run_debug_session "init-debug in real rootfs" $HALT_BOOT

    # If we don't do this then udev will not be able to create /dev/block/*
    rm /dev/block

    # Now try to boot the real init
    # Prefer /sbin/preinit over /sbin/init
    [ -x /sbin/preinit ] && INIT=/sbin/preinit || INIT=/sbin/init
    exec $INIT --log-level=debug --log-target=kmsg &> /boot/systemd_stdouterr
    run_debug_session "init in real rootfs failed"'''

new = '''    do_mount_devprocsys

    # Re-establish SD logging: SDLOG does not survive the exec into
    # /init-debug (this is a fresh interpretation of the same script).
    sdlog_init
    sdlog_mark "entered real rootfs as init-debug"

    HALT_BOOT="n"
    [ -f /init_enter_debug2 ] && HALT_BOOT="y"
    [ -f /init_disable_telnet ] && DISABLE_TELNET="y"
    sdlog_mark "before-real-init-debug-session"
    run_debug_session "init-debug in real rootfs" $HALT_BOOT
    sdlog_mark "after-real-init-debug-session"

    # If we don't do this then udev will not be able to create /dev/block/*
    rm /dev/block

    # Now try to boot the real init
    # Prefer /sbin/preinit over /sbin/init
    [ -x /sbin/preinit ] && INIT=/sbin/preinit || INIT=/sbin/init
    sdlog_mark "before-exec-real-init INIT=$INIT executable=$([ -x "$INIT" ] && echo yes || echo no)"
    exec $INIT --log-level=debug --log-target=kmsg &> /boot/systemd_stdouterr
    sdlog_mark "exec of real init returned -- this should be unreachable"
    run_debug_session "init in real rootfs failed"'''

if old not in s:
    sys.exit('expected init-debug else-branch not found -- init-script may have changed')

p.write_text(s.replace(old, new))
print(f'patched {p} with post-switch_root checkpoints')
