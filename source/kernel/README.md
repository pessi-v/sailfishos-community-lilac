# Kernel source

The kernel in `hybris-boot.img` (Linux 4.14.264, version string `4.14.264-g8db245937d42-dirty`, build `#1 SMP PREEMPT Fri Nov 6 15:56:36 UTC 2026`) is
built from:

- upstream: <https://github.com/mer-hybris/android_kernel_sony_msm>, branch `hybris-sony-aosp/LA.UM.7.1.r1`, commit
  `8db245937d42dbfd0f61f3a14871a3215098d9f0`, with its submodules (for example `wireguard-linux-compat`, `drivers/staging/wlan-qc/*`) at the revisions that commit records
- plus [`lilac-kernel.diff`](lilac-kernel.diff): the changes made for this device, 19 files (17 modified, 2 new)
- kernel headers: `kernel-sony-msm-4.14-headers` at the revision in [`../android-hybris/manifest-pinned.xml`](../android-hybris/manifest-pinned.xml)

What the changes are, in short: UFS device-detection retry and reference-clock handling, a Bluetooth advertising-report fix, camera flash driving both LED
strings, no spurious 0 % battery capacity from the fuel gauge, modem (MSS) bring-up clock and reset ordering, a light-sensor time fix, ION legacy
interface for the Android HAL, device-tree changes for the lilac, and defconfig options (for example Bluetooth RFCOMM/BNEP/HIDP, and run-queue statistics, which the interrupt balancer of the vendor blobs needs). The exact changes are in the diff.

## Rebuild

```
git clone https://github.com/mer-hybris/android_kernel_sony_msm && cd android_kernel_sony_msm
git checkout 8db245937d42dbfd0f61f3a14871a3215098d9f0 && git submodule update --init
git apply /path/to/lilac-kernel.diff

# toolchain: the AOSP prebuilts used by the build (clang r383902b1 and the 4.9 gcc cross compilers for arm64 and arm32)
ARGS="O=$PWD/../kernel-out ARCH=arm64 CC=clang CLANG_TRIPLE=aarch64-linux-gnu- \
      CROSS_COMPILE=aarch64-linux-android- CROSS_COMPILE_ARM32=arm-linux-androideabi-"
make $ARGS aosp_yoshino_lilac_defconfig
make $ARGS -j4 Image.gz-dtb          # result: arch/arm64/boot/Image.gz-dtb
```

`CROSS_COMPILE_ARM32` is required (the compat vDSO does not build without it). The resulting `.config` equals [`lilac-shipped.config`](lilac-shipped.config) (compare
the sorted lines that do not start with `#`; no difference was found when this was checked).

The shipped kernel image is `Image.gz-dtb`, 13,859,236 bytes, md5 `9b4b955fb703af4d3b6b467fb8e5753e`. A rebuild will not match byte for byte (timestamp and host
name are embedded), but the sources and configuration are the same.

The boot image that wraps this kernel is described in [`../boot-image/README.md`](../boot-image/README.md).
