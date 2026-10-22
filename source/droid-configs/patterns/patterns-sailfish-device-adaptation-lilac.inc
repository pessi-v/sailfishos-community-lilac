# Feel free to disable non-critical HA parts during devel by commenting lines out
# Generated for lilac, following add_new_device.sh convention

%package -n patterns-sailfish-device-adaptation-lilac
Summary: Jolla HW Adaptation lilac
Requires: droid-hal-lilac
Requires: droid-hal-lilac-img-boot
Requires: droid-hal-lilac-kernel-modules
Requires: droid-config-lilac-sailfish
Requires: droid-config-lilac-pulseaudio-settings
Requires: droid-config-lilac-policy-settings
Requires: droid-config-lilac-preinit-plugin
Requires: droid-config-lilac-flashing
Requires: droid-config-lilac-bluez5
# droid-config-lilac-bluez5 only ships bluez/pulse config, no transport -- bluebinder bridges
# the Android BT HAL (binder) to /dev/vhci, which is what makes hci0 exist at all (needs
# CONFIG_BT_HCIVHCI=y, already in patch-defconfig-sailfish-reqs.py).
Requires: bluebinder
Requires: droid-hal-version-lilac

# Hybris packages
Requires: libhybris-libEGL
Requires: libhybris-libGLESv2
Requires: libhybris-libwayland-egl

# Sensors
# Pinned to the -binder flavor, not the generic virtual package: this device has no legacy
# sensors.<platform>.so HAL module at all (only the HIDL android.hardware.sensors@1.0-service),
# so an unpinned `Requires: hybris-libsensorfw-qt5` lets the resolver pick either flavor and it
# has been observed picking -hal, which exits 1 with no sensors at all. Same bug, same fix, as
# the sibling porting attempt hit on this same msm8998 platform.
Requires: hybris-libsensorfw-qt5-binder

# Vibra
Requires: ngfd-plugin-native-vibrator
Requires: libngf-qt5-qtfeedback

# Needed for /dev/touchscreen symlink
Requires: qt5-plugin-generic-evdev

Requires: pulseaudio-modules-droid
Requires: pulseaudio-modules-droid-hidl

# The -dummy-af is needed for newer devices that run the main
# audiosystem-passthrough in qti mode (e.g. >=Android 9 Qualcomm),
# to fix non-responding Camera app and/or voice during a phone call:
#Requires: audiosystem-passthrough-dummy-af

# for audio recording to work:
Requires: qt5-qtmultimedia-plugin-mediaservice-gstmediacapture

# These need to be per-device due to differing backends (fbdev, eglfs, hwc, ..?)
Requires: qt5-qtwayland-wayland_egl
Requires: qt5-qpa-hwcomposer-plugin
Requires: qtscenegraph-adaptation

# For hybris devices with droidmedia, see HADK pdf for more information
Requires: gstreamer1.0-droid

# Flashlight toggle in the top menu. droidmedia-flashlight drives the torch through the camera HAL
# (droid_media_camera_set_torch_mode); jolla-settings-system-flashlight is the UI. Neither was
# pulled in by anything else.
Requires: droidmedia-flashlight
Requires: jolla-settings-system-flashlight
Obsoletes: gmp-droid

# This is needed for notification LEDs
Requires: mce-plugin-libhybris

# USB mode controller
Requires: usb-moded

# hammerhead, grouper, and maguro use this in scripts, so include for all
Requires: rfkill

# Fingerprint reader (FPC1145, android.hardware.biometrics.fingerprint@2.1
# HIDL service): the daemon plus its HIDL-over-libgbinder slave. This device
# uses the binder HAL, not the legacy -hal transport, hence -slave-binder.
Requires: sailfish-fpd
Requires: sailfish-fpd-slave-binder

# enable device lock and allow to select untrusted software; sailfish-devicelock-fpd
# is jolla-devicelock-daemon-encsfa's encsfa backend *plus* the fingerprint bridge
# that FingerSettingsPage.qml/NemoDeviceLock::FingerprintSensor actually talk to
# (org.nemomobile.devicelock.client.Fingerprint.Sensor is served by the devicelock
# daemon, not by sailfish-fpd itself) -- plain encsfa never instantiates that object.
Requires: sailfish-devicelock-fpd

# Enable home encryption
#Requires: sailfish-device-encryption

# For GPS
Requires: geoclue-provider-hybris

# For FM radio on some QCOM devices
#Requires: qt5-qtmultimedia-plugin-mediaservice-irisradio
#Requires: jolla-mediaplayer-radio

# NFC support
# 1. binder plugin requires Android 8 or a newer base
# 2. pn54x plugin talks directly to pn54x driver
# These plugins are mutually exclusive, you need to pick one:
# lilac: binder plugin -- Android 11 base, and android.hardware.nfc@1.2-service runs;
# nfcd finds it as android.hardware.nfc@1.0::INfc/default => nfc0.
Requires: nfcd-binder-plugin
#Requires: nfcd-pn54x-plugin

# Modem/cellular: oFono's own closed-source "AML" plugin (ofono-configs-lilac's default) only
# ever registers with oFono, it never actually provides a binder/HIDL transport to
# android.hardware.radio -- GetModems stays permanently empty without this. ofono-binder-plugin
# is the real, open-source bridge (pulls in libgbinder-radio + libofonobinderpluginext).
# /etc/ofono/binder.conf is already correct and shipped by this same package (below), matching
# what this plugin expects (ExpectSlots=slot1, path=/ril_0) -- do NOT also add
# ofono-configs-binder, droid-config-lilac already obsoletes it.
Requires: ofono-binder-plugin

%description -n patterns-sailfish-device-adaptation-lilac
Pattern with packages for lilac HW Adaptation

%files -n patterns-sailfish-device-adaptation-lilac
