#!/bin/sh
# The part of the installer that runs on the screen in the initramfs (FEL boot, busybox).
# install-screen.sh on the PC sends it over and calls it. Steps:
#   net                        network: power the hub via the MCU, DHCP on the NIC with a cable
#   identity                   IP/gateway/DNS from the Android config (sys_lan.xml) before it is overwritten
#   send DEV HOST PORT         copy a block device to the PC (dd | nc), then SHA-256
#   flash URL SIZE [keep-boot0]            write the eMMC image from the PC (wget | gunzip | dd), SHA-256 of the written bytes
#   config HOSTNAME IP/PREFIX GW DNS KEYS_URL [MAC]   this screen's settings and root SSH keys in the new system
#   uboot URL SIZE             a different U-Boot at 8 KiB of eMMC (e.g. slower DRAM), SHA-256 of the written bytes
#   boot0payload URL SIZE      payload for the vendor boot0 (sector 38192), SHA-256 of the written bytes
#   sd-done                    SD card install: rename the card's boot config -> .installer so that
#                              the card's U-Boot boots the system from eMMC (the card stays as a rescue)
set -e
EMMC=/dev/mmcblk1

case "$1" in
net)
	pidof mcu-init >/dev/null || { mcu-init >/dev/null 2>&1 & }
	# The MCU powers the USB hub with the NICs after ~2 s of heartbeat
	for n in $(seq 40); do ls /sys/class/net | grep -q '^eth' && break; sleep 1; done
	for i in /sys/class/net/eth*; do ip link set "$(basename "$i")" up; done
	IF=
	for n in $(seq 20); do
		for i in /sys/class/net/eth*; do
			[ "$(cat "$i/carrier" 2>/dev/null)" = 1 ] && IF=$(basename "$i") && break 2
		done
		sleep 1
	done
	[ -n "$IF" ] || { echo "ERROR: no network card has a cable"; exit 1; }
	# the initramfs has no udhcpc script: our own, address and gateway only
	cat > /tmp/dhcp.sh <<'EOF'
#!/bin/sh
[ "$1" = bound ] || [ "$1" = renew ] || exit 0
ip addr flush dev "$interface"
ip addr add "$ip/${mask:-24}" dev "$interface"
[ -n "$router" ] && ip route replace default via "${router%% *}" dev "$interface"
exit 0
EOF
	chmod +x /tmp/dhcp.sh
	udhcpc -i "$IF" -n -q -t 10 -s /tmp/dhcp.sh >/dev/null 2>&1 || true
	ADDR=$(ip -4 -o addr show "$IF" | awk '{print $4}')
	[ -n "$ADDR" ] || { echo "ERROR: no DHCP address on $IF"; exit 1; }
	echo "IF=$IF MAC=$(cat /sys/class/net/$IF/address) IP=$ADDR"
	;;
identity)
	mkdir -p /mnt/a
	# Android syscfg partition (p14) with /dnake/cfg; missing = screen already without Android
	if mount -o ro -t ext4 ${EMMC}p14 /mnt/a 2>/dev/null; then
		for k in ip gateway dns; do
			echo "$k=$(sed -n "s:.*<$k>\([^<]*\)</$k>.*:\1:p" /mnt/a/sys_lan.xml)"
		done
		# MAC that Android assigns to the NICs (they have factory 00:e0:99:...)
		echo "mac=$(tr -d '\n' < /mnt/a/sys_net.xml | sed -n 's:.*<mac>\([^<]*\)</mac>.*:\1:p')"
		umount /mnt/a
	else
		echo "android=none"
	fi
	;;
send)
	dd if="$2" bs=1M 2>/dev/null | nc "$3" "$4"
	sha256sum "$2" | cut -d' ' -f1
	;;
flash)
	# When booting from an SD card there are two MMC devices: write only to the built-in 4 GB eMMC (not the card)
	[ "$(cat /sys/block/mmcblk1/device/type 2>/dev/null)" = MMC ] && [ "$(cat /sys/block/mmcblk1/size)" = 7634944 ] || \
		{ echo "ERROR: $EMMC is not the built-in 4 GB eMMC, writing nothing"; exit 1; }
	grep -q " /mnt/" /proc/mounts && umount /mnt/* 2>/dev/null || true
	wget -q -O - "$2" | gunzip | dd of=$EMMC bs=1M 2>/dev/null
	sync
	blockdev --rereadpt $EMMC
	# Android boots from the hidden eMMC boot0 partition (PARTITION_CONFIG 0x48): its bootloader will no
	# longer find Android and the screen falls back to FEL. We disable booting from boot0 (it is not
	# overwritten), so the BROM takes the U-Boot SPL from 8 KiB of the main area. Back to Android:
	# mmc bootpart enable 1 0 $EMMC
	# KEEP_BOOT0=1 (screens where the mainline SPL does not train DRAM): boot from boot0 stays, the
	# vendor boot0 sets up DRAM and loads boot0-payload (step boot0payload)
	if [ "${4:-}" = keep-boot0 ]; then
		mmc extcsd read $EMMC | grep -q "PARTITION_CONFIG: 0x48" || { echo "ERROR: boot from boot0 is not enabled"; exit 1; }
	else
		mmc bootpart enable 0 0 $EMMC
		mmc extcsd read $EMMC | grep -q "PARTITION_CONFIG: 0x00" || { echo "ERROR: boot from boot0 is still enabled"; exit 1; }
	fi
	head -c "$3" $EMMC | sha256sum | cut -d' ' -f1
	;;
config)
	HN=$2; ADDR=$3; GW=$4; DNS=$5; KEYS=$6; MAC=${7:-}
	mkdir -p /mnt/r
	mount -t ext4 ${EMMC}p1 /mnt/r
	echo "$HN" > /mnt/r/etc/hostname
	sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HN/" /mnt/r/etc/hosts
	grep -q "^127.0.1.1" /mnt/r/etc/hosts || printf '127.0.1.1\t%s\n' "$HN" >> /mnt/r/etc/hosts
	# Static address from Android: the intercom's screen list is based on IP
	cat > /mnt/r/etc/systemd/network/10-meetme-static.network <<EOF
# Static screen address (from the Android config at install time): the panel calls the addresses from the SCREENS list
[Match]
Name=en* eth* lan*

[Network]
Address=$ADDR
Gateway=$GW
DNS=$DNS
EOF
	# Static MAC from Android (otherwise the NICs revert to the factory 00:e0:99:... after a power cut)
	[ -n "$MAC" ] && sh /mnt/r/usr/local/sbin/meetme-set-mac "$MAC" /mnt/r
	# SSH keys for root: the image has none and no root password
	mkdir -p /mnt/r/root/.ssh && chmod 700 /mnt/r/root/.ssh
	wget -q -O /mnt/r/root/.ssh/authorized_keys "$KEYS"
	chmod 600 /mnt/r/root/.ssh/authorized_keys
	sync
	umount /mnt/r
	echo "configured $HN $ADDR $MAC"
	;;
uboot)
	wget -q -O /tmp/u-boot.bin "$2"
	dd if=/tmp/u-boot.bin of=$EMMC bs=1024 seek=8 conv=notrunc 2>/dev/null
	sync
	dd if=$EMMC bs=1024 skip=8 count=$(( ($3 + 1023) / 1024 )) 2>/dev/null | head -c "$3" | sha256sum | cut -d' ' -f1
	;;
boot0payload)
	# Payload for the vendor boot0 in place of its u-boot (sector 38192 = 0x9530): boot0 sets up DRAM
	wget -q -O /tmp/payload.bin "$2"
	dd if=/tmp/payload.bin of=$EMMC bs=512 seek=38192 conv=notrunc 2>/dev/null
	sync
	dd if=$EMMC bs=512 skip=38192 count=$(( ($3 + 511) / 512 )) 2>/dev/null | head -c "$3" | sha256sum | cut -d' ' -f1
	;;
sd-done)
	mkdir -p /mnt/sd
	mount -t vfat /dev/mmcblk0p1 /mnt/sd
	mv /mnt/sd/extlinux/extlinux.conf /mnt/sd/extlinux/extlinux.conf.installer
	sync
	umount /mnt/sd
	echo "SD card: installer disabled (extlinux.conf.installer)"
	;;
*)
	echo "usage: $0 net|identity|send|flash|config|uboot|boot0payload|sd-done"; exit 2
	;;
esac
