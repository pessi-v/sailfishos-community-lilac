# Night light in qt5-qpa-hwcomposer-plugin (GPU colour pass)

The vendor composer answers `SET_COLOR_TRANSFORM` with `UNSUPPORTED` on this device (its log says
`HwcComposer: command 0x2000000 generated error 8`; the phone has no panel calibration data for the vendor colour manager),
so the plugin applies the transform itself, like SurfaceFlinger does when the HWC refuses: `HwComposerContext::swapToWindow` draws one full-screen quad with the blend `dst * (r, g, b)`
right before the frame is queued to the composer. That is a diagonal colour matrix, which is what a night light needs.

- `nightlight.{h,cpp}`: new files for `hwcomposer/` (state save/restore around the pass; `QFileSystemWatcher` on
  `$XDG_RUNTIME_DIR`; forces a repaint when the gains change; no cost while the gains are `1 1 1`).
- `hook.patch`: `hwcomposer.pro`, `hwcomposer_context.{h,cpp}` (constructs `NightLight`, calls it before `backend->swap`).
- Control: the file `$XDG_RUNTIME_DIR/hwc-nightlight` (for lipstick `/run/user/100000/hwc-nightlight`) holding `r g b`,
  each 0..1, for example `1 0.8 0.5`. Delete it or write `1 1 1` to switch off.
- Screenshots: lipstick grabs the frame before the swap, so they are not tinted.
- Built against qt5-qpa-hwcomposer-plugin 31f4f65 with `qmake CONFIG+=enable-systrace` in the sonylilacv2-lilac-aarch64 target.
