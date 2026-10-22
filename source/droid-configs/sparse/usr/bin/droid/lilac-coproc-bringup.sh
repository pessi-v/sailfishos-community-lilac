#!/bin/sh
# lilac-coproc-bringup.sh -- bring up modem and WLAN on this port.
#
# Root cause: `class_start hal`/`core`/`main`/
# `late_start` never fire on this hybris boot at all -- confirmed directly by
# instrumenting do_class_start() itself (patches/patch-init-debug-class-start-v2.py):
# it is called exactly twice, ever, for the hybris-internal `mer`/`trimarea` classes
# only. Real AOSP HAL startup mostly survives this because hwservicemanager's own
# lazy ctl.interface_start mechanism is independent of class_start (section 30) --
# but the modem/WLAN co-processor chain (qrtr-ns, pd-mapper, tftp_server,
# rmt_storage, sct_service, ta_qmi_service, mlog_qmi_service, per_mgr, qcrild,
# cnss-daemon) are all plain `class core`/`main`/`late_start` binaries with no HIDL
# interface line for hwservicemanager to trigger -- nothing ever starts any of them.
# All ten binaries and their .rc files ARE present and correctly wired on our own
# /odm.img (confirmed by hand, one at a time); the only gap is that nothing issues
# the `ctl.start`. This script is that trigger, run once per boot.
#
# Same shape of fix as the first port's own lilac-coproc-bringup.sh (before ITS
# class_start bug was later root-caused and fixed upstream in ITS own tree) -- our own class_start dead-code finding
# is unconditional (called twice total, not just delayed), so we don't have that
# option here; this script IS the permanent fix, not a stopgap.
LOG=/var/log/lilac-coproc-bringup.log
exec >>"$LOG" 2>&1
echo "===== lilac-coproc-bringup boot=$(cut -c1-8 /proc/sys/kernel/random/boot_id 2>/dev/null) uptime=$(cut -d' ' -f1 /proc/uptime) ====="

subsys_state() {
	for d in /sys/bus/msm_subsys/devices/subsys*; do
		[ "$(cat "$d/name" 2>/dev/null)" = "$1" ] && cat "$d/state" 2>/dev/null
	done
}
svcstate() { getprop "init.svc.$1" 2>/dev/null | tr -d '\r\n'; }
# droid-hal-init's SVC_RUNNING bookkeeping can stick on a service that never
# actually started (same class of bug documented by the first port) -- ctl.stop first is a no-op on a
# genuinely-stopped service and clears the flag on a stuck one, so it is always
# safe here.
ensure_svc() {
	st=$(svcstate "$1")
	if [ "$st" = running ]; then
		echo "   $1: running"
		return
	fi
	setprop ctl.stop "$1" >/dev/null 2>&1
	sleep 1
	setprop ctl.start "$1" >/dev/null 2>&1
	sleep 2
	echo "   $1: was '${st:-unknown}', now '$(svcstate "$1")'"
}

# /odm carries every binary below (qrtr-ns, pd-mapper, tftp_server, rmt_storage,
# sct_service, ta_qmi_service, mlog_qmi_service, per_mgr, qcrild's own
# libril-qc-hal-qmi.so, cnss-daemon); without it there is nothing to start.
i=0
while [ $i -lt 60 ]; do
	grep -q ' /odm ' /proc/mounts && break
	sleep 2
	i=$((i + 1))
done
grep -q ' /odm ' /proc/mounts || { echo "FATAL: /odm not mounted after $((i * 2))s"; exit 0; }
echo "/odm mounted after $((i * 2))s"

# Safety net BEFORE anything is triggered, not after: a modem crash at the kernel
# default restart_level (SYSTEM) panics the WHOLE SoC via the watchdog, which
# resets clean back to whatever is persistently flashed -- on this device that is
# the phone's real, unmodified Sony stock firmware, not this RAM-booted image.
# Hit exactly this way once mid-development (an early, kernel-patch-less modem PIL
# attempt crashed and the device came back up running Sony's own stock Android 9).
# RELATED restarts only the modem subsystem and leaves the device inspectable.
for d in /sys/bus/msm_subsys/devices/subsys*; do
	[ "$(cat "$d/name" 2>/dev/null)" = modem ] || continue
	[ "$(cat "$d/restart_level" 2>/dev/null)" = RELATED ] || echo RELATED > "$d/restart_level" 2>/dev/null
	echo "modem restart_level=$(cat "$d/restart_level" 2>/dev/null)"
done

echo "-- QMI name service, servreg locator, tftp (must precede the modem)"
ensure_svc vendor.qrtr-ns
ensure_svc vendor.pd_mapper
ensure_svc vendor.tftp_server

echo "-- modem stack"
for s in vendor.rmt_storage vendor.sct_service vendor.ta_qmi_service vendor.mlog_qmi_service vendor.per_mgr vendor.qcrild; do
	ensure_svc "$s"
done

i=0
while [ $i -lt 45 ]; do
	[ "$(subsys_state modem)" = ONLINE ] && break
	sleep 2
	i=$((i + 1))
done
echo "modem=$(subsys_state modem) after $((i * 2))s"

echo "-- cnss-daemon (triggers WLAN FW_READY -> driver probe -> wlan0)"
ensure_svc vendor.cnss-daemon

# CONFIG_QCA_CLD_WLAN=y (built-in, not a module): the kernel's own qcacld-3.0 driver
# only creates this sysfs trigger at boot (wlan_init_sysfs()) rather than actually
# loading -- real driver load needs an explicit userspace write here. Confirmed
# live, icnss reaches "FW READY" on its own via
# cnss-daemon, but never advances to DRIVER PROBED / wlan0 without this write.
if [ -w /sys/kernel/boot_wlan/boot_wlan ]; then
	echo 1 > /sys/kernel/boot_wlan/boot_wlan 2>&1
	echo "-- boot_wlan triggered"
fi

i=0
while [ $i -lt 45 ]; do
	[ -d /sys/class/net/wlan0 ] && break
	sleep 2
	i=$((i + 1))
done
if [ -d /sys/class/net/wlan0 ]; then
	echo "RESULT: WLAN UP after $((i * 2))s -- $(ls /sys/class/net | tr '\n' ' ')"
	echo "  mac=$(cat /sys/class/net/wlan0/address 2>/dev/null) wiphy=$(ls /sys/class/ieee80211 2>/dev/null)"
else
	echo "RESULT: NO wlan0 after $((i * 2))s"
	grep "^State:" /sys/kernel/debug/icnss/stats 2>/dev/null
fi

echo "===== done uptime=$(cut -d' ' -f1 /proc/uptime) ====="
sync
