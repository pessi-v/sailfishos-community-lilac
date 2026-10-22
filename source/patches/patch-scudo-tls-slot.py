#!/usr/bin/env python3
"""Fix the real cause of the `hwservicemanager` (and every other native binary's) SIGBUS
first found in §14 and precisely diagnosed via gdb in §18 -- the actual final layer under
the apexd device-crash, not the apexd bug itself.

`gdb` traced the fault to `scudo::HybridMutex::tryLock()` (Android's hardened allocator,
built into bionic's libc.so) being called with a garbage, misaligned `this` pointer,
itself computed as `*(tls[6]) + 8004` -- `external/scudo/standalone/linux.h`'s
`getAndroidTlsPtr()` reads Scudo's own thread-specific-data cache out of a raw bionic TLS
slot, hardcoded as `TLS_SLOT_SANITIZER = 6`, completely independent of (and never updated
alongside) `bionic/libc/platform/bionic/tls_defines.h`.

That's the bug: `patches/patch-bionic-hybris-tls.py`'s own `hybris-patches` set (patch
0002, applied for the *original* TLS segfault) shifts
`TLS_SLOT_SANITIZER` from slot 6 to slot 7 in bionic's own `tls_defines.h`, precisely to
free up slot 6 for `TLS_SLOT_STACK_GUARD` (moved down from 5) as part of freeing room for
`TLS_SLOT_ART_THREAD_SELF`'s new home. `hybris-patches` only ever touches `bionic/` --
`external/scudo/`'s own separate, hardcoded copy of the same constant was never in scope
for that patch set, so it's stayed at the pre-hybris-patches value (6) that no longer
matches. Scudo ends up reading the stack-protector canary (a small random value, not a
pointer) out of slot 6, believing it's a valid pointer to its own per-thread cache, and
crashes trying to lock a "mutex" at `canary + 8004`.

Confirmed via the actual instruction stream at the fault (`mrs x27, tpidr_el0` /
`ldr x27, [x27, #48]` -- byte offset 48 = slot 6 -- `add x0, x27, #8004` /
`bl tryLock`), and via `tls_defines.h`'s own diff: stock (pre-patch) bionic had
`TLS_SLOT_SANITIZER = 6` -- the exact value still hardcoded in Scudo -- and hybris-patches'
0002 moves it to 7.

Fix: update Scudo's own copy to match. One line, no new dependency on `tls_defines.h` (kept
independent, matching Scudo's existing "standalone" design -- it deliberately avoids
including bionic's own headers).

Idempotent. Run from the repo-synced tree root (needs external/scudo/ as a subdirectory),
or pass that root as argv[1]. Note this changes libc.so itself, so it needs a real rebuild
(m libc or m hybris-hal), not a fast `init`-only build like the last several patches here.
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
linux_h = root / 'external/scudo/standalone/linux.h'
if not linux_h.is_file():
    sys.exit(f'not found: {linux_h}')

s = linux_h.read_text()
old = 'static const int TLS_SLOT_SANITIZER = 6;'
new = (
    'static const int TLS_SLOT_SANITIZER = 7;  // lilac: hybris-patches\n'
    '  // shift bionic\'s own TLS_SLOT_SANITIZER from 6 to 7 to free slot 6 for\n'
    '  // TLS_SLOT_STACK_GUARD -- this copy, independent of bionic/libc/platform/bionic/\n'
    '  // tls_defines.h by Scudo\'s own "standalone" design, must track that shift by hand.'
)

if new in s:
    print('already patched')
    sys.exit(0)
if old not in s:
    sys.exit(f'anchor not found in {linux_h} -- tree changed, re-derive it')
assert s.count(old) == 1, f'expected exactly one occurrence, found {s.count(old)}'

linux_h.write_text(s.replace(old, new, 1))
print(f'patched {linux_h}: TLS_SLOT_SANITIZER 6 -> 7')
