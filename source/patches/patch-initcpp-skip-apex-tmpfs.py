#!/usr/bin/env python3
"""Stop real `init` from mounting a fresh, `noexec` tmpfs over `/apex` every boot.

`init.cpp`'s `MountExtraFilesystems()` unconditionally does
`mount("tmpfs", "/apex", "tmpfs", MS_NOEXEC|MS_NOSUID|MS_NODEV, ...)` very early in first
stage, to give `apexd` a clean, empty staging area to populate. On real Android this is
correct -- `apexd` mounts each `.apex` file as a loopback device *under* that tmpfs a
moment later. Here, `apexd` never runs at all (§16: disabled by
`patch-initrc-disable-apexd.py`, since nothing in this Sailfish-hosted stack needs it), so
the tmpfs just sits there empty forever -- and it completely shadows `/apex`'s real
persistent content: this port populates `/apex/com.android.runtime/bin/{linker,linker64}`
directly on Sailfish's own writable rootfs (§14 -- a plain, ordinary directory, nothing to
do with the read-only `/system`/`/vendor` partitions), specifically so every binary's
hardcoded `/system/bin/linker64 -> /apex/com.android.runtime/bin/linker64` symlink
resolves. Once this tmpfs mounts on top, those files are still physically there
underneath, just invisible -- and even a live bind-mount-back onto the fresh tmpfs can't
be executed anyway, since `MS_NOEXEC` blocks it (confirmed: `Permission denied`, not `not
found` -- that's what gave this away rather than a plain missing-file error).

Fix: skip mounting anything over `/apex` at all. `/linkerconfig`'s neighboring tmpfs mount
is untouched -- it only ever holds generated *text* config, never anything executed, so
`MS_NOEXEC` there is harmless and it still needs the fresh empty directory apexd would
otherwise populate (which, again, never runs, but nothing depends on /linkerconfig's
*persistent* content the way §14 does for /apex).

Idempotent. Run from the root of this kernel/system tree (needs system/core/ as a
subdirectory, same convention as the other patch-*.py scripts here), or pass that root as
argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
init_cpp = root / 'system/core/init/init.cpp'
if not init_cpp.is_file():
    sys.exit(f'not found: {init_cpp}')

s = init_cpp.read_text()
MARK = '// lilac: apex is never activated on this Sailfish-hosted setup'

if MARK in s:
    print('already patched')
    sys.exit(0)

old = (
    '    // /apex is used to mount APEXes\n'
    '    CHECKCALL(mount("tmpfs", "/apex", "tmpfs", MS_NOEXEC | MS_NOSUID | MS_NODEV,\n'
    '                    "mode=0755,uid=0,gid=0"));\n'
)
if old not in s:
    sys.exit('anchor not found, tree changed -- re-derive the /apex mount block')
assert s.count(old) == 1, f'expected exactly one occurrence, found {s.count(old)}'

new = (
    f'    {MARK}. Leaving /apex\n'
    '    // as-is (a plain persistent directory on this rootfs, pre-populated with real\n'
    '    // linker binaries -- see /apex/com.android.runtime/bin) instead of shadowing it\n'
    '    // with a fresh noexec tmpfs apexd would otherwise populate but never runs here.\n'
    '    // was:\n'
    '    // CHECKCALL(mount("tmpfs", "/apex", "tmpfs", MS_NOEXEC | MS_NOSUID | MS_NODEV,\n'
    '    //                 "mode=0755,uid=0,gid=0"));\n'
)
init_cpp.write_text(s.replace(old, new, 1))
print(f'patched {init_cpp}: skip mounting tmpfs over /apex')
