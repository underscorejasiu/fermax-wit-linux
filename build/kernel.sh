#!/bin/bash
# Mainline Linux for the MEET ME 10" screen: fetch, add the board DTS and patches, build
# zImage, DTB and modules into work/linux.
# Usage: build/kernel.sh
set -euo pipefail
. "$(dirname "$0")/common.sh"
K="$WORK/linux"
fetch_tag "$K" "$LINUX_GIT" "$LINUX_VERSION"
cp "$REPO/kernel/sun8i-a33-fermax-meetme.dts" "$K/arch/arm/boot/dts/allwinner/"
apply_patches "$K" "$REPO"/kernel/*.patch
if [ ! -f "$K/.config" ] || [ "$REPO/kernel/fermax_meetme_defconfig" -nt "$K/.config" ]; then
	cp "$REPO/kernel/fermax_meetme_defconfig" "$K/arch/arm/configs/"
	make -s -C "$K" fermax_meetme_defconfig
fi
log "building Linux $(make -s -C "$K" kernelrelease)"
make -s -C "$K" -j"$JOBS" zImage dtbs modules
ls -la "$K/arch/arm/boot/zImage" "$K/arch/arm/boot/dts/allwinner/$DTB"
