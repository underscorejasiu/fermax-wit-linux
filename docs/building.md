# Building

Everything is built on a Linux PC (tested on Ubuntu 24.04, x86-64) without root. Downloads and
build output go to `work/` (git-ignored, ~6 GB).

## Host packages

```bash
sudo apt install git make bc bison flex libssl-dev gcc-arm-linux-gnueabihf \
  swig python3-dev python3-setuptools python3-pyelftools device-tree-compiler \
  mmdebstrap qemu-user-static binfmt-support uidmap e2fsprogs fdisk pigz cpio \
  sunxi-tools adb
```

- `mmdebstrap --mode=unshare` and `installer/build-image.sh` use a user namespace: your user needs
  subordinate IDs in `/etc/subuid` and `/etc/subgid` (Ubuntu adds them for regular users).
- `qemu-user-static` with binfmt runs the armhf maintainer scripts while building the root file
  system.
- If U-Boot fails with Python errors about `setuptools`/`elftools`, a Python virtualenv is first on
  your `PATH`; run the build with `PATH=/usr/bin:$PATH`.

## Steps

```bash
build/kernel.sh      # work/linux: Linux v7.3.1 + kernel/*.patch + board DTS + defconfig
build/u-boot.sh      # work/u-boot and work/u-boot-nodram: U-Boot v2026.10 + u-boot/*.patch
build/rootfs.sh      # work/rootfs.tar: Debian 13 (trixie) armhf + rootfs/overlay + intercom
build/initramfs.sh   # work/initramfs.cpio.gz + work/boot.scr: the RAM installer
installer/build-image.sh   # work/out/meetme-emmc.img.gz: what gets written to the eMMC
```

Versions, mirrors and the toolchain prefix are at the top of `build/common.sh` and can be
overridden from the environment (`LINUX_VERSION=…`, `DEBIAN_MIRROR=…`, `WORK=…`).

`installer/build-image.sh --from-screen IP` takes the root file system from a screen that already
runs the system instead of `work/rootfs.tar`, e.g. to clone a screen you tuned by hand. Either way
the image never contains: SSH host keys, machine-id, network settings, the HA token or webhook, your
SSH keys, the touch firmware or the ring tone. The script checks for the secrets in `site/site.conf`
and for the vendor files and aborts if it finds them.

## What is in the image

- Debian 13 armhf, systemd, systemd-networkd/resolved/timesyncd, zram swap, earlyoom, OpenSSH.
- Kiosk: `cage` + `cog` (WPE WebKit) on tty1 as user `kiosk`, nginx on `127.0.0.1:8080` proxying
  Home Assistant and injecting the access token. `kiosk-recycle.timer` restarts the browser while
  the screen is blanked (WebKit grows ~35 MB/h); `kiosk-crash-watch` restarts it when the renderer dies.
- `screen-blank`: backlight off after inactivity, wake on touch; HTTP on `127.0.0.1:8099`.
- `meetme-intercom`: SIP intercom with a GTK call window (`intercom/meetme-intercom.py`).
- `mcu-init`: heartbeat for the MCU that powers the USB hub with the network chips.
- `audio-init`: codec mixer levels tuned against feedback howling.
- `meetme-set-mac`: MAC addresses from Android as systemd `.link` files.
- The root file system fills the eMMC on first boot (`x-systemd.growfs`).

## Kernel notes

- `CONFIG_IP_MULTICAST=y` is required: the intercom listens to the panel's discovery on
  `238.9.9.1:8400`.
- `cma=160M` on the command line: the Cedrus H.264 decoder and the display need it.
- Modules for both Ethernet variants: `r8152` (with the SR9900 USB ID patch) and `dm9601`.
- The board DTS (`kernel/sun8i-a33-fermax-meetme.dts`) covers display, backlight, touch, audio,
  USB host/OTG, MMC, the PMIC regulators and the MCU UART.
