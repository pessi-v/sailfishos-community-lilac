#!/usr/bin/env python3
"""Allow the host `cpio` binary through Soong's PATH-tool hermeticity gate.

hybris-boot's Android.mk (real mer-hybris upstream, unmodified) builds its
initramfs with a plain shell pipeline:

    (cd .../initramfs && find . -printf '%P\\n' | cpio -H newc -o) | gzip -9 > boot-initramfs.gz

Modern Soong intercepts every host PATH tool through a "path interposer" and
refuses to actually exec anything not on its allowlist
(build/soong/ui/build/paths/config.go) -- cpio isn't listed, so it defaults
to `Missing` (Symlink: true, Error: true): the interposer REFUSES to run the
real cpio and returns an error instead. Because the recipe pipes cpio's
(nonexistent) stdout into `gzip -9 > $@` unconditionally, the pipeline still
"succeeds" (gzip's own exit code is 0, and nothing checks cpio's) and
silently writes a valid-but-empty ~20 byte gzip file -- no build error at
all, just a hybris-boot.img with a functionally empty ramdisk (no init, no
busybox, nothing) that will never boot.

The officially-documented escape hatch, `TEMPORARY_DISABLE_PATH_RESTRICTIONS`
(plus `ALLOW_NINJA_ENV`, since ninja's own subprocess environment is
separately filtered to a small allowlist -- see build/soong/ui/build/ninja.go)
was tried first and did NOT work in this tree even with both set on the `m`
invocation -- the interposer still refused cpio. Rather than keep chasing
env-var propagation through soong_ui -> ninja -> bash -> path_interposer,
this patches the allowlist directly: a one-line, narrowly-scoped addition of
a completely standard, reproducible POSIX archiving tool, not a blanket
disable.

Idempotent. Run from the repo-synced tree root, or pass it as argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'build/soong/ui/build/paths/config.go'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if '"cpio":' in s:
    print('already patched')
    sys.exit(0)

old = '\t"bash":    Allowed,\n'
new = '\t"bash":    Allowed,\n\t"cpio":    Allowed,\n'

if old not in s:
    sys.exit('expected Configuration map entry not found -- config.go may have changed upstream')

p.write_text(s.replace(old, new))
print(f'patched {p}: added "cpio": Allowed')
