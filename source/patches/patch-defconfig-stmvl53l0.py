#!/usr/bin/env python3
"""Enable the VL53L0 laser ranging (ToF / laser AF) sensor in the lilac 4.14 defconfig.

The chip is fully described in the device tree (`tof_sensor@29` on i2c@c1b6000,
compatible "st,stmvl53l0", with tof_avdd/vdd supplies, reset GPIO 27 and IRQ GPIO 22;
lilac even overrides it in msm8998-yoshino-lilac_common.dtsi) and the driver
source is in the tree (drivers/input/misc/vl53L0/), but SODP's
aosp_yoshino_lilac_defconfig leaves CONFIG_INPUT_STMVL53L0 unset -- SODP enables
it only for loire/tone. LineageOS's lilac kernel (whatawurst, lineage-21) sets
CONFIG_INPUT_STMVL53L0=y.

This enables the plain-I2C variant, which is what our device tree describes; it
gives a working distance sensor. INPUT_STMVL53L0_SOMC_PARAMS defaults to y.
Stock Sony and LineageOS build the camera-CCI variant instead (their vl53L0
Makefile hard-codes -DCAMERA_CCI and adds camera_v2 include paths), which is
most likely how Sony's camera blobs get ToF data for laser-assisted AF -- not
done here.

Idempotent. Run from the 4.14 kernel root (common-kernel), or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'CONFIG_INPUT_STMVL53L0=y' in s:
    print('already applied')
    sys.exit(0)
s = s.replace('# CONFIG_INPUT_STMVL53L0 is not set\n', '')
if not s.endswith('\n'):
    s += '\n'
s += 'CONFIG_INPUT_STMVL53L0=y\n'
p.write_text(s)
print('applied: CONFIG_INPUT_STMVL53L0=y')
