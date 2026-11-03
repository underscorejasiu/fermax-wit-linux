#!/bin/bash
# RAM-only installer that boots over USB (FEL) or from an SD card:
#   busybox (static) and mmc-utils from Debian armhf, network and touch modules from work/linux,
#   mcu-init (powers the USB hub with the network cards), installer/device-install.sh as
#   /bin/meetme-install, installer/initramfs/init; touch firmware from vendor/ when present.
# Result: work/initramfs.cpio.gz and work/boot.scr (for FEL boots; it carries the initramfs size).
# BOOTARGS_EXTRA: extra kernel parameters for the installer.
# Usage: build/initramfs.sh   (after build/kernel.sh and build/u-boot.sh)
set -euo pipefail
. "$(dirname "$0")/common.sh"
K="$WORK/linux"; I="$WORK/initramfs"
rm -rf "$I"; mkdir -p "$I"/{bin,sbin,dev,etc,lib/modules,mnt,proc,root,sys,tmp,usr/bin,usr/sbin}

if [ ! -d "$WORK/initramfs-debs" ]; then
	log "busybox-static and mmc-utils from Debian $DEBIAN_SUITE"
	# To a tarball: a directory would be created by the namespace root, which may not write to $HOME
	mmdebstrap --mode=unshare --architectures=armhf --variant=extract \
		--include=busybox-static,mmc-utils,libc6 "$DEBIAN_SUITE" "$WORK/initramfs-debs.tar" "$DEBIAN_MIRROR"
	mkdir -p "$WORK/initramfs-debs"
	tar -xf "$WORK/initramfs-debs.tar" -C "$WORK/initramfs-debs" --exclude='./dev/*'
	rm "$WORK/initramfs-debs.tar"
fi
D="$WORK/initramfs-debs"
cp "$D/usr/bin/busybox" "$I/bin/busybox"
cp "$D/usr/bin/mmc" "$I/usr/bin/mmc"
mkdir -p "$I/usr/lib/arm-linux-gnueabihf"
cp -L "$D"/usr/lib/arm-linux-gnueabihf/{libc.so.6,ld-linux-armhf.so.3} "$I/usr/lib/arm-linux-gnueabihf/"
ln -s ../usr/lib/arm-linux-gnueabihf/ld-linux-armhf.so.3 "$I/lib/ld-linux-armhf.so.3"

# Network modules (r8152 for SR9900, dm9601 for DM9621) and touch from the current kernel build
for m in drivers/net/usb/r8152.ko drivers/net/usb/dm9601.ko drivers/input/touchscreen/silead.ko; do
	cp "$K/$m" "$I/lib/modules/"
	"${CROSS_COMPILE}strip" --strip-debug "$I/lib/modules/$(basename "$m")"
done
if [ -f "$REPO/vendor/silead/gsl3680-fermax-meetme.fw" ]; then
	mkdir -p "$I/lib/firmware/silead"
	cp "$REPO/vendor/silead/gsl3680-fermax-meetme.fw" "$I/lib/firmware/silead/"
fi
# mcu-init as in the system (heartbeat only, the full DNAKE startup sequence blocked the USB hub)
install -m 755 "$REPO/rootfs/overlay/usr/local/sbin/mcu-init" "$I/usr/bin/mcu-init"
# The installer is built in: when booting from an SD card (no USB) it cannot be sent over the console
install -m 755 "$REPO/installer/device-install.sh" "$I/bin/meetme-install"
install -m 755 "$REPO/installer/initramfs/init" "$I/init"

( cd "$I" && find . | sort | cpio -o -H newc -R 0:0 --quiet ) | gzip -9 > "$WORK/initramfs.cpio.gz"
SIZE=$(printf "%x" "$(stat -c %s "$WORK/initramfs.cpio.gz")")
cat > "$WORK/boot.cmd" <<EOF
setenv bootargs console=ttyS0,115200 console=tty1 loglevel=7 rdinit=/init${BOOTARGS_EXTRA:+ $BOOTARGS_EXTRA}
bootz 0x42000000 0x43300000:$SIZE 0x43000000
EOF
"$WORK/u-boot/tools/mkimage" -q -C none -A arm -T script -d "$WORK/boot.cmd" "$WORK/boot.scr"
log "initramfs $(stat -c %s "$WORK/initramfs.cpio.gz") B (0x$SIZE), kernel $(make -s -C "$K" kernelrelease)"
