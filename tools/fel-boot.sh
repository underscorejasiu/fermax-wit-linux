#!/bin/bash
# Boots U-Boot + Linux from RAM over FEL. If the monitor is running Android, it is first switched to FEL.
# UBOOT=file: a different U-Boot (e.g. with another DRAM clock); screens with DRAM via the vendor boot0: installer/fel-boot-boot0.sh
B="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
W="${WORK:-$B/work}"
end=$((SECONDS + ${1:-300}))
while [ $SECONDS -lt $end ]; do
	if sunxi-fel version >/dev/null 2>&1; then
		echo "$(date +%T) FEL detected, loading..."
		sunxi-fel -v -p uboot "${UBOOT:-$W/u-boot/u-boot-sunxi-with-spl.bin}" \
			write 0x42000000 "$W/linux/arch/arm/boot/zImage" \
			write 0x43000000 "$W/linux/arch/arm/boot/dts/allwinner/sun8i-a33-fermax-meetme.dtb" \
			write 0x43100000 "$W/boot.scr" \
			write 0x43300000 "$W/initramfs.cpio.gz"
		exit $?
	fi
	if [ "$(adb get-state 2>/dev/null)" = "device" ]; then
		echo "$(date +%T) Android detected, switching to FEL"
		adb shell reboot efex
		sleep 5
	fi
	sleep 1
done
echo "No device detected"; exit 1
