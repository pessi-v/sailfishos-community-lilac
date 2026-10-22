#!/bin/sh
# real netd's own INPUT chain (iptables) only carries explicit
# ACCEPT rules for the interfaces it already knows about at boot -- usb0, wlan0, lo -- never
# for rmnet_data*/r_rmnet_data* (the cellular data interfaces that only start existing once a
# GPRS/LTE context actually attaches, entirely under connman's control, which netd is never
# told about, matching this whole port's own "connman owns routing, real netd is otherwise
# unmodified" design -- see lilac-netd-routing-fix.sh's own comment for that context).
#
# Confirmed live: with a real LTE data context attached and connman's own default route
# pointed at rmnet_data1, outbound ICMP requests left the device fine (ARP/ICMP take a
# different path, same as lilac-netd-routing-fix.sh's own finding for TCP) but every reply
# packet coming back in on rmnet_data1 hit the INPUT chain's unconditional policy DROP --
# zero packets ever reached connman or any application. Adding an explicit ACCEPT rule for
# the interface, matching the existing usb0/wlan0 rules exactly, fixed it immediately: real
# internet over LTE, confirmed with `ping 8.8.8.8` succeeding end to end.
#
# Same reassertion shape as lilac-netd-routing-fix.sh/lilac-usbnet.sh, for the same reason:
# netd can rebuild its whole iptables ruleset on a network state change, silently dropping
# this again.
while :; do
	iptables -C INPUT -i rmnet_data+ -j ACCEPT 2>/dev/null || iptables -I INPUT -i rmnet_data+ -j ACCEPT 2>/dev/null
	iptables -C INPUT -i r_rmnet_data+ -j ACCEPT 2>/dev/null || iptables -I INPUT -i r_rmnet_data+ -j ACCEPT 2>/dev/null
	sleep 5
done
