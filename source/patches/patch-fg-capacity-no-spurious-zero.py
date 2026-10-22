#!/usr/bin/env python3
"""qpnp-fg-gen3: never report a bogus capacity of 0 (or no capacity) while the battery is healthy.

Symptom: at 81 % charge mce suddenly logged
    mcebat_update(): battery_level : 81 -> 0
and DSME started "Battery empty shutdown in 8 seconds" (cancelled 0.2 s later when the next read
returned 81 again), which also plays the low-battery alarm. It happened on the display waking from
suspend. The fuel gauge's SRAM interface is flaky on this board: the same boot logged
    FG: fg_direct_mem_request: wait for mem_grant timed out
    Error in reading SRAM address 0x60[0], rc=-110 ... fg_get_charge_counter: Error in getting CC_SOC_SW
so a capacity read can fail or yield 0 transiently.

Fix, in fg_psy_get_property() for POWER_SUPPLY_PROP_CAPACITY: if the read fails, or returns 0 while
the cached last_soc is non-zero and the battery voltage is more than 250 mV above the cutoff voltage,
return last_soc. A genuinely empty battery (low voltage) still reports 0.

Idempotent. Run from the 4.14 kernel root (common-kernel), or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/power/supply/qcom/qpnp-fg-gen3.c'
if not p.is_file():
    sys.exit(f'not found: {p}')
s = p.read_text()
if 'lilac: spurious capacity 0' in s:
    print('already applied')
    sys.exit(0)

old = '''	case POWER_SUPPLY_PROP_CAPACITY:
		rc = fg_get_prop_capacity(fg, &pval->intval);
		break;
'''
new = '''	case POWER_SUPPLY_PROP_CAPACITY:
		rc = fg_get_prop_capacity(fg, &pval->intval);
		/* lilac: spurious capacity 0 / failed read (flaky FG SRAM access) must not look like
		 * an empty battery to mce/DSME; keep the last known value while the voltage is healthy. */
		if (fg->last_soc > 0 && (rc < 0 || pval->intval == 0)) {
			int vbatt_uv;

			if (rc < 0 || (!fg_get_battery_voltage(fg, &vbatt_uv) &&
				vbatt_uv > (chip->dt.cutoff_volt_mv + 250) * 1000)) {
				pval->intval = fg->last_soc;
				rc = 0;
			}
		}
		break;
'''
assert s.count(old) == 1
p.write_text(s.replace(old, new, 1))
print('applied')
