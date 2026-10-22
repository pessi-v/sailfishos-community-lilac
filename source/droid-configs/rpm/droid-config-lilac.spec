%define device lilac
%define device_pretty Xperia XZ1 Compact

# droid-configs-device's own sparse/etc/ofono/binder.conf (real settings:
# ExpectSlots=slot1, path=/ril_0) conflicts at `mic` install time with the
# generic ofono-configs-binder package from Sailfish's own repos, which owns
# the same path. `Provides:` alone (droid-configs.inc's documented remedy)
# does not evict the generic package -- something else Requires it by name,
# so the resolver installs both. Both tags are needed, and must precede the
# %include below (preamble tags are order-independent but must come before
# the first section, which droid-configs.inc supplies). The first port hit
# and fixed this identically -- confirmed via
# diff that ours is the real config, not the generic package's placeholder
# (~190 lines of commented-out documentation with no active settings).
Provides: ofono-configs-binder
Obsoletes: ofono-configs-binder

# sparse/usr/libexec/droid-*/ ships this port's own Android /system binaries
# (bionic-linked, run via droid-hal-init, never by the Sailfish side). Left to
# rpm's automatic dependency generator they turn into hundreds of unresolvable
# Requires (libc.so(LIBC_R), libEGL.so(LIBEGL), libart.so, ...) and matching
# Provides that could satisfy real Sailfish packages -- `mic` aborted with
# "nothing provides 'libEGL.so(LIBEGL)'".
%global __requires_exclude_from ^/usr/libexec/droid-.*$
%global __provides_exclude_from ^/usr/libexec/droid-.*$

# Ship those binaries byte-for-byte. rpm's post-install processing otherwise
# rewrites the statically linked ones (adds a .gnu_debuglink section): the
# patched droid-hal-init, linkerconfig and the lmkd stub all came out 32
# bytes larger than the files in git.
%global debug_package %{nil}
%global __os_install_post %{nil}

%include droid-config-common.inc
%include droid-configs-device/droid-configs.inc
%include patterns/patterns-sailfish-device-adaptation-lilac.inc
%include patterns/patterns-sailfish-device-configuration-lilac.inc

# sparse/usr/libexec/droid-hybris-overrides/ holds this port's whole
# /usr/libexec/droid-hybris overlay (our own AOSP build output and fixes: the
# patched linker, libc, libutils, servicemanager, init.rc, the /apex payloads
# droid-hal-prepare.sh installs, ...). About 150 of those paths are also
# shipped by droid-hal-lilac/droidmedia, and rpm treats any content *or mode*
# difference on a shared path as a file conflict, so this package owns none
# of /usr/libexec/droid-hybris and copies the overlay over it instead --
# whenever this package, droid-hal-lilac or droidmedia is installed or
# upgraded, so an upgrade of either can't silently revert it. The real fix
# is to rebuild droid-hal-lilac with these changes.
#
# droid-hal-lilac also ships /init-debug. If present, the boot image's init
# execs it instead of the real init, and it ends in `sleep 60; reboot -f`
# so delete it here too.
#
# Its /sbin/droid-hal-init is the stock build; ours (droid-hal-init-patched/)
# carries the fmt-skew fix (section 15) and skips the tmpfs over /apex
# (section 18, patch-initcpp-skip-apex-tmpfs.py). With the stock one the
# Android side never comes up and the screen stays black.
%triggerin -- droid-hal-lilac, droidmedia
rm -f /init-debug
# lipstick is setgid, so its LD_PRELOAD'd screenshot fix must be setuid (glibc secure-
# execution rules); git can't carry that bit (70-no-bgra-readback.conf).
[ -f /usr/lib64/liblilac-no-bgra-readback.so ] && chmod 4755 /usr/lib64/liblilac-no-bgra-readback.so
if [ -f /usr/libexec/droid-hal-init-patched/droid-hal-init ]; then
    rm -f /sbin/droid-hal-init
    cp -a /usr/libexec/droid-hal-init-patched/droid-hal-init /sbin/droid-hal-init
fi
cd /usr/libexec/droid-hybris-overrides || exit 0
find . -type f | while read -r f; do
    mkdir -p "/usr/libexec/droid-hybris/$(dirname "$f")"
    # rm first: several destinations are symlinks into /apex, and busybox cp
    # follows them rather than honouring --remove-destination.
    rm -f "/usr/libexec/droid-hybris/$f"
    cp -a "$f" "/usr/libexec/droid-hybris/$f"
done
