# Debian for Fermax MEET ME 10" intercom screens (DNAKE WIT)

Mainline Linux and Debian 13 for the **Fermax MEET ME 10"** video intercom monitor (made by DNAKE,
platform "WIT", Android board `v902`, Allwinner A33). The original Android 4.4 firmware is old,
slow and unmaintained; this project turns the screens into Home Assistant wall panels that are
still fully working intercoms — instead of e-waste.

What you get on every screen:

- **Home Assistant kiosk**: your dashboard full screen, logged in with a token, touch, automatic
  backlight off and wake on touch.
- **Intercom** compatible with the original Fermax MEET door panel: ringing (on all screens of the
  apartment and in the Fermax phone app), two-way audio with echo cancellation, opening the gate,
  panel camera view, a second camera in the call window, events in Home Assistant.
- Plain Debian: SSH, systemd, `apt`. Original screens and Debian screens work side by side.

Nothing on the door panel changes. The panel talks plain SIP over UDP to the screens, without any
server — documented in [docs/protocol.md](docs/protocol.md).

> **Status:** running on six screens of one apartment since November 2026. Other MEET models
> (7", MEET ME with a different board) are untested and need at least their own device tree.

## How it works

```
door panel ──SIP/RTP (LAN)──► screen: meetme-intercom (Python, GStreamer, GTK)
                                      cage + cog (WPE WebKit) ──► nginx :8080 ──► Home Assistant
```

- Linux v7.3.1 with a board device tree and one small driver patch, U-Boot v2026.10.
- Debian armhf root file system built with `mmdebstrap`.
- An installer that boots from RAM over USB (Allwinner FEL) or from an SD card, backs up the whole
  Android eMMC to your PC, verifies it, then writes the image.

## Repository layout

| Path | What |
| --- | --- |
| [`kernel/`](kernel) | board DTS, patches, defconfig |
| [`u-boot/`](u-boot) | board DTS, defconfig, patches (incl. the no-DRAM SPL) |
| [`rootfs/`](rootfs) | Debian package list, system overlay (services, kiosk, nginx), `screen-blank` |
| [`intercom/`](intercom) | `meetme-intercom.py` and SIP/RTP debugging tools |
| [`installer/`](installer) | image builder, PC-side installer, on-device installer, SD card, provisioning |
| [`build/`](build) | build scripts for kernel, U-Boot, root file system and installer |
| [`tools/`](tools) | FEL boot, USB console helpers, vendor file extraction |
| [`site.example/`](site.example) | template of your home's settings (`site/` stays local) |
| [`docs/`](docs) | everything you need to know |

## Quick start

1. Read [docs/install.md](docs/install.md) to the end, and [docs/hardware.md](docs/hardware.md).
2. Build: [docs/building.md](docs/building.md)
   ```bash
   build/kernel.sh && build/u-boot.sh && build/rootfs.sh && build/initramfs.sh
   ```
3. Configure: `cp -r site.example site`, edit `site/site.conf`, add your SSH key to
   `site/authorized_keys` ([docs/home-assistant.md](docs/home-assistant.md) for the token).
4. `installer/build-image.sh`
5. Screen on USB and LAN: `installer/install-screen.sh 101`

## What is not in this repository

No firmware images, backups, keys or anyone's home settings. The two files from the original
firmware that the screens need — the touch controller firmware and the ring tone — are extracted
from **your own** Android backup by `tools/extract-vendor-files.py` (the installer does it for you;
without the ring tone the screens ring with a generated chime).
The installer always backs up the original eMMC before writing anything: keep those backups, there
is no other way back to Android.

## Documentation

- [docs/install.md](docs/install.md): installing, SD card install, going back to Android
- [docs/building.md](docs/building.md): building everything, what is in the image
- [docs/hardware.md](docs/hardware.md): board, chips, variants, boot chain, RAM upgrade notes
- [docs/protocol.md](docs/protocol.md): the Fermax MEET / DNAKE SIP protocol
- [docs/home-assistant.md](docs/home-assistant.md): kiosk, intercom events, camera relay
- [docs/dram-boot0-workaround.md](docs/dram-boot0-workaround.md): screens whose DRAM only the vendor boot loader can train
- [docs/troubleshooting.md](docs/troubleshooting.md): problems we hit and how they were solved

## Security note

The door panel accepts calls and "open gate" commands from any device on the LAN, without a
password. Put the panel and the screens on their own VLAN or behind a firewall.

## License

MIT ([LICENSE](LICENSE)) for the scripts, the intercom application and the documentation.
The kernel and U-Boot patches and device trees are GPL-2.0, like the projects they apply to.
Fermax and MEET are trademarks of Fermax; this project is not affiliated with Fermax or DNAKE.
