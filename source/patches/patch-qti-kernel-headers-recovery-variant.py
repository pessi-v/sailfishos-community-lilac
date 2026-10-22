#!/usr/bin/env python3
"""Add the missing recovery-image Soong variant to qti_kernel_headers_4.14.

Build break found 2026-09-14 attempting `m hybris-hal`:

    error: kernel/sony/qti-headers/Android.bp:33:1: dependency
    "qti_kernel_headers_4.14" of "qti_kernel_headers" missing variant:
      os:android, image:recovery, arch:arm64_armv8-a, sdk:
    available variants:
      os:android, image:, ...
      os:android, image:vendor.30, ...

`kernel/sony/qti-headers/Android.bp` defines `qti_kernel_headers` with
`recovery_available: true`, and a Go LoadHook (kernel_headers.go) makes it
depend on `qti_kernel_headers_4.14` (the actual headers, from
kernel/sony/msm-4.14/common-headers/Android.bp) via `header_libs`. Soong
requires every header_libs dependency of a recovery_available module to
itself be recovery_available, so it can build a matching recovery-image
variant -- but `qti_kernel_headers_4.14` only declares `vendor_available`.
Simply missing from Sony's source; the export_include_dirs are the same
headers regardless of image variant, so recovery_available is safe to add.

Idempotent. Run from the kernel root, or pass the tree as argv[1] --
NOTE: this touches kernel/sony/msm-4.14/common-headers, a sibling checkout
to the kernel itself, not the kernel tree proper.
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'kernel/sony/msm-4.14/common-headers/Android.bp'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'recovery_available' in s:
    print('already patched')
    sys.exit(0)

old = '    vendor_available: true,\n    export_include_dirs: ["kernel-headers"],'
new = '    vendor_available: true,\n    recovery_available: true,\n    export_include_dirs: ["kernel-headers"],'
if old not in s:
    sys.exit('expected pattern not found -- re-derive against current source')

p.write_text(s.replace(old, new))
print(f'patched {p}: added recovery_available: true')
