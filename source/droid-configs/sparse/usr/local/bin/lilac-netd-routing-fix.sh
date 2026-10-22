#!/bin/sh
# root cause of the whole-project "alive but unreachable" mystery
# that survived every crash-loop fix (WifiService, sphal, hwc2, droid-hal-prepare's mount race,
# surfaceflinger's onrestart-kills-zygote) -- found by mining a sibling porting attempt's own
# notes, which deliberately runs a *stub* netd because "Sailfish deliberately does not run AOSP
# netd -- connman owns routing and the two would fight." This port never did that: `netd.rc`
# inside this build's own system.img is the real, unmodified AOSP service.
#
# Confirmed live (lilac-usbnet.sh's own `ip rule show` capture): by
# ~30s into every boot, real netd rewrites the routing rule table from the kernel default
#     0:     from all lookup local
#     32766: from all lookup main
#     32767: from all lookup default
# to its own fwmark-based network-selection scheme, terminating in an unconditional catch-all:
#     0:     from all lookup local
#     10000: from all fwmark 0xc0000/0xd0000 lookup 99
#     13000: from all fwmark 0x10063/0x1ffff iif lo lookup 97
#     15000: from all fwmark 0/0x10000 lookup 99
#     16000: from all fwmark 0/0x10000 lookup 98
#     17000: from all fwmark 0/0x10000 lookup 97
#     32000: from all unreachable
# Every SailfishOS/glibc daemon on this system (sshd, connman, everything) has an unmarked
# (fwmark 0) socket -- none of them talk to netd's own `fwmarkd` socket to request a mark, that
# being an Android-app-only mechanism. Every reply packet from one of these daemons matches
# rules 15000/16000/17000 in turn, looks up tables 99/98/97 -- which netd never populates with
# routes for connman-managed interfaces, since connman never registers them with netd at all --
# gets a miss on all three, and falls through to the unconditional 32000 rule, which drops it
# outright. This happens entirely at the IP routing layer, before the packet ever reaches the
# network device: it explains why ARP/ICMP work (different code path) while TCP replies vanish
# with zero `tx_dropped`/`tx_errors` on the interface itself (section 76's own finding -- the
# packet never got that far), and why CPU/scheduling were never the cause (section 75's own
# finding) no matter how cleanly the rest of the boot behaved.
#
# Fix: reinstate a fallback rule at a priority below netd's own specific rules (so a genuine
# netd-managed network, if one ever exists on this port, still wins when it has a real match)
# but above the unconditional 32000 unreachable catch-all -- exactly restoring what netd's own
# presence removed, without touching netd or connman's own setup at all.
#
# netd can rebuild its entire rule table (e.g. on a network state change), which would silently
# remove this fix again -- reassert on a loop for the life of the boot, the same shape as
# lilac-usbnet.sh's own iptables re-assertion loop (section 63) for the identical reason.
while :; do
	ip rule show 2>/dev/null | grep -q "^20000:" || ip rule add pref 20000 from all lookup main 2>/dev/null
	ip rule show 2>/dev/null | grep -q "^20001:" || ip rule add pref 20001 from all lookup default 2>/dev/null
	sleep 5
done
