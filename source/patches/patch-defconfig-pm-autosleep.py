#!/usr/bin/env python3
"""Enable CONFIG_PM_AUTOSLEEP in the lilac 4.14 defconfig, so the phone can suspend.

mce puts the device to sleep by writing "mem" to /sys/power/autosleep once the
display is off and no wakelock is held. That file only exists with
CONFIG_PM_AUTOSLEEP; SODP leaves it off because Android's suspend HAL drives
/sys/power/state itself. Without it the phone never suspended at all (0
suspends in a 9-hour night, 50-600 mA idle draw). Hybris's reference defconfig
delta sets it too.

Manual suspend on the running kernel was verified first: devices, noirq and
CPU stages all complete and it resumes on an RTC alarm, once WoWLAN is
configured (see lilac-wlan-wowlan.sh).

Idempotent. Run from the 4.14 kernel root (common-kernel), or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'CONFIG_PM_AUTOSLEEP=y' in s:
    print('already applied')
    sys.exit(0)
s = s.replace('# CONFIG_PM_AUTOSLEEP is not set\n', '')
if not s.endswith('\n'):
    s += '\n'
s += 'CONFIG_PM_AUTOSLEEP=y\n'
p.write_text(s)
print('applied: CONFIG_PM_AUTOSLEEP=y')
