#!/usr/bin/env python3
"""Add the Sailfish/hybris requirements to the lilac 4.14 defconfig.

Carried over from the first port (`sailfishOS-lilac` repo,
`patches/patch-defconfig-414.py`), which derived this same list against the
same file -- `arch/arm64/configs/aosp_yoshino_lilac_defconfig` -- while
building Sony's stock 4.14 source directly. This effort's kernel is
mer-hybris's hybris-patched fork of the identical LA.UM.7.1.r1 tree, and Jolla's patches don't touch this
device's camera/sensor-era defconfig gaps, so the same omissions are present
here verbatim -- confirmed 2026-09-14 by running `mer_verify_kernel_config`
against a fresh build of this tree rather than assumed from the old result.

Original analysis, still accurate: every symbol below is =y in the working
4.4 port's build and missing or =n in the stock 4.14 one.

  AUTOFS4_FS DEVTMPFS DEVTMPFS_MOUNT SYSVIPC   hybris-boot's check_kernel_config refuses
                                              to boot without them -> /diagnosis.log ->
                                              debug session -> sleep 60; reboot -f.
  DUMMY=n                                     same list, on the "must NOT be set" side.
  FHANDLE UTS_NS IPC_NS                       systemd.
  PID_NS USER_NS                              sailjail/firejail; without them clone()
                                              returns EINVAL and no sandboxed app starts.
  BLK_CGROUP                                  systemd's io accounting (4.4 has it).
  BT_HCIVHCI                                  no /dev/vhci -> no HCI adapter -> bluebinder
                                              has nothing to open (10.44).
  USB_CONFIGFS_ECM                            USB networking to the host.

Deliberately NOT carried over:
  CONFIG_VT           -- omitted on 4.4 because VT=y killed that kernel before the
                         initramfs could log; the init-script is patched to drop VT from
                         the mandatory list (patch-initscript-novt.py). 4.14 stock already
                         has it off, so nothing to do.
  NETFILTER_XT_MATCH_QTAGUID -- patch-defconfig.py lists it, but it is ABSENT from the
                         generated 4.4 .config too (unmet dependency), so it has never
                         actually been on. Not replicated here.
  dummycon.c fix      -- that was a typo in LineageOS's tree, and with VT off the file is
                         not compiled at all.

Run from the root of the 4.14 kernel tree, or pass the tree as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
MARK = "# --- Sailfish OS / hybris requirements,md"
if MARK in s:
    print('already patched')
    sys.exit(0)

# The stock file sets some of these to "is not set"; a later "=y" wins in a defconfig,
# but leaving both lines in is confusing, so drop the negations we override.
drop = {
    'CONFIG_AUTOFS4_FS', 'CONFIG_DEVTMPFS', 'CONFIG_SYSVIPC', 'CONFIG_FHANDLE',
    'CONFIG_UTS_NS', 'CONFIG_PID_NS', 'CONFIG_USER_NS', 'CONFIG_BLK_CGROUP',
    'CONFIG_BT_HCIVHCI', 'CONFIG_USB_CONFIGFS_ECM', 'CONFIG_DUMMY',
}
kept = []
removed = 0
for line in s.splitlines():
    if line.startswith('# CONFIG_') and line.endswith(' is not set'):
        sym = line.split()[1]
        if sym in drop:
            removed += 1
            continue
    kept.append(line)

block = '''
# --- Sailfish OS / hybris requirements,md sec.5 ---
# hybris-boot check_kernel_config
CONFIG_SYSVIPC=y
CONFIG_DEVTMPFS=y
CONFIG_DEVTMPFS_MOUNT=y
CONFIG_AUTOFS4_FS=y
# CONFIG_DUMMY is not set
# NB: CONFIG_VT stays off -- the init-script drops it from the mandatory list.

# systemd
CONFIG_FHANDLE=y
CONFIG_UTS_NS=y
CONFIG_IPC_NS=y
CONFIG_BLK_CGROUP=y

# sailjail/firejail: without these clone() returns EINVAL and nothing sandboxed starts
CONFIG_PID_NS=y
CONFIG_USER_NS=y

# bluebinder needs /dev/vhci
CONFIG_BT_HCIVHCI=y

# USB networking to the host
CONFIG_USB_CONFIGFS_ECM=y
'''

p.write_text('\n'.join(kept).rstrip('\n') + '\n' + block)
print(f'patched {p} (dropped {removed} overridden "is not set" lines)')
