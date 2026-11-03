#!/bin/bash
# Builds the eMMC image written by installer/install-screen.sh:
#   work/out/meetme-emmc.img.gz  — MBR + U-Boot (SPL at 8 KiB) + ext4 "meetme-root" from sector 131056
# The root filesystem comes from work/rootfs.tar (build/rootfs.sh), or with --from-screen IP from a
# screen that already runs the system (to clone a hand-tuned screen). Kernel, modules and DTB come
# from work/linux. Secrets and per-screen data (SSH host keys, machine-id, network, HA token,
# vendor files) never go into the image: every screen gets them from installer/provision.sh.
# No root needed: a user namespace with subordinate UIDs (/etc/subuid) lets tar set the real
# owners and mke2fs -d see them.
# Usage: installer/build-image.sh [--from-screen IP]
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
W="${WORK:-$B/work}"
OUT="$W/out"
KVER=$(make -s -C "$W/linux" kernelrelease)
DTB=sun8i-a33-fermax-meetme.dtb
# Same layout as on the screens: partition from sector 131056 to the end of the 4 GB eMMC
P1_START=131056
DISK_SECTORS=7634944
FS_SIZE=1800M            # grows to the full partition on first boot (x-systemd.growfs)
NS="unshare --map-auto --map-root-user"
mkdir -p "$W/image" "$OUT"
# Files from the previous build belong to subordinate UIDs: remove them inside the namespace
$NS rm -rf "$W/image/root"

if [ "${1:-}" = --from-screen ]; then
	SRC=${2:?--from-screen IP}
	echo "== snapshot of $SRC"
	# tar exits with 1 when a file (e.g. a log) changed while being read: logs are emptied anyway
	rc=0
	ssh -o BatchMode=yes root@"$SRC" "tar --one-file-system --numeric-owner --xattrs -cpf - \
		--exclude=./proc --exclude=./sys --exclude=./dev --exclude=./run --exclude=./tmp --exclude=./var/tmp \
		--exclude=./var/cache/apt/archives --exclude=./var/lib/apt/lists --exclude=./var/log/journal \
		--exclude=./home/kiosk/.cache --exclude=./home/kiosk/.local/share/wpe \
		-C / ." > "$W/image/rootfs.tar" || rc=$?
	[ $rc -le 1 ] || { echo "snapshot failed (tar/ssh: $rc)"; exit 1; }
	TAR="$W/image/rootfs.tar"
else
	SRC="build/rootfs.sh"
	TAR="$W/rootfs.tar"
	[ -f "$TAR" ] || { echo "missing $TAR: run build/rootfs.sh first"; exit 1; }
fi

echo "== unpack, clean up, kernel, ext4"
$NS bash -euo pipefail -c '
R="$1"; TAR="$2"; W="$3"; B="$4"; KVER="$5"; DTB="$6"; FS_SIZE="$7"
mkdir -p "$R"
# Device nodes cannot be created in a user namespace (and /dev is a devtmpfs at runtime anyway)
tar --numeric-owner --xattrs -xpf "$TAR" -C "$R" --exclude="./dev/*"
mkdir -p "$R"/{proc,sys,dev,run,tmp,var/tmp,var/log/journal,var/lib/apt/lists/partial,var/cache/apt/archives/partial}
chmod 1777 "$R/tmp" "$R/var/tmp"

# Secrets and data of the source screen
rm -f "$R"/etc/ssh/ssh_host_* "$R"/etc/nginx/meetme-ha-*.conf "$R"/var/lib/systemd/random-seed
rm -f "$R"/etc/systemd/network/10-meetme-* "$R"/root/.ssh/authorized_keys
: > "$R/etc/machine-id"; rm -f "$R/var/lib/dbus/machine-id"
install -m 600 "$B/rootfs/overlay/etc/default/meetme-intercom" "$R/etc/default/meetme-intercom"
install -m 644 "$B/rootfs/overlay/etc/default/meetme-kiosk" "$R/etc/default/meetme-kiosk"
install -m 644 "$B/rootfs/overlay/etc/nginx/sites-enabled/meetme-ha" "$R/etc/nginx/sites-enabled/meetme-ha"
# Vendor files (touch firmware, ring tone) are not ours to redistribute: provision.sh installs them
rm -rf "$R/usr/lib/firmware/silead" "$R/usr/local/share/meetme/ring4.wav"
echo meetme > "$R/etc/hostname"
find "$R/root" -mindepth 1 -maxdepth 1 ! -name .ssh ! -name .bashrc ! -name .profile -exec rm -rf {} +
find "$R/var/log" -type f \( -name "*.gz" -o -name "*.[0-9]" \) -delete
find "$R/var/log" -type f -exec truncate -s 0 {} +

# Kernel from work/linux
rm -rf "$R"/usr/lib/modules/* "$R"/boot/vmlinuz-* "$R"/boot/config-* "$R"/boot/dtbs
make -s -C "$W/linux" ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- INSTALL_MOD_PATH="$R/usr" INSTALL_MOD_STRIP=1 modules_install >/dev/null
rm -f "$R/usr/lib/modules/$KVER/build" "$R/usr/lib/modules/$KVER/source"
mkdir -p "$R/boot/dtbs/$KVER" "$R/boot/extlinux"
cp "$W/linux/arch/arm/boot/zImage" "$R/boot/vmlinuz-$KVER"
cp "$W/linux/arch/arm/boot/dts/allwinner/$DTB" "$R/boot/dtbs/$KVER/$DTB"
cp "$W/linux/.config" "$R/boot/config-$KVER"
cat > "$R/boot/extlinux/extlinux.conf" <<EOF
TIMEOUT 10
DEFAULT meetme
LABEL meetme
	KERNEL /boot/vmlinuz-$KVER
	FDT /boot/dtbs/$KVER/$DTB
	APPEND root=/dev/mmcblk1p1 rootfstype=ext4 rootwait rw console=ttyS0,115200 console=tty1 quiet cma=160M
EOF

rm -f "$W/image/rootfs.ext4"
mke2fs -q -t ext4 -L meetme-root -d "$R" "$W/image/rootfs.ext4" "$FS_SIZE"
' _ "$W/image/root" "$TAR" "$W" "$B" "$KVER" "$DTB" "$FS_SIZE"
e2fsck -fn "$W/image/rootfs.ext4" >/dev/null

echo "== check: no secrets or vendor files in the image"
pats=()
if [ -f "$B/site/site.conf" ]; then
	# Exact secret values of your home; never printed
	for k in HA_TOKEN HA_WEBHOOK_ID; do
		v=$(. "$B/site/site.conf"; eval echo "\${$k:-}")
		[ -n "$v" ] && pats+=("$v")
	done
fi
for i in "${!pats[@]}"; do
	[ ${#pats[$i]} -ge 16 ] || { echo "!! secret pattern $i is too short, check site/site.conf"; exit 1; }
	grep -aqF -- "${pats[$i]}" "$W/image/rootfs.ext4" && { echo "!! the image contains secret $i, aborting"; exit 1; }
done
for f in "$B/vendor/silead/gsl3680-fermax-meetme.fw" "$B/vendor/ring4.wav"; do
	[ -f "$f" ] || continue
	python3 -c 'import mmap,sys; d=open(sys.argv[1],"rb").read(); n=d[len(d)//2:len(d)//2+256]
m=mmap.mmap(open(sys.argv[2],"rb").fileno(),0,access=mmap.ACCESS_READ); sys.exit(m.find(n)>=0)' "$f" "$W/image/rootfs.ext4" \
		|| { echo "!! the image contains $(basename "$f"), aborting"; exit 1; }
done
echo "   ${#pats[@]} secret(s) and the vendor files are absent"

echo "== eMMC image"
IMG="$W/image/meetme-emmc.img"
rm -f "$IMG"
# The partition table describes the full eMMC; the file is cut after the file system
truncate -s $(( DISK_SECTORS * 512 )) "$IMG"
echo "start=$P1_START, size=$(( DISK_SECTORS - P1_START )), type=83" | sfdisk -q --label dos "$IMG"
dd if="$W/u-boot/u-boot-sunxi-with-spl.bin" of="$IMG" bs=1024 seek=8 conv=notrunc status=none
dd if="$W/image/rootfs.ext4" of="$IMG" bs=4M seek=$(( P1_START * 512 )) oflag=seek_bytes conv=notrunc,sparse status=none
truncate -s $(( P1_START * 512 + $(stat -c %s "$W/image/rootfs.ext4") )) "$IMG"
stat -c %s "$IMG" > "$OUT/meetme-emmc.img.size"
sha256sum "$IMG" | cut -d' ' -f1 > "$OUT/meetme-emmc.img.sha256raw"
pigz -9 -c "$IMG" > "$OUT/meetme-emmc.img.gz"
( cd "$OUT" && sha256sum meetme-emmc.img.gz > meetme-emmc.img.gz.sha256 )
rm -f "$IMG"
ls -la "$OUT"
echo "Done: kernel $KVER, root file system from $SRC"
