Diagnostic only: a native Camera2 client that asks
CameraService for characteristics (capabilities, ISO / exposure ranges, hardware level, ...), opens
a HAL3 device with `connectDevice`, and prints the default request templates. Drop the directory
into `device/sony/lilac/`, then `m lilac-camera2-client-probe` (lunch aosp_g8441-userdebug); the
binary lands in `out/target/product/lilac/system/bin/`. Copy it to the phone (e.g. /tmp) and run it
as root; it has no side effects on the camera beyond opening and closing camera 0.
