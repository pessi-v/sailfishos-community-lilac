#!/usr/bin/env python3
"""Drop the SPMI AHB-bus workaround that reads outside the cnfg mapping. Straight port of the first port's own patches/patch-dts-drop-ahb-wa-414.py --
this device hits the identical bug on this tree too, found via the same technique (matching
the kernel's ramoops geometry to LineageOS's own, then reading /sys/fs/pstore/console-
ramoops-0 after a fastboot-boot fallback).

THE root cause of a 0.3s qpnp_pon panic, decoded from the vmlinux there and confirmed by
inspection here (same driver, same DT property, same missing v2.1 override). In
pmic_arb_base_write():

    if (pmic_arb->ahb_bus_wa) {
        readl_relaxed(pmic_arb->cnfg + SPMI_PROTOCOL_IRQ_STATUS);   // cnfg + 0x6000
        ...
    }

SPMI_PROTOCOL_IRQ_STATUS is 0x6000, but lilac's cnfg region is DT reg <0x800a000 0x3000> --
only 0x3000 mapped. The dummy read lands 0x6000 into a 0x3000 ioremap and faults. ahb_bus_wa
is set solely by the DT property qcom,enable-ahb-bus-workaround, and the very first SPMI
write (qpnp_pon's power-key IRQ set_type, during its probe) trips it -- which is why this
panics before any userspace code runs at all, invisible to every logging mechanism that
depends on the initramfs's own /init ever executing (checkpoint log, systemd units, etc.)
and only visible via ramoops.

The workaround is silicon-revision-specific: Qualcomm's own sdm845-v2.1.dtsi does
`/delete-property/ qcom,enable-ahb-bus-workaround;`, but msm8998-v2.1.dtsi (this device's
own SoC family) never got an equivalent override -- confirmed by reading it directly, it
only `#include`s msm8998-v2.dtsi with no delete-property of its own. Our board is msm8998
**v2.1** (the boot banner reads "SoMC Lilac-ROW(MSM8998 v2.1)"), so the property stays set
for lilac's actual board dts (msm8998-v2.1-yoshino-lilac-sde_generic.dts) even though the
0x6000 offset does not exist in this SoC's cnfg block. Removing the property clears
ahb_bus_wa, so the dummy read is skipped and writes go straight to wr_base.

Removes the single line from msm8998.dtsi. Idempotent. Run from this kernel's root
(kernel/sony/msm-4.14/, one level *above* common-kernel/, matching this repo's other kernel
patches), or pass the tree as argv[1].
"""
import sys, pathlib, re

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'common-kernel/arch/arm64/boot/dts/qcom/msm8998.dtsi'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'lilac: AHB workaround removed' in s:
    print('already patched')
    sys.exit(0)

pat = re.compile(r'^[ \t]*qcom,enable-ahb-bus-workaround;[ \t]*\n', re.M)
if not pat.search(s):
    sys.exit('qcom,enable-ahb-bus-workaround not found in msm8998.dtsi -- re-derive')

s = pat.sub('\t\t/* lilac: AHB workaround removed -- reads cnfg+0x6000 outside the '
            '0x3000 cnfg mapping and panics at qpnp_pon probe */\n',
            s, count=1)
p.write_text(s)
print(f'patched {p}: dropped qcom,enable-ahb-bus-workaround')
