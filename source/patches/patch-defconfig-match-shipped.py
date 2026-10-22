#!/usr/bin/env python3
"""Make aosp_yoshino_lilac_defconfig reproduce the kernel this port actually ships.

Found while enabling the VL53L0 ToF sensor: running
`make aosp_yoshino_lilac_defconfig` on the patched tree did NOT reproduce the
running kernel's .config. Three options differed from SODP's defconfig lines:

  defconfig (SODP original)            running, validated kernel
  CONFIG_CC_STACKPROTECTOR_REGULAR=y   CONFIG_CC_STACKPROTECTOR_NONE=y
  CONFIG_COMPAT_VDSO=y                 # CONFIG_COMPAT_VDSO is not set
  (default follows COMPAT_VDSO)        CONFIG_ARM_ARCH_TIMER_VCT_ACCESS=y

The running kernel's values came from undocumented hand edits to the build
directory's .config (COMPAT_VDSO most likely from section 42's temporary
workaround); every test in this project ran on them, so the defconfig now
records them. Turning stack protection or COMPAT_VDSO back on is a separate change that needs its own
boot test (section 42 saw config drift of this kind break user sessions).

Also drops SODP's `CONFIG_DUMMY=y`, which our Sailfish requirements already
override further down with `# CONFIG_DUMMY is not set` (mer's kernel check
wants it off); the duplicate only produced an "override" warning.

Verified: after this patch, `make aosp_yoshino_lilac_defconfig` produces a
.config identical to the shipped kernel's (plus CONFIG_INPUT_STMVL53L0 from
patch-defconfig-stmvl53l0.py).

Idempotent. Run from the 4.14 kernel root (common-kernel), or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

lines = p.read_text().split('\n')
changes = {
    'CONFIG_CC_STACKPROTECTOR_REGULAR=y': 'CONFIG_CC_STACKPROTECTOR_NONE=y',
    'CONFIG_COMPAT_VDSO=y': '# CONFIG_COMPAT_VDSO is not set',
}
out = []
changed = 0
for line in lines:
    if line in changes:
        out.append(changes[line])
        changed += 1
    elif line == 'CONFIG_DUMMY=y':
        changed += 1
    else:
        out.append(line)
if 'CONFIG_ARM_ARCH_TIMER_VCT_ACCESS=y' not in out:
    # its default follows COMPAT_VDSO, so with that off it must be set explicitly
    out.insert(out.index('# CONFIG_COMPAT_VDSO is not set') + 1, 'CONFIG_ARM_ARCH_TIMER_VCT_ACCESS=y')
    changed += 1
if changed:
    p.write_text('\n'.join(out))
    print(f'applied: {changed} line(s) changed')
else:
    print('already applied')
