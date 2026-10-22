#!/usr/bin/env python3
"""Build the REAL fingerprint HAL from source instead of disabling it.

Supersedes patch-boardconfig-no-fpc.py's TARGET_DEVICE_NO_FPC workaround,
which deferred fingerprint bring-up entirely. Re-examined
the actual build break it was working around:

    FAILED: ninja: '.../libdmabufheap.../libdmabufheap.so.toc', needed by
    '.../android.hardware.biometrics.fingerprint@2.1-service.sony', missing
    and no known rule to make it.

`libdmabufheap` is a newer AOSP library (DMA-BUF Heaps) genuinely absent
from this Android-11 tree -- confirmed absent at the kernel level too: no
linux/dma-heap.h UAPI header anywhere in this 4.14 tree, so
CONFIG_DMABUF_HEAPS was never backported here either. Its one real caller
in this codebase, `DmaBuffer.cpp`/`.h` (a `BufferAllocator`-based helper),
is only reachable through the `egistec/` sensor implementation -- a
different fingerprint chip vendor entirely, used on other Sony devices;
lilac's own `SOMC_PLATFORM=yoshino` always selects the FPC1145 path
instead (`fpc_imp_yoshino_nile_tama.c`). But `egistec/` genuinely can't
just be deleted: `service.cpp` -- the actual `main()`, needed on every
platform -- unconditionally `#include`s all three sensor implementations
(FPC, Egistec current, Egistec legacy) and picks between them at RUNTIME,
not compile time; deleting egistec/ breaks the real build. (Tried exactly
that, and a same-directory rename first -- both tested directly and
failed; rename doesn't work either, since `all-subdir-cpp-files`'s own
`find -L . -name '*.cpp'` walks into any directory regardless of its
name.)

So the actual fix is a small, real compat shim, not a deletion:
`patches/libdmabufheap-compat/` provides `BufferAllocator/
BufferAllocator.h` + `BufferAllocator.cpp` implementing the one method
DmaBuffer.cpp calls (`Alloc()`) against the real, stable DMA-BUF Heaps
ioctl protocol -- genuine code, not a fake stub: on a kernel that actually
has CONFIG_DMABUF_HEAPS it would really work, and on this one it
correctly fails via a real `open()` on `/dev/dma_heap/<name>` (which does
not exist), exactly like the real library would on any kernel lacking the
feature. Since lilac's own sensor is FPC1145, this path is never actually
exercised at runtime regardless -- but the binary needs to *link*, and
this makes that link honest rather than papering over it.

The first lilac port never had to solve this at all -- it uses the real,
precompiled Android 9 blob off the factory partition, not a from-source
build -- so this gap is specific to this port's own from-source approach
and has no equivalent patch to mine from there. Their own kernel-side
fingerprint fixes (drivers/input/fingerprint ABI compat, sysfs path
compat, IRQ re-arm) still apply once this HAL actually builds and runs --
but this port's own from-source HAL already speaks the modern
/dev/fingerprint + ioctl interface natively (confirmed: common.c opens
/dev/fingerprint and uses FPC_IOC* ioctls directly), so those specific
compat patches -- which existed only to accommodate an old precompiled
Android-9-era blob -- do not apply here at all.

Idempotent. Run from the tree root, or pass it as argv[1]. Copies
patches/libdmabufheap-compat/ alongside this script -- run it from a
checkout of this repo, or pass --compat-src to point at that directory
explicitly.
"""
import argparse
import shutil
import sys
import pathlib

parser = argparse.ArgumentParser()
parser.add_argument('root', nargs='?', default='.')
parser.add_argument('--compat-src', default=None,
                     help='path to this repo\'s patches/libdmabufheap-compat/ '
                          '(default: alongside this script)')
args = parser.parse_args()

root = pathlib.Path(args.root)
fpdir = root / 'vendor/oss/fingerprint'
p = fpdir / 'Android.mk'
if not p.is_file():
    sys.exit(f'not found: {p}')

compat_src = pathlib.Path(args.compat_src) if args.compat_src else (
    pathlib.Path(__file__).resolve().parent / 'libdmabufheap-compat')
if not (compat_src / 'BufferAllocator.cpp').is_file():
    sys.exit(f'compat source not found: {compat_src}')

s = p.read_text()
if 'libdmabufheap' not in s and 'dmabufheap-compat' in s:
    print('already patched')
    sys.exit(0)

old_lib = '    libdmabufheap \\\n'
if s.count(old_lib) != 1:
    sys.exit(f'libdmabufheap anchor count: {s.count(old_lib)} -- re-derive against current source')
s = s.replace(old_lib, '')

anchor = ('LOCAL_SRC_FILES := \\\n'
          '    $(call all-subdir-cpp-files) \\\n'
          '    QSEEComFunc.c \\\n'
          '    common.c\n')
if s.count(anchor) != 1:
    sys.exit(f'LOCAL_SRC_FILES anchor count: {s.count(anchor)} -- re-derive against current source')
# dmabufheap-compat/ lives inside LOCAL_PATH so the existing
# all-subdir-cpp-files glob picks up BufferAllocator.cpp automatically; only
# the extra -I so `#include <BufferAllocator/BufferAllocator.h>` resolves.
# Inserted only AFTER the whole (backslash-continued) LOCAL_SRC_FILES
# statement ends -- splicing a new statement into the middle of a `\`
# continuation breaks the continuation (tested directly: "missing
# separator" from make, since the next real line stops looking like part
# of the same assignment).
s = s.replace(anchor, anchor + '\nLOCAL_C_INCLUDES += $(LOCAL_PATH)/dmabufheap-compat\n')

p.write_text(s)

dest = fpdir / 'dmabufheap-compat'
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(compat_src, dest)

print(f'patched {p}: dropped the missing libdmabufheap dependency, added a real compat shim')
