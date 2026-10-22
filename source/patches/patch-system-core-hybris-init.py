#!/usr/bin/env python3
"""Turn stock AOSP `init` into a real hybris/Sailfish `droid-hal-init`.

Same class of gap as `patch-bionic-hybris-tls.py`: this manifest's
`system/core` project is stock/vanilla AOSP source, never patched for
hybris use, even though the manifest's *kernel* got its own dedicated
hybris fork. `mer-hybris/hybris-patches` (branch `hybris-sony-aosp-11`,
same branch that fixed bionic) also carries a 39-patch `system/core/`
set that is the actual source of "droid-hal-init" as a distinct thing
from plain Android init: systemd cgroup/notify integration (0005, 0008),
loading service .rc files from `/usr/libexec/droid-hybris/system/etc/init`
instead of the real (unmounted-as-such) Android partition (0019, 0022),
disabling SELinux/zygote/ueventd/ipc setup that doesn't apply under
Sailfish (0014-0017, 0023, 0028, 0034), and reworking mount handling since
Mer/systemd -- not init -- owns mounting here (0002, 0004, 0020, 0021,
0024, 0027, 0029).

Discovered 2026-09-16 by fixing the *live-only* bug-1 `/system` ELOOP
mount workaround correctly for the first time (previous sessions bind-
mounted the raw partition -- itself still Android system-as-root layout,
with its own `etc -> /system/etc` self-referential symlink -- directly
onto `/system`; the fix is to bind-mount that partition's *nested*
`system/` subdirectory instead). Once `/system` paths actually resolved,
`droid-hal-init` got past its earlier "Too many levels of symbolic links"
failure for the first time all session, immediately exposing that it had
never actually been running at all: it crashed on load with `CANNOT LINK
EXECUTABLE ... cannot locate symbol
_ZN3fmt2v68internal10basic_dataIvE23zero_or_powers_of_10_32E` (an
fmtlib-via-libbase symbol). This wasn't a version skew or a real bug in
libbase.so -- `hwservicemanager`, built fresh from the same tree, links
against the exact same libbase.so without issue. It's simply that vanilla
AOSP `init` was never meant to run standalone here in the first place;
this patch set is the actual missing piece, exactly parallel to bionic's
missing TLS patches.

Applied in filename order, exactly as hybris-patches' own
`apply-patches.sh` does. All 39 apply cleanly in sequence against a
pristine sync (each depends on context from the ones before it -- a
`git apply --check` run against *all* of them independently, before any
are actually applied, will show spurious failures for anything after
0009; that's an artifact of checking out of order, not a real conflict).

Idempotent. Run from the repo-synced tree root (needs system/core/ as a
subdirectory), or pass that root as argv[1].
"""
import subprocess
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
core = root / 'system' / 'core'
if not core.is_dir():
    sys.exit(f'not found: {core}')

patch_dir = pathlib.Path(__file__).parent / 'hybris-system-core-init'
patches = sorted(patch_dir.glob('*.patch'))
if len(patches) != 39:
    sys.exit(f'expected 39 patches in {patch_dir}, found {len(patches)}')

first_stage_init = core / 'init/first_stage_init.cpp'
marker = '"/sbin/droid-hal-init"'
already_done = marker in first_stage_init.read_text()

if not already_done:
    for p in patches:
        subprocess.run(['git', 'apply', str(p.resolve())], cwd=core, check=True)
        print(f'applied {p.name}')
else:
    print('hybris-patches system/core/ set already applied, skipping')
