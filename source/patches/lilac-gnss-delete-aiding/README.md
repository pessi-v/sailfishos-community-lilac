Diagnostic only: connects to `android.hardware.gnss@2.1` and calls
`deleteAidingData(ALL)` so the next GNSS start is a cold start. Drop the directory into
`device/sony/lilac/`, `m lilac-gnss-delete-aiding` (lunch aosp_g8441-userdebug), copy
`out/target/product/lilac/system/bin/lilac-gnss-delete-aiding` to the phone and run it as root while
nothing is tracking (with the engine running the HAL answers `eQMI_LOC_ENGINE_BUSY` and the delete does
not happen).
