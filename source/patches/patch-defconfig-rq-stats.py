#!/usr/bin/env python3
"""Enable CONFIG_QCOM_RUN_QUEUE_STATS in the lilac 4.14 defconfig, so vendor.msm_irqbalance can run.

The Sony oem blob's /odm/bin/msm_irqbalance waits between balancing rounds on
/sys/devices/system/cpu/cpu0/rq-stats/def_timer_ms. That node is created by
drivers/soc/qcom/rq_stats.c, which is only built with CONFIG_QCOM_RUN_QUEUE_STATS.
SODP leaves it off, the daemon cannot open the node ("Failed to sleep for 5 seconds"),
exits with status 0 after ~40 ms, and Android's init restarts it every 5 s, each time
followed by flags_health_check UPDATABLE_CRASHING.

Idempotent. Run from the 4.14 kernel root (common-kernel), or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'CONFIG_QCOM_RUN_QUEUE_STATS=y' in s:
    print('already applied')
    sys.exit(0)
s = s.replace('# CONFIG_QCOM_RUN_QUEUE_STATS is not set\n', '')
if not s.endswith('\n'):
    s += '\n'
s += 'CONFIG_QCOM_RUN_QUEUE_STATS=y\n'
p.write_text(s)
print('applied: CONFIG_QCOM_RUN_QUEUE_STATS=y')
