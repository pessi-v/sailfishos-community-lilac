#!/usr/bin/env python3
"""Fix the main-thread bionic TLS segfault that killed lipstick/pulseaudio.

Root cause (the "libc.so segfault"
section): this manifest's `bionic` project is stock/vanilla AOSP source --
never patched for hybris use. Bionic keeps small per-thread state (notably
the current C locale, read by `uselocale()`/`__ctype_get_mb_cur_max()`) in a
raw TLS slot reached via `mrs x8, tpidr_el0` + a fixed negative offset. That
scheme assumes bionic's OWN thread-creation code populated the slot -- true
for a thread bionic itself spawned, never true for glibc's own main thread
(or any glibc-created thread) that a hybris process uses to call into a
dlopen'd bionic .so. On this device the slot is simply zero, so the first
bionic call that touches it (here: a bionic libc++.so global iostream
static initializer, which runs unconditionally the moment libc++.so loads,
calling `uselocale(nullptr)` internally) reads through a null pointer and
segfaults -- on lipstick's *only* thread, before any UI code runs. Same
crash, same address pattern, killed pulseaudio too.

This is a known, already-solved problem: mer-hybris maintains a dedicated
patch set for exactly this, `mer-hybris/hybris-patches`, branch
`hybris-sony-aosp-11` (matching this device's own AOSP-11 base) -- NOT
pulled by this repo's manifest at all (only the kernel's own hybris fork
was; the general tree-wide hybris-patches repo was missed entirely). The
fix: bionic's `locale.cpp` gets built with `USE_TLS_SLOT 0`, so the current
locale is a normal C++ `thread_local` variable instead of a raw TLS-slot
read -- compiled with `-femulated-tls` (patch 0008), which routes access
through `__emutls_get_address()`, a portable runtime keyed off pthread
TLS/keys rather than `tpidr_el0`, so it works correctly regardless of which
C library "owns" the hardware thread pointer. Confirmed on-device via gdb:
`uselocale`/`__ctype_get_mb_cur_max` now call `__emutls_get_address`
instead of doing the raw slot dereference, and lipstick survived indefinitely
under gdb afterward (previously: SIGSEGV within milliseconds, every time).

The 8 patches in patches/hybris-bionic-tls/ are fetched verbatim from
https://github.com/mer-hybris/hybris-patches (branch hybris-sony-aosp-11,
directory bionic/) -- applied in filename order, exactly as that repo's own
`apply-patches.sh` does. Only 0002/0003/0004/0007/0008 are directly related
to the TLS bug; 0001/0005/0006 are unrelated hybris-compat fixes bundled in
the same upstream commit range for this AOSP base and carried along rather
than cherry-picked apart.

One extra, NOT-upstream fix is needed on top: patches 0002 and 0004 blank
out `TLS_SLOT_ART_THREAD_SELF`'s value entirely (`#define
TLS_SLOT_ART_THREAD_SELF` with no number), freeing that slot number for
libhybris's own use. Upstream hybris builds never compile ART, so nothing
ever notices. This tree's `m hybris-hal` target DOES pull in ART (as part
of building the full product image), and `art/runtime/thread-current-inl.h`
still does `__get_tls()[TLS_SLOT_ART_THREAD_SELF]` literally -- a hard
compile error ("expected expression") with the macro empty. Since ART never
actually runs on this Sailfish image (this bring-up doesn't use the Android
app runtime at all), it doesn't matter what number the slot gets, only that
compilation succeeds self-consistently within ART's own translation units --
patched back to a real placeholder value (3, a slot 0002/0004 already freed
up) in both the 32-bit and 64-bit blocks of tls_defines.h.

Idempotent. Run from the repo-synced tree root (needs bionic/ as a
subdirectory), or pass that root as argv[1].
"""
import subprocess
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
bionic = root / 'bionic'
if not bionic.is_dir():
    sys.exit(f'not found: {bionic}')

patch_dir = pathlib.Path(__file__).parent / 'hybris-bionic-tls'
patches = sorted(patch_dir.glob('*.patch'))
if not patches:
    sys.exit(f'no patches found in {patch_dir}')

locale_cpp = bionic / 'libc/bionic/locale.cpp'
marker = '//#if defined(__BIONIC_BUILD_FOR_ANDROID_SUPPORT)'
already_done = marker in locale_cpp.read_text()

if not already_done:
    for p in patches:
        subprocess.run(['git', 'apply', str(p.resolve())], cwd=bionic, check=True)
        print(f'applied {p.name}')
else:
    print('hybris-patches bionic/ set already applied, skipping')

tls_defines = bionic / 'libc/platform/bionic/tls_defines.h'
s = tls_defines.read_text()
if '#define TLS_SLOT_ART_THREAD_SELF\n' in s:
    s = s.replace(
        '#define TLS_SLOT_ART_THREAD_SELF\n',
        '#define TLS_SLOT_ART_THREAD_SELF  3\n',
    )
    tls_defines.write_text(s)
    print(f'patched {tls_defines}: gave TLS_SLOT_ART_THREAD_SELF a real placeholder value (3)')
elif '#define TLS_SLOT_ART_THREAD_SELF  3\n' in s:
    print('TLS_SLOT_ART_THREAD_SELF placeholder already applied, skipping')
else:
    sys.exit('expected TLS_SLOT_ART_THREAD_SELF define not found -- '
             'did the hybris-patches bionic/ set apply as expected?')
