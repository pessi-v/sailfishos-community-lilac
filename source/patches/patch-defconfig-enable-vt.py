#!/usr/bin/env python3
"""Enable CONFIG_VT -- tested working on THIS kernel, unlike the 4.4 one.

The "VT=y crashes this hardware" finding (patch-defconfig-sailfish-reqs.py's
"Deliberately NOT carried over" section) was made on the first port's older
4.4 kernel. It was never actually retested on 4.14: Sony's stock 4.14
defconfig already ships CONFIG_VT off, so that assumption just carried
forward untested. Tested directly on this port's kernel 2026-09-15 (in the
course of debugging why hybris-boot's own check_kernel_config -- a THIRD,
independent place this same requirement is checked, see
patch-initscript-no-vt-check.py -- was diverting the boot into a debug
fallback): enabling CONFIG_VT here does not crash the display. The initial
dark-screen boot (systemd starts, power button/backlight responds) has an
unrelated cause under investigation, not VT.

Given this, prefer keeping CONFIG_VT on and patch-initscript-no-vt-check.py
unnecessary going forward -- though harmless to leave applied if already
present (check_kernel_config's requirement is then simply satisfied for
real, and the patch just skips a check that would have passed anyway).

Idempotent. Run from the root of the 4.14 kernel tree, or pass the tree as
argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if '\nCONFIG_VT=y\n' in s:
    print('already patched')
    sys.exit(0)

old = '# CONFIG_VT is not set'
if old not in s:
    sys.exit('expected "# CONFIG_VT is not set" line not found -- defconfig may have changed')

p.write_text(s.replace(old, 'CONFIG_VT=y', 1))
print(f'patched {p}: CONFIG_VT=y')
