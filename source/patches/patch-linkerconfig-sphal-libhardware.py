#!/usr/bin/env python3
"""Direct continuation of `patch-linkerconfig-sphal-libbinder.py`, same session, same root cause,
same vendor blob (`hwcomposer.msm8998.so`): once `libbinder.so` resolved, `lipstick`'s next
attempt got further and surfaced two more genuine, direct `NEEDED` entries of that same blob
(confirmed with `readelf -d`, same as before) that the `sphal` namespace also doesn't expose:

    lipstick[NNNNN]: library "libbinder.so" not found        <- gone after the previous patch
    lipstick[NNNNN]: library "libhardware.so" not found       <- new
    lipstick[NNNNN]: library "libhardware_legacy.so" not found <- new

`libhardware.so` is nominally already in `VNDK_SAMEPROCESS_LIBRARIES_VENDOR` (visible in the
generated `ld.config.txt`'s `namespace.sphal.link.vndk.shared_libs`), but the `vndk` namespace's
own search paths (`/odm/${LIB}/vndk-sp`, `/vendor/${LIB}/vndk-sp`,
`/apex/com.android.vndk.v30/${LIB}`) evidently don't actually have a real file there for it on
this device -- same shape of gap as every other "nominally listed but never actually populated"
issue this project has hit all night. `libhardware_legacy.so` isn't in either list at all.
Simplest, most direct fix, matching the same one-more-named-library approach as the previous
patch: link both from the `default` namespace instead (real `/system/lib{64,}/` copies of both
are always present) rather than chasing why the `vndk` namespace's own copy isn't reachable.

Idempotent -- requires `patch-linkerconfig-sphal-libbinder.py` to have already been applied (adds
its two new lines right after that patch's `libbinder.so` ones). Run from the root of this AOSP
source tree, or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
sphal_cc = root / 'system/linkerconfig/contents/namespace/sphal.cc'
if not sphal_cc.is_file():
    sys.exit(f'not found: {sphal_cc}')

s = sphal_cc.read_text()
MARK = '// lilac: libhardware.so/libhardware_legacy.so, same reasoning as libbinder.so above'

if MARK in s:
    print('already patched')
    sys.exit(0)

# The two branches indent this line differently (6 spaces in the apex branch, 4 in the
# plain/else branch, per the previous patch) -- handle both explicitly rather than assume one.
# Match with a leading newline so the shorter (4-space) anchor can't false-positive-match as a
# substring of the longer (6-space) line (both start with the same 4 spaces).
total = 0
for indent in ('      ', '    '):
    old = f'\n{indent}ns.GetLink(ctx.GetSystemNamespaceName()).AddSharedLib("libbinder.so");\n'
    if old not in s:
        continue
    new = (
        old
        + f'{indent}{MARK}\n'
        + f'{indent}//: both are genuine NEEDED entries of the same blob,\n'
        + f'{indent}// surfaced only once libbinder.so itself stopped being the first failure.\n'
        + f'{indent}ns.GetLink(ctx.GetSystemNamespaceName()).AddSharedLib("libhardware.so");\n'
        + f'{indent}ns.GetLink(ctx.GetSystemNamespaceName()).AddSharedLib("libhardware_legacy.so");\n'
    )
    # old itself now starts with '\n', which is fine for count()/replace() -- both operate on
    # the literal substring regardless of what precedes it.
    count = s.count(old)
    if count != 1:
        sys.exit(f'expected exactly 1 occurrence of the {len(indent)}-space-indent anchor, found {count} -- tree changed')
    s = s.replace(old, new, 1)
    total += 1

if total == 0:
    sys.exit('no libbinder.so anchor found at all (either indent) -- tree changed, or the libbinder patch was never applied')
sphal_cc.write_text(s)
print(f'patched {sphal_cc}: sphal namespace now also links libhardware.so/libhardware_legacy.so ({total} branch(es))')
