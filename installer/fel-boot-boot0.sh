#!/bin/bash
# Boots the installer over FEL with DRAM initialized by the vendor boot0 (vendor/boot0-fel.bin
# from make-boot0-fel.py), for screens where the mainline SPL does not train DRAM (.103).
#  1. boot0-fel.bin as the SPL: DRAM the vendor way, then boot0 returns to FEL by itself
#  2. SPL from u-boot-nodram/ (clocks, pins, PMIC; skips DRAM), then U-Boot, kernel and installer
#     as in fel-boot.sh
# Switches from Android by itself (adb reboot efex). Usage: installer/fel-boot-boot0.sh [seconds]
set -uo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
W="${WORK:-$B/work}"
BOOT0="$B/vendor/boot0-fel.bin"
[ -f "$BOOT0" ] || { echo "missing $BOOT0: installer/make-boot0-fel.py BOOT0_COPY $BOOT0"; exit 1; }
end=$((SECONDS + ${1:-300}))
until timeout 3 sunxi-fel version >/dev/null 2>&1; do
	[ $SECONDS -gt $end ] && { echo "No device detected"; exit 1; }
	if [ "$(adb get-state 2>/dev/null)" = "device" ]; then
		echo "$(date +%T) Android detected, switching to FEL"
		adb shell reboot efex
		sleep 5
	fi
	sleep 1
done
# DRAM_READY=1: FEL after boot0-fel.bin from the SD card (rescue without Android), DRAM already works; running
# boot0 a second time with DRAM already up hangs the screen
if [ "${DRAM_READY:-0}" = 1 ]; then
	echo "$(date +%T) FEL detected, DRAM already initialized (DRAM_READY=1)"
else
	echo "$(date +%T) FEL detected, DRAM via boot0..."
	# boot0 does not return to sunxi-fel, it jumps to FEL in the BROM (USB reconnects)
	timeout 15 sunxi-fel spl "$BOOT0" >/dev/null 2>&1
	for n in $(seq 20); do timeout 3 sunxi-fel version >/dev/null 2>&1 && break; sleep 1; done
	timeout 3 sunxi-fel version >/dev/null 2>&1 || { echo "boot0 did not return to FEL"; exit 1; }
fi
echo "$(date +%T) DRAM ready, loading the no-DRAM SPL, U-Boot and installer..."
# The SPL from u-boot-nodram/ sets up clocks, pins and PMIC as on other screens, but does not touch the DRAM controller
sunxi-fel -p uboot "$W/u-boot-nodram/u-boot-sunxi-with-spl.bin" \
	write 0x42000000 "$W/linux/arch/arm/boot/zImage" \
	write 0x43000000 "$W/linux/arch/arm/boot/dts/allwinner/sun8i-a33-fermax-meetme.dtb" \
	write 0x43100000 "$W/boot.scr" \
	write 0x43300000 "$W/initramfs.cpio.gz"
