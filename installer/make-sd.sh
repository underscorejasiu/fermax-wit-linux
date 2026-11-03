#!/bin/bash
# SD card for installing / rescuing a screen, built from files in the project (the card is not the only copy):
#   installer  network installer (screens without USB, e.g. .102): SPL from u-boot/ at 8 KiB, on the FAT
#              partition the kernel, DTB, initramfs (build/initramfs.sh) and installer/sd-extlinux.conf; then
#              install-screen.sh --net 192.168.0.199 NAME
#   boot0      rescue of screens with DRAM via the vendor boot0 (.103): vendor/boot0-fel.bin at 8 KiB;
#              the screen starts in FEL with working RAM, then DRAM_READY=1 installer/fel-boot-boot0.sh
# The card must have a FAT partition starting at 1 MiB (like a factory card).
# Usage: installer/make-sd.sh installer|boot0 /dev/sdX      (writing the bootloader needs sudo)
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
W="${WORK:-$B/work}"
MODE=${1:?installer or boot0}; DEV=${2:?card device, e.g. /dev/sda}
[ "$(cat /sys/block/"$(basename "$DEV")"/removable)" = 1 ] || { echo "$DEV is not a removable card"; exit 1; }
START=$(cat /sys/block/"$(basename "$DEV")"/"$(basename "$DEV")"1/start)
case $MODE in
installer) SPL="$W/u-boot/u-boot-sunxi-with-spl.bin" ;;
boot0) SPL="$B/vendor/boot0-fel.bin" ;;
*) echo "unknown mode $MODE"; exit 2 ;;
esac
# The bootloader at 8 KiB must not reach the partition
[ $(( 8192 + $(stat -c %s "$SPL") )) -le $(( START * 512 )) ] || { echo "partition starts too early ($START)"; exit 1; }
sudo dd if="$SPL" of="$DEV" bs=1k seek=8 conv=notrunc,fsync status=none
sudo cmp -n "$(stat -c %s "$SPL")" -i 0:8192 "$SPL" "$DEV"
echo "bootloader $(basename "$SPL") written"
if [ "$MODE" = installer ]; then
	"$B/build/initramfs.sh" >/dev/null
	M=$(findmnt -n -o TARGET "${DEV}1" || true)
	[ -n "$M" ] || { udisksctl mount -b "${DEV}1" >/dev/null; M=$(findmnt -n -o TARGET "${DEV}1"); }
	mkdir -p "$M/meetme" "$M/extlinux"
	cp "$W/linux/arch/arm/boot/zImage" "$W/linux/arch/arm/boot/dts/allwinner/sun8i-a33-fermax-meetme.dtb" \
		"$W/initramfs.cpio.gz" "$M/meetme/"
	rm -f "$M/extlinux/extlinux.conf.installer"
	cp "$B/installer/sd-extlinux.conf" "$M/extlinux/extlinux.conf"
	sync
	echo "installer on the card ($M)"
fi
sync; udisksctl unmount -b "${DEV}1" >/dev/null 2>&1 || true
echo "done: the card can be removed"
