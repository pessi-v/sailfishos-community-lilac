#!/bin/sh
# 2026-09-21 (fresh-boot USB-net TX-starvation session): the zygote/
# system_server crash loop keeps taking network access down
# with it (netd/wificond torn down every restart, and separately a USB-CDC-ECM
# debug link showed its TX path essentially starved under the same load), so we
# have never once been able to `adb logcat`/ssh in live to see *why* zygote exits.
#
# Same fix as kmsg-sdlog.sh already applies to kernel messages: stop depending on
# a live channel at all. Capture logcat continuously to this rootfs's own
# /var/log (SD card, mmcblk0p2) with a tight background sync, so even a hard
# power-cycle mid-crash-loop leaves the log readable afterward from the
# LineageOS side (mount mmcblk0p2 read-only, no live access needed).
#
# Started After=droid-hal-init.service (not Before=, unlike kmsg-sdlog): logcat
# needs logd + /system, both of which come up partway through droid-hal-init's
# own startup, not before it.
LOG=/var/log/testmode-crash-logcat.log
LOGCAT=/system/bin/logcat
command -v "$LOGCAT" >/dev/null 2>&1 || LOGCAT=logcat
: > "$LOG"
echo "using LOGCAT=$LOGCAT" >> "$LOG"

# 2026-09-21, lipstick/hwcomposer/libbinder session: /linkerconfig/ld.config.txt is a tmpfs,
# regenerated fresh every boot by droid-hal-init before this script even starts (this unit's
# own After=droid-hal-init.service means it's already there by the time we get here) -- copy it
# out to persistent storage once, unconditionally, so it survives to be read from the LineageOS
# side the same way every other testmode-crash-*.log does. Needed to directly verify what the
# generated [sphal] namespace section actually says, rather than guessing further from source.
cp /linkerconfig/ld.config.txt /var/log/testmode-ld-config.txt 2>&1

# Same session: the deployed /apex/com.android.runtime/bin/linkerconfig is confirmed
# byte-identical (md5) to the freshly-rebuilt, patched copy on every hop (build machine, this
# Mac, the device's persistent /apex tree) -- yet the captured ld.config.txt above still didn't
# show the patch's added libbinder.so anywhere. Before assuming anything more exotic: capture
# exactly what droid-hal-init would actually resolve and run at /system/bin/linkerconfig, from
# inside this live boot's own mount/namespace context, not the LineageOS-side static view.
{
	echo "=== /system/bin/linkerconfig resolution, from inside the live boot ==="
	ls -la /system/bin/linkerconfig 2>&1
	REAL=$(readlink -f /system/bin/linkerconfig 2>&1)
	echo "readlink -f: $REAL"
	ls -la "$REAL" 2>&1
	md5sum "$REAL" 2>&1
	echo "=== for comparison, the file this session deployed to ==="
	ls -la /apex/com.android.runtime/bin/linkerconfig 2>&1
	md5sum /apex/com.android.runtime/bin/linkerconfig 2>&1
	echo "=== which /system this boot actually has (our own system.img, or the real partition?) ==="
	mount | grep ' /system '
	echo "--- /system/build.prop, first 15 lines ---"
	head -15 /system/build.prop 2>&1
	echo "--- does it say our own build? ---"
	grep -n 'aosp_g8441\|ro.build.fingerprint\|ro.build.date' /system/build.prop 2>&1
} > /var/log/testmode-linkerconfig-resolution.log 2>&1

(while true; do sync; sleep 1; done) &
while true; do
	"$LOGCAT" -b all -v threadtime >> "$LOG" 2>&1
	echo "===== logcat exited rc=$? at $(cut -d' ' -f1 /proc/uptime), restarting =====" >> "$LOG"
	sleep 1
done
