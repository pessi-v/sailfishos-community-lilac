/*
 * lmkd_stub.c -- replaces the real /system/bin/lmkd with a binary that never exits.
 *
 * Root cause, the real /system/bin/lmkd (Android's
 * low-memory-killer daemon) fails to even link in this environment --
 * `CANNOT LINK EXECUTABLE "/system/bin/lmkd": cannot locate symbol "pidfd_open"` -- our
 * own built libc.so genuinely doesn't export that bionic-API-31 symbol, a version-skew
 * bug in the LineageOS 18.1 tree's own component sync, not something this port introduced.
 * lmkd crash-loops every ~5s forever as a result, and because it's marked `critical` in its
 * own .rc and `sys.boot_completed` is never set anywhere in this hybris/SailfishOS boot
 * chain, its 5th crash trips a real, intentional AOSP init safety net
 * (system/core/init/service.cpp, Service::Reap()) that calls LOG(FATAL) -> abort(),
 * killing droid-hal-init's entire "second stage" supervisor process outright --
 * deterministically, on every single boot, around the 150-second mark.
 *
 * SailfishOS doesn't use Android's own low-memory-killer at all (mce/lipstick manage memory
 * pressure their own way), so the fix is to make lmkd disappear as a problem entirely rather
 * than repair the actual symbol mismatch: replace it with a binary that starts instantly and
 * simply never exits, so it can never crash, never trigger the crash-counting logic, and
 * never needs restarting.
 *
 * A `#!/system/bin/sh` shebang script (`exec sleep infinity`) was tried first and did NOT
 * work -- identical crash loop, identical exit status 1, despite running fine when invoked
 * directly as root. The failure is specific to how droid-hal-init itself invokes the
 * service (fork, drop to `user lmkd`/`group lmkd system readproc`, apply `capabilities
 * DAC_OVERRIDE KILL IPC_LOCK SYS_NICE SYS_RESOURCE`, *then* exec) -- not fully root-caused,
 * but a genuine statically-linked ELF binary (this file) sidesteps the whole question by
 * avoiding shebang/interpreter resolution entirely.
 *
 * Deliberately freestanding (no libc, no crt, no startup machinery) -- the raw nanosleep
 * syscall in an infinite loop is all it needs to do, and freestanding means it has no
 * dependency on bionic at all, so it can never hit a missing-symbol problem of its own.
 *
 * Built on the AOSP tree's own bundled clang (any recent clang with an aarch64 backend
 * works fine, but this uses the exact one used when this file was first compiled and
 * validated, to keep the build reproducible):
 *
 *   clang -target aarch64-linux-gnu -nostdlib -static -fuse-ld=lld \
 *       -o lmkd device-integration/hybris/droid-configs/sparse/usr/libexec/droid-lmkd-stub/lmkd_stub.c
 *
 * clang path used originally (from this repo's own AOSP source checkout on the build host):
 *   prebuilts/clang/host/linux-x86/clang-r383902b1/bin/clang
 *
 * The resulting binary is checked into this repo directly (it's ~1.3KB) at
 * device-integration/hybris/droid-configs/sparse/usr/libexec/droid-lmkd-stub/lmkd --
 * droid-hal-prepare.sh bind-mounts it over the real /system/bin/lmkd on every boot.
 */

void _start(void) {
    struct { long tv_sec; long tv_nsec; } ts = { 1000000000L, 0 };
    for (;;) {
        register long x8 asm("x8") = 101; /* nanosleep */
        register long x0 asm("x0") = (long)&ts;
        register long x1 asm("x1") = 0;
        asm volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1) : "memory");
    }
}
