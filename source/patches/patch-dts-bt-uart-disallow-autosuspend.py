#!/usr/bin/env python3
"""Add `qcom,disallow-autosuspend;` to lilac's Bluetooth UART node (BLSP1 UART3,
`uart@c171000` in `msm8998-yoshino-common.dtsi` -- confirmed by the adjacent GPIO comments,
`BT_HCI_UART_TXD/RXD/CTS_N/RFR_N`).

Root cause of the intermittent `chip_ver: 0x0/INVALID_CHIP_VERSION` Bluetooth init failure
(confirmed real firmware, real vendor libraries, real chip -- §83/§84 already ruled all of
that out; a genuinely clean, untouched boot still failed 8/8 consecutive automatic retries,
ruling out rapid-restart/settle-time theories too). The vendor HAL's own logcat shows
`InitTransport: opening /dev/ttyHS0` succeeding, then `CleanUp: send out shutdown signal`
~30ms later with no valid chip response -- and the kernel's own `msm_serial_hs.c` exports a
`MSM_HS_WARN("%s(): Clocks are off\\n", ...)` from exactly the modem-control/RX/TX paths
(`msm_hs_set_mctrl_locked()` et al.) that fires whenever `msm_uport->pm_state !=
MSM_HS_PM_ACTIVE` -- i.e. userspace touches the port before the runtime-PM resume (which
enables real clocks/regulators, not instant) has actually completed. The sibling porting
attempt's own notes independently hit the identical symptom on a different kernel line
(`msm_hs_set_mctrl_locked(): Clocks are off`, every attempt) and did not chase it further.

This UART's own node sets `qcom,inject-rx-on-wakeup;`/`qcom,rx-char-to-inject = <0xFD>;` --
confirming autosuspend is expected and normally handled by injecting a synthetic wake-marker
byte (0xFD, the same byte the sibling repo's own strace saw as the chip's "one byte" reply --
not a real chip response, the driver's own placeholder) rather than genuinely never
suspending. That marker fires immediately on wake, but nothing guarantees the *real* runtime-
PM resume (clocks, regulators, GPIO reset -- inherently slow, sleeping operations) has
finished by the time the userspace vendor HAL's very next write/ioctl lands, which is exactly
the shape of bug this whole investigation has been chasing: intermittent, timing-dependent,
narrower on some boots than others.

The exact same kernel tree already carries the fix for a structurally identical problem on a
different Sony device (`ebeb78e0aea7 tty: msm_serial_hs: Implement no-autosuspend mechanism
for SoMC Blanc`, already merged here) -- a `CONFIG_MACH_SONY_BLANC`-gated in-driver change
plus a devicetree-driven `qcom,disallow-autosuspend` property
(`msm_uport->no_autosuspend = of_property_read_bool(..., "qcom,disallow-autosuspend")`) that
keeps that port's clocks permanently active rather than autosuspending between uses. Blanc's
own commit message: "this port needs to never get autosuspended to avoid connection drops and
scheduling while atomic bugs" -- the same failure class, on a different peripheral. This
patch applies the devicetree half of that same mechanism to lilac's own Bluetooth UART node
(the driver-side `of_property_read_bool()` call is unconditional, not gated behind
`CONFIG_MACH_SONY_BLANC`, so no C code change is needed here -- confirmed by reading
`msm_hs_probe()` directly).

Not yet confirmed working on real hardware -- needs a real kernel rebuild + `fastboot boot`
to test, unlike everything else fixed so far this session.

Idempotent. Run from this kernel's root (kernel/sony/msm-4.14/, one level *above*
common-kernel/, matching this repo's other kernel patches), or pass the tree as argv[1].
"""
import sys, pathlib, re

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'common-kernel/arch/arm64/boot/dts/qcom/msm8998-yoshino-common.dtsi'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'qcom,disallow-autosuspend' in s:
    print('already patched')
    sys.exit(0)

pat = re.compile(
    r'(uart@c171000 \{ /\* BLSP1 UART3 \*/\n'
    r'\t\tqcom,clk-freq-out = <4000000>;\n)'
    r'(\t\tstatus = "okay";\n)'
)
if not pat.search(s):
    sys.exit('BLSP1 UART3 node not found in the expected shape -- re-derive')

replacement = (
    '\\g<1>'
    '\t\t/* lilac: keep clocks active across the BT chip wake/sleep (IBS) cycling --\n'
    '\t\t * same mechanism as ebeb78e0aea7 (CONFIG_MACH_SONY_BLANC) elsewhere in this\n'
    '\t\t * tree, applied here instead of there. */\n'
    '\t\tqcom,disallow-autosuspend;\n'
    '\\g<2>'
)
s = pat.sub(replacement, s, count=1)
p.write_text(s)
print(f'patched {p}: added qcom,disallow-autosuspend to BLSP1 UART3 (Bluetooth)')
