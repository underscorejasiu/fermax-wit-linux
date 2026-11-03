# Shared settings for the build scripts (sourced, not executed).
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Everything downloaded or generated goes to work/ (git-ignored); override with WORK=/path
WORK=${WORK:-$REPO/work}
LINUX_VERSION=${LINUX_VERSION:-v7.3.1}
LINUX_GIT=${LINUX_GIT:-https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git}
UBOOT_VERSION=${UBOOT_VERSION:-v2026.10}
UBOOT_GIT=${UBOOT_GIT:-https://source.denx.de/u-boot/u-boot.git}
DEBIAN_SUITE=${DEBIAN_SUITE:-trixie}
DEBIAN_MIRROR=${DEBIAN_MIRROR:-http://deb.debian.org/debian}
CROSS_COMPILE=${CROSS_COMPILE:-arm-linux-gnueabihf-}
DTB=sun8i-a33-fermax-meetme.dtb
JOBS=${JOBS:-$(nproc)}
export ARCH=arm CROSS_COMPILE
mkdir -p "$WORK"

log() { echo "$(date +%T) == $*"; }

# Shallow clone of a tag into $1 (kept between runs; patches are applied once, tracked by a stamp)
fetch_tag() {
	local dir=$1 url=$2 tag=$3
	if [ ! -d "$dir/.git" ]; then
		log "cloning $url $tag"
		git clone -q --depth 1 --branch "$tag" "$url" "$dir"
	fi
}

# Apply each patch once; `git apply --check` makes a half-patched tree fail loudly
apply_patches() {
	local dir=$1; shift
	local p
	for p in "$@"; do
		[ -e "$dir/.applied-$(basename "$p")" ] && continue
		git -C "$dir" apply --check "$p"
		git -C "$dir" apply "$p"
		touch "$dir/.applied-$(basename "$p")"
	done
}
