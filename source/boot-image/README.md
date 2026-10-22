# Boot image

`hybris-boot.img` (md5 `85a18848f8f534c5301e20f7125211bb`) is an Android boot image made of:

- the kernel ([`../kernel/`](../kernel/README.md))
- the Sailfish X modular initrd: an **unmodified** copy of <https://github.com/mer-hybris/hybris-initrd> at commit
  `7b972b6f9498358bdf0a9df6ea1e2587405244c3` (GPL-2.0-only), assembled with the tools from Jolla's SDK target; its helper binaries (LVM2, cryptsetup, busybox and
  similar) are Jolla's builds of the open-source projects, with source from Jolla
- this directory's `rpm/droid-hal-lilac-img-boot.spec`, modelled on `mer-hybris/droid-hal-img-boot-sony-nile`, which builds the image inside the SDK

The image header parameters: base `0x80000000`, kernel offset `0x8000`, ramdisk offset `0x2000000`, tags offset `0x1e00000`, page size 4096, header version 0, OS version
11.0.0, patch level 2021-10, and the kernel command line

```
lpm_levels.sleep_disabled=1 service_locator.enable=1 androidboot.selinux=permissive androidboot.memcg=1 msm_rtb.filter=0x3F ehci-hcd.park=3
coherent_pool=8M sched_enable_power_aware=1 user_debug=31 printk.devkmsg=on loop.max_part=16 kpti=0 androidboot.hardware=lilac
androidboot.mode=normal androidboot.configfs=true androidboot.usbcontroller=a800000.dwc3
```
