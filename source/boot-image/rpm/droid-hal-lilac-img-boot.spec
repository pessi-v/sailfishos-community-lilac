%define device lilac

# Boot image for the Xperia XZ1 Compact (lilac), modular Sailfish X initrd (hybris-initrd).
#
# Offsets/cmdline come from the working debug boot image (hybris-boot-v2-bt-flash-fg.img, md5
# 3bd56068...; unpack_bootimg: kernel 0x80008000, ramdisk 0x82000000, tags 0x81e00000, page 4096,
# header v0, os 11.0.0 / 2021-10). The legacy-init-only arguments are dropped (data_subdir=...
# selected the SD-card stowaways root; jolla.test_mode=USER was read by the old init script).
# Everything else is kept as it boots today.
%define mkbootimg_cmd mkbootimg --ramdisk %{initrd} --kernel %{kernel} --base 0x80000000 --pagesize 4096 --kernel_offset 0x00008000 --ramdisk_offset 0x02000000 --tags_offset 0x01e00000 --os_version 11.0.0 --os_patch_level 2021-10 --cmdline "lpm_levels.sleep_disabled=1 service_locator.enable=1 androidboot.selinux=permissive androidboot.memcg=1 msm_rtb.filter=0x3F ehci-hcd.park=3 coherent_pool=8M sched_enable_power_aware=1 user_debug=31 printk.devkmsg=on loop.max_part=16 kpti=0 androidboot.hardware=lilac androidboot.mode=normal androidboot.configfs=true androidboot.usbcontroller=a800000.dwc3" --output

# LVM physical volume lives in the (Android) userdata partition. lilac is not A/B and has no
# spare partition for the factory image: it is stored as ext4 inside the 5000 MiB "system"
# partition.
%define root_part_label userdata
%define factory_part_label system
%define bcb_part_label misc

# panel0-backlight: max 4095
%define display_brightness_path /sys/class/backlight/panel0-backlight/brightness
%define display_brightness 400

# The fuel gauge reports spurious 0 % at times: no factory-reset battery gate.
%define battery_capacity_file /sys/class/power_supply/battery/capacity
%define battery_capacity_threshold 0

# Measured: rootfs 2.31 GiB + shrunk system.img ~1.4 GB + vendor.img ~0.1 GB
# is ~3.9 GiB used; vendor.img is mounted rw and system.img is rewritten at boot, so leave room.
%define lvm_root_size 6000

%define initrd_combined 1

# Extra key handling in yamui-powerkey
BuildRequires: yamui >= 1.4.0

%include initrd/droid-hal-device-img-boot.inc
