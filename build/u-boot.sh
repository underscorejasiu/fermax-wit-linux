#!/bin/bash
# U-Boot for the MEET ME 10" screen, two variants:
#   work/u-boot         normal SPL (trains DRAM itself) — almost every screen
#   work/u-boot-nodram  SPL that skips DRAM init — screens whose DRAM only the vendor boot0 can
#                       train (docs/dram-boot0-workaround.md)
# Needs the host packages from docs/building.md (swig, python3-dev, python3-setuptools, ...).
# Usage: build/u-boot.sh
set -euo pipefail
. "$(dirname "$0")/common.sh"
# U-Boot builds Python extensions with the system Python: a virtualenv first on PATH breaks it
export PATH=/usr/bin:$PATH
build() {
	local dir=$1; shift
	fetch_tag "$dir" "$UBOOT_GIT" "$UBOOT_VERSION"
	cp "$REPO/u-boot/sun8i-a33-fermax-meetme.dts" "$dir/arch/arm/dts/"
	cp "$REPO/u-boot/fermax_meetme_defconfig" "$dir/configs/"
	apply_patches "$dir" "$@"
	make -s -C "$dir" fermax_meetme_defconfig
	log "building $(basename "$dir")"
	make -s -C "$dir" -j"$JOBS"
	ls -la "$dir/u-boot-sunxi-with-spl.bin"
}
build "$WORK/u-boot" "$REPO/u-boot/0001-sunxi-add-Fermax-MEET-ME-10-dts.patch"
build "$WORK/u-boot-nodram" "$REPO/u-boot/0001-sunxi-add-Fermax-MEET-ME-10-dts.patch" \
	"$REPO/u-boot/0002-sunxi-spl-skip-DRAM-init-boot0-did-it.patch"
