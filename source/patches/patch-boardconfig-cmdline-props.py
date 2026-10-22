#!/usr/bin/env python3
"""Add five kernel cmdline properties to `device/sony/lilac/BoardConfig.mk` that
every plain `m hybris-boot` build has always been missing.

`device/sony/lilac/BoardConfig.mk` only ever sets `androidboot.hardware=lilac`
via `BOARD_KERNEL_CMDLINE +=`. Comparing the known-good, already-working
`hybris-boot-v2-modemfix-kmsgdiag.img`'s own boot image header (parsed directly,
no external tool needed -- the Android boot image header is a small, fixed
layout) against every fresh `m hybris-boot` build done this session found five
properties present in the working image and absent from every fresh one:

    androidboot.mode=normal
    androidboot.configfs=true
    androidboot.usbcontroller=a800000.dwc3
    data_subdir=sfos-v2
    jolla.test_mode=USER

Two of these are directly relevant to a real, independent bug this session hit
while chasing something else entirely: `androidboot.configfs=true` and
`androidboot.usbcontroller=a800000.dwc3` are the hints init needs to configure
the USB gadget via configfs on this specific controller -- without them, the
`configfs-gadget a800000.dwc3` USB debug interface this whole project's own
`lilac-usbnet.sh` depends on for SSH access is worse off (a real, if not fully
proven, contributing factor to a USB gadget bring-up failure captured the same
session, ~t=12s, `failed to start g1: -22`). `androidboot.mode=normal` matters
independently: without it, the bootloader's own `androidboot.mode=charger`
(appended to every cmdline whenever the device is powered from USB, which
`fastboot boot` always is) takes over unopposed, offlining 7 of the SoC's 8
cores for the whole boot -- the sibling porting attempt's own notes (their
section 10.181) already documented this exact mechanism and fix once.

Note: adding these five properties alone did
**not** resolve the USB-gadget/reboot bug this session was actually chasing --
a properly rebuilt image with all five present still failed identically. Keep
this patch anyway; it is a real, independent, verified-correct fix (confirmed
by parsing the rebuilt image's own header) for a real gap, whether or not it
turns out to be part of the bigger bug's own explanation.

Idempotent. Run from the root of this AOSP tree (the directory containing
`device/`), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'device/sony/lilac/BoardConfig.mk'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
MARK = '# lilac-v2 change 92'
if MARK in s:
    print('already patched')
    sys.exit(0)

PROPS = [
    'androidboot.mode=normal',
    'androidboot.configfs=true',
    'androidboot.usbcontroller=a800000.dwc3',
    'data_subdir=sfos-v2',
    'jolla.test_mode=USER',
]

block = (
    f'\n{MARK}: these five properties are present in the known-good\n'
    '# hybris-boot-v2-modemfix-kmsgdiag.img (built via a manual/scripted repack process\n'
    '# outside m hybris-boot) but were never added here, so every m hybris-boot build\n'
    '# silently ships without them -- see the patch script docstring for the full story.\n'
    + ''.join(f'BOARD_KERNEL_CMDLINE += {prop}\n' for prop in PROPS)
)

p.write_text(s.rstrip('\n') + '\n' + block)
print(f'patched {p}: added {len(PROPS)} cmdline properties')
