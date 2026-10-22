#!/bin/sh
# droid-hal-early-init.sh -- runs before every droid-hal-init start (including restarts),
# via droid-hal-init.service's own ExecStartPre=-/bin/sh .../droid-hal-early-init.sh.
# The leading '-' means systemd ignores this script's exit status.
#
# Real AOSP first-stage init unconditionally does:
#     CHECKCALL(mknod("/dev/kmsg_debug", S_IFCHR | 0622, makedev(1, 11)));
# (system/core/init/first_stage_init.cpp) -- with zero tolerance for the node already
# existing, because on genuine Android hardware /dev is a fresh devtmpfs on every single
# boot; init only ever runs once per kernel lifetime there.
#
# droid-hal-init is not real Android's own /init -- it's a systemd-managed service that can
# and does restart (Restart=always) within the *same* kernel boot, and /dev is real,
# persistent devtmpfs across those restarts. Once the very first successful run creates
# /dev/kmsg_debug, every later restart's mknod() call fails EEXIST, first-stage init aborts
# immediately ("Init encountered errors starting first stage, aborting", exit status
# 6/NOTCONFIGURED), and the entire Android-side environment (servicemanager,
# hwservicemanager, every HAL, everything) is gone for the rest of that boot -- confirmed
# happening roughly every two minutes in practice,
# independent of anything else fixed this session, silently invalidating whatever state
# any HIDL client (lipstick included) was relying on.
#
# Idempotent -- safe to run whether or not the node exists yet.
rm -f /dev/kmsg_debug
