# Android / hybris source trees

The Android system and vendor images (`/usr/libexec/droid-hybris/system.img` and `vendor.img`) and the locally built `droid-hal-lilac*`
packages are built from the trees listed in [`manifest-pinned.xml`](manifest-pinned.xml), each at the exact revision given there, with the
patches in this directory applied on top.

The patches are kept in the layout of [mer-hybris/hybris-patches](https://github.com/mer-hybris/hybris-patches):
`<layer>/<project path>/NNNN-<subject>.patch`, one `git format-patch` file per commit. The layers are applied in this order:

| Layer                 | What it is                                                                                                                                                                                                                                                        |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `00-droid-src-sony/`  | The patches of [mer-hybris/droid-src-sony](https://github.com/mer-hybris/droid-src-sony), branch `hybris-sony-aosp-11`, unchanged (they include the cherry-picks of Sony's `repo_update.sh`).                                                                     |
| `10-hybris-patches/`  | The patches of [mer-hybris/hybris-patches](https://github.com/mer-hybris/hybris-patches), branch `hybris-sony-aosp-11`, unchanged. `build/make/0001-*.patch.not-applied` is kept for reference but not applied (see `NOT-APPLIED.txt` next to it). |
| `20-lilac/`           | The changes made for this device, including the kernel.                                                                                                                                                                                                           |

## Applying them

For every project that has patches: check out the revision from the manifest, then apply the patches of the three layers in order. For example:

```
cd frameworks/av
git checkout <revision from manifest-pinned.xml>
for l in 00-droid-src-sony 10-hybris-patches 20-lilac; do
    [ -d /path/to/android-hybris/$l/frameworks/av ] && git am -3 /path/to/android-hybris/$l/frameworks/av/*.patch
done
```

A few upstream patches need the three-way merge (`-3`) because their context lines have drifted on the pinned revisions; none of them conflicts.
[`hp.py`](hp.py) does the same without a checkout (it commits the series with a temporary index and prints the resulting commit):
`HP_MANIFEST=manifest-pinned.xml python3 hp.py build <android tree> 00-droid-src-sony:10-hybris-patches:20-lilac <project path>`.

The kernel is the project `kernel/sony/msm-4.14/common-kernel`; its patches are the same changes as [`../kernel/lilac-kernel.diff`](../kernel/README.md).

The images are then built with the usual hybris adaptation steps (`source build/envsetup.sh; lunch aosp_g8441-userdebug; ALLOW_MISSING_DEPENDENCIES=true m droidcore`).
