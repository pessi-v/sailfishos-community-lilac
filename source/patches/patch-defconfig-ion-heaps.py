#!/usr/bin/env python3
"""Enable the ION heap types in the lilac 4.14 defconfig.

Carried over unmodified from the first port's `patch-defconfig-ion-heaps-414.py`
: confirmed 2026-09-14 that mer-hybris's
fork has the identical gap (`CONFIG_ION=y` with no heap type enabled) since Jolla's
patches don't touch this. The camera/gralloc symptom this fixes hasn't been
re-observed here yet -- there's no built vendor/droid-hal to trigger it against
-- but the defconfig gap itself is real and worth closing at the same time as
the other kernel-config work, not re-discovered the hard way once there is.

Original analysis, still accurate:

4.14 split ION's heap implementations into separate Kconfig options. The lilac
defconfig carried over only `CONFIG_ION=y`, so ION core and QC's DT-driven
`msm_ion_of.c` were both built, the eight heaps in `msm8998-ion.dtsi` were parsed
-- and not one of them could be created, because no heap *type* was compiled in.

Every allocation then failed:

    E qdgralloc: ION_IOC_ALLOC failed with error - Invalid argument
    E qdgralloc: AllocateMem: Failed to allocate buffer - heap: 0x2000000 flags: 0x0
    E GraphicBufferAllocator: Failed to allocate (720 x 1280) ... usage 10001800: 5
    I Adreno  : IsValidNativeBuffer: Buffer has a NULL handle
    I Adreno  : DequeueBuffer: Dequeued Buffer is not valid

`heap: 0x2000000` is `1 << 25`, i.e. QC's ION_SYSTEM_HEAP_ID -- the heap declared
as `qcom,ion-heap@25` with type SYSTEM, which needs CONFIG_ION_SYSTEM_HEAP.

4.4 never hit this because it got the heaps implicitly from `CONFIG_ION_MSM=y`,
which does not exist in 4.14.

Effect (measured): all eight heaps in msm8998-ion.dtsi now create at boot, where
before not one did. That much is verified in dmesg and is why this patch stays.

NOT sufficient, and less sufficient than 10.142 claimed. That section also said
the qdgralloc errors "went to zero"; 10.146 withdraws that, because logcat shows
ZERO lines from the allocator service (pid 1750) or the composer (16414) under
any conditions -- vendor HAL services cannot log to logd on this rootfs, so their
silence measures nothing.

The real blocker behind this one is the ION ABI (10.146): the blobs call
ION_IOC_ALLOC with the 4.4 32-byte struct, 4.14's is 24 bytes, _IOWR encodes the
size into the ioctl number, and the dispatcher returns -EINVAL on
`_IOC_SIZE(cmd) > sizeof(union ion_ioctl_arg)` before it looks at the command.
Heaps that exist cannot help a call that never reaches them.

Idempotent. Run from the 4.14 kernel root, or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'arch/arm64/configs/aosp_yoshino_lilac_defconfig'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'CONFIG_ION_SYSTEM_HEAP' in s:
    print('already patched')
    sys.exit(0)
if 'CONFIG_ION=y' not in s:
    sys.exit('CONFIG_ION=y not found -- re-derive against current defconfig')

s = s.replace('CONFIG_ION=y', '\n'.join([
    'CONFIG_ION=y',
    '# lilac 10.142: 4.14 split the ION heaps into their own configs and this',
    '# defconfig kept only CONFIG_ION. Without a heap type compiled in,',
    '# msm_ion_of parses the DT heaps and can create none, so ION_IOC_ALLOC',
    '# fails EINVAL and gralloc returns NULL buffer handles. 4.4 got these via',
    '# CONFIG_ION_MSM=y, which no longer exists.',
    'CONFIG_ION_SYSTEM_HEAP=y',
    'CONFIG_ION_CARVEOUT_HEAP=y',
    'CONFIG_ION_CHUNK_HEAP=y',
    'CONFIG_ION_CMA_HEAP=y',
]), 1)

p.write_text(s)
print(f'patched {p}: enabled ION_SYSTEM/CARVEOUT/CHUNK/CMA heaps')
