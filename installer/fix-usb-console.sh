#!/bin/sh
# Fix for the systemd hang without a USB cable: login console on ttyGS0 disabled, no status messages on the console
systemctl mask serial-getty@ttyGS0.service >/dev/null 2>&1
rm -rf /etc/systemd/system/serial-getty@ttyGS0.service.d
mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nShowStatus=no\n' > /etc/systemd/system.conf.d/meetme.conf
for p in /proc/[0-9]*; do
	c=$(cat $p/comm 2>/dev/null)
	if [ "$c" = "(agetty)" ] || [ "$c" = agetty ] || ls -l $p/fd 2>/dev/null | grep -q ttyGS0; then
		echo "kill $(basename $p) $c"; kill -9 $(basename $p)
	fi
done
sleep 2
systemctl daemon-reexec
sleep 2
echo "ShowStatus: $(systemctl show -p ShowStatus --value), getty: $(systemctl is-active serial-getty@ttyGS0.service)/$(systemctl is-enabled serial-getty@ttyGS0.service 2>/dev/null), kiosk: $(systemctl is-active meetme-kiosk), intercom: $(systemctl is-active meetme-intercom)"
