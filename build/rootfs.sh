#!/bin/bash
# Debian root filesystem for the screens, built from scratch without root (mmdebstrap in a user
# namespace, armhf code runs through qemu-user binfmt; files go in with mmdebstrap's sync-in/upload,
# because the namespace root may not read your home directory):
#   Debian packages from rootfs/packages.txt, rootfs/overlay, the intercom app, screen-blank,
#   kiosk user, enabled services. Kernel, modules and home-specific settings are added later
#   (installer/build-image.sh, installer/provision.sh).
# Result: work/rootfs.tar
# Usage: build/rootfs.sh
set -euo pipefail
. "$(dirname "$0")/common.sh"
OUT="$WORK/rootfs.tar"

log "screen-blank (static, armhf)"
mkdir -p "$WORK/bin"
"${CROSS_COMPILE}gcc" -O2 -static -o "$WORK/bin/screen-blank" "$REPO/rootfs/screen-blank.c"

PKGS=$(grep -v '^#' "$REPO/rootfs/packages.txt" | tr '\n' ',' | sed 's/,$//')
log "mmdebstrap $DEBIAN_SUITE armhf"
mmdebstrap --mode=unshare --architectures=armhf --variant=apt \
	--include="$PKGS" \
	--customize-hook="sync-in '$REPO/rootfs/overlay' /" \
	--customize-hook="upload '$REPO/intercom/meetme-intercom.py' /usr/local/bin/meetme-intercom" \
	--customize-hook="upload '$WORK/bin/screen-blank' /usr/local/bin/screen-blank" \
	--customize-hook='chmod 755 "$1/usr/local/bin/meetme-intercom" "$1/usr/local/bin/screen-blank"' \
	--customize-hook='chroot "$1" useradd -m -s /bin/bash -G audio,video,input,render kiosk' \
	--customize-hook='chroot "$1" systemctl enable mcu-init audio-init meetme-intercom meetme-kiosk \
		kiosk-crash-watch screen-blank kiosk-recycle.timer meetme-ssh-keys systemd-networkd \
		systemd-resolved systemd-timesyncd seatd nginx earlyoom ssh' \
	--customize-hook='chroot "$1" systemctl set-default graphical.target' \
	--customize-hook='ln -sf ../run/systemd/resolve/stub-resolv.conf "$1/etc/resolv.conf"' \
	--customize-hook='rm -f "$1"/etc/nginx/sites-enabled/default "$1"/etc/ssh/ssh_host_*' \
	--customize-hook='chmod 600 "$1/etc/default/meetme-intercom"' \
	--customize-hook='passwd --root "$1" -l root' \
	"$DEBIAN_SUITE" "$OUT" "$DEBIAN_MIRROR"
ls -la "$OUT"
