%define device lilac
%define vendor sony

%define vendor_pretty Sony
%define device_pretty Xperia XZ1 Compact

# Haptics deferred, matching the first port's own droid-hal-version-lilac.spec
# (patches/droid-hal-version-lilac.spec there): ngfd-plugin-native-vibrator has
# no buildable repo (sailfishos/ and mer-hybris/ both 404), and the only
# buildable alternative, mer-hybris/ngfd-plugin-droid-vibrator, is flagged by
# dhd's own util.sh as "known to halt under various scenarios". Revisit once
# booting -- this device does have HIDL android.hardware.vibrator@1.0.
#define have_vibrator_native 1
%define have_led 1

%include droid-hal-version/droid-hal-version.inc
