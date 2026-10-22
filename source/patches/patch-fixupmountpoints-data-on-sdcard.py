#!/usr/bin/env python3
"""Point DATA_PARTITION at the microSD card instead of real internal storage.

ROOT CAUSE (found 2026-09-23 via a ramdisk content diff against the last
known-good image, `hybris-boot-v2-modemfix-kmsgdiag.img`): the init-script's
`DATA_PARTITION` variable is a build-time template (`%DATA_PART%`, see
`hybris/hybris-boot/Android.mk`'s `HYBRIS_DATA_PART`, derived from the
device's own real Android fstab entry for `/data`) that then gets run
through `hybris/hybris-boot/fixup-mountpoints` -- a static per-device
`by-name -> /dev/sdaN|mmcblkXpY` lookup table, needed because there is no
udev this early in boot to resolve `/dev/block/bootdevice/by-name/*`
symlinks. For `"lilac"`, that table's `userdata` entry says `sda66` -- Sony's
real, correct internal UFS partition for Android's own `/data`. That is
exactly right for a normal hybris installation, and exactly wrong for this
project, which never touches internal storage and runs its entire test
rootfs (`sfos-v2/.stowaways/sailfishos/...`) from the microSD card's
`mmcblk0p2` partition instead.

The very first working image got the right
value the hard way: by hand-editing the *already-built* ramdisk's `init`
after every `m hybris-boot`, never as a source patch. That manual step was
never repeated for any rebuild this session (2026-09-23) -- so every one of
today's six independently-rebuilt "still fails identically" images actually
carried `DATA_PARTITION=/dev/sda66` the whole time, silently pointing `/data`
at internal storage instead of the SD card. (Whether that alone explains the
day's USB-gadget/reboot signature, or whether it's masked by an even earlier
divergence -- see patches/patch-initscript-no-vt-check.py, also found reset
to upstream in the same tree -- is for the next boot test to show; both are
real, independent gaps regardless.)

This patch fixes it at the source instead, so it survives every future
`m hybris-boot` automatically: changes just the one `userdata` line in
`fixup-mountpoints`'s `"lilac")` case from `sda66` to `mmcblk0p2` (the raw
devtmpfs node -- `/dev/block/*` symlinks don't exist yet at this initramfs
stage, per the same working precedent).

Idempotent. Run from the root of this AOSP tree (the directory containing
`hybris/`), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'hybris/hybris-boot/fixup-mountpoints'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()

old = "            -e 's block/bootdevice/by-name/userdata sda66 ' \\\n"
new = "            -e 's block/bootdevice/by-name/userdata mmcblk0p2 ' \\\n"

if new in s:
    print('already patched')
    sys.exit(0)
if old not in s:
    sys.exit("expected lilac case's userdata->sda66 line not found -- fixup-mountpoints may have changed")

# Only touch the one occurrence inside the "lilac" case, not any other
# device's identical-looking line elsewhere in this same file.
marker = '    "lilac")'
idx = s.index(marker)
end = s.index('\n\n    "', idx + 1)  # start of the next case block
block = s[idx:end]
if old not in block:
    sys.exit('userdata->sda66 line not found inside the lilac case block specifically')
patched_block = block.replace(old, new)
s = s[:idx] + patched_block + s[end:]

p.write_text(s)
print(f'patched {p}: lilac userdata now maps to mmcblk0p2 (microSD) instead of sda66 (internal storage)')
