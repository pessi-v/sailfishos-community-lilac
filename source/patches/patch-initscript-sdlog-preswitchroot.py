#!/usr/bin/env python3
"""Add one more SD-log checkpoint immediately before switch_root.

Requires patch-initscript-sdlog.py already applied (needs sdlog_mark()).

2026-09-15 boot attempt: all four existing checkpoints (sdlog-mounted,
after-check_kernel_config, after-bootsplash, after-mount_stowaways) were
reached and persisted to sfos-v2/boot.log, but neither
/init-debug-stderrout nor /init-stderrout ever appeared in the rootfs
afterward -- meaning either switch_root's own `&> /target/...` redirect
never got flushed to disk before a hard reset (ext4 writes aren't synced
immediately), or the `[ -x "/target$INIT" ]` check somehow failed despite
/sbin/preinit existing and being executable. This checkpoint, with an
explicit `sync` right after it (sdlog_mark already syncs), disambiguates:
if it's missing after the next attempt, the failure is between
mount_stowaways and this point; if present, switch_root itself (or
whatever it execs into) is where to look next.

Idempotent. Run against an init-script that already has patch-
initscript-sdlog.py applied -- pass its path as argv[1], or it defaults
to `init-script` in the current directory.
"""
import sys
import pathlib

p = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('init-script')
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'before-switch_root' in s:
    print('already patched')
    sys.exit(0)
if 'sdlog_mark' not in s:
    sys.exit('sdlog_mark() not found -- apply patch-initscript-sdlog.py first')

old = '''    if [ -f "/target/init-debug" ]; then
	exec switch_root /target /init-debug &> /target/init-debug-stderrout
    else
	# Prefer /sbin/preinit over /sbin/init
	[ -x /target/sbin/preinit ] && INIT=/sbin/preinit || INIT=/sbin/init
	if [ -x "/target$INIT" ]; then
	    exec switch_root /target $INIT --log-level=debug --log-target=kmsg &> /target/init-stderrout
	fi
    fi
    run_debug_session "Failed to boot init in real rootfs"'''

new = '''    if [ -f "/target/init-debug" ]; then
	sdlog_mark "before-switch_root (init-debug path)"
	exec switch_root /target /init-debug &> /target/init-debug-stderrout
    else
	# Prefer /sbin/preinit over /sbin/init
	[ -x /target/sbin/preinit ] && INIT=/sbin/preinit || INIT=/sbin/init
	sdlog_mark "before-switch_root INIT=$INIT executable=$([ -x "/target$INIT" ] && echo yes || echo no)"
	if [ -x "/target$INIT" ]; then
	    exec switch_root /target $INIT --log-level=debug --log-target=kmsg &> /target/init-stderrout
	fi
    fi
    sdlog_mark "switch_root fell through -- entering run_debug_session"
    run_debug_session "Failed to boot init in real rootfs"'''

if old not in s:
    sys.exit('expected switch_root block not found -- init-script may have changed')

p.write_text(s.replace(old, new))
print(f'patched {p} with a pre-switch_root checkpoint')
