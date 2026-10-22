#!/usr/bin/env python3
"""Stop `init` from rebooting the whole device over a missing `apexd`.

Root cause, fully bisected via a `/proc/kmsg`-to-SD-card capture surviving the actual hard
reset (pstore came back empty twice -- this was never a kernel panic): real Android's
`system/core/rootdir/init.rc` treats a failed `apexd` as a fatal, device-wide condition,
because on stock Android nothing else can run without the runtime APEX it activates (ART,
Zygote). Three separate `reboot_on_failure` traps exist for this:

  1. `exec_start apexd-bootstrap` (blocking) -- `apexd-bootstrap`'s own service definition
     in `system/apex/apexd/apexd.rc` carries `reboot_on_failure
     reboot,bootloader,bootstrap-apexd-failed` -- the exact reason string this port's device
     was observed rebooting with.
  2. `start apexd` (non-blocking, but the plain `apexd` service ALSO carries
     `reboot_on_failure reboot,apexd-failed`).
  3. `wait_for_prop apexd.status activated` -- not a reboot trap, but a blocking wait that
     would stall boot forever once (1) and (2) stop ever setting that property.

None of this is needed here: this port never runs a real `apexd` at all (by design -- see
§14's static `/apex/com.android.runtime/bin/{linker,linker64}` population, which sidesteps
needing apexd's actual activation machinery for anything) and, more fundamentally, nothing
downstream ever needs what apexd provides -- Zygote itself is unconditionally disabled by
`mer-hybris/hybris-patches`' own `0015-hybris-Disable-all-zygote-variations.patch` (already
applied, see `patch-system-core-hybris-init.py`), so the one real consumer of the runtime
APEX apexd-bootstrap exists to unblock is already cut off upstream of this.

Fix: comment out all three lines. Deliberately NOT faking `apexd.status=ready` -- doing so
would just trigger a *different* reboot trap, since `on property:apexd.status=ready ...`
also starts `boringssl_self_test_apex32`/`64` against `/apex/com.android.conscrypt/bin/...`
paths that don't exist here either, and those carry their own
`reboot_on_failure reboot,boringssl-self-check-failed`. Leaving `apexd.status` permanently
unset means those blocks simply never fire -- the correct outcome, since nothing needs them.

Idempotent. Run from the root of this kernel/system tree (needs system/core/ as a
subdirectory, same convention as patch-system-core-hybris-init.py), or pass that root as
argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
init_rc = root / 'system/core/rootdir/init.rc'
if not init_rc.is_file():
    sys.exit(f'not found: {init_rc}')

s = init_rc.read_text()
MARK = '# lilac: apexd is never run on this Sailfish-hosted setup'

if MARK in s:
    print('already patched')
    sys.exit(0)

replacements = [
    (
        '    exec_start apexd-bootstrap\n',
        f'    {MARK}.\n'
        '    # apexd-bootstrap carries its own reboot_on_failure and always fails here.\n'
        '    # was: exec_start apexd-bootstrap\n',
    ),
    (
        '    start apexd\n',
        f'    {MARK}.\n'
        '    # the plain apexd service also carries reboot_on_failure.\n'
        '    # was: start apexd\n',
    ),
    (
        '    wait_for_prop apexd.status activated\n',
        f'    {MARK}.\n'
        '    # apexd.status is never set now, so this would stall boot forever otherwise.\n'
        '    # was: wait_for_prop apexd.status activated\n',
    ),
]

missing = [old for old, _ in replacements if old not in s]
if missing:
    sys.exit(f'anchor(s) not found, tree changed: {missing!r}')

for old, new in replacements:
    assert s.count(old) == 1, f'expected exactly one occurrence of {old!r}, found {s.count(old)}'
    s = s.replace(old, new, 1)

init_rc.write_text(s)
print(f'patched {init_rc}: disabled apexd-bootstrap/apexd/wait_for_prop apexd.status')
