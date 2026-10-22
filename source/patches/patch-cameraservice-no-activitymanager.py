#!/usr/bin/env python3
"""Stop CameraService from gating camera access on two Android-framework
concepts this port will never have: ActivityManager-reported UID activity,
and multi-user device-user switching.

Found 2026-09-28 while diagnosing a
"camera regression": jolla-camera's viewfinder stayed blank, and logcat
showed CameraService itself denying every open attempt, first one way, then
(once the first was fixed) another.

Bug 1 -- idle UID. CameraService::UidPolicy::isUidActiveLocked() only
enforces its UID-active check when its own mRegistered flag is true; its own
comment says why it exists at all: "If activity manager is unreachable,
assume everything is active." This port deliberately never runs
system_server (commit 1540502, "Stop running zygote, system_server and
surfaceflinger" -- zygote crash-looped without surfaceflinger and killed
audioserver/cameraserver/netd/etc. every few seconds), so ActivityManager is
never reachable and mRegistered should stay false forever, correctly
bypassing this whole check. It doesn't: `service list` shows a real, listed
"activity" entry with an empty interface descriptor (`activity: []`, unlike
every genuine service on the list, which shows its real AIDL interface) --
something transient registered it and is now dead or unresponsive (`dumpsys
activity` hangs indefinitely rather than erroring; no process ever calls
`start zygote`/`app_process` in the boot log, so the culprit wasn't
identified). registerSelf()'s own linkToDeath() call against that stale
handle still returns OK, so mRegistered flips to true anyway, and every
later isUidActiveLocked() call enforces a check that can now never be
satisfied -- there is nothing left alive to ever report any UID as active.
Confirmed live: restarting cameraserver gets a fresh UidPolicy that hits the
exact same stale registration and the exact same permanent denial, so this
isn't a one-off race in a single process.

Fix: since ActivityManager will never legitimately be reachable on this
port, make registerSelf() a no-op outright, rather than only working around
whatever is (still unexplained) leaving a dead "activity" registration
behind. mRegistered then stays false unconditionally, and
isUidActiveLocked()'s own existing bypass -- already written to handle
exactly this "unreachable" case -- takes over correctly, matching normal
hybris-port behavior.

Bug 2 -- disallowed device user, found immediately after rebuilding and
redeploying the bug 1 fix: `CameraService::connect X (PID <pid>) rejected
(cannot connect from device user 1, currently allowed device users: )`.
validateClientPermissionsLocked() restricts camera access to whichever
Android user is currently in the foreground, tracked in mAllowedUsers (a
std::set<userid_t>, default-constructed empty) and populated only by
doUserSwitch(), itself only ever called in response to a real
ActivityManager user-switch broadcast -- another thing that will never
happen here. Android's own multiuser math (multiuser_get_user_id(uid) =
uid / 100000) means this port's own convention of running every Sailfish
app as UID 100000 lands exactly on "device user 1", not user 0 -- so even a
single-user-only device trips this multi-user check. Fix: skip it
unconditionally, the same way bug 1's check is skipped -- this port has no
concept of Android multi-user switching at all.

Idempotent. Run from the root of this AOSP tree (the directory containing
frameworks/), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'frameworks/av/services/camera/libcameraservice/CameraService.cpp'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
MARK = 'lilac-v2: never link to ActivityManager'
MARK2 = 'lilac-v2: never enforce the foreground-device-user restriction'
bug1_done = MARK in s
bug2_done = MARK2 in s
if bug1_done and bug2_done:
    print('already patched')
    sys.exit(0)

old = '''void CameraService::UidPolicy::registerSelf() {
    Mutex::Autolock _l(mUidLock);

    if (mRegistered) return;
    status_t res = mAm.linkToDeath(this);
    mAm.registerUidObserver(this, ActivityManager::UID_OBSERVER_GONE
            | ActivityManager::UID_OBSERVER_IDLE
            | ActivityManager::UID_OBSERVER_ACTIVE | ActivityManager::UID_OBSERVER_PROCSTATE,
            ActivityManager::PROCESS_STATE_UNKNOWN,
            String16("cameraserver"));
    if (res == OK) {
        mRegistered = true;
        ALOGV("UidPolicy: Registered with ActivityManager");
    }
}'''

new = '''void CameraService::UidPolicy::registerSelf() {
    /* lilac-v2: never link to ActivityManager --
     * this port never runs system_server, so
     * ActivityManager is never legitimately reachable, and mRegistered must
     * stay false so isUidActiveLocked()'s own "activity manager is
     * unreachable, assume everything is active" bypass takes over. A stale,
     * unexplained "activity" service registration (empty interface
     * descriptor in `service list`, dumpsys hangs) was otherwise making
     * linkToDeath() return OK anyway, permanently denying every camera open
     * with "can't use the camera from an idle UID".
     */
    return;
}'''

if not bug1_done:
    if old not in s:
        sys.exit('expected registerSelf() body not found -- CameraService.cpp may have changed')
    s = s.replace(old, new)

old2 = '''    // Only allow clients who are being used by the current foreground device user, unless calling
    // from our own process OR the caller is using the cameraserver's HIDL interface.
    if (getCurrentServingCall() != BinderCallType::HWBINDER && callingPid != getpid() &&
            (mAllowedUsers.find(clientUserId) == mAllowedUsers.end())) {
        ALOGE("CameraService::connect X (PID %d) rejected (cannot connect from "
                "device user %d, currently allowed device users: %s)", callingPid, clientUserId,
                toString(mAllowedUsers).string());
        return STATUS_ERROR_FMT(ERROR_PERMISSION_DENIED,
                "Callers from device user %d are not currently allowed to connect to camera \\"%s\\"",
                clientUserId, cameraId.string());
    }'''

new2 = '''    // lilac-v2: never enforce the foreground-device-user restriction
    // -- mAllowedUsers is only ever populated by
    // doUserSwitch(), itself only called from a real ActivityManager user-switch
    // broadcast this port's system_server-less design never sends (see bug 1's
    // own comment above). Android's own multiuser math also means this port's
    // convention of running every Sailfish app as UID 100000 lands on "device
    // user 1", not user 0, so even a single-user device would trip this. This
    // port has no concept of Android multi-user switching at all.
    (void)clientUserId;'''

if not bug2_done:
    if old2 not in s:
        sys.exit('expected foreground-device-user check not found -- CameraService.cpp may have changed')
    s = s.replace(old2, new2)

p.write_text(s)
print(f'patched {p}: CameraService::UidPolicy::registerSelf() is a no-op, and the '
      'foreground-device-user check is skipped')
