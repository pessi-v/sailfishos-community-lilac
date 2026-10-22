#!/usr/bin/env python3
"""
Make servicemanager and hwservicemanager survive a system with no SELinux policy.

Why this is needed
------------------
hybris/Sailfish runs with SELinux effectively off: the kernel starts it in
permissive mode but nothing ever loads a policy, and droid-hal-init logs
"SELinux: SELinux is disabled, skipping restorecon".  Android 15's
servicemanager and hwservicemanager both treat that as fatal:

    servicemanager:   CHECK(selinux_status_open(true) >= 0)     -> abort
                      CHECK(getcon(&mThisProcessContext) == 0)  -> abort
    hwservicemanager: LOG_ALWAYS_FATAL_IF(mSeHandle == nullptr) -> abort

hwservicemanager is marked `critical` in its .rc, so four aborts make
droid-hal-init give up with status=6/NOTCONFIGURED and the boot ends.

Why not just mount selinuxfs
----------------------------
Tried, and it is actively harmful: mounting
/sys/fs/selinux with no policy loaded makes is_selinux_enabled() true for the
whole system, and systemd's own daemons then core-dump -- systemd-udevd,
systemd-logind and systemd-resolved all died, so there was no udev and
therefore no USB gadget at all.  Note also that systemd refuses a .mount unit
for /sys/fs/selinux ("not loaded properly: Invalid argument") because it
classes it as an API filesystem, so it has to be a oneshot service.

What this does
--------------
Degrades both daemons to "allow everything" when SELinux is not enabled,
instead of aborting.  Access control is a no-op on this system either way --
there is no policy to enforce -- so this loses nothing that was working.
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
    # A cached "is SELinux actually usable" probe, right after the kIsVendor block.
    ("""#ifdef __ANDROID__
static std::string getPidcon(pid_t pid) {""",
     """#ifdef __ANDROID__
// hybris: this system boots with no SELinux policy loaded.  Probe once and
// degrade to permissive rather than aborting.  See patch header.
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

# canFind/canAdd funnel through actionAllowedFromLookup; canList calls
# actionAllowed directly (with mThisProcessContext, which is now nullptr).
# Guard both entry points rather than adding a new member function.
patch('frameworks/native/cmds/servicemanager/Access.cpp', [
    ("""bool Access::actionAllowed(const CallingContext& sctx, const char* tctx, const char* perm,
        const std::string& tname) {
#ifdef __ANDROID__
    const char* tclass = "service_manager";""",
     """bool Access::actionAllowed(const CallingContext& sctx, const char* tctx, const char* perm,
        const std::string& tname) {
#ifdef __ANDROID__
    if (!seUsable()) return true;

    const char* tclass = "service_manager";"""),

    ("""bool Access::actionAllowedFromLookup(const CallingContext& sctx, const std::string& name, const char *perm) {
#ifdef __ANDROID__
    char *tctx = nullptr;""",
     """bool Access::actionAllowedFromLookup(const CallingContext& sctx, const std::string& name, const char *perm) {
#ifdef __ANDROID__
    if (!seUsable()) return true;

    char *tctx = nullptr;"""),
])

# ------------------------------------------------------------- hwservicemanager
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
    // hybris: no SELinux policy is loaded on this system.  Aborting here is what
    // ended the boot (this service is `critical` in its .rc).  See patch header.
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
