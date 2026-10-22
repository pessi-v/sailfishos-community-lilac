#!/bin/sh
# droid-hal-prepare.sh -- runs once, before droid-hal-init.service, every boot.
#
# Historically: fixed the gaps between the phone's real (kept-as-factory) /system
# and this port's own from-source droid-hybris build, and (since §26) replaced
# /vendor and /odm outright with our own matching-generation images.
#
# Since §53: /system gets the same full-image treatment as /vendor/odm did in
# §26, for the same reason -- our own system.img is a genuine, self-consistent,
# single-origin build matching /vendor's own Android-11 generation exactly,
# instead of the phone's real LineageOS 20 (Android 13) partition. Steps 1-4
# and 6-8 below are the *original* per-file reconciliation against that real
# partition; deliberately left in place rather than deleted. Most become
# harmless no-ops once our own system.img is mounted (bind-mounting a file over
# an identical copy of itself does nothing), a couple (the ELOOP fix, the lmkd
# stub) are still genuinely needed against our own image too, and if the image
# is ever missing/bad, everything below still runs exactly as before against
# the real partition -- this step is purely additive.
#
# Idempotent -- safe to run more than once.

set -e

# -2. If UFS enumerated late (the kernel's device-detection retry brings the LUNs up a few
#     seconds into boot, while systemd-udevd is still cold-plugging), udev built the
#     by-name links from incomplete parent data: the intermediate SCSI devices have no
#     PLATFORM_FOLDER/PLATFORM_DEVICE, so /lib/udev/rules.d/998-droid-system.rules ran
#     "ln -s ... /dev/block/platform///by-name/..." and failed. Without /dev/block/
#     bootdevice/by-name, vendor.rmt_storage (modemst1/2, fsc, fsg) and vendor.qseecomd
#     exit in a restart loop, and everything behind them (miscta, tad_static, netmgrd,
#     IMS, qcrild) never starts. Re-trigger the whole ufshc subtree in one call, which
#     udev orders parents first. Verified live: 0 -> 68 by-name links. Does nothing on a
#     normal boot where the links already exist, and never touches mmcblk0p2.
if [ ! -e /dev/block/bootdevice/by-name/modem ] && [ -d /sys/devices/platform/soc/1da4000.ufshc ]; then
    udevadm trigger --action=add --parent-match=/sys/devices/platform/soc/1da4000.ufshc || true
    udevadm settle --timeout=60 || true
fi

# -1. /system, /vendor, /odm themselves (the mountpoint directories every step below mounts
#     onto) are not declared by any package this project builds -- on every rootfs this
#     project has shipped before tonight, they only existed because an early, undocumented
#     manual `mkdir` (or a kickstart %post step never carried into this repo) created them
#     once, and every *incremental* droid-configs/rootfs update since then left them alone.
#     2026-10-05/06: the first genuinely from-scratch rootfs rebuild in a long time (done for
#     the sensorfwd graceful-degradation patch) produced an
#     image with none of the three -- confirmed live: `mount -o loop,rw .../system.img
#     /system` failed with "mount point does not exist", which (since that line is itself
#     guarded with `|| true`) left /system genuinely unmounted; step 1 below then resolved an
#     empty $DEV from `mount | grep " /system "` and ran `mount "" /run/lilac-real-system`
#     unguarded, which is what actually aborted the whole script under `set -e` ("wrong fs
#     type, bad option, bad superblock on ,", exit status 32). Create them defensively here,
#     every boot, the same "purely additive, safe if already present" way every mountpoint
#     this script touches is already handled -- cheaper than chasing down which upstream
#     packaging step is supposed to own this and fixing it there instead.
mkdir -p /system /vendor /odm

# -0. Flash build: there is no odm.img in the rootfs; /odm is the Sony SW_binaries image that was flashed to
#     the `oem` partition. The SD-card build keeps its odm.img and skips this.
#     by-name exists here: step -2 above repairs it if udev missed it.
if [ ! -f /usr/libexec/droid-hybris/odm.img ] && ! grep -q " /odm " /proc/mounts; then
    oem=$(readlink -f /dev/block/bootdevice/by-name/oem 2>/dev/null)
    if [ -b "$oem" ]; then
        mount -o ro "$oem" /odm 2>/dev/null || true
    fi
    [ -e /odm/etc/build.prop ] || \
        echo "droid-hal-prepare: /odm unavailable (oem partition: ${oem:-missing}); flash the Sony SW_binaries image to oem" > /dev/kmsg
fi

# 0. Swap /system for our own from-source system.img outright, the same way
#    step 5 already does for /vendor and /odm -- see this step's own comment
#    there for the full "full image vs per-file overlay" reasoning (PORTING-
#    NOTES.md section 26), which applies here identically now that a real,
#    complete system.img exists (section 53).
#    (guarded with || true: a missing/bad image must never block droid-hal-
#    init.service from starting at all -- falling back to the real factory
#    partition + the per-file overlay below is always safer than an
#    unbootable device.)
if [ -f /usr/libexec/droid-hybris/system.img ] && ! grep -q aosp_g8441 /system/build.prop 2>/dev/null; then
    umount /system 2>/dev/null || true
    mount -o loop,rw /usr/libexec/droid-hybris/system.img /system || true
fi

# 0b. ro.hardware.egl -- surfaceflinger's libEGL.so derives the vendor driver's filename
#     suffix from this property (falling back to ro.board.platform=msm8998 if unset), but
#     nothing in this from-source AOSP build's own device tree sets it, unlike LineageOS's
#     device tree (the sibling hybris port hit and fixed the exact same gap).
#     The real driver is /vendor/lib64/egl/libEGL_adreno.so
#     -- Qualcomm's HAL naming is "adreno" across all their SoCs, never the platform name --
#     so the msm8998 fallback never matches anything. system.img is our own, writable, so
#     fix it at the source instead of a runtime setprop.
if [ -f /system/build.prop ] && ! grep -q "^ro.hardware.egl=" /system/build.prop; then
    echo "ro.hardware.egl=adreno" >> /system/build.prop
fi

# 1. The /system partition (/dev/sda65, Android system-as-root layout, OR our own
#    system.img -- same layout, built by the same underlying AOSP machinery) has
#    its OWN nested system/ subdirectory holding the real content; mounted at
#    /system directly, its own etc -> /system/etc symlink becomes self-
#    referential (ELOOP). Bind the nested subdirectory instead. Runs against
#    whatever step 0 above just mounted -- $DEV below resolves to our own loop
#    device when system.img is in use, the real sda65 otherwise.
if ! test -e /system/etc/linker.config.pb 2>/dev/null; then
    DEV=$(mount | grep " /system " | awk '{print $1}')
    # 2026-09-25: staged under /run, not /mnt. Android's vold runs
    # VolumeManager::unmountAll() at startup, which umount2()s every mount under
    # /mnt/ it can (caught with strace -f -e umount2 on droid-hal-init). /system
    # is a bind of this staging mount, so the per-file binds below propagated to
    # /mnt/real-system/... too, and vold took down every one that wasn't busy at
    # that moment -- surfaceflinger.rc and vold.rc (so section 73's nozygotekill
    # fix never actually held), linkerconfig, logd, gatekeeperd, logcat, ...
    REAL=/run/lilac-real-system
    mkdir -p "$REAL"
    umount /system 2>/dev/null || true
    # 2026-09-22: this step's own guard (linker.config.pb missing) re-triggers on every
    # droid-hal-init restart that happens to race it, because `umount /system` above only
    # undoes the bind-mount onto /system, never the earlier `mount "$DEV" /mnt/real-system`
    # -- so a second pass within the same boot found /mnt/real-system already mounted,
    # aborted here (bare `mount` with no idempotency check, and `set -e` above), and took
    # the whole script down with it. Confirmed live: droid-hal-prepare.service failed with
    # exactly "mount: /mnt/real-system: .../system.img is already mounted.", which meant
    # droid-hal-init started anyway (After=, not Requires=, by design) against a /system
    # that was never actually bind-fixed, immediately hit "interpreter /system/bin/
    # bootstrap/linker64: No such file or directory", and burned through
    # StartLimitBurst=2 in under a second -- taking the whole Android/HAL/zygote/lipstick
    # environment down with it for the rest of the boot. Skip the remount, not the whole
    # step, when /mnt/real-system is already there.
    mount | grep -q " $REAL " || mount "$DEV" "$REAL"
    # 2026-09-24: this line had the exact same class of gap line 75 above was already fixed
    # for, one level up -- unconditional, no idempotency check of its own. If /system gets
    # unmounted by something outside this script between two droid-hal-init restarts (this
    # session found the outer `linker.config.pb` guard above can't be trusted alone: it only
    # checks the SYMPTOM of a correct bind-mount, not whether one is already in place right
    # now), this line re-runs and stacks a brand new bind-mount of the same source on top of
    # the existing one -- which doesn't undo any earlier per-file content change (bind mounts
    # share the same underlying inodes), but DOES hide every later step's own per-file
    # bind-mount (lmkd stub, vold.rc, surfaceflinger.rc, linkerconfig sphal fixes, ...) behind
    # the new mount, since Linux mount stacking makes only the most recent mount at a given
    # path visible. Symptom matched exactly: surfaceflinger/composer crash-looping right after
    # a droid-hal-init restart, on a boot where every one of those per-file fixes should
    # already have been in place. Guard it the same way as line 75 -- but by comparing
    # device:inode, not by grepping `mount`'s output: a bind mount of a subdirectory of an
    # already-mounted filesystem shows up in `mount`/`/proc/mounts` under that filesystem's
    # OWN backing device (e.g. the system.img loop device), never under the bind source path
    # given to the `mount --bind` command itself, so a text match against "/mnt/real-system/
    # system on /system" can never work -- confirmed directly against a live device.
    [ "$(stat -c '%d:%i' /system 2>/dev/null)" = "$(stat -c '%d:%i' "$REAL/system" 2>/dev/null)" ] || \
        mount --bind "$REAL/system" /system
fi

# 2. This port's from-source AOSP-11 build and the phone's factory /system partition
#    have each independently drifted from a common Android 11 base (fmtlib v7 vs v8
#    symbols being the most visible; several other libraries mismatched in the opposite
#    direction). Prefer our own build's copy wherever a library exists under both names,
#    leaving factory-only libraries (proprietary HAL/vendor pieces we don't build) alone.
for f in /usr/libexec/droid-hybris/system/lib64/*.so; do
    name=$(basename "$f")
    target="/system/lib64/$name"
    [ -f "$target" ] && mount --bind "$f" "$target" 2>/dev/null || true
done
for f in /usr/libexec/droid-hybris/system/lib/*.so; do
    name=$(basename "$f")
    target="/system/lib/$name"
    [ -f "$target" ] && mount --bind "$f" "$target" 2>/dev/null || true
done
# These exist in our build but have no same-named counterpart on the factory partition at
# all, so the by-name bind-mount loop above never touches them -- create the mountpoint
# instead. libdexfile_support.so: needed by our libunwindstack.so.
# android.hardware.graphics.common-V1-ndk_platform.so and android.hardware.common-V1-ndk_
# platform.so (the latter is the former's own dependency): LineageOS 20's /system only
# ships the newer android.hardware.graphics.common-V3-ndk.so naming; our own build's
# vendor-side binaries (e.g. android.hardware.graphics.composer@2.3-service, PORTING-
# NOTES.md section 30) are compiled against the older V1_platform names and fail to dlopen
# hwcomposer.msm8998.so as a result, exiting silently.
# android.hardware.radio{,.config,.deprecated}@*.so, android.hidl.*.so, libandroidicu.so,
# libicui18n.so, libicuuc.so (modem/WLAN bring-up): qcrild's own linker error named these
# one at a time (`CANNOT LINK EXECUTABLE ... library "X" not found`) -- they're real,
# genuinely-built parts of our own from-source AOSP-11 tree, but they only ever land inside
# the VNDK (com.android.vndk.v30) and ART (com.android.art) APEX payloads under
# out/target/product/lilac/apex/, which this hybris boot never mounts/activates (nothing
# here runs apexd). Copied straight out of those APEX payloads, stripped, and checked in --
# same treatment as droid-lmkd-stub's binary just below.
# libkeystore_aidl.so, libkeystore_binder.so, libkeystore_parcelables.so (gatekeeperd's own
# dependency chain): genuinely absent from the factory
# partition outright, not just a mismatched version -- gatekeeperd's linker error named them
# one at a time the same way qcrild's did above.
# libstatssocket.so, libstatspull.so, libstats_jni.so: same
# shape again, found via surfaceflinger's own linker errors once system.img (section 53) was
# booting far enough to reach it -- all three live inside the com.android.os.statsd APEX,
# which this port never activates, same as the other APEX payloads above.
# 2026-09-25: + libnativehelper.so (32-bit), for minimediaservice -> /system/lib/
# libmediandk.so; same class as section 68's 32-bit ICU libs -- it only exists in the
# com.android.art APEX payload, which the default namespace doesn't search.
for libname in libdexfile_support.so android.hardware.graphics.common-V1-ndk_platform.so \
               android.hardware.common-V1-ndk_platform.so \
               android.hardware.radio.config@1.0.so android.hardware.radio.config@1.1.so \
               android.hardware.radio.config@1.2.so android.hardware.radio.deprecated@1.0.so \
               android.hardware.radio@1.0.so android.hardware.radio@1.1.so \
               android.hardware.radio@1.2.so android.hardware.radio@1.3.so \
               android.hardware.radio@1.4.so android.hardware.radio@1.5.so \
               android.hidl.allocator@1.0.so android.hidl.memory.block@1.0.so \
               android.hidl.memory.token@1.0.so android.hidl.memory@1.0.so \
               android.hidl.safe_union@1.0.so android.hidl.token@1.0-utils.so \
               android.hidl.token@1.0.so libandroidicu.so libicui18n.so libicuuc.so \
               libkeystore_aidl.so libkeystore_binder.so libkeystore_parcelables.so \
               libstatssocket.so libstatspull.so libstats_jni.so libnativehelper.so; do
    for libdir in lib64 lib; do
        src="/usr/libexec/droid-hybris/system/$libdir/$libname"
        dst="/system/$libdir/$libname"
        if [ -f "$src" ] && [ ! -e "$dst" ]; then
            touch "$dst"
            mount --bind "$src" "$dst"
        fi
    done
done

# 3. servicemanager/hwservicemanager hardcode absolute exec paths (/system/bin/...) that
#    assume a hybris-specific tree is bind-mounted there -- but this port keeps the real
#    factory /system partition instead. Bind our own built binaries onto those real paths.
#    (vndservicemanager doesn't need the same treatment: step 5 below replaces the whole
#    /vendor partition with our own build's, whose own vndservicemanager binary comes along
#    for free -- no separate bind-mount needed, unlike the /system case.)
#    logd/logcat/gatekeeperd: same shape of bug, found
#    later -- the factory partition's own copies are from a newer AOSP generation than this
#    tree (logd/logcat needed android::base::Tokenize; gatekeeperd needed a Parcel::
#    markSensitive() that doesn't exist anywhere in this tree's own source), confirmed by
#    building fresh from this tree's own already-present source and finding no such
#    dependency at all. Same fix, same mechanism, just discovered by chasing a live
#    crash-loop with `logcat` instead of by a build-time symbol audit like the others above.
for svc in servicemanager hwservicemanager logd logcat gatekeeperd; do
    src="/usr/libexec/droid-hybris/system/bin/$svc"
    dst="/system/bin/$svc"
    if [ -f "$src" ] && [ -f "$dst" ]; then
        mount --bind "$src" "$dst"
    fi
done

# 3b. linkerconfig itself (lipstick can't dlopen
#     hwcomposer.msm8998.so via the sphal namespace -- it directly needs libbinder.so, which
#     real VNDK/SP-HAL policy deliberately never exposes to vendor code -- patched
#     system/linkerconfig/contents/namespace/sphal.cc to widen that one allow-list). A prior
#     attempt this same session tried to fix this by statically overwriting the file this
#     port assumed was live (system.img's own /system/bin/linkerconfig, and separately the
#     symlink target it appeared to point at under /apex/com.android.runtime/bin/) from
#     outside a real boot -- confirmed, live, from inside an actual boot session, that neither
#     write ever mattered: /system/bin/linkerconfig there is a genuine, ordinary file (not a
#     symlink) belonging to whichever of system.img/the real factory partition step 0 above
#     actually left mounted, exactly like every other binary in the loop just above. Same
#     mechanism, same reasoning, same safety requirement as that loop: bind-mount, never `cp`
#     -- step 0's own comment already establishes /system may be the real, kept-as-factory
#     partition rather than our own system.img, and this must never risk a write landing on
#     the phone's actual onboard partition instead of something reversible. The patched binary
#     itself was already staged (this session, live) at /apex/com.android.runtime/bin/
#     linkerconfig, on this rootfs's own persistent (SD-card) storage -- bind-mount it over
#     whatever real file is at /system/bin/linkerconfig, the same as any other entry above.
if [ -f /apex/com.android.runtime/bin/linkerconfig ] && [ -f /system/bin/linkerconfig ]; then
    mount --bind /apex/com.android.runtime/bin/linkerconfig /system/bin/linkerconfig
fi

# 4. /system/lib{64,}/{libc,libdl,libdl_android,libm}.so are themselves symlinks into
#    /apex/com.android.runtime/{lib64,lib}/bionic/ -- populate that subdirectory the same
#    way §14 populated apex/.../bin/{linker,linker64}, from our own already-TLS-fixed
#    build. Real init.cpp no longer shadows /apex with a fresh tmpfs (see
#    patch-initcpp-skip-apex-tmpfs.py), so a plain copy here persists correctly.
mkdir -p /apex/com.android.runtime/lib64/bionic /apex/com.android.runtime/lib/bionic
for f in libc.so libdl.so libdl_android.so libm.so; do
    if [ -f "/usr/libexec/droid-hybris/system/lib64/$f" ] && [ ! -e "/apex/com.android.runtime/lib64/bionic/$f" ]; then
        cp "/usr/libexec/droid-hybris/system/lib64/$f" "/apex/com.android.runtime/lib64/bionic/$f"
        chmod 755 "/apex/com.android.runtime/lib64/bionic/$f"
    fi
    if [ -f "/usr/libexec/droid-hybris/system/lib/$f" ] && [ ! -e "/apex/com.android.runtime/lib/bionic/$f" ]; then
        cp "/usr/libexec/droid-hybris/system/lib/$f" "/apex/com.android.runtime/lib/bionic/$f"
        chmod 755 "/apex/com.android.runtime/lib/bionic/$f"
    fi
done

# 4b. Same shape of gap as 4 above, generalized: nothing here runs a real apexd, so every
#     APEX-provided payload this build produces -- native libs, javalib jars, binaries -- sits
#     unused under out/target/product/lilac/apex/<name>/ instead of a real, activated mount.
#     Three completely different subsystems turned out to depend on this, found one at a time
#     chasing real crashes rather than guessed up front:
#       - droid-hal-init's own linkerconfig call (it runs this internally, confirmed by the
#         literal string in the binary) only builds the "sphal" linker namespace when
#         Context::IsVndkAvailable() finds a com.android.vndk.* APEX (system/linkerconfig/
#         contents/context/context.cc) -- without it, surfaceflinger's dlopen of the vendor
#         GLES driver silently fails in the *default* namespace and SIGABRTs deep inside
#         GLESRenderEngine::create().
#       - init.rc's boringssl_self_test_apex{32,64} exec (com.android.conscrypt) and ART's
#         libadbconnection.so plugin (com.android.adbd's libadbconnection_client.so) both
#         crash/reboot the device outright if their APEX payload isn't there.
#       - zygote's own BOOTCLASSPATH (captured live from a real running service's own
#         /proc/<pid>/environ rather than guessed) spans twelve APEX-provided jars
#         (com.android.conscrypt/media/mediaprovider/os.statsd/permission/sdkext/wifi/
#         tethering); missing even one is a silent NoClassDefFoundError deep inside
#         SystemServiceRegistry with no stack trace.
#       - netd itself fails to link ("library libnetd_resolv.so not found") without
#         com.android.resolv populated, which system_server discovers indirectly as a JNI
#         FatalError ("Unable to get socket name") rather than anything naming netd directly.
#     apex::GetActivePackages() (system/apex/libs/libapexutil) and PackageManagerService's own
#     package scanning both just need a real directory with a valid apex_manifest.pb in it --
#     no actual apexd activation required -- so populating each one is enough. com.android.art
#     itself is a special case: this build's own "release" out/.../apex/com.android.art/ only
#     ever gets javalib/ staged (no lib/lib64/bin/apex_manifest.pb at all); the complete payload
#     -- confirmed via its own manifest's name field genuinely reading "com.android.art", not
#     ".debug" -- only exists staged under the com.android.art.debug/ directory. Loop over
#     every APEX this port's own build produces and stage under our overlay source tree.
for apexname in /usr/libexec/droid-hybris/system/apex/*; do
    name=$(basename "$apexname")
    if [ -d "$apexname" ] && [ ! -e "/apex/$name/apex_manifest.pb" ]; then
        mkdir -p "/apex/$name"
        cp -r "$apexname/." "/apex/$name/"
    fi
done

# 4c. system_server's own PackageManagerService resolves "the permissions manager" purely by
#     querying installed packages for an ACTION_MANAGE_PERMISSIONS intent filter
#     (getRequiredPermissionControllerLPr(), frameworks/base's PackageManagerService.java) --
#     it does not care where the package physically lives. But package *discovery* for
#     APEX-provided priv-apps goes through a completely different path than 4b above
#     (ApexManager.scanApexPackagesTraced(), which needs a real apexd to enumerate active
#     packages) -- the ApexManagerFlattenedApex fallback this environment actually exercises
#     returns an empty list unconditionally (frameworks/base's own ApexManager.java), so
#     PermissionController.apk, though genuinely present under
#     /apex/com.android.permission/priv-app/ since 4b, is never scanned as a package at all,
#     and PackageManagerService.<init> throws "There must be exactly one permissions manager;
#     found []" before system_server can finish booting. Copy the APK into a plain
#     /system/priv-app path instead -- the regular, non-APEX-aware partition scan (already
#     working, per the "Not a coreApp" skip messages for every other /system/priv-app entry)
#     picks it up there with no further change needed.
if [ -f /apex/com.android.permission/priv-app/PermissionController/PermissionController.apk ] && \
   [ ! -f /system/priv-app/PermissionController/PermissionController.apk ]; then
    mkdir -p /system/priv-app/PermissionController
    cp /apex/com.android.permission/priv-app/PermissionController/PermissionController.apk \
       /system/priv-app/PermissionController/PermissionController.apk
fi

# 4c-2. Same gap as 4c, same fix, different package: root cause of the zygote/system_server
#     crash loop chased since §59 under the "BinderProxy race" theory turned out to be this --
#     WifiService's constructor (WifiCarrierInfoManager -> WifiContext.getResourcesApkContext())
#     resolves the WiFi resources overlay package by querying PackageManager, gets null back
#     for the same "ApexManagerFlattenedApex returns an empty list" reason as 4c, and then
#     passes that null package name into createPackageContext() -- ContextImpl.
#     createPackageContextAsUser() calls .equals() on it and throws an uncaught
#     NullPointerException, which SystemServer.startOtherServices() treats as fatal: the whole
#     system_server process dies, zygote exits with it, and the entire userspace restarts --
#     every ~15s, all night, on every session since this became reachable. Confirmed via a new
#     logcat-sdlog capture (2026-09-21) after two other theories (WLAN/coproc bring-up, USB-net
#     firewall race, USB-net TX starvation) were investigated and ruled out as the actual boot
#     blocker, though real in their own right. Same fix as 4c: copy the APK into a plain
#     /system/priv-app path the ordinary partition scan already covers.
if [ -f /apex/com.android.wifi/priv-app/ServiceWifiResources/ServiceWifiResources.apk ] && \
   [ ! -f /system/priv-app/ServiceWifiResources/ServiceWifiResources.apk ]; then
    mkdir -p /system/priv-app/ServiceWifiResources
    cp /apex/com.android.wifi/priv-app/ServiceWifiResources/ServiceWifiResources.apk \
       /system/priv-app/ServiceWifiResources/ServiceWifiResources.apk
fi

# 4d. Per-user storage layout system_server expects to already exist, normally prepared by
#     vold during real Android boot (vold.rc, step 7 below, never runs for real here). Without
#     /storage itself, system_server's own early mount of /mnt/user/0 onto /storage fails
#     outright ("Failed to mount /mnt/user/0 to /storage: No such file or directory", a JNI
#     FatalError -- not recoverable, kills system_server). Without the per-user "0"
#     subdirectories under each of /data/{user_de,misc_ce,misc_de,system_ce,system_de}/,
#     installd's own per-package app-data preparation fails for every single package during
#     early boot (PackageManager: "Failed to prepare /data/user_de/0/<pkg> (code 2)"),
#     eventually cascading into the same permissions-manager failure 4c fixes directly.
#     Ownership/mode mirror real vold's own values closely enough to get past these two
#     failures; nothing here is a substitute for real per-user encryption support.
mkdir -p /storage
chmod 0751 /storage
mkdir -p /data/user_de/0 && chown system:system /data/user_de/0 && chmod 0771 /data/user_de/0
mkdir -p /data/misc_ce/0 && chown system:misc /data/misc_ce/0 && chmod 1771 /data/misc_ce/0
mkdir -p /data/misc_de/0 && chown system:misc /data/misc_de/0 && chmod 1771 /data/misc_de/0
mkdir -p /data/system_ce/0 && chown system:system /data/system_ce/0 && chmod 0770 /data/system_ce/0
mkdir -p /data/system_de/0 && chown system:system /data/system_de/0 && chmod 0770 /data/system_de/0
# Same shape, found one step later: installd also maintains a per-app ART profile directory
# tree under /data/misc/profiles -- "Failed to mkdir(/data/misc/profiles/cur/0/<pkg>)" for
# every package, same underlying cause (no real vold ever prepares the "0" subdirectory).
mkdir -p /data/misc/profiles/cur/0 && chown system:system /data/misc/profiles/cur/0 && chmod 0771 /data/misc/profiles/cur/0
mkdir -p /data/misc/profiles/ref/0 && chown system:system /data/misc/profiles/ref/0 && chmod 0700 /data/misc/profiles/ref/0

# 5. Real /vendor and /odm are the phone's factory partitions (Sony stock Android 9 /vendor,
#    LineageOS-repackaged /odm -- neither ever this port's own build,
#    §23/§24) -- a full Android generation older than this port's own Android-11 /system
#    side, and the actual source of most of this port's one-off missing-symbol bugs
#    (incStrongRequireStrong, AServiceManager_waitForService, ...). Unlike /system, both
#    replacement images here are complete, self-consistent, single-origin partition builds
#    already matching each other and our own /system's Android-11 generation -- a full
#    loop-mount swap, not a per-file overlay, per §26's reasoning.
# (each guarded with || true: a missing/bad image must never block droid-hal-init.service
# from starting at all -- falling back to the real factory partition, i.e. today's status
# quo, is always safer than an unbootable device.)
#
# Mounted `rw` here deliberately, not `ro` -- steps 5b/5d below both need to add files that
# don't exist anywhere in vendor.img at all, which needs real write access to the loop
# device's own backing file, not just a mount flag flip. Found the hard way: `mount -o loop,ro ... ; mount -o remount,rw /vendor` later does NOT actually
# grant that -- `mount -o loop,ro` opens the loop device's backing file descriptor read-only
# at `losetup` time, and neither `mount -o remount,rw` nor `blockdev --setrw` reopens it; both
# report success, but every write after either one throws real `dmesg` "Buffer I/O error ...
# lost async page write" and leaves the loop device unable to even remount `ro` again cleanly.
# 5b's own `mount -o remount,rw /vendor` has almost certainly been silently failing exactly
# this way since it was written -- this fixes it too, not just 5d's new addition. Remounted
# back to `ro` once, at the very end of 5d below, after every writer in this script is done --
# matching real vendor-partition semantics for the rest of the boot, and confirmed to actually
# work now that the loop device's own fd was opened read-write from the start.
# 2026-10-14 (flash build): the Android-built vendor.img is created with exactly as many
# inodes as it has files (1056 of 1056 used), so on a clean image every `touch "$dst"` placeholder in 5b..5f fails
# with "No space left on device" -- the SD builds only worked because the persistent image had accumulated
# placeholder files from earlier manual testing. A writable overlay (image read-only below, tmpfs above) gives
# every step below the same view as before without needing inodes in the image, and nothing is ever written to it.
if [ -f /usr/libexec/droid-hybris/vendor.img ] && ! grep -q '^overlay /vendor ' /proc/mounts; then
    umount /vendor 2>/dev/null || true
    mkdir -p /run/vendor-lower /run/vendor-upper
    if mount -o loop,ro /usr/libexec/droid-hybris/vendor.img /run/vendor-lower && \
       mount -t tmpfs -o size=8m tmpfs /run/vendor-upper && \
       mkdir -p /run/vendor-upper/u /run/vendor-upper/w && \
       mount -t overlay overlay -o lowerdir=/run/vendor-lower,upperdir=/run/vendor-upper/u,workdir=/run/vendor-upper/w /vendor; then
        :
    else
        echo "droid-hal-prepare: vendor overlay failed, falling back to the plain image" > /dev/kmsg
        umount /run/vendor-upper 2>/dev/null || true
        umount /run/vendor-lower 2>/dev/null || true
        mount -o loop,rw /usr/libexec/droid-hybris/vendor.img /vendor || true
    fi
fi
if [ -f /usr/libexec/droid-hybris/odm.img ] && ! grep -q 11_4.14_yoshino_v8 /odm/etc/build.prop 2>/dev/null; then
    umount /odm 2>/dev/null || true
    mount -o loop,ro /usr/libexec/droid-hybris/odm.img /odm || true
fi

# 5-stock. Sony's own stock-firmware partitions are the source of the few proprietary files that are in
#     neither SW_binaries blob: the four sensor files in 5d come from
#     the real `vendor` partition, the Bluetooth firmware in 5c from the real `bluetooth` partition.
#     Both are byte-identical to Sony's 47.2.A.11.234 firmware and are never written by anything. The
#     package REQUIRES the phone to carry that stock firmware (the same prerequisite as for modem,
#     dsp, TA and persist); nothing proprietary is shipped in the rootfs. Mounted read-only on a
#     private mountpoint, because the vendor.img loop mount above shadows the real /vendor.
STOCK_VENDOR=/run/stock-vendor
mkdir -p "$STOCK_VENDOR"
if ! grep -q " $STOCK_VENDOR " /proc/mounts; then
    sv=$(readlink -f /dev/block/bootdevice/by-name/vendor 2>/dev/null)
    if [ -b "$sv" ]; then
        mount -o ro "$sv" "$STOCK_VENDOR" 2>/dev/null || true
    fi
    [ -f "$STOCK_VENDOR/bin/sensors.qti" ] || \
        echo "droid-hal-prepare: stock vendor partition unavailable ($sv): sensors will not work; the phone must carry Sony stock firmware 47.2.A.11.234" > /dev/kmsg
fi

# 5a. ro.hardware.sensors -- sensorfwd's own HIDL-passthrough loader (hw_get_module()) only
#     tries the "ssc" HAL variant name (sensors.ssc.so -- the real file this device ships,
#     section 5d/5f) when this property names it explicitly; its default fallback list
#     (board/product/platform names, then "default") never includes "ssc". Same class of gap
#     as 0b's ro.hardware.egl -- nothing in this from-source AOSP build's own device tree sets
#     it. Confirmed live, 2026-10-01/02 night: without this, sensorfwd's probe exhausts its
#     whole candidate list and every sensor (ALS/proximity/accelerometer/orientation/
#     magnetometer) fails to instantiate, even with 5f's library bind-mount already in place --
#     found the hard way, as a second, separate missing piece after 5f alone didn't fix it.
#     vendor.img is mounted rw here already (step 5); fix it at the source, not a runtime
#     setprop, matching 0b's own reasoning for system.img.
if [ -f /vendor/build.prop ] && ! grep -q "^ro.hardware.sensors=" /vendor/build.prop; then
    echo "ro.hardware.sensors=ssc" >> /vendor/build.prop
fi

# 5b. Bluetooth's real vendor driver (libbthost_if.so/libbtnv.so -- the actual chip-specific
#     firmware-download/NV-data implementation the closed HAL dlopen()s at runtime) is present
#     on /odm but not /vendor. Vendor HAL processes only search /vendor's own lib dirs (plus a
#     few others via the sphal linker namespace, which does NOT include /odm) -- confirmed live,
#     without this, `android.hardware.bluetooth@1.0-service-qti`
#     immediately reports `chip_ver: 0x0, INVALID_CHIP_VERSION` and self-kills, in a tight
#     restart loop, forever. The real permanent fix is adding these to vendor.img itself at
#     build time; this is the same "stage it live every boot" stopgap this whole script already
#     uses elsewhere, needed here because our own vendor.img's backing loop device is mounted
#     read-only (matching real vendor-partition semantics) so a placeholder file must be created
#     before it can be bind-mounted over. (Step 5 above now mounts it `rw` from the start for
#     exactly this reason -- no remount needed here anymore, see that step's own comment.)
if [ -d /odm/lib64 ] && [ -d /vendor/lib64 ]; then
    for f in libbthost_if.so libbtnv.so; do
        for libdir in lib64 lib; do
            src="/odm/$libdir/$f"
            dst="/vendor/$libdir/$f"
            [ -f "$src" ] || continue
            mount | grep -q " $dst " && continue
            [ -f "$dst" ] || touch "$dst" 2>/dev/null || continue
            mount --bind "$src" "$dst" 2>/dev/null || true
        done
    done
fi

# 5c. Even with 5b's vendor driver in place, the BT HAL still failed: it opens /dev/ttyHS0 fine but gets no valid response from the chip and
#     reports chip_ver: 0x0/INVALID_CHIP_VERSION within ~30ms, because it never finds the real
#     firmware to stream down that UART (`.../image/crbtfw21.tlv` etc). Those blobs are NOT in
#     Sony's SW_binaries_for_Xperia_Android_11_4.14_v8a_yoshino.img -- confirmed directly by
#     mounting and searching the whole thing: it has only the two libraries 5b already stages,
#     no firmware/NV blobs at all. Real firmware only ever lived on the phone's own dedicated
#     `bt_firmware` partition (confirmed present and correct there, `/dev/sda39`), which our own
#     vendor.img swap (step 5) shadows outright since it replaces /vendor wholesale, including
#     its own empty bt_firmware/ subdirectory.
#     Deliberately NOT mounting that real device partition here, even though it works: this
#     script should never depend on what happens to be present on a specific physical device's
#     onboard storage -- these 8 files (~237KB total) are checked into this repo instead
#     (`sparse/usr/libexec/droid-hybris/vendor/bt_firmware/image/`), copied once, by hand, off
#     this device's own real bt_firmware partition (a real, working Xperia XZ1 Compact,
#     Sept. 2019 vintage per their mtimes) -- the same "stage our own checked-in copy" pattern
#     as everything else in this script, not a new exception to it.
#     CORRECTION (found 2026-09-23, first real boot with this step live): the assumption above
#     was wrong -- step 5's vendor.img swap does NOT shadow /vendor/bt_firmware. The real
#     `/dev/sda39` partition is still mounted there directly (Android's own fstab, independent
#     of /vendor's own backing image), read-only, and empty on this device -- so `mkdir -p
#     /vendor/bt_firmware/image` failed outright ("Read-only file system"), even right after
#     `mount -o remount,rw /vendor`, because that remount only affects the outer /vendor
#     mountpoint, not this separately-mounted child. Fixed by overlaying a tmpfs at
#     /vendor/bt_firmware itself instead of trying to remount the real partition rw -- writing
#     to the real sda39 partition, even just an empty directory, would be a real, persistent
#     write to this specific physical device's onboard storage, exactly what this step's own
#     rationale above says to avoid; tmpfs keeps this entirely in-memory and gone on reboot.
# (171.9) The Bluetooth firmware is no longer copied from the repo: the real `bluetooth` partition is
#     mounted over /vendor/bt_firmware with the same options Android's fstab uses (uid bluetooth, so
#     the HAL, which runs as bluetooth, can read the 0440 files). Only needed because the vendor.img
#     loop mount hides the real partition's mount underneath.
if [ -d /vendor/bt_firmware ] && [ ! -e /vendor/bt_firmware/image/apbtfw10.tlv ]; then
    bt=$(readlink -f /dev/block/bootdevice/by-name/bluetooth 2>/dev/null)
    if [ -b "$bt" ]; then
        mount -t vfat -o ro,uid=1002,gid=3002,fmask=0337,dmask=0227,codepage=437,iocharset=iso8859-1,shortname=lower \
            "$bt" /vendor/bt_firmware 2>/dev/null || true
    fi
    [ -e /vendor/bt_firmware/image/apbtfw10.tlv ] || \
        echo "droid-hal-prepare: Bluetooth firmware not found on the bluetooth partition ($bt); the phone must carry Sony stock firmware" > /dev/kmsg
fi

# 5d. vendor.sensors.qti -- the AP-side SSC companion daemon sensors.ssc.so needs, genuinely
#     absent from this port's own from-source /vendor build: proprietary, SODP source can't produce it, sourced instead from this same
#     physical device's own LineageOS install on internal storage -- a deliberate, flagged
#     exception to this project's own "vendor is source, not a device dump" premise. Same
#     touch/bind-mount shape as 5b above (already `rw` from step 5, no remount needed here).
#     Also bind-mounts our own sensors.rc over the real one, since this is a genuinely NEW
#     service definition droid-hal-init needs to parse, not just a backing library swap.
if [ -f "$STOCK_VENDOR/bin/sensors.qti" ] && [ -d /vendor/bin ]; then
    for relpath in bin/sensors.qti etc/sensors/sensor_def_somc_product.conf \
                   lib64/libsensor1.so lib64/libsensor_reg.so; do
        src="$STOCK_VENDOR/$relpath"
        dst="/vendor/$relpath"
        [ -f "$src" ] || continue
        mount | grep -q " $dst " && continue
        [ -f "$dst" ] || touch "$dst" 2>/dev/null || continue
        mount --bind "$src" "$dst" 2>/dev/null || true
    done
    # 2026-10-14: bionic's linker searches /odm/lib64 BEFORE /vendor/lib64, and Sony's
    # oem blob carries its own, different libsensor1.so / libsensor_reg.so (no sensor1_has_acessto_directory),
    # so sensors.qti (stock) crash-looped with "cannot locate symbol" even though /vendor had the right file.
    # Put the stock copies over the /odm ones too (bind over a file on a read-only mount works).
    for lib in libsensor1.so libsensor_reg.so; do
        [ -f "$STOCK_VENDOR/lib64/$lib" ] && [ -f "/odm/lib64/$lib" ] || continue
        mount | grep -q " /odm/lib64/$lib " || \
            mount --bind "$STOCK_VENDOR/lib64/$lib" "/odm/lib64/$lib" 2>/dev/null || true
    done
    if [ -f /usr/libexec/droid-hybris/vendor/etc/init/sensors.rc ]; then
        mount | grep -q ' /vendor/etc/init/sensors.rc ' || \
            mount --bind /usr/libexec/droid-hybris/vendor/etc/init/sensors.rc \
                         /vendor/etc/init/sensors.rc 2>/dev/null || true
    fi
fi

# 5e. android.hardware.biometrics.fingerprint@2.1-service.sony -- the from-source-built
#     fingerprint HAL and its service/vintf definitions were
#     staged into this overlay tree at the time, but no bind-mount step was ever added to
#     actually place them on /vendor -- confirmed absent (no process, no hwservicemanager
#     registration, no .rc anywhere on a live device) despite the files sitting right here the
#     whole time. The working chain this unblocks (fpslave -> sailfish-fpd -> FPSTATE_IDLE) is
#     documented in full in section 50; this step is the missing last link. Same touch/bind-
#     mount shape as 5b/5d above.
#     ⚠️ 2026-10-02: enabling this HAL service surfaced a new, real, unexplained instability --
#     restarting/stopping `sailfish-fpd` (and, once, just letting it cycle through its own
#     normal startup retries) was immediately followed by the whole device going fully
#     unresponsive (no USB enumeration at all, not even charge-only mode -- a harder hang than
#     any previously-documented crash-loop) twice in the same session, each requiring a full
#     physical power cycle to recover. Root cause not yet found. The HAL binary/service itself
#     still gets deployed here deliberately (so the files and plumbing are in place for whoever
#     investigates next), but `sailfish-fpd.service` was masked by this package by default.
#     2026-10-08 UPDATE -- RESOLVED, the mask is gone: the hangs were not fingerprint-specific
#     (see the VINTF note just below). With that fixed,
#     sailfish-fpd + fpslave + this HAL run stably and enrolment/unlock work, so the service is
#     enabled like on any other device. History kept below for context; sections 47-50 and
#     133 have the earlier session logs.
#     2026-10-06 correction: the VINTF fragment this step used to stage
#     (etc/vintf/manifest/android.hardware.biometrics.fingerprint.xml) is a byte-for-byte
#     duplicate of the android.hardware.biometrics.fingerprint HAL entry already present in the
#     main, build-time-merged /vendor/etc/vintf/manifest.xml -- confirmed live via
#     hwservicemanager's own startup log: "VINTF parse error: Cannot add manifest fragment
#     .../android.hardware.biometrics.fingerprint.xml: HAL ... has a conflict." libvintf treats
#     any duplicate HAL entry between the static manifest and a runtime fragment as a hard
#     parse failure for the ENTIRE device manifest, not just the duplicated HAL -- every single
#     getDeviceHalManifest() call for the rest of boot fails outright, which is why completely
#     unrelated HALs (android.hardware.graphics.composer@2.3, keymaster@3.0, configstore@1.1,
#     vendor.display.config@1.10, vendor.qti.hardware.display.allocator@3.0, ...) all failed to
#     register, and why the composer service's own IComposer registration failure cascaded into
#     a native SIGABRT in its HWCUEvent uevent thread (destroy-on-registration-failure races its
#     own still-running background thread) -- blocking lipstick from ever getting a working
#     hwcomposer client. Almost certainly also the real explanation for the still-unexplained
#     "whole device unresponsive" hang logged just above (2026-10-02): once this same conflict
#     was already silently crippling HAL discovery device-wide, restarting/stopping fpd was
#     just the straw that tipped an already-degraded boot into a full hang under load, not a
#     fingerprint-specific bug. Fix: stop staging the redundant fragment -- the binary and .rc
#     still get deployed (so the files and plumbing stay in place for whoever investigates
#     sailfish-fpd's own masked status next), only the conflicting manifest duplicate is
#     dropped.
#     2026-10-06, same day, second half: no longer mounting it here isn't enough on its own --
#     vendor.img is a persistent image carried forward across every redeploy (never rebuilt from
#     scratch), so the empty placeholder file an earlier `touch "$dst"` created the first time
#     this step ever ran is still physically sitting on it, and libvintf parses every file under
#     /vendor/etc/vintf/manifest/ as a manifest fragment regardless of whether this script is the
#     one that put it there. Confirmed live on a genuinely clean boot of the rebuilt image: same
#     device-wide HAL registration failure, new error ("Illformed file: .../android.hardware.
#     biometrics.fingerprint.xml: Not a valid XML" instead of the earlier "has a conflict"), same
#     underlying cause -- a file at that path that shouldn't exist. Remove it outright, every
#     boot, idempotently (`-f` makes a no-op of removing something already gone).
rm -f /vendor/etc/vintf/manifest/android.hardware.biometrics.fingerprint.xml
if [ -f /usr/libexec/droid-hybris/vendor/bin/hw/android.hardware.biometrics.fingerprint@2.1-service.sony ] && [ -d /vendor/bin/hw ]; then
    for relpath in bin/hw/android.hardware.biometrics.fingerprint@2.1-service.sony \
                   etc/init/android.hardware.biometrics.fingerprint@2.1-service.sony.rc; do
        src="/usr/libexec/droid-hybris/vendor/$relpath"
        dst="/vendor/$relpath"
        [ -f "$src" ] || continue
        mount | grep -q " $dst " && continue
        [ -f "$dst" ] || touch "$dst" 2>/dev/null || continue
        mount --bind "$src" "$dst" 2>/dev/null || true
    done
fi

# 5f. android.hardware.sensors@2.0.so -- sensorfwd's own HIDL-passthrough loader (distinct from
#     the legacy hw_get_module() lookup 5d's sensors.qti/sensors.ssc.so fix already covers)
#     searches only /odm/lib64, /vendor/lib64, /odm/lib64/egl and /vendor/lib64/hw for this
#     library and gives up if none of them have it -- confirmed via strace, 2026-10-01 night.
#     The library itself is not missing from this build at all: it's a genuine, already-present
#     part of our own from-source system.img (plain /system/lib64, no overlay needed, unlike
#     section 4b's APEX-only libraries) -- sensorfwd just never looks under /system for it. Same
#     by-name bind-mount shape as section 2's loop, but /system -> /vendor instead of /system ->
#     /system, since nothing here replaces a whole partition the way step 5 does for vendor/odm.
#     2026-10-02 correction: the first version of this step checked `[ ! -e dst ]` (file
#     existence) instead of `mount | grep -q " dst "` (actually mounted) like every other step
#     in this section -- not idempotent against droid-hal-init restarting mid-boot (a real,
#     already-documented thing this project's init does, section 9.22/9.24): the second pass
#     found the first pass's own empty placeholder file already sitting at $dst, treated that as
#     "already done", and skipped re-establishing the bind-mount entirely, leaving a 0-byte file
#     in place of the real library -- confirmed live the hard way (sensorfwd failed identically
#     to never having this fix at all, since an empty file fails to load exactly like a missing
#     one). Fixed to use the same mount-state check as 5b/5d/5e.
#     2026-10-04 generalization: fixing 5f's one file (android.hardware.sensors@2.0.so) alone
#     was not enough to actually get sensorfwd past probe-failure -- the real `sensors.ssc.so`
#     HAL blob (loaded via 5d's legacy hw_get_module() path, confirmed via `strace -f` following
#     every openat() it makes) pulls in a long transitive chain of its own HIDL/multihal runtime
#     dependencies that are *also* missing from /vendor/lib64 the exact same way: libutils.so,
#     libhidlbase.so, android.hardware.sensors@{1.0,2.0,2.1}.so, the
#     android.hardware.sensors@2.0-ScopedWakelock.so helper (a real AOSP `cc_library_shared`,
#     hardware/interfaces/sensors/common/default/2.X/multihal/Android.bp, simply never in this
#     product's build graph until now --md section 135), several
#     android.hardware.graphics.mapper@*.so and vendor.qti.hardware.display.mapper@{1.0,1.1,3.0}.so
#     versions (display already works fine via a completely different HWC2 path -- these are
#     needed by this *separate* sensors probe only), libprocessgroup.so, libbase.so, libfmq.so,
#     libpower.so, libbinder.so, libcgrouprc.so, android.system.suspend@1.0.so, and others.
#     Chasing each one individually (as the paragraph above did for just the first one) does not
#     scale and will keep breaking again every time this probe's own dependency closure changes
#     (e.g. after any AOSP component version bump) -- so this step is a loop over every .so this
#     port's own build already produces in the droid-hybris system overlay, bind-mounting
#     whichever ones are missing from /vendor/lib64, rather than a hardcoded list of names.
#     Safe by construction: it only ever fills a gap (skips only a real, non-empty vendor file --
#     `[ -s "$dst" ]`, size check, not mere existence), never overwrites a real vendor-specific
#     file that's already there, so it cannot regress any other vendor process that relies on its
#     own /vendor/lib64 copy taking priority. Deliberately *not* `[ -e "$dst" ]` (existence only)
#     like an earlier draft of this step used: this exact card's `vendor.img` already carries
#     forward hundreds of zero-byte placeholder files from manual by-hand testing earlier the same
#     day this step was written (every `touch "$dst"` from that testing left a real, persisted
#     0-byte file sitting in the loop-mounted filesystem, carried forward across deployments same
#     as any other vendor.img content) -- an existence-only check would see each of those and
#     skip re-establishing the real bind-mount, silently reproducing section 133's own
#     already-documented idempotency bug in a new place. A size check correctly treats a 0-byte
#     leftover the same as "missing" while still never touching a real, differently-named vendor
#     file that happens to already be there with real content.
if [ -d /usr/libexec/droid-hybris/system/lib64 ] && [ -d /vendor/lib64 ]; then
    for src in /usr/libexec/droid-hybris/system/lib64/*.so; do
        [ -f "$src" ] || continue
        name=$(basename "$src")
        dst="/vendor/lib64/$name"
        mount | grep -q " $dst " && continue
        [ -s "$dst" ] && continue
        touch "$dst" 2>/dev/null || continue
        mount --bind "$src" "$dst" 2>/dev/null || true
    done
fi

# 5f2. /dev/pmsg0 -- the last blocker found chasing the same sensors.ssc.so probe failure as 5f
#      above: once every missing library from 5f is fixed, the
#      HAL blob's own init code does `open("/dev/pmsg0", O_WRONLY)` and exits(1) immediately if
#      that fails, confirmed via `strace -f` with no further syscalls in between. This is
#      Android's persistent-log pseudo-device, created by the kernel's pstore/pmsg driver only
#      once an actual ramoops backend (a reserved-memory region in the devicetree) is attached --
#      this kernel has `CONFIG_PSTORE_PMSG=y` built in (the driver exists) but no such devicetree
#      region, so the real character device is never instantiated. Wiring up a genuine ramoops
#      region is a real devicetree + kernel rebuild + reboot-test undertaking for a feature this
#      port has no other use for (persistent crash logs across reboots); symlinking the path to
#      /dev/null instead is enough to satisfy this one open() call and matches this project's
#      existing pragmatism elsewhere (same shape of trade-off as masking sailfish-fpd.service).
#      /dev is tmpfs, recreated every boot, so this needs to be redone here every time, not just
#      once.
if [ ! -e /dev/pmsg0 ]; then
    ln -sf /dev/null /dev/pmsg0 2>/dev/null || true
fi

# 5f3. sensors.ssc.so -- the ROOT CAUSE of "hw_get_module() probe failed" for every sensor
# Sony's /odm blob ships TWO different libraries with this
#      name: /odm/lib{,64}/sensors.ssc.so is the *legacy* HAL (exports HMI = HAL_MODULE_INFO_SYM,
#      what sensors_leg.ssc in device/sony/yoshino/platform.mk refers to), while
#      /odm/lib{,64}/hw/sensors.ssc.so is a Sensors-HAL-2.0 *sub-HAL* for a multi-HAL service
#      ("QTI-SubHAL"; exports sensorsHalGetSubHal, NO HMI). hw_get_module() only looks in
#      <dir>/hw/, finds the sub-HAL first, fails with "HAL: load: couldn't find symbol HMI"
#      (the probe runs in a forked child that then exits 1) and never reaches the legacy library
#      one directory up. Nothing here runs a multi-HAL service (only android.hardware.sensors@1.0),
#      so put the legacy library where hw_get_module() looks. Verified live 2026-10-08: with this
#      bind-mount the probe passes and the light/proximity/accelerometer adaptors instantiate.
#      Guarded on the hw/ copy really being the sub-HAL so a different blob is left alone.
for d in lib64 lib; do
    hw="/odm/$d/hw/sensors.ssc.so"
    leg="/odm/$d/sensors.ssc.so"
    if [ -f "$hw" ] && [ -f "$leg" ] && grep -q sensorsHalGetSubHal "$hw" 2>/dev/null \
            && ! grep -q " $hw " /proc/mounts; then
        mount --bind "$leg" "$hw" || true
    fi
done

# 5d3. Who initialises ACDB (audio calibration). The kernel's audio calibration driver (msm_audio_cal) accepts the
#      allocations of ONE process. Two HAL instances run on this device: Android's audio.service (started first, ~75 s) and the one
#      PulseAudio loads in-process (user session, ~140 s); the second always failed with "AUDIO_ALLOCATE_CALIBRATION result = -1 /
#      ACDB initialization failed", and PulseAudio's HAL is the one that carries all real playback and recording. Make the ACDB files
#      readable only for group "users" (defaultuser is a member, the audioserver user is not): the Android-side HAL then fails its init
#      harmlessly and PulseAudio's HAL gets the calibration. (This runs while /vendor is still writable, see 5g.)
if [ -d /vendor/etc/acdbdata ]; then
    chgrp users /vendor/etc/acdbdata /vendor/etc/acdbdata/* 2>/dev/null || true
    chmod 750 /vendor/etc/acdbdata 2>/dev/null || true
    chmod 640 /vendor/etc/acdbdata/*.acdb 2>/dev/null || true
fi

# 5g. Every writer to /vendor above is done -- remount it back to `ro` once, here, matching
#     real vendor-partition semantics for the rest of the boot. This is the one place in the
#     whole script that does it, now that step 5's own mount is `rw` from the start (see that
#     step's comment for why the old ro-then-remount-rw sequence never actually worked).
mount -o remount,ro /vendor 2>/dev/null || true

# 6. Real /system/bin/lmkd fails to link (missing bionic symbol pidfd_open -- a version-skew
#    bug in the LineageOS 18.1 tree's own component sync)
#    and crash-loops every ~5s forever; since it's `critical` and sys.boot_completed is never
#    set in this environment, its 5th crash trips a real AOSP init safety net that kills the
#    whole droid-hal-init supervisor, deterministically, every single boot. SailfishOS
#    doesn't use lmkd at all -- bind our own never-exiting stub over it instead of trying to
#    fix the actual symbol mismatch.
if [ -f /usr/libexec/droid-lmkd-stub/lmkd ] && [ -f /system/bin/lmkd ]; then
    mount --bind /usr/libexec/droid-lmkd-stub/lmkd /system/bin/lmkd
fi

# 7. Real /system/etc/init/vold.rc (the factory partition's own, LineageOS/Sony-shipped
#    file -- our own from-source build's vold.rc has no such line) sets
#    `reboot_on_failure reboot,vold-failed`. vold does real Android FDE/FBE volume
#    management this port has no use for (Sailfish mounts everything its own way, see
#    droid-hal-prepare.sh's own step 1 and 5); it reliably fails here, same as
#    lmkd/apexd already did (sections 16, 36/37), but `reboot_on_failure` turns THIS
#    one's expected crash into init deliberately rebooting the entire device --
#    confirmed directly in a live kmsg capture: "Reboot start, reason: reboot,vold-
#    failed, reboot_target: vold-failed", ~130s into a boot that was otherwise
#    progressing normally. Bind our own copy (identical
#    except for that one line) over the real file so vold crash-loops harmlessly like
#    logd/qseecomd/keymaster-3-0 already do, instead of taking the whole device down.
if [ -f /usr/libexec/droid-vold-norebootfix/vold.rc ] && [ -f /system/etc/init/vold.rc ]; then
    mount --bind /usr/libexec/droid-vold-norebootfix/vold.rc /system/etc/init/vold.rc
fi

# 7b. Real /system/etc/init/surfaceflinger.rc sets `onrestart restart zygote` -- real
#     AOSP's own stock behaviour, since on real hardware a dead display server means no app
#     can render anyway, so a crash is treated as catastrophic enough to nuke the whole app
#     framework and start clean. In this architecture `surfaceflinger` is not the real
#     display server -- `lipstick` is -- and the two fight over
#     the same single-client composer HAL service (section 73's own captured backtrace:
#     `SurfaceFlinger::init() -> createHWComposer() -> HWComposer() -> Hwc2::impl::Composer::
#     Composer()` aborting via `__android_log_assert`). Confirmed live via a real `rich-core`
#     capture (only possible once section 72's `CORE_SIZE_LIMIT` fix let a core actually get
#     written): every one of these crashes was firing `onrestart restart zygote` for real,
#     and the resulting zygote restart could not even complete --
#     `DisplayManagerService.<init>() -> SurfaceControl.getCompositionColorSpaces()` throws a
#     NullPointerException querying a `SurfaceFlinger` that is, per the same root cause, still
#     down -- which `SystemServiceManager.startService()` treats as fatal, killing zygote
#     again immediately. That second failure is self-sustaining and fires every 1-3 seconds
#     independent of `surfaceflinger`'s own crash rate once it starts (776 total crashes in
#     one session) -- almost certainly the single largest source of this project's long-
#     running CPU/IO churn and the SSH-unreachable-during-a-healthy-boot symptom (sections 63/
#     70/71). Bind our own copy (identical except for the one `onrestart` line) over the real
#     file, the same mechanism as step 7's `vold.rc` fix just above -- `surfaceflinger` can
#     still crash-loop against `lipstick` harmlessly on its own, but can no longer take zygote
#     down with it.
if [ -f /usr/libexec/droid-surfaceflinger-nozygotekill/surfaceflinger.rc ] && [ -f /system/etc/init/surfaceflinger.rc ]; then
    mount --bind /usr/libexec/droid-surfaceflinger-nozygotekill/surfaceflinger.rc /system/etc/init/surfaceflinger.rc
fi

# 8. Modem/ADSP/WLAN firmware (modem.mdt, adsp.mdt, WLAN board-data bdwlan.*, ...) does
#    NOT live inside /vendor's own filesystem at all -- `/vendor/firmware_mnt` is only
#    ever a bare mountpoint (confirmed empty on both our own vendor.img and the real
#    factory partition). The actual content is on its own dedicated VFAT partition,
#    PARTLABEL=modem (/dev/block/bootdevice/by-name/modem), normally mounted here by
#    vold at boot -- which this port never runs for real (vold.rc, step 7 above).
#    Without this mount, PIL's own request_firmware() can't find modem.mdt and the
#    modem never boots at all (`Failed to locate modem.mdt(rc:-11)`), no matter how
#    correct everything else in the modem bring-up chain is. Mount the raw partition node directly, never a by-name symlink (those
#    have their own, separate UFS-enumeration-timing intermittency elsewhere in this
#    port's history) -- resolved once, here, from the by-name symlink that already
#    exists by the time this script runs.
if [ -f /vendor/firmware_mnt/image/modem.mdt ] 2>/dev/null; then
    : # already mounted (idempotent re-run of this script)
elif [ -e /dev/block/bootdevice/by-name/modem ]; then
    mount -o ro /dev/block/bootdevice/by-name/modem /vendor/firmware_mnt || true
fi

# 9b. Android's own camera sounds. cameraserver plays VideoRecord.ogg / VideoStop.ogg itself, through
#     MediaPlayer -> AudioFlinger -> Android's audio HAL (audio.service). PulseAudio's in-process HAL plays the Sailfish camera sounds
#     (ngfd) on the same PCM device (pcmC0D0p, deep-buffer-playback), which only one HAL can open: the loser gets EBUSY, falls into
#     standby and retries every ~200 ms, and each retry re-routes the codec and re-uploads calibration. That retry storm stalls the
#     microphone for 0.5-0.9 s at a time during video recording. Android's copies are made empty so only the Sailfish sounds play.
for f in VideoRecord VideoStop; do
    dst="/system/product/media/audio/ui/$f.ogg"
    [ -f "$dst" ] || continue
    mount | grep -q " $dst " || mount --bind /dev/null "$dst" 2>/dev/null || true
done

touch /run/droid-hal-prepare.done
