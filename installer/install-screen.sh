#!/bin/bash
# Installs Debian with the intercom on one Fermax MEET ME 10" (DNAKE WIT/v902) screen, from a PC.
#  1. boots the RAM installer over FEL (tools/fel-boot.sh; from Android it switches with adb reboot efex)
#  2. network in the installer, the screen's IP/MAC read from the Android configuration
#  3. full eMMC backup (+ boot0/boot1) to work/backup/<name>/, verified with SHA-256; the vendor
#     files are extracted from it to vendor/ (tools/extract-vendor-files.py)
#  4. writes work/out/meetme-emmc.img.gz, verified with SHA-256
#  5. hostname, static IP, MAC and SSH keys in the new system, reboot
#  6. installer/provision.sh: the settings of your home over SSH
# Needs: the screen's mini-USB cable to the PC, the screen on the LAN, the image from
# installer/build-image.sh, site/site.conf and site/authorized_keys.
# Usage: installer/install-screen.sh [options] NAME     (NAME=104 -> hostname meetme-104)
#   --no-backup      skip the backup (the screen already runs Debian)
#   --backup-only    only back up Android, leave the eMMC untouched
#   --no-fel         the installer already runs on the screen (e.g. retry after an error)
#   --net [IP]       installer booted from an SD card (installer/make-sd.sh), driven over the network
#   --ip IP          static IP when it cannot be read from Android
#   --uboot FILE     a different U-Boot for FEL and the eMMC
#   --boot0          screens whose DRAM only the vendor boot0 can train (docs/dram-boot0-workaround.md)
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
W="${WORK:-$B/work}"
BACKUP=1; FORCE_IP=; FEL=1; UBOOT=; NET=; BACKUP_ONLY=0; BOOT0=
while [[ ${1:-} == --* ]]; do
	case $1 in
	--no-backup) BACKUP=0 ;;
	--backup-only) BACKUP_ONLY=1 ;;
	--no-fel) FEL=0 ;;
	--net) NET=192.168.0.199; FEL=0
		[[ ${2:-} =~ ^[0-9.]+$ ]] && { NET=$2; shift; } ;;
	--ip) FORCE_IP=$2; shift ;;
	--uboot) UBOOT=$(readlink -f "$2"); shift ;;
	--boot0) BOOT0=1; UBOOT=$W/u-boot-nodram/u-boot-sunxi-with-spl.bin ;;
	*) echo "unknown option $1"; exit 2 ;;
	esac
	shift
done
NAME=${1:?give the screen a name, e.g. 104}
HN=meetme-$NAME
OUT="$W/out"
IMG="$OUT/meetme-emmc.img.gz"
[ -f "$IMG" ] || { echo "missing $IMG: run installer/build-image.sh first"; exit 1; }
SIZE=$(cat "$OUT/meetme-emmc.img.size")
SHA=$(cat "$OUT/meetme-emmc.img.sha256raw")
[ -f "$B/site/site.conf" ] || { echo "missing site/site.conf: cp -r site.example site, then edit it"; exit 1; }
# Without a key you could not log in to the new system (it has no root password)
grep -qv '^#' "$B/site/authorized_keys" 2>/dev/null || { echo "put your SSH public key in site/authorized_keys"; exit 1; }
PANEL_IP=$(. "$B/site/site.conf"; echo "${PANEL_IP:-}")
HOST=$(ip -4 route get "${PANEL_IP:-1.1.1.1}" | sed -n 's/.* src \([0-9.]*\).*/\1/p')
if [ -n "$BOOT0" ] && [ ! -f "$B/vendor/boot0-fel.bin" ]; then
	# boot0 is identical on all screens: take it from Android over adb (read only)
	echo "making vendor/boot0-fel.bin from this screen's boot0 (adb)"
	mkdir -p "$B/vendor"
	adb shell 'dd if=/dev/block/mmcblk0boot0 of=/data/local/tmp/boot0.img bs=4096 2>/dev/null'
	adb pull /data/local/tmp/boot0.img "$B/vendor/boot0.img" >/dev/null && adb shell rm /data/local/tmp/boot0.img
	python3 "$B/installer/make-boot0-fel.py" "$B/vendor/boot0.img" "$B/vendor/boot0-fel.bin"
fi
[ -n "$BOOT0" ] && "$B/installer/make-boot0-payload.sh" >/dev/null
dev() {
	if [ -n "$NET" ]; then NETCMD=$NET T=${T:-30} python3 "$B/installer/netcmd.py" "$@"
	else T=${T:-30} python3 "$B/tools/sercmd.py" "$@"; fi
}
log() { echo "$(date +%T) == $*"; }

if [ $FEL = 1 ]; then
	log "1/6 booting the installer over FEL (connect the screen's USB cable; it switches from Android by itself)"
	"$B/build/initramfs.sh" >/dev/null
	if [ -n "$BOOT0" ]; then "$B/installer/fel-boot-boot0.sh" 600
	else UBOOT=$UBOOT "$B/tools/fel-boot.sh" 600; fi
else
	log "1/6 the installer is already running (--no-fel)"
fi
if [ -n "$NET" ]; then
	for n in $(seq 60); do timeout 2 bash -c "</dev/tcp/$NET/2323" 2>/dev/null && break; sleep 2; done
	timeout 2 bash -c "</dev/tcp/$NET/2323" 2>/dev/null || { echo "the installer does not answer on $NET:2323"; exit 1; }
	# The installer is inside the initramfs on the card: it must match the version on the PC
	[ "$(dev md5sum /bin/meetme-install | cut -d' ' -f1)" = "$(md5sum < "$B/installer/device-install.sh" | cut -d' ' -f1)" ] || \
		{ echo "the installer on the card is outdated: run installer/make-sd.sh installer /dev/sdX"; exit 1; }
else
	for n in $(seq 90); do [ -e /dev/ttyACM0 ] && break; sleep 1; done
	[ -e /dev/ttyACM0 ] || { echo "the installer does not answer on /dev/ttyACM0"; exit 1; }
	sleep 3
	python3 "$B/tools/sendfile.py" "$B/installer/device-install.sh" /bin/meetme-install >/dev/null
	sleep 1
fi

log "2/6 network and identity of the screen"
if [ -n "$NET" ]; then
	# The initramfs set up the network at boot; another DHCP would drop the address we talk to
	NETINFO=$(dev cat /tmp/net.log); echo "$NETINFO"
else
	NETINFO=$(T=90 dev meetme-install net); echo "$NETINFO"
	grep -q "^IF=.* IP=[0-9]" <<<"$NETINFO" || { echo "no network in the installer: stopping, eMMC untouched"; exit 1; }
fi
ID=$(dev meetme-install identity); echo "$ID"
IP=${FORCE_IP:-$(sed -n 's/^ip=//p' <<<"$ID")}
GW=$(sed -n 's/^gateway=//p' <<<"$ID"); GW=${GW:-$(ip -4 route | sed -n 's/^default via \([0-9.]*\).*/\1/p' | head -1)}
DNS=$(sed -n 's/^dns=//p' <<<"$ID"); DNS=${DNS:-$GW}
MAC=$(sed -n 's/^mac=//p' <<<"$ID")
[ -n "$IP" ] || { echo "unknown IP of the screen (no Android?): use --ip"; exit 1; }
log "screen $HN, IP $IP, gateway $GW, DNS $DNS, MAC ${MAC:-factory}"

if [ $BACKUP = 1 ]; then
	log "3/6 eMMC backup to work/backup/$HN (about 6 min, 11 min on 100 Mbit cards)"
	D="$W/backup/$HN"; mkdir -p "$D"; : > "$D/SHA256SUMS"
	for part in mmcblk1 mmcblk1boot0 mmcblk1boot1; do
		python3 "$B/installer/recv.py" 9000 "$D/$part.img" 600 > "$D/$part.recv" &
		R=$!; sleep 1
		DEVSHA=$(T=1200 dev meetme-install send /dev/$part "$HOST" 9000 | tail -1)
		wait $R
		read -r BYTES HOSTSHA < "$D/$part.recv"
		[ "$DEVSHA" = "$HOSTSHA" ] || { echo "backup of $part does not match ($BYTES B): stopping, eMMC untouched"; exit 1; }
		echo "$HOSTSHA  $part.img" >> "$D/SHA256SUMS"
		echo "  $part: $BYTES B, SHA-256 matches"
	done
	[ -f "$B/vendor/ring4.wav" ] || python3 "$B/tools/extract-vendor-files.py" "$D/mmcblk1.img" "$B/vendor"
else
	log "3/6 backup skipped (--no-backup)"
fi
[ $BACKUP_ONLY = 1 ] && { log "done: backup only (--backup-only), eMMC untouched"; exit 0; }

log "4/6 writing the image (about 5 min)"
cp "$B/site/authorized_keys" "$OUT/authorized_keys"
( cd "$OUT" && exec python3 -m http.server 8000 >/dev/null 2>&1 ) &
HTTP=$!; trap 'kill $HTTP 2>/dev/null; rm -f "$OUT/authorized_keys" "$OUT/u-boot-alt.bin"' EXIT; sleep 1
WSHA=$(T=1200 dev meetme-install flash "http://$HOST:8000/meetme-emmc.img.gz" "$SIZE" ${BOOT0:+keep-boot0} | tail -1)
[ "$WSHA" = "$SHA" ] || { echo "the written image does not match: do NOT reboot, repeat this step (the Android backup is in work/backup)"; exit 1; }
echo "  written data matches the image"
if [ -n "$UBOOT" ]; then
	cp "$UBOOT" "$OUT/u-boot-alt.bin"
	USIZE=$(stat -c %s "$UBOOT")
	USHA=$(T=60 dev meetme-install uboot "http://$HOST:8000/u-boot-alt.bin" "$USIZE" | tail -1)
	[ "$USHA" = "$(sha256sum < "$UBOOT" | cut -d' ' -f1)" ] || { echo "U-Boot write does not match: do NOT reboot"; exit 1; }
	echo "  U-Boot $(basename "$(dirname "$UBOOT")") written to the eMMC"
fi
if [ -n "$BOOT0" ]; then
	P="$OUT/boot0-payload.bin"
	PSHA=$(T=60 dev meetme-install boot0payload "http://$HOST:8000/boot0-payload.bin" "$(stat -c %s "$P")" | tail -1)
	[ "$PSHA" = "$(sha256sum < "$P" | cut -d' ' -f1)" ] || { echo "boot0-payload write does not match: do NOT reboot"; exit 1; }
	echo "  boot0-payload written (sector 38192), the vendor boot0 stays the boot loader"
fi

log "5/6 screen settings and reboot"
dev meetme-install config "$HN" "$IP/24" "$GW" "$DNS" "http://$HOST:8000/authorized_keys" $MAC
kill $HTTP; trap - EXIT; rm -f "$OUT/authorized_keys" "$OUT/u-boot-alt.bin"
[ -n "$NET" ] && dev meetme-install sd-done
dev reboot -f >/dev/null || true

log "6/6 waiting for Debian at $IP, then applying the settings of your home"
ssh-keygen -R "$IP" >/dev/null 2>&1 || true
for n in $(seq 120); do
	ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new root@"$IP" true 2>/dev/null && break
	sleep 5
done
"$B/installer/provision.sh" "$IP"
log "done: $HN ($IP)"
