#!/usr/bin/env python3
"""Enable Bluetooth RFCOMM, BNEP and HIDP in the lilac 4.14 defconfig.

SODP's aosp_yoshino_lilac_defconfig leaves them unset, so bluetoothd cannot open any RFCOMM
socket: at every start it logs "RFCOMM server failed for Phone Book Access / Object Push:
socket(STREAM, RFCOMM): Protocol not supported (93)". RFCOMM carries the headset profiles
(HSP/HFP, so Bluetooth headset calls), OBEX (file transfer, phonebook access) and serial
profiles; BNEP is Bluetooth tethering/PAN; HIDP is Bluetooth keyboards and mice.
A2DP audio does not need them, which is why audio streaming already worked.

Idempotent. Run from the 4.14 kernel root (common-kernel), or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

wanted = [
    'CONFIG_BT_RFCOMM=y',
    'CONFIG_BT_RFCOMM_TTY=y',
    'CONFIG_BT_BNEP=y',
    'CONFIG_BT_BNEP_MC_FILTER=y',
    'CONFIG_BT_BNEP_PROTO_FILTER=y',
    'CONFIG_BT_HIDP=y',
]
s = p.read_text()
lines = [l for l in s.splitlines()
         if not any(l == '# %s is not set' % w[:-2] for w in wanted)]
have = set(lines)
added = [w for w in wanted if w not in have]
if not added:
    print('already applied')
    sys.exit(0)
lines += added
p.write_text('\n'.join(lines) + '\n')
print('applied:', ' '.join(added))
