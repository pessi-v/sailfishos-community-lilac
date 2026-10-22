#!/usr/bin/env python3
"""Disable CONFIG_IOMMU_DEBUG, CONFIG_IOMMU_DEBUG_TRACKING, and CONFIG_IOMMU_TESTS
in the lilac defconfig, matching LineageOS's own working config for this device.

Found 2026-09-28 while chasing a real photo-capture
bug: JPEG hardware encoding fails on every attempt with

    msm_cam_smmu soc:qcom,cam_smmu:msm_cam_smmu_cb5: No iommu associated with device
    CAM-SMMU cam_smmu_attach_device:535 Error: ARM IOMMU attach failed. ret = -22

-- cb4/cb5 (jpeg_enc0/jpeg_dma, the two IOMMU context banks JPEG hardware needs)
never get a real Linux iommu_group at all, while every other camera context bank
(cb1-cb3, backing preview/VFE/CPP) does. Traced two levels deep into the actual
driver source (system/.../cam_smmu_api.c, drivers/iommu/arm-smmu.c) without
finding a definitive single cause -- the device tree is symmetric across all
five context banks,
and the driver logic that processes them is identical for all five.

The sibling porting attempt (xperia-xz1-compact-lilac-sailfishos, a separate,
independent project) did an extensive investigation of a *different* camera
JPEG bug years earlier and confirmed directly, on real hardware: "the device
tree is eliminated as a cause -- our kernel sees exactly the camera hardware
description LineageOS's does" and "the rear camera works on LineageOS -- a
2.7 MB JPEG, same hardware, same vendor blobs, same device tree" -- i.e. this
exact SoC/board's JPEG hardware, on this exact device tree, is known to work
correctly under a real, working kernel (LineageOS's own).

Compared this port's own shipped kernel config (patches/kernel-config/
lilac-shipped.config) against LineageOS lilac's own defconfig
(whatawurst/android_kernel_sony_msm8998, lineage-21 branch,
arch/arm64/configs/lineage-msm8998-yoshino-lilac_defconfig) for every
SMMU/IOMMU-related option. Nearly all match; three don't, all three enabled on
this port's kernel and *not* on LineageOS's:

    CONFIG_IOMMU_DEBUG=y
    CONFIG_IOMMU_DEBUG_TRACKING=y
    CONFIG_IOMMU_TESTS=y

Confirmed these are genuinely SODP's own baseline, not something this project's
own patches turned on -- `git show HEAD~5:arch/arm64/configs/
aosp_yoshino_lilac_defconfig` (before any of this project's defconfig patches
apply) already has all three. Live evidence CONFIG_IOMMU_TESTS is doing real
work at boot, not just exposing an unused debugfs knob: dmesg shows
`iommu: Adding device soc:iommu_test_device to group 4` and
`soc:iommu_coherent_test_device to group 5` -- two IOMMU groups consumed by
self-test devices before any real hardware IOMMU client gets one, on every
single boot. Not proven that these three options are the actual cause of the
cb4/cb5 failure -- the mechanism inside the arm-smmu driver by which
IOMMU_DEBUG/IOMMU_TESTS could affect real device group assignment wasn't
traced -- but they're the only concrete, evidenced difference found between a
kernel that's confirmed to get real JPEG capture working on this exact
hardware/device-tree and this port's own, and they're debug/test-only options
this port has no use for regardless of outcome.

Idempotent. Run from the root of the kernel tree (the directory containing
arch/arm64/configs/), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()

replacements = [
    ('CONFIG_IOMMU_DEBUG=y\n', '# CONFIG_IOMMU_DEBUG is not set\n'),
    ('CONFIG_IOMMU_DEBUG_TRACKING=y\n', '# CONFIG_IOMMU_DEBUG_TRACKING is not set\n'),
    ('CONFIG_IOMMU_TESTS=y\n', '# CONFIG_IOMMU_TESTS is not set\n'),
]

already = sum(1 for _, new in replacements if new in s)
if already == len(replacements):
    print('already applied')
    sys.exit(0)

applied = 0
for old, new in replacements:
    if old in s:
        s = s.replace(old, new)
        applied += 1
    elif new in s:
        pass  # already disabled
    else:
        sys.exit(f'expected line not found and not already disabled: {old.strip()!r} -- defconfig may have changed')

p.write_text(s)
print(f'patched {p}: disabled CONFIG_IOMMU_DEBUG, CONFIG_IOMMU_DEBUG_TRACKING, CONFIG_IOMMU_TESTS ({applied} newly changed)')
