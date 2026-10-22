#!/usr/bin/env python3
"""Fix tcs3490.c for a scalar ktime_t (build break found 2026-09-14).

Enabling CONFIG_SENSORS_TCS3490 (patch-defconfig-rgbcir-tcs3490.py) breaks the
build on this kernel:

    drivers/misc/tcs3490.c:604:48: error: member reference base type 'ktime_t'
    (aka 'long long') is not a structure or union
        chip->als_inf.timestamp = (uint64_t)cur_ktime.tv64;

The driver was written against a kernel where `ktime_t` is `union ktime` with
a `.tv64` member (the pre-4.17-ish "safe on 32-bit" representation, still
selectable via CONFIG_KTIME_SCALAR on some trees). This kernel's `ktime_t` is
already a plain `s64`/`long long` -- exactly the value `.tv64` used to expose
-- so the fix is just to drop the `.tv64` access, not to convert anything.

This driver did not need this fix in the first port's stock-Sony-source 4.14
tree (that repo enabled this same symbol and built
fine), so something in mer-hybris's ~175 commits on top of the same
LA.UM.7.1.r1 base changed ktime_t's representation for this config -- not
investigated further since the fix is correct either way.

Idempotent. Run from the kernel root, or pass the tree as argv[1].
"""
import re
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/misc/tcs3490.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
old = 'chip->als_inf.timestamp = (uint64_t)cur_ktime.tv64;'
new = 'chip->als_inf.timestamp = (uint64_t)cur_ktime;'
count = s.count(old)
if count == 0:
    if s.count(new) > 0:
        print('already patched')
        sys.exit(0)
    sys.exit('expected pattern not found -- re-derive against current source')

s = s.replace(old, new)
p.write_text(s)
print(f'patched {p}: dropped .tv64 from ktime_t access ({count} occurrences)')
