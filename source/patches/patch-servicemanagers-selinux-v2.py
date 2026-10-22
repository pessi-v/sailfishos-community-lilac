#!/usr/bin/env python3
"""
Make servicemanager and hwservicemanager survive a system with no SELinux policy.

Adapted from the first port's own patches/patch-servicemanagers-selinux.py
(patches/patch-servicemanagers-selinux-REFERENCE-from-first-port.py in this repo) for this
build's actual, different-generation AOSP-11 source -- its own Access.cpp lacks the
`#ifdef __ANDROID__` guards the first port's (much newer) source had, so the anchors below
are rewritten to match; the fix technique and rationale are identical.

Why this is needed
-------------------
hybris/Sailfish runs with SELinux effectively off: the kernel has it built in
(CONFIG_SECURITY_SELINUX=y) but nothing ever mounts selinuxfs or loads a policy -- confirmed
directly: /sys/fs/selinux/ exists only as an empty, unmounted stub, no
enforce file, no policy file. servicemanager's constructor hard-aborts on this:

    CHECK(selinux_status_open(true /*fallback*/) >= 0);   -- fails: no live selinuxfs status
                                                               file to talk to -- aborts here
    CHECK(getcon(&mThisProcessContext) == 0);              -- never reached in our case

Confirmed via `gdb -batch -ex run -ex bt --args /system/bin/servicemanager`
 -- droid-hal-init respawns it in a tight loop forever, and since nothing
that depends on binder (including hwservicemanager's own clients, lipstick's compositor
startup, ...) can ever reach the plain /dev/binder context manager, everything downstream
retries forever against a permanently-dead binder handle 0.

Why hwservicemanager does *not* currently need this (confirmed by direct source read, not
assumed): its own AccessControl() constructor matches the *unpatched* first-port anchor
almost exactly, but its two startup calls happen to survive the same missing-policy
condition for an unrelated reason -- selinux_android_hw_service_context_handle() only opens
and parses a local *_hwservice_contexts file (pure userspace file I/O, no live kernel policy
required), and getcon() reads /proc/self/attr/current (works even with no policy loaded).
servicemanager's abort is specifically from selinux_status_open(), a genuinely different,
policy-dependent kernel call neither of hwservicemanager's own calls make. Patched anyway,
defensively, matching the first port's own belt-and-suspenders approach -- this is a latent
landmine (a future libselinux/environment change could easily make hwservicemanager hit the
same wall), and the cost of degrading gracefully here is nil.

Why not just mount selinuxfs
-----------------------------
Tried by the first port, found actively harmful: mounting /sys/fs/selinux with no policy loaded flips
is_selinux_enabled() true system-wide, and systemd's own SELinux-aware daemons then
core-dump -- systemd-udevd, systemd-logind, systemd-resolved -- killing udev and the USB
gadget with it. systemd also refuses a plain .mount unit for /sys/fs/selinux at all (treats
it as a protected API filesystem).

What this does
---------------
Degrades both daemons to "allow everything" when SELinux isn't enabled, instead of
aborting. Access control is a no-op on this system either way -- there is no policy to
enforce -- so this loses nothing that was working.
"""

import sys

HADK = sys.argv[1] if len(sys.argv) > 1 else '.'
edits = 0


def patch(path, replacements):
    """Apply (old, new) pairs, asserting each anchor appears exactly once."""
    global edits
    full = HADK + '/' + path
    src = open(full).read()
    for old, new in replacements:
        n = src.count(old)
        if n != 1:
            print('ANCHOR MISS in %s: %d occurrences of:\n%s' % (path, n, old))
            sys.exit(1)
        src = src.replace(old, new)
    open(full, 'w').write(src)
    edits += 1
    print('patched %s' % path)


# ---------------------------------------------------------------- servicemanager
patch('frameworks/native/cmds/servicemanager/Access.cpp', [
    # Explicit include -- relied on getting this transitively via selinux/android.h
    # before; make it direct so the probe below doesn't depend on that.
    ("""#include <selinux/android.h>
#include <selinux/avc.h>""",
     """#include <selinux/android.h>
#include <selinux/avc.h>
#include <selinux/selinux.h>"""),

    # A cached "is SELinux actually usable" probe, right before getPidcon (this source
    # has no #ifdef __ANDROID__ wrapping it, unlike the first port's newer source).
    ("""static std::string getPidcon(pid_t pid) {""",
     """// hybris: this system boots with no SELinux policy loaded. Probe once and
// degrade to permissive rather than aborting. See patch header.
static bool seUsable() {
    static const bool kUsable = (is_selinux_enabled() == 1);
    return kUsable;
}

static std::string getPidcon(pid_t pid) {"""),

    # Constructor: skip the two fatal CHECKs when SELinux is unavailable.
    ("""    CHECK(selinux_status_open(true /*fallback*/) >= 0);

    CHECK(getcon(&mThisProcessContext) == 0);""",
     """    if (!seUsable()) {
        LOG(WARNING) << "SELinux not enabled; servicemanager access control disabled";
        return;
    }

    CHECK(selinux_status_open(true /*fallback*/) >= 0);

    CHECK(getcon(&mThisProcessContext) == 0);"""),
])

# canFind/canAdd funnel through actionAllowedFromLookup; canList calls actionAllowed
# directly (with mThisProcessContext, which is now uninitialized garbage if the
# constructor returned early above) -- guard both entry points rather than adding a new
# member function.
patch('frameworks/native/cmds/servicemanager/Access.cpp', [
    ("""bool Access::actionAllowed(const CallingContext& sctx, const char* tctx, const char* perm,
        const std::string& tname) {
    const char* tclass = "service_manager";""",
     """bool Access::actionAllowed(const CallingContext& sctx, const char* tctx, const char* perm,
        const std::string& tname) {
    if (!seUsable()) return true;

    const char* tclass = "service_manager";"""),

    ("""bool Access::actionAllowedFromLookup(const CallingContext& sctx, const std::string& name, const char *perm) {
    char *tctx = nullptr;""",
     """bool Access::actionAllowedFromLookup(const CallingContext& sctx, const std::string& name, const char *perm) {
    if (!seUsable()) return true;

    char *tctx = nullptr;"""),
])

# ------------------------------------------------------------- hwservicemanager
# Not currently triggered on this build (confirmed by source read, not assumed -- see
# patch header) -- applied defensively, verbatim from the first port's patch: this
# source's AccessControl.{h,cpp} matches its anchors exactly, no adaptation needed.
patch('system/hwservicemanager/AccessControl.h', [
    ("""    char*                  mSeContext;
    struct selabel_handle* mSeHandle;""",
     """    // hybris: false when no SELinux policy is loaded -> allow everything.
    bool                   mSeEnabled;
    char*                  mSeContext;
    struct selabel_handle* mSeHandle;"""),
])

patch('system/hwservicemanager/AccessControl.cpp', [
    ("""AccessControl::AccessControl() {
    mSeHandle = selinux_android_hw_service_context_handle();
    LOG_ALWAYS_FATAL_IF(mSeHandle == nullptr, "Failed to acquire SELinux handle.");

    if (getcon(&mSeContext) != 0) {
        LOG_ALWAYS_FATAL("Failed to acquire hwservicemanager context.");
    }
""",
     """AccessControl::AccessControl() {
    // hybris: no SELinux policy is loaded on this system. Aborting here is what would end
    // the boot (this service is `critical` in its .rc). See patch header -- not currently
    // triggered (both calls below happen to survive a missing policy on this build), kept
    // as a defensive fallback rather than relied on.
    mSeEnabled = (is_selinux_enabled() == 1);
    if (!mSeEnabled) {
        ALOGW("SELinux not enabled; hwservicemanager access control disabled");
        mSeContext = nullptr;
        mSeHandle = nullptr;
        return;
    }

    mSeHandle = selinux_android_hw_service_context_handle();
    LOG_ALWAYS_FATAL_IF(mSeHandle == nullptr, "Failed to acquire SELinux handle.");

    if (getcon(&mSeContext) != 0) {
        LOG_ALWAYS_FATAL("Failed to acquire hwservicemanager context.");
    }
"""),

    ("""bool AccessControl::canAdd(const std::string& fqName, const CallingContext& callingContext) {
    FQName fqIface;""",
     """bool AccessControl::canAdd(const std::string& fqName, const CallingContext& callingContext) {
    if (!mSeEnabled) return true;
    FQName fqIface;"""),

    ("""bool AccessControl::canGet(const std::string& fqName, const CallingContext& callingContext) {
    FQName fqIface;""",
     """bool AccessControl::canGet(const std::string& fqName, const CallingContext& callingContext) {
    if (!mSeEnabled) return true;
    FQName fqIface;"""),

    ("""bool AccessControl::canList(const CallingContext& callingContext) {
    return checkPermission(callingContext, mSeContext, kPermissionList, nullptr);""",
     """bool AccessControl::canList(const CallingContext& callingContext) {
    if (!mSeEnabled) return true;
    return checkPermission(callingContext, mSeContext, kPermissionList, nullptr);"""),
])

print('\n%d files patched' % edits)
