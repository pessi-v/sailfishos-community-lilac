#!/bin/sh
# on a real Jolla device, first-boot account provisioning adds the
# interactive account to the "privileged" group, which connman's own "sailfish:1" D-Bus access
# policy requires for Connect()/Disconnect()/Remove()/ResetCounters()/ClearProperty(*) on any
# service (and gates other privileged D-Bus actions the same way). This image's rootfs was
# assembled directly rather than through that real first-boot flow, so defaultuser was never
# added -- confirmed live: `id defaultuser` had no `privileged` group at all, and every
# WLAN-connect attempt through the Settings UI silently failed (Connect() denied, no visible
# error) as a direct result. Idempotent: usermod -aG is a no-op if already a member.
usermod -aG privileged defaultuser 2>/dev/null || true
