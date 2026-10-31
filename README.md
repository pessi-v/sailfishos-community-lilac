# Sailfish OS for the Sony Xperia XZ1 Compact (lilac, G8441): community image


A community port of Sailfish OS 5.2.0.22 for the **Sony Xperia XZ1 Compact, model G8441**, installed to internal storage in the
Sailfish X layout (LVM user data, factory reset, modular boot image). It is not affiliated with or endorsed by Jolla or Sony and comes
with no warranty. **Flashing erases everything on the phone.** Back up first.

This repository holds the flashing scripts and this guide. The images are attached to the
[release](https://github.com/pessi-v/sailfishos-community-lilac/releases) (they are too large for git). Sony's proprietary binaries are not included; you download them from Sony
and the included script prepares them (step 3).

## What you need

- A **Sony Xperia XZ1 Compact, model G8441** (no other model or variant).
- A computer with `fastboot` (Linux: `android-tools-fastboot`; macOS: `brew install --cask android-platform-tools`), `python3`,
  `unzip`, `gunzip`, and `e2fsprogs` 1.43 or newer (Linux: usually installed; macOS: `brew install e2fsprogs`).
  Windows is untested (the scripts are bash).
- A USB cable that works with the phone (a bad cable is the most common reason the phone is not seen in fastboot mode).
- About 12 GB of free disk space while preparing.

You do **not** need `adb` or Android developer tools on the computer; everything is done with `fastboot`.

## Step 1: Unlock the bootloader (once)

`flash.sh` refuses to run on a locked phone, so this is required. Sony officially supports it for this model.
**Unlocking erases the phone and permanently deletes Sony's DRM keys** (stored in the TA partition; stock Android
features that depend on them stop working). It cannot be undone. Sony's page is authoritative and may
change; follow it: <https://developer.sony.com/develop/open-devices/get-started/unlock-bootloader/>. In short:

1. On the phone's dialer, enter `*#*#7378423#*#*` > _Service info_ > _Configuration_. It must say **Bootloader unlock allowed: Yes**.
   If it says No, this phone cannot be unlocked and this port cannot be installed on it.
2. Settings > About phone: tap _Build number_ seven times. Settings > Developer options: switch **OEM unlocking** on
   (this needs an internet connection).
3. Get the phone's IMEI (`*#06#`), request the unlock key on Sony's page, and receive it by e-mail.
4. Power the phone off, wait 15 seconds, plug in the USB cable, then hold **Volume Up** + Power button until the device vibrates and a blue LED turns on.
   The **blue LED** means the device is in fastboot mode.
   Then run the command Sony shows, which has the form `fastboot oem unlock 0x<your key>`.

If you already unlocked the phone, check with `fastboot getvar unlocked` (answer `yes`). `flash.sh` checks it again before it writes anything.

## Step 2: Put Sony's stock firmware 47.2.A.11.234 on the phone

The port uses the phone's own stock `vendor`, `bluetooth` and modem partitions at every boot, and this package does not
touch them. They must come from Sony stock Android 9, **build 47.2.A.11.234** (G8441, any region). Check in Settings > About phone > Build number.
If the phone is on another build, download that firmware with XperiFirm and flash it with
[newflasher](https://github.com/munjeni/newflasher) (follow its instructions; use the stock flash only, never wipe or flash the
TA or persist partitions). Other builds are untested.

## Step 3: Build the Sony `oem` image

Download the two software-binary packages for Yoshino from
<https://developer.sony.com/develop/open-devices/downloads/software-binaries/> (accept Sony's licence):

- `SW_binaries_for_Xperia_Android_11_4.14_v9a_yoshino`
- `SW_binaries_for_Xperia_Android_11_4.14_v8a_yoshino`

Clone or download this repository, put both `.zip` files next to `merge-oem.sh`, and run:

```
./merge-oem.sh
```

It writes `SW_binaries_merged_yoshino.img` (v9a plus 58 files that v9a dropped but the modem stack still needs from v8a)
and checks the result. It never changes your downloads and needs no root.

## Step 4: Download the images

From the [release page](https://github.com/pessi-v/sailfishos-community-lilac/releases) download these three files into the same folder as `flash.sh`:

- `hybris-boot.img`
- `fimage.img001`
- `sailfish.img001.gz`, then unpack it: `gunzip sailfish.img001.gz`

`md5.lst` (in this repository, from the release tag) lists the expected checksums. `flash.sh` checks them before it writes anything.

## Step 5: Flash

1. Power the phone off, wait 15 seconds, plug in the USB cable, then hold **Volume Up** + Power button until the device vibrates and a blue LED turns on.
   The **blue LED** means the device is in fastboot mode.
2. Check that the computer sees it: `fastboot devices` must list the phone. If not, try another cable or port.
3. Run `./flash.sh`. It verifies every file against `md5.lst`, does a dry run, and only then writes
   `boot`, `userdata`, `system` and `oem`. It never writes `vendor`, `bluetooth`, the modem and DSP partitions, `persist`, `TA`
   or the bootloader chain.
4. When it says flashing is complete, unplug the cable and power the phone on with the power key.

The first boot takes several minutes: the storage is resized and Sailfish OS sets itself up. Then the setup wizard starts.

## If something goes wrong

- **No blue LED / `fastboot devices` is empty:** unplug, power off completely (hold the power key 10 s), wait 15 s, plug in, hold
  Volume Up + Power button. Try another USB port or cable.
- **`flash.sh` says the device is not unlocked:** do step 1.
- **The phone does not boot, or shows no display after flashing:** power off, wait 30 s, power on again once. The phone's UFS
  storage sometimes fails to initialise on a cold boot (a known hardware quirk); a second power cycle normally fixes it.
- **Go back to Android:** flash Sony's stock firmware again with newflasher (step 2). Unlocking stays in place.

## Known issues

Please report issues. Generally things should work, but needs testing.

## What is in the images, and licences

- `hybris-boot.img`: Linux kernel 4.14 (GPL-2.0) and the Sailfish X initrd (GPL-2.0).
- `sailfish.img001`: the Sailfish OS 5.2.0.22 root and home file systems, with the Android hardware-adaptation layer built from AOSP-based sources.
  Almost all of it is unmodified software from Jolla's public package repositories (`releases.jolla.com`), including Jolla's closed-source
  packages (the user interface and its apps). Those packages are included as Jolla publishes them and remain under Jolla's terms (shown in
  Settings > About on the phone).
- `fimage.img001`: the factory-reset copy of the same file systems.
- **No Sony binaries are included.** You obtain them from Sony under Sony's licence (step 3).

### Source code

The source for the GPL and LGPL parts that were built or changed is in [`source/`](source/README.md): the kernel (upstream commit, the 19-file diff and the exact configuration),
the boot image, the device-specific packages and the changes made to the Android and hybris source trees. The source
of unchanged packages from Jolla is available from Jolla (<https://github.com/sailfishos>, and the source code offer in Settings > About on the phone).

### Trademarks and licences of this repository

"Sailfish" and "Jolla" are trademarks of Jolla Mobile Ltd, and "Xperia" is a trademark of Sony. This is an unofficial community build; it is not made, supported or endorsed
by Jolla or Sony. The scripts in this repository are MIT-licensed (`LICENSE`), except `flash.sh`, which is Jolla's generic flashing script under the
BSD 3-clause licence (its header). Files under `source/` keep the licences of the projects they come from.
