#!/usr/bin/env python3
"""Make this kernel's ramoops layout byte-compatible with LineageOS's (the "pull the pstore panic" work, and the first port's own patches/patch-dts-ramoops-414.py,
which this is a straight port of onto this tree's own kernel path).

This device has no serial console, so when a `fastboot boot` of an experimental kernel
crashes the whole device, it falls back to the real LineageOS install and takes its panic
with it (see [[lilac-lineageos-side-access]]). ramoops is the way back: the kernel's console
output lives in a reserved DRAM region (`ramoops@ffc00000`, from Qualcomm's own
msm8998-yoshino-common.dtsi) that survives a warm reset, and the *next* kernel to boot can
read it out at /sys/fs/pstore/ -- but only if both kernels carve up that same 1 MB region
the same way. This v2 kernel's DTS (nested one level deeper than the first port's own kernel
tree: kernel/sony/msm-4.14/common-kernel/arch/arm64/boot/dts/qcom/, not
arch/arm64/boot/dts/qcom/ directly) ships Sony's original AOSP sizing, byte-for-byte
identical to what the first port found and fixed:

    zone          LineageOS   this kernel (before)
    record-size    0x1000        0x10000
    console-size  0x40000        0x60000
    ftrace-size        0         0x10000
    pmsg-size          0         0x20000
    ecc-size           0             16

fs/pstore/ram.c lays the zones out in a fixed order (dump records first, filling
region-console-ftrace-pmsg, then console, then ftrace, then pmsg), so different sizes put
this kernel's console zone at a different physical offset than the one LineageOS's driver
reads from -- the log comes back absent rather than garbage. Matching LineageOS's geometry
makes a failed boot's console log actually readable from the LineageOS side afterward.

⚠️ Only captures panics after pstore_init() runs. A failure earlier leaves nothing -- absence
of a log is then itself evidence.

Idempotent. Run from the root of this kernel tree (kernel/sony/msm-4.14/), or pass the tree
as argv[1] -- note this is one level *above* common-kernel/, matching how the rest of this
repo's kernel patches address it.
"""
import sys, pathlib, re

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'common-kernel/arch/arm64/boot/dts/qcom/msm8998-yoshino-common.dtsi'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
MARK = '/* lilac: LineageOS-compatible ramoops geometry'
if MARK in s:
    print('already patched')
    sys.exit(0)

m = re.search(r'(\t\tramoops@ffc00000 \{.*?\n\t\t\};\n)', s, re.S)
if not m:
    sys.exit('ramoops@ffc00000 node not found -- tree changed, re-derive the anchor')

old = m.group(1)
new = '''\t\t/* lilac: LineageOS-compatible ramoops geometry, so a failed boot's console
\t\t * log can be read back from LineageOS at /sys/fs/pstore/ afterward.
\t\t * This kernel's own sizes were record 0x10000 / console 0x60000 /
\t\t * ftrace 0x10000 / pmsg 0x20000 / ecc 16.
\t\t */
\t\tramoops@ffc00000 {
\t\t\tcompatible = "removed-dma-pool", "ramoops";
\t\t\tno-map;
\t\t\treg = <0 0xffc00000 0 0x00100000>;
\t\t\trecord-size = <0x1000>;
\t\t\tconsole-size = <0x40000>;
\t\t\tftrace-size = <0x0>;
\t\t\tpmsg-size = <0x0>;
\t\t\tecc-size = <0x0>;
\t\t};
'''
p.write_text(s.replace(old, new, 1))
print(f'patched {p}: ramoops geometry now matches LineageOS')
