# flash-config.sh for the Sony Xperia XZ1 Compact (lilac, G8441), read by flash.sh.
#
# What it writes (Sailfish X layout):
#   boot      the modular Sailfish boot image (kernel + initrd; the initrd also contains the recovery)
#   userdata  one LVM physical volume with the volumes "root" and "home"; the initrd grows it to the whole partition
#   system    a small ext4 "fimage" holding the factory-reset images (lilac is not A/B: there is no spare slot)
#   oem       the Sony software-binaries image, used as /odm
# What it NEVER writes: vendor, bluetooth, modem*, dsp, persist, TA, fsg/fsc, the bootloader chain, FOTAKernel.
# The phone must run Sony stock Android 9, build 47.2.A.11.234: Sailfish reads the stock vendor and bluetooth
# partitions, the modem and the other firmware partitions at every boot.

VALID_PRODUCTS=(
"G8441"
)

FLASH_OPS=(
"getvar_fail_if secure yes"
"flash boot hybris-boot.img"
"flash userdata sailfish.img001"
"flash system fimage.img001"
"flash_blob oem *_merged_yoshino.img"
)

GETVAR_ERROR_secure="
This device has not been unlocked, but you need that for flashing.
Please go to https://developer.sony.com/develop/open-devices/get-started/unlock-bootloader/
and follow the instructions to unlock the bootloader of your Xperia XZ1 Compact.
"

BLOB_ERROR_NOT_FOUND_oem="
The Sony software-binaries image for the oem partition was not found in this directory.
Download both SW_binaries_for_Xperia_Android_11_4.14_v8a_yoshino and ..._v9a_yoshino from
https://developer.sony.com/develop/open-devices/downloads/software-binaries/
(accept Sony's licence), unzip them next to this script and build the combined image
with ./merge-oem.sh, which creates SW_binaries_merged_yoshino.img. See README.md.
"

BLOB_ERROR_TOO_MANY_oem="
More than one combined Sony vendor image was found in this directory.
Please remove any additional *_merged_yoshino.img files.
"

FLASH_COMPLETED_MESSAGE="
Flashing is complete. Remove the USB cable and power on the phone with the power key.
The first boot takes several minutes: the storage is resized and Sailfish OS sets itself up.
"
