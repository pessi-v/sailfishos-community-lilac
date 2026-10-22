#!/bin/sh
# bring up USB networking on the 4.14 port, without usb-moded.
#
# WHY NOT usb-moded -- two independent blockers, both verified, not guessed:
#   1. usb-moded.service carries Wants=/After=systemd-udev-settle.service, and
#      udev-settle is exactly what fails to complete on this port (10.101). It is
#      the same dependency the early /vendor mount had to be written to avoid.
#   2. On a droid device usb-moded picks dyn-modes/developer_mode-android.ini,
#      which drives /sys/class/android_usb/android0/functions -- the legacy
#      android_usb gadget. This kernel does not build it (no CONFIG_USB_G_ANDROID
#      in lilac-414-out-sfos/.config), so that path does not exist at all.
#
# What the kernel DOES have: CONFIG_USB_CONFIGFS=y with _ECM and _NCM, and
# configfs is already mounted at /config (seen in the 4.14 boot mount table). So
# drive the gadget directly and skip usb-moded entirely.
#
# ECM, not RNDIS, on purpose: the host here is macOS, which has never supported
# RNDIS but speaks CDC-ECM natively. RNDIS is not built in this kernel anyway.
#
# Serves DHCP so the host configures itself -- no sudo ifconfig on the Mac side.
# Deliberately advertises NO router and NO DNS: this link is for debugging, and
# must never become the host's default route.
#
# Purpose: kill the LineageOS round-trip. Today every sample costs a boot into
# SFOS plus a second boot into LineageOS to read the SD. With ssh on 2222 the
# device can be read live -- and live dmesg beats a canned one-line verdict when
# the bug under investigation is intermittent.
LOG=/data/usbnet.log
exec >>"$LOG" 2>&1
echo "===== lilac-usbnet boot=$(cut -c1-8 /proc/sys/kernel/random/boot_id 2>/dev/null) uptime=$(cut -d' ' -f1 /proc/uptime) ====="

CFG=/config/usb_gadget
G=$CFG/lilac
IP=192.168.2.15

# configfs should already be mounted by droid-hal-init; mount it if not.
if [ ! -d /config/usb_gadget ]; then
	echo "configfs not at /config, trying to mount"
	mkdir -p /config
	mount -t configfs none /config 2>&1
fi
[ -d "$CFG" ] || { echo "FATAL: $CFG missing after mount attempt"; exit 0; }

# Wait for a UDC rather than giving up on the first look. v3 checked once and
# exited for good if the list was empty, which makes the whole script hostage to
# one moment in a boot that is still settling -- and leaves no way in for the rest
# of the boot.
UDC=""
i=0
while [ $i -lt 30 ]; do
	UDC=$(ls /sys/class/udc 2>/dev/null | head -1)
	[ -n "$UDC" ] && break
	sleep 2
	i=$((i + 1))
done
echo "udc='$UDC' after $((i * 2))s"
echo "nets before: $(ls /sys/class/net | tr '\n' ' ')"
[ -n "$UDC" ] || { echo "FATAL: no UDC after 60s -- controller never came up"; exit 0; }

# Report anything already there, and get out of its way. Nothing useful is lost:
# adb does not run on the SFOS side of this port, so whatever droid-hal-init may
# have bound is not something being used.
for g in "$CFG"/*; do
	[ -d "$g" ] || continue
	echo "existing gadget $g UDC='$(cat "$g/UDC" 2>/dev/null)' funcs: $(ls "$g/functions" 2>/dev/null | tr '\n' ' ')"
	if [ "$g" != "$G" ] && [ -n "$(cat "$g/UDC" 2>/dev/null | tr -d ' \n')" ]; then
		echo "  unbinding $g to take over the UDC"
		echo "" > "$g/UDC" 2>&1
	fi
done

if [ -d "$G" ] && [ -n "$(cat "$G/UDC" 2>/dev/null | tr -d ' \n')" ]; then
	echo "our gadget already bound, leaving it alone"
else
	echo "creating ECM gadget at $G"
	mkdir -p "$G" 2>&1
	echo 0x1d6b > "$G/idVendor"          # Linux Foundation
	echo 0x0104 > "$G/idProduct"         # Multifunction Composite Gadget
	echo 0x0100 > "$G/bcdDevice"
	echo 0x0200 > "$G/bcdUSB"
	mkdir -p "$G/strings/0x409"
	echo "lilac"            > "$G/strings/0x409/serialnumber"
	echo "SailfishOS"       > "$G/strings/0x409/manufacturer"
	echo "lilac debug ecm"  > "$G/strings/0x409/product"
	mkdir -p "$G/configs/c.1/strings/0x409"
	echo "ecm" > "$G/configs/c.1/strings/0x409/configuration"
	echo 250   > "$G/configs/c.1/MaxPower"
	mkdir -p "$G/functions/ecm.usb0"
	# Fixed MACs: a stable host-side MAC keeps macOS from inventing a new network
	# location on every boot, which would need re-approving each time.
	echo "02:1a:11:00:00:01" > "$G/functions/ecm.usb0/host_addr" 2>&1
	echo "02:1a:11:00:00:02" > "$G/functions/ecm.usb0/dev_addr"  2>&1
	ln -sf "$G/functions/ecm.usb0" "$G/configs/c.1/" 2>&1
	echo "binding to $UDC"
	echo "$UDC" > "$G/UDC" 2>&1
	echo "bind rc=$? UDC now='$(cat "$G/UDC" 2>/dev/null)'"
fi

# The netdev name is assigned by the gadget, so discover it rather than assume.
IFACE=$(cat "$G/functions/ecm.usb0/ifname" 2>/dev/null | tr -d ' \n')
[ -n "$IFACE" ] || IFACE=usb0
echo "iface='$IFACE'"
echo "nets after: $(ls /sys/class/net | tr '\n' ' ')"

if [ ! -d "/sys/class/net/$IFACE" ]; then
	echo "FATAL: $IFACE never appeared -- gadget did not bind"
	exit 0
fi

ip addr add "$IP/24" dev "$IFACE" 2>&1
ip link set "$IFACE" up 2>&1

# v1 configured the interface and inspected it in the same breath, and reported
# NO-CARRIER / state DOWN. That was a race, not a fault: carrier only appears once
# the host has enumerated the gadget and selected a configuration, which happens a
# moment after the bind. Wait for it before doing anything that needs the link.
i=0
while [ $i -lt 30 ]; do
	[ "$(cat "/sys/class/net/$IFACE/carrier" 2>/dev/null)" = "1" ] && break
	sleep 2
	i=$((i + 1))
done
echo "carrier=$(cat "/sys/class/net/$IFACE/carrier" 2>/dev/null) after $((i * 2))s"
echo "addr: $(ip -4 addr show dev "$IFACE" 2>&1 | tr '\n' ' ')"

# DHCP so the host needs no manual configuration. No router, no DNS -- see above.
CONF=/run/lilac-udhcpd.conf
cat > "$CONF" <<EOF
start 192.168.2.20
end 192.168.2.29
interface $IFACE
max_leases 5
option subnet 255.255.255.0
option lease 3600
lease_file /run/lilac-udhcpd.leases
pidfile /run/lilac-udhcpd.pid
EOF
: > /run/lilac-udhcpd.leases
if [ -x /usr/sbin/udhcpd ]; then
	/usr/sbin/udhcpd "$CONF" 2>&1
	echo "udhcpd rc=$?"
else
	echo "no udhcpd; host must be configured statically (192.168.2.x/24)"
fi

# Open the link in the packet filter.
#
# v2 got as far as a working L2/L3 link -- the host took a DHCP lease from our
# udhcpd and ARP for 192.168.2.15 resolved -- while ICMP and TCP were both
# silently dropped. That split is diagnostic: udhcpd serves over raw packet
# sockets and works even through a filter, so reaching DHCP but nothing else means
# addressing is fine and something is filtering. SFOS ships a connman firewall and
# droid-hal-init installs Android's netd rules, either of which defaults to
# dropping on an interface nothing has whitelisted.
echo "--- filter before ---"
iptables -S 2>&1 | head -20
for t in iptables ip6tables; do
	command -v $t >/dev/null 2>&1 || { echo "$t missing"; continue; }
	for c in INPUT OUTPUT; do
		[ "$c" = INPUT ] && a="-i" || a="-o"
		$t -C $c $a "$IFACE" -j ACCEPT 2>/dev/null || $t -I $c 1 $a "$IFACE" -j ACCEPT 2>&1
	done
done
echo "--- filter after ---"
iptables -S 2>&1 | head -20
# 2026-09-22 (mined from the sibling porting attempt's own notes):
# real AOSP netd (confirmed present and unmodified on this build, unlike the sibling port's
# own deliberate netd-stub -- "Sailfish deliberately does not run AOSP netd... the two would
# fight") sets up SO_MARK-based policy routing via its `fwmarkd` socket for exactly this
# reason. The sibling port's own words: "a non-zero mark with no matching `ip rule` would
# route data traffic to a table that does not exist -- traffic would vanish with everything
# looking healthy." That is our exact symptom (ARP/ICMP fine, TCP data never arrives, no
# tx_dropped increment). Capture the full rule/route picture once at startup to check for
# stray netd-owned rules/tables connman's own routing setup wouldn't know about.
echo "--- ip rule ---"
ip rule show 2>&1
echo "--- ip route table all ---"
ip route show table all 2>&1

# Hold the link up for a few minutes, re-asserting it if anything takes it away.
#
# v1 set this up at t~129 and by the time the host was tested the link was dead,
# with no record of what happened in between. connman is blacklisted from managing
# usb* (NetworkInterfaceBlacklist in /etc/connman/main.conf) but its separate
# "bring everything down at startup" pass exempts only what DontBringDownAtStartup
# lists, and it starts AFTER us. droid-hal-init also touches the gadget late.
# Rather than guess which, re-assert and log every transition -- this both fixes it
# and names the culprit by when the state changes.
# Runs for the life of the boot, not a fixed window: this is the only way into the
# device, so it should stay up as long as the device does. Tight polling for the
# first 30 minutes while the rest of the boot is still moving and things get torn
# down, then a slow heartbeat.
#
# 2026-09-21: the 5s fast-phase interval turned out not to be tight enough.
# usbnet.log from a live session showed UDC/carrier/IP never wavering, but the
# usb0 iptables ACCEPT rule gone on every single 5s poll, all session --
# `iptables-restore` (connman, reacting to the zygote/system_server crash loop's
# constant netd restarts, ~158 reloads in one 15-minute session, averaging faster
# than one every 3s) was winning the race against a 5s recheck. Tightened to 1s/5s
# and widened the fast window to 30 minutes so a whole live-debugging session stays
# in the tight phase instead of backing off after 5 minutes.
#
# 2026-09-21, same night, second attempt: the 1s loop itself went silent after
# ~20s (systemd never saw the service stop -- it just stopped updating the log),
# worse than the 5s version it replaced. `sync` was still being called every pass
# -- fine at one flush per 5s, but on a device already under heavy write load from
# the zygote crash loop (repeated APEX/data writes) and a card already flagged
# for controller retuning, one flush per second plus 5x more
# `iptables` calls (one `Resource temporarily unavailable` lock-contention error
# was caught) plausibly stalled the loop on I/O or a lock. Decoupled: the cheap
# iptables recheck still runs every fast-phase pass, but `sync` is throttled back
# to its original ~5s cadence regardless of phase, via SYNC_EVERY below.
SYNC_EVERY=5
SYNC_COUNT=0
FAST_UNTIL=$(( $(cut -d. -f1 /proc/uptime) + 1800 ))
LAST=""
NOCARR=0
while :; do
	BOUND=$(cat "$G/UDC" 2>/dev/null | tr -d ' \n')
	OPER=$(cat "/sys/class/net/$IFACE/operstate" 2>/dev/null)
	CARR=$(cat "/sys/class/net/$IFACE/carrier" 2>/dev/null)
	HASIP=$(ip -4 addr show dev "$IFACE" 2>/dev/null | grep -c "$IP")
	SSHD=$(ss -lnt 2>/dev/null | grep -c ':2222')
	STATE="udc='$BOUND' oper=$OPER carrier=$CARR ip=$HASIP sshd=$SSHD"
	if [ "$STATE" != "$LAST" ]; then
		echo "t=$(cut -d' ' -f1 /proc/uptime) $STATE"
		LAST="$STATE"
	fi
	# 2026-09-21, third attempt: neither the firewall-timing fix nor decoupling
	# sync changed anything -- ARP for our own IP never resolves from the host
	# side, on every attempt tonight, regardless of script config. iptables can't
	# explain that (it doesn't touch ARP), so before guessing further: log packet
	# counters and the live ARP table every pass, unconditionally (not gated by
	# STATE dedup, since these change even when nothing else does), to see
	# directly whether inbound frames ever reach this interface at all.
	RX=$(cat "/sys/class/net/$IFACE/statistics/rx_packets" 2>/dev/null)
	TX=$(cat "/sys/class/net/$IFACE/statistics/tx_packets" 2>/dev/null)
	RXERR=$(cat "/sys/class/net/$IFACE/statistics/rx_errors" 2>/dev/null)
	RXDROP=$(cat "/sys/class/net/$IFACE/statistics/rx_dropped" 2>/dev/null)
	# 2026-09-22: a full-power-cycle boot with none of tonight's
	# fixed crash loops still showed tx frozen for 35s straight (538->570 rx, tx stuck at
	# 25) with the CPU 50-55% idle the whole time -- ruling out CPU/scheduling contention
	# as *the* cause. tx_packets alone can't distinguish "kernel never tried to transmit"
	# from "tried and failed at the driver/queue level" -- these three do.
	TXERR=$(cat "/sys/class/net/$IFACE/statistics/tx_errors" 2>/dev/null)
	TXDROP=$(cat "/sys/class/net/$IFACE/statistics/tx_dropped" 2>/dev/null)
	TXFIFO=$(cat "/sys/class/net/$IFACE/statistics/tx_fifo_errors" 2>/dev/null)
	LOAD=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)
	echo "  t=$(cut -d' ' -f1 /proc/uptime) rx=$RX tx=$TX rx_err=$RXERR rx_drop=$RXDROP tx_err=$TXERR tx_drop=$TXDROP tx_fifo=$TXFIFO load=$LOAD arp=[$(tr '\n' ';' < /proc/net/arp 2>/dev/null)]"
	# 2026-09-22: tx_dropped only reached 2 total across dozens of
	# inbound probes over a 20-minute session -- ruling out "kernel tries and fails at the
	# driver level" as the explanation, since a real per-attempt failure would track the probe
	# count far more closely. Next suspect is upstream of the driver entirely: whether inbound
	# frames are even being NAPI-polled/softirq-processed at a rate that could ever generate a
	# reply. /proc/net/softnet_stat's columns are, per CPU: processed, dropped, time_squeeze,
	# ..., in hex -- cheap enough to log every poll, unlike top.
	echo "  softnet=[$(tr '\n' ';' < /proc/net/softnet_stat 2>/dev/null)]"
	# 2026-09-22: this session found rx climbing steadily while tx stayed flat for
	# minutes at a time -- packets arriving but the device almost never
	# transmitting a reply -- with zygote/system_server confirmed NOT
	# crash-looping this time (zero restarts in testmode-crash-logcat.log), so it
	# cannot be the §63 cause again. loadavg above is cheap enough for every
	# poll; a heavier top(1) snapshot only every ~30s of wall time, to catch
	# whatever is consuming CPU without adding load itself on every pass.
	if command -v top >/dev/null 2>&1; then
		NOWSEC=$(cut -d. -f1 /proc/uptime)
		if [ -z "$LASTTOP" ] || [ $((NOWSEC - LASTTOP)) -ge 30 ]; then
			echo "  --- top ---"
			top -bn1 2>&1 | head -14 | sed 's/^/  /'
			# real netd can (re)install SO_MARK-based ip rules at any
			# point during boot, not just at startup -- re-check alongside top rather than only
			# once, cheap enough at the same 30s cadence.
			echo "  --- ip rule ---"
			ip rule show 2>&1 | sed 's/^/  /'
			LASTTOP=$NOWSEC
		fi
	fi
	[ -z "$BOUND" ] && { echo "  UDC lost -- rebinding"; echo "$UDC" > "$G/UDC" 2>&1; }
	# Carrier can sit at 0 with the UDC still bound and the link otherwise
	# healthy -- the case is a cable replugged around the time we bound, where
	# the host never enumerates and nothing here notices, because oper/ip/UDC
	# all look fine. Force a re-enumeration by cycling the bind, but only after
	# several consecutive misses so a genuinely unplugged cable does not cause
	# a rebind on every pass.
	if [ "$CARR" != "1" ] && [ -n "$BOUND" ]; then
		NOCARR=$((NOCARR + 1))
		if [ "$NOCARR" -ge 4 ]; then
			echo "  no carrier for $((NOCARR * 5))s with UDC bound -- cycling bind to force re-enumeration"
			echo "" > "$G/UDC" 2>&1
			sleep 1
			echo "$UDC" > "$G/UDC" 2>&1
			NOCARR=0
		fi
	else
		NOCARR=0
	fi
	[ "$HASIP" = "0" ] && { echo "  address gone -- re-adding"; ip addr add "$IP/24" dev "$IFACE" 2>&1; }
	[ "$OPER" = "down" ] && { echo "  link down -- bringing up"; ip link set "$IFACE" up 2>&1; }
	# Keep the filter open -- connman's firewall and netd both reload and would
	# otherwise drop our rules on the floor partway through the boot.
	iptables -C INPUT -i "$IFACE" -j ACCEPT 2>/dev/null || {
		echo "  filter rule gone -- re-adding"
		iptables -I INPUT 1 -i "$IFACE" -j ACCEPT 2>&1
		iptables -I OUTPUT 1 -o "$IFACE" -j ACCEPT 2>&1
	}

	NOW=$(cut -d. -f1 /proc/uptime)
	# Do not depend on multi-user.target for the way in. lilac-sshd-always.service
	# is WantedBy=multi-user.target, which is both later than this and not
	# guaranteed on a half-booted port -- and if the boot is broken enough to need
	# ssh, it is broken enough not to reach multi-user.
	if [ "$SSHD" = "0" ] && [ "$NOW" -gt "$FAST_UNTIL" ] && [ -x /usr/sbin/sshd ]; then
		echo "  nothing on 2222 -- starting sshd ourselves"
		/usr/sbin/sshd -p 2222 2>&1
		echo "  sshd rc=$?"
	fi

	SYNC_COUNT=$((SYNC_COUNT + 1))
	if [ "$SYNC_COUNT" -ge "$SYNC_EVERY" ] || [ "$NOW" -ge "$FAST_UNTIL" ]; then
		sync
		SYNC_COUNT=0
	fi
	if [ "$NOW" -lt "$FAST_UNTIL" ]; then sleep 1; else sleep 5; fi
done
