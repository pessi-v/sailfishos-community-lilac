#!/usr/bin/env python3
"""Stop the fingerprint HAL build from installing its own VINTF manifest
fragment -- it conflicts with a static declaration that's already there.

Once logd was fixed enough to get real logcat output for the first time in
this project, this showed up immediately:

    hwservicemanager: getDeviceHalManifest: VINTF parse error: Cannot add
    manifest fragment
    /vendor/etc/vintf/manifest/android.hardware.biometrics.fingerprint.xml:
    HAL "android.hardware.biometrics.fingerprint" has a conflict.

This wasn't a narrow fingerprint-only problem: a failing
getDeviceHalManifest() call fails HAL lookups for the *entire* device, which
explains a big chunk of the unrelated "Cannot find entry ... in either
framework or device manifest" cascade also visible in that first real log
(sensors, audio, the QTI display allocator, etc.).

Root cause: `device/sony/common/vintf/manifest.xml` -- Sony's own shared
manifest for the whole yoshino/common device family, declared
unconditionally regardless of whether a given device actually builds the
fingerprint HAL -- already declares
android.hardware.biometrics.fingerprint@2.1::IBiometricsFingerprint/default,
byte-for-byte identical to the fragment this HAL's own Android.mk
(LOCAL_VINTF_FRAGMENTS) additionally installs to
/vendor/etc/vintf/manifest/. Two declarations of the same instance is a
conflict, not a merge.

That common manifest is shared with other devices in the family and isn't
ours to edit. The redundant side is this HAL's own
LOCAL_VINTF_FRAGMENTS line (vendor/oss/fingerprint/Android.mk) -- dropping
it stops the duplicate fragment from being installed at all; the HAL is
still fully declared via the common manifest.

Idempotent. Run from the tree root, or pass it as argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
p = root / 'vendor/oss/fingerprint/Android.mk'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'LOCAL_VINTF_FRAGMENTS' not in s:
    print('already patched')
    sys.exit(0)

old = 'LOCAL_VINTF_FRAGMENTS := android.hardware.biometrics.fingerprint.xml\n'
if s.count(old) != 1:
    sys.exit(f'anchor count: {s.count(old)} -- re-derive against current source')
s = s.replace(old, '')

p.write_text(s)
print(f'patched {p}: dropped the duplicate VINTF manifest fragment '
      f'(device/sony/common/vintf/manifest.xml already declares this HAL)')
