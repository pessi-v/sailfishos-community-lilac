# Corresponding source for the community image (Xperia XZ1 Compact, release 1.4)

The images in the release contain software under the GNU GPL, LGPL and other licences. This directory holds, or points to, the source
for the parts that were built or changed, and says where the source of everything else comes from. Sony's proprietary binaries are
not part of the images (users prepare them from Sony's own download, see the main README).

## Where the source of each part is

| Part of the image                                                                       | Licence                               | Source                                                                                                                                                                                                                                                       |
| --------------------------------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Linux kernel 4.14.264** in `hybris-boot.img`                                          | GPL-2.0                               | [`kernel/`](kernel/README.md): upstream commit, the diff, the exact kernel configuration, build commands                                                                                                                                                     |
| **Boot image ramdisk** (Sailfish X `hybris-initrd`) and how the boot image is assembled | GPL-2.0 and others                    | [`boot-image/`](boot-image/README.md): unmodified upstream commit, packaging spec, boot image parameters                                                                                                                                                     |
| **Locally built packages** (34 RPMs, see below)                                         | GPL-2.0, LGPL, BSD, Apache-2.0, MIT   | [`android-hybris/`](android-hybris/) (pinned upstream revisions and the changes made to them) and [`droid-configs/`](droid-configs/) (the device configuration)                                                                                              |
| **Android system and vendor images** (the hardware adaptation layer)                    | mostly Apache-2.0 and BSD, some GPL   | [`android-hybris/manifest-pinned.xml`](android-hybris/manifest-pinned.xml) lists every source tree and the exact revision, [`android-hybris/`](android-hybris/README.md) the patches applied to them                                                        |
| **Packages from Jolla's repositories** (752 of 785 packages)                            | as declared by Jolla for each package | Jolla's open-source components are published by Jolla, see <https://github.com/sailfishos> and the source code offer in Settings > About on the phone. Closed Jolla packages are included as published in Jolla's public repositories (see the main README). |

The 34 locally built packages: `droid-config-lilac*` and `patterns-sailfish-device-*` (GPLv2, in `droid-configs/`), `droid-hal-lilac*` and
`droid-hal-version-lilac` (BSD, `boot-image/` and the manifest), `libhybris*` (several permissive licences and LGPL), `droidmedia` and
`droid-hal-lilac-tools` (Apache-2.0), `pulseaudio-modules-droid*`, `hybris-libsensorfw-qt5-binder` (LGPLv2+), `mce-plugin-libhybris` (LGPLv2),
`qt5-qpa-hwcomposer-plugin` (LGPLv2 with exception or GPLv3 or Qt Commercial). All except the ones in `droid-configs/` are builds of the upstream
projects named in the manifest, plus the patches in `android-hybris/`.

[`patches/`](patches/) holds the changes to packages that are built outside the Android tree: the sensor HAL plugin (`patch-sensorfw-*.py`)
and `hwcomposer-nightlight/`, a change to the display plugin that lets a night light tint the screen. It also holds the source of two small
helpers that are installed as binaries (`lmkd-stub/`, `lilac-no-bgra-readback/`).

## What this source is, exactly

- The kernel diff applies cleanly to the pinned upstream commit, and `make aosp_yoshino_lilac_defconfig` on the patched tree reproduces the shipped
  kernel configuration with no differing line. The compiled kernel itself is not bit-for-bit reproducible (the build embeds a timestamp).
- The Android system and vendor images in this release were built from the trees in the manifest with the patch layers in `android-hybris/`
  applied, and nothing else.
- Some files of the Android adaptation are still laid over the built image from an overlay (`droid-hybris-overrides`: mostly APEX payloads that the
  packaging does not include yet, and 41 libraries and init files from an earlier build of the same trees). They are binary build outputs and are not
  included here; they are built from the trees in the manifest. The overlay is planned to be removed in a later release.
