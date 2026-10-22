#!/usr/bin/env python3
"""Drop Venus's unresolvable smmu-vdd-supply so it falls back to a dummy regulator
. Straight port of the first port's own
patches/patch-dts-venus-enable-414.py, simplified: v2 never carried that port's own
intermediate patches/patch-dts-disable-vidc-414.py workaround, so there is no "disabled"
status to undo here -- msm_vidc's node is already status = "ok" in this tree, unmodified.

Root cause (identical on both ports' kernels -- confirmed by reading vmlinux there, and by a
byte-for-byte matching panic here via the same ramoops technique): msm_vidc's DT node names
`smmu-vdd-supply = <&gdsc_bimc_smmu>`, but gdsc_bimc_smmu carries status = "disabled" and
nothing enables it. On a provider that never registers, this kernel's regulator core returns
-EPROBE_DEFER (not -ENODEV), which venus_hfi.c's caller treats as fatal but does not actually
bail on -- it calls regulator_enable(NULL) anyway, a NULL deref at offset 0x18 inside
__enable_regulators, panicking msm_vidc_probe's initcall (kernel_init_freeable, PID 1) at
around t=0.55s, right after the AHB-workaround/qpnp_pon fix clears the earlier 0.3s panic.

Retail 4.4 (this device's own shipped kernel) has the identical DT and driver logic, and
never panics here -- because when a supply property names nothing at all, the regulator core
returns -ENODEV instead, which resolves to a dummy regulator given full constraints. Dropping
the property reproduces exactly that fallback rather than enabling a GDSC Qualcomm ships
disabled on this SoC.

Idempotent. Run from this kernel's root (kernel/sony/msm-4.14/, one level above
common-kernel/), or pass the tree as argv[1].

Not yet investigated here: whether Venus (video encode/decode) actually functions with a
dummy smmu-vdd, or only avoids crashing -- same open question the first port's own patch
docstring flags, worth revisiting once boot reaches userspace.
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'common-kernel/arch/arm64/boot/dts/qcom/msm8998-vidc.dtsi'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'lilac: no smmu-vdd-supply' in s:
    print('already patched')
    sys.exit(0)

old = '\t\tsmmu-vdd-supply = <&gdsc_bimc_smmu>;\n'
if old not in s:
    sys.exit('smmu-vdd-supply line not found -- re-derive the anchor')

new = ('\t\t/* lilac: no smmu-vdd-supply. gdsc_bimc_smmu is status="disabled" here as it\n'
       '\t\t * is on 4.4, and naming an unregistered provider makes this kernel return\n'
       '\t\t * -EPROBE_DEFER where 4.4 fell back to a dummy. Omitting it gives -ENODEV\n'
       '\t\t * -> dummy, i.e. exactly the rail Venus has always had on 4.4.\n'
       '\t\t * */\n')
p.write_text(s.replace(old, new, 1))
print(f'patched {p}: dropped smmu-vdd-supply')
