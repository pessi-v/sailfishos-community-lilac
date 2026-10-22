#!/usr/bin/env python3
"""Tolerate exactly one known mer_verify_kernel_config error: CONFIG_VT.

droid-hal-device's build step (rpm/dhd/droid-hal-device.inc) re-runs
mer_verify_kernel_config against the real kernel .config and treats ANY
"ERROR:" line as fatal, with no skip macro. Build 2026-09-14 against this
port's kernel found exactly one: CONFIG_VT is invalid.

CONFIG_VT is left off deliberately (see patches/patch-defconfig-sailfish-reqs.py)
-- the first port found VT=y crashes
this hardware's display before the initramfs can even log anything, and this
kernel already ships with it off by default. Re-enabling it to satisfy this
check would risk reintroducing that crash.

Unlike the first port (which also had to tolerate a QTAGUID gap -- not present
here, this kernel's defconfig already has CONFIG_NF_NAT_IPV4 and friends), only
CONFIG_VT needs an exception. Deliberately NOT "|| true": any other error still
fails the build.

Idempotent. Run from the repo-synced tree root (rpm/dhd must already be
cloned), or pass the tree root as argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'rpm/dhd/droid-hal-device.inc'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
marker = 'tolerating known-deliberate CONFIG_VT error'
if marker in s:
    print('already patched')
    sys.exit(0)

old = '''echo Verifying kernel config
# AOSP seems to use .../obj/kernel/.config not obj/KERNEL_OBJ/.config like CM : so wildcard it
hybris/mer-kernel-check/mer_verify_kernel_config \\
    %{android_root}/out/target/product/%{device}/obj/*/.config'''

new = '''echo Verifying kernel config
# AOSP seems to use .../obj/kernel/.config not obj/KERNEL_OBJ/.config like CM : so wildcard it
# Sailfish OS lilac-v2 port: tolerate exactly one known error, CONFIG_VT --
# left off deliberately (see patches/patch-defconfig-sailfish-reqs.py).
# Deliberately NOT "|| true": any other error still fails the build.
set +e
hybris/mer-kernel-check/mer_verify_kernel_config \\
    %{android_root}/out/target/product/%{device}/obj/*/.config > tmp/mkc.out 2>&1
mkc_rc=$?
set -e
cat tmp/mkc.out
if [ $mkc_rc -ne 0 ]; then
    mkc_other=$(grep -c "^ERROR" tmp/mkc.out || true)
    mkc_known=$(grep "^ERROR" tmp/mkc.out | grep -c "CONFIG_VT is invalid" || true)
    if [ "$mkc_other" != "$mkc_known" ]; then
        echo "mer_verify_kernel_config: errors beyond CONFIG_VT -- failing"
        grep "^ERROR" tmp/mkc.out | grep -v "CONFIG_VT is invalid"
        exit 1
    fi
    echo "NOTE: tolerating known-deliberate CONFIG_VT error"
fi'''

if old not in s:
    sys.exit('expected mer_verify_kernel_config block not found -- droid-hal-device.inc may have changed')

p.write_text(s.replace(old, new))
print(f'patched {p}: tolerate CONFIG_VT only')
