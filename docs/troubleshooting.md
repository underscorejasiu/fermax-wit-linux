# Troubleshooting and lessons learned

## Access

- SSH as root with the keys from `site/authorized_keys`; there is no root password.
- Over the mini-USB cable the installer (FEL or SD) gives a shell on `/dev/ttyACM0`
  (`tools/sercmd.py CMD`). The installed system does **not** run a USB console, see below.
- The kernel also logs to the UART (`ttyS0`, 115200); nothing here needs it.

## The screen hangs on kernel messages after unplugging USB

Fixed in the image. A login console on the USB gadget (`serial-getty@ttyGS0`) holds the console
lock while it waits for a host; the next restart of the kiosk made systemd print a status line and
block, and the screen stayed on kernel messages until a USB cable was plugged in. The image masks
`serial-getty@ttyGS0` and sets `ShowStatus=no`. Older installs: `ssh root@IP 'sh -s' <
installer/fix-usb-console.sh` (plug USB in first if the screen is stuck).

## Network

- The MCU powers the USB hub with both Ethernet chips only while it gets a heartbeat
  (`mcu-init.service`). No heartbeat, no network.
- After a power cut the chips come back with their factory MAC; `meetme-set-mac` writes Android's
  MAC addresses into `/etc/systemd/network/10-meetme-lan{0,1}.link` so they stick.
- `CONFIG_IP_MULTICAST` must be on: without it the screen never hears the panel's discovery and
  nobody rings.

## Audio

- Mono playback hangs `alsasink` on stop with the A33 codec: play stereo 48 kHz.
- Capture and playback share a clock: record at 48 kHz too.
- Feedback howling: `audio-init` sets Headphone 48, Mic1 Boost 4; the intercom uses `webrtcdsp`
  with delay-agnostic echo cancellation and extended filter, gain control off.

## Intercom

- `journalctl -u meetme-intercom -f` shows SIP traffic decisions, calls and HA events.
- Nobody rings: check `SCREENS`, that the screen hears `238.9.9.1:8400` (`tcpdump -ni lan0 port
  8400`), and that no original master screen answers discovery with a different list first.
- The phone app does not ring: the Fermax cloud account is missing from `EXTRA_URLS`.
- No video before answering: use the panel's RTSP stream through a relay (`PANEL_VIDEO_URL`).

## Kiosk

- WebKit grows ~35 MB/h; `kiosk-recycle.timer` restarts it while the screen is blanked, and
  memory limits in `meetme-kiosk.service.d/memory.conf` stop it from taking the system down.
- The WebKit sandbox (`bwrap`) refuses to start when systemd gives the session `CAP_WAKE_ALARM`;
  the service clears ambient capabilities.
- Touch does not work: the touch firmware is missing (`vendor/silead/…`, run provision again).

## Installer

- Run the build scripts from a plain shell: a Python virtualenv first on `PATH` breaks U-Boot.
- `usb_bulk_send() ERROR -7` after "Executing the SPL": see
  [dram-boot0-workaround.md](dram-boot0-workaround.md).
- A screen that shows no USB device at all and whose `axp20x-usb` reports power with the cable
  unplugged has no USB data lines: use the SD card installer.
- Do not run `pkill -f PATTERN` over the installer shell with a pattern that is also in your own
  command line: it kills the shell.
