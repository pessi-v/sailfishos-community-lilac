#!/usr/bin/env python3
"""Enable the RGBC-IR (tcs3490) sensor in the lilac 4.14 defconfig.

Carried over unmodified from the first port's
`patch-defconfig-rgbcir-tcs3490-414.py`.
The symptom this fixes only shows up once a camera HAL is actually running
against this kernel, which this effort hasn't reached yet -- included now
because the underlying defconfig gap is identical and cheap to close early.
⚠️ This script anchors on `CONFIG_SONY_CAM_V4L2` or `CONFIG_MSMB_CAMERA`
already being =y; if neither is present yet in this tree's defconfig it
exits cleanly with "no camera anchor" rather than guessing -- that's a
signal the camera driver backport work (10.178/10.179 in the first port)
hasn't been redone here yet, not a bug in this script.

Original analysis, still accurate:

With Sony's sensor driver (10.178) and the media-controller legacy ABI (10.179)
in place, both cameras probe and libcammw's V4l2Mgr connects, yet the HAL still
counts zero cameras. Tracing the running provider shows the ONLY failure before
the count is:

    openat("/sys/devices/virtual/input/rgbcir_sensor/chip_pow") = -1 ENOENT  (x2)
    E cammw: readIntAttr: Open faild                                          (x2)
    I camera-hal: module_api_get_number_of_cameras: num 0

and, tellingly, the provider never reads /sys/devices/sony_camera_N/info at all
-- excalibur's System init aborts at the RGBC-IR read, before it enumerates
sensors, so getNumberOfCameras returns its zero-initialised count.

That sysfs path is created by the AMS tcs3490 RGBC-IR driver
(RGBCIR_SENSOR_SYSFS_LINK_NAME, DEVICE_ATTR(chip_pow)). The driver source and
the `tcs3490@72` DT node are BOTH already present in Sony's 4.14 tree, and its
I2C dependency is met (CONFIG_I2C_MSM_V2=y). Only the defconfig switch is
missing -- the same omission class as the sony_camera driver itself (10.178) and
the ION heaps (10.142). Sony's own 4.4 lineage config sets CONFIG_SENSORS_TCS3490=y.

The RGBC-IR sensor is a genuine part of the XZ1 camera subsystem (auto white
balance / flicker), so this is restoring shipped behaviour, not a workaround.

Idempotent. Run from the 4.14 kernel root, or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'CONFIG_SENSORS_TCS3490' in s:
    print('already patched')
    sys.exit(0)

# Anchor on the sony camera switch, which this defconfig already carries and
# which is the nearest logically-related entry.
anchor = 'CONFIG_SONY_CAM_V4L2=y'
if anchor not in s:
    # Fall back to a stable, always-present symbol.
    anchor = 'CONFIG_MSMB_CAMERA=y'
if anchor not in s:
    sys.exit('no camera anchor in defconfig -- re-derive')

block = (anchor + '\n'
         '# lilac 10.180: the AMS tcs3490 RGBC-IR sensor. excalibur\'s camera\n'
         '# HAL reads /sys/devices/virtual/input/rgbcir_sensor/chip_pow during\n'
         '# init and aborts (num 0 cameras) if it is absent. Driver source and\n'
         '# the tcs3490@72 DT node are already in the tree; only this switch was\n'
         '# dropped from the 4.14 defconfig (present in Sony\'s 4.4 config).\n'
         'CONFIG_SENSORS_TCS3490=y')
s = s.replace(anchor, block, 1)
p.write_text(s)
print(f'patched {p}: CONFIG_SENSORS_TCS3490=y')
