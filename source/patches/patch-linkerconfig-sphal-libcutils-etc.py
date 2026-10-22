#!/usr/bin/env python3
"""Third round of the same `hwcomposer.msm8998.so`/`sphal` fix this session
(`patch-linkerconfig-sphal-libbinder.py`, `patch-linkerconfig-sphal-libhardware.py`): once
`libbinder.so`/`libhardware.so` resolved, `lipstick`'s next attempt surfaced five more genuine,
direct `NEEDED` entries of the same blob (confirmed with `readelf -d` earlier this session) that
the `sphal` namespace still doesn't expose:

    lipstick[NNNNN]: library "libutils.so" not found
    lipstick[NNNNN]: library "libcutils.so" not found
    lipstick[NNNNN]: library "libsync.so" not found
    lipstick[NNNNN]: library "libc++.so" not found
    lipstick[NNNNN]: library "libui.so" not found

(`libhardware_legacy.so` also still appeared here despite being added in round two -- that one
turned out to be a `droid-hal-prepare.sh` file-staging gap, not a namespace-policy gap: it was
never checked into this project's overlay source tree at all, so the existing by-name bind-mount
loop (step 2) had nothing to mount even once the namespace allowed it. Fixed separately by
staging the file, not by this patch.)

Same fix, same reasoning as the previous two rounds: link all five from the `default` namespace.
`libsync.so` is oddly already nominally in the same list this session's earlier reads showed --
included again here anyway (idempotent duplicate entries in `ld.config.txt` are harmless) in case
that entry alone wasn't sufficient for some path-specific reason not otherwise investigated
tonight.

Idempotent -- requires the previous two patches (specifically
`patch-linkerconfig-sphal-libhardware.py`) to have already been applied. Run from the root of
this AOSP source tree, or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
sphal_cc = root / 'system/linkerconfig/contents/namespace/sphal.cc'
if not sphal_cc.is_file():
    sys.exit(f'not found: {sphal_cc}')

s = sphal_cc.read_text()
MARK = '// lilac: libutils.so/libcutils.so/libsync.so/libc++.so/libui.so, same reasoning'

if MARK in s:
    print('already patched')
    sys.exit(0)

LIBS = ['libutils.so', 'libcutils.so', 'libsync.so', 'libc++.so', 'libui.so']

total = 0
for indent in ('      ', '    '):
    old = f'\n{indent}ns.GetLink(ctx.GetSystemNamespaceName()).AddSharedLib("libhardware_legacy.so");\n'
    if old not in s:
        continue
    lines = ''.join(f'{indent}ns.GetLink(ctx.GetSystemNamespaceName()).AddSharedLib("{lib}");\n' for lib in LIBS)
    new = (
        old
        + f'{indent}{MARK} as libbinder.so/libhardware.so above\n'
        + f'{indent}//.\n'
        + lines
    )
    count = s.count(old)
    if count != 1:
        sys.exit(f'expected exactly 1 occurrence of the {len(indent)}-space-indent anchor, found {count} -- tree changed')
    s = s.replace(old, new, 1)
    total += 1

if total == 0:
    sys.exit('no libhardware_legacy.so anchor found at all (either indent) -- tree changed, or round two was never applied')

sphal_cc.write_text(s)
print(f'patched {sphal_cc}: sphal namespace now also links {", ".join(LIBS)} ({total} branch(es))')
