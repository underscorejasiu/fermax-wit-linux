#!/bin/bash
# Applies the settings of your home to a screen running the image (over SSH). Nothing of this is in
# the image itself:
#   site/site.conf          Home Assistant URL and token, intercom settings, cameras, time zone
#   site/authorized_keys    SSH keys for root
#   vendor/                 touch firmware and ring tone from your Android backup
#                           (tools/extract-vendor-files.py)
# Usage: installer/provision.sh SCREEN_IP
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
S="$REPO/site"; V="$REPO/vendor"
IP=${1:?usage: installer/provision.sh SCREEN_IP}
[ -f "$S/site.conf" ] || { echo "missing $S/site.conf: cp -r site.example site, then edit it"; exit 1; }
. "$S/site.conf"
: "${HA_URL:?set HA_URL in site/site.conf}" "${HA_TOKEN:?set HA_TOKEN in site/site.conf}"
: "${PANEL_IP:?set PANEL_IP in site/site.conf}"
SSH="ssh -o BatchMode=yes root@$IP"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# nginx: the token in the Authorization header (camera snapshots) and in the kiosk's localStorage
printf 'proxy_set_header Authorization "Bearer %s";\n' "$HA_TOKEN" > "$T/meetme-ha-auth.conf"
printf '%s\n' "sub_filter '<head>' \"<head><script>(function(){var o=location.origin,y=315360000;localStorage.setItem('hassTokens',JSON.stringify({access_token:'$HA_TOKEN',token_type:'Bearer',expires_in:y,hassUrl:o,clientId:o+'/',expires:Date.now()+y*1000,refresh_token:''}));localStorage.setItem('dockedSidebar',JSON.stringify('always_hidden'));})();</script>\";" \
	> "$T/meetme-ha-token.conf"
# Intercom values, appended to /etc/default/meetme-intercom (later lines win)
{
	echo "PANEL_IP=$PANEL_IP"
	echo "SCREENS=\"${SCREENS:-}\""
	echo "EXTRA_URLS=\"${EXTRA_URLS:-}\""
	echo "ROOM=${ROOM:-1000001}"
	echo "PANEL_USER=${PANEL_USER:-10001000001}"
	echo "PANEL_VIDEO_URL=${PANEL_VIDEO_URL:-}"
	echo "CAMERA_URL=${CAMERA_URL:-}"
	[ -n "${HA_WEBHOOK_ID:-}" ] && echo "HA_WEBHOOK=${HA_URL%/}/api/webhook/$HA_WEBHOOK_ID"
} > "$T/intercom.env"
echo "KIOSK_URL=http://localhost:8080${KIOSK_PATH:-/}" > "$T/meetme-kiosk"

scp -q "$T/meetme-ha-auth.conf" "$T/meetme-ha-token.conf" root@"$IP":/etc/nginx/
scp -q "$T/intercom.env" root@"$IP":/etc/default/meetme-intercom.site
scp -q "$T/meetme-kiosk" root@"$IP":/etc/default/meetme-kiosk
if [ -s "$S/authorized_keys" ] && grep -qv '^#' "$S/authorized_keys"; then
	$SSH 'mkdir -p -m 700 /root/.ssh'
	scp -q "$S/authorized_keys" root@"$IP":/root/.ssh/authorized_keys
fi
if [ -f "$V/silead/gsl3680-fermax-meetme.fw" ]; then
	$SSH 'mkdir -p /usr/lib/firmware/silead'
	scp -q "$V/silead/gsl3680-fermax-meetme.fw" root@"$IP":/usr/lib/firmware/silead/
else
	echo "!! no vendor/silead/gsl3680-fermax-meetme.fw: the touchscreen will not work (tools/extract-vendor-files.py)"
fi
if [ -f "$V/ring4.wav" ]; then
	scp -q "$V/ring4.wav" root@"$IP":/usr/local/share/meetme/ring4.wav
else
	echo "!! no vendor/ring4.wav: the screen rings with a generated chime (tools/extract-vendor-files.py)"
fi

$SSH "set -e
chmod 600 /etc/nginx/meetme-ha-*.conf
sed -i 's|proxy_pass .*; # ha-upstream|proxy_pass ${HA_URL%/}; # ha-upstream|' /etc/nginx/sites-enabled/meetme-ha
F=/etc/default/meetme-intercom
# Replace earlier provisioning, keep the defaults from the image
sed -i '/^# --- site ---/,\$d' \$F
{ echo '# --- site ---'; cat \$F.site; } >> \$F; rm \$F.site; chmod 600 \$F
timedatectl set-timezone '${TIMEZONE:-UTC}' 2>/dev/null || ln -sf '/usr/share/zoneinfo/${TIMEZONE:-UTC}' /etc/localtime
# Touch firmware is loaded when the driver binds
modprobe -r silead 2>/dev/null; modprobe silead 2>/dev/null || true
# Without the token files nginx did not start on the first boot: restart, not reload
nginx -t 2>/dev/null && systemctl restart nginx
systemctl restart meetme-kiosk meetme-intercom
sleep 5
echo \"\$(hostname): kiosk \$(systemctl is-active meetme-kiosk), intercom \$(systemctl is-active meetme-intercom)\""
