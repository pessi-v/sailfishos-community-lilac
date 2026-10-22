#!/bin/sh
# the first time WiFi ever actually associated on this port (after
# the wlan0/wlan1 scan-collision fix and the missing-`privileged`-group fix, both same session),
# it still couldn't be reached from the LAN and had no outbound internet -- `iptables -L INPUT`
# showed `policy DROP` with only `usb0` ever granted a persistent ACCEPT (by lilac-usbnet.sh's own
# reassertion loop, which exists for exactly this same reload-wipes-rules reason). `OUTPUT`'s
# default policy is ACCEPT, so that direction was never the problem; only INPUT replies on wlan0
# (ICMP echo-reply, SSH SYN-ACK, everything) were being silently dropped.
#
# Same root mechanism as `lilac-netd-routing-fix.sh`'s `ip rule` reassertion: netd/connman
# regenerate their own iptables chains on network state changes and wipe any rule we add outside
# of that regeneration, so this has to be reasserted on a loop for the life of the boot rather
# than set once at startup.
#
# Loopback too (section 101): connman's own `connman-INPUT -i lo -j ACCEPT` is never reached once
# netd rebuilds INPUT, so every loopback packet hit the DROP policy -- including DNS to
# systemd-resolved's stub at 127.0.0.53. Host tools didn't notice (nss-resolve asks resolved over
# D-Bus), but sandboxed apps can't reach that D-Bus service and fall back to the stub, so the
# browser sat on its DNS queries forever and never drew a page.
while :; do
	iptables -C INPUT -i lo -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i lo -j ACCEPT 2>/dev/null
	iptables -C INPUT -i wlan0 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i wlan0 -j ACCEPT 2>/dev/null
	sleep 5
done
