# Installing a screen

Every screen gets the same image. It keeps its IP and MAC address (read from Android during the
install), and a full, verified copy of its Android eMMC goes to your PC first, so you can always
go back. Plan ~20 minutes per screen.

> **Risk.** This replaces the manufacturer's firmware. Keep the Android backups: Fermax publishes no
> firmware image, so they are the only way back. Try one secondary screen first.

## 1. Prepare (once)

1. Build everything ([building.md](building.md)).
2. Your settings: `cp -r site.example site`, then edit `site/site.conf` and put your SSH public key
   in `site/authorized_keys`. `site/` is git-ignored and never goes into the image.
   - Home Assistant: create a non-admin user for the kiosk, log in as that user once, create a
     long-lived access token (profile → Security) and set `HA_TOKEN`. See
     [home-assistant.md](home-assistant.md).
   - Intercom: `PANEL_IP`, `SCREENS` (all screens of the apartment, same list everywhere) and
     `EXTRA_URLS` (the Fermax cloud account, or the phone app stops ringing; see
     [protocol.md](protocol.md#discovery-who-rings)).
3. `installer/build-image.sh`

The vendor files (touch firmware, ring tone) are extracted to `vendor/` automatically from the
first Android backup.

## 2. Install one screen (USB)

1. Connect the screen's mini-USB port to the PC (the cable that gives you `adb devices` under
   Android) and the screen to the LAN.
2. ```bash
   installer/install-screen.sh 101
   ```
   (`101` is a name: hostname `meetme-101`). The script:
   - switches Android to FEL (`adb reboot efex`) and boots the installer from RAM,
   - brings up the network and reads IP, gateway, DNS and MAC from Android's configuration,
   - copies the whole eMMC (+ `boot0`/`boot1`) to `work/backup/meetme-101/` and compares SHA-256
     with the screen — on any mismatch it stops without writing anything,
   - writes the image and checks the SHA-256 of the written data,
   - sets hostname, static IP, MAC and your SSH keys, makes the eMMC boot U-Boot instead of
     Android's boot loader (`PARTITION_CONFIG` 0x48 → 0x00), reboots,
   - applies your settings over SSH (`installer/provision.sh`).
3. Check: dashboard on the screen, the camera button, a ring from the panel on every screen,
   talking, opening the gate, the phone app.

Options: `--no-backup` (the screen already runs Debian), `--ip 192.168.1.101` (if the IP cannot be
read from Android), `--backup-only` (back up Android and stop).

## 3. Install from an SD card (no working USB)

For screens whose USB port is dead. The A33 boot ROM tries the SD card before the eMMC, so a card
is also the rescue path.

1. `installer/make-sd.sh installer /dev/sdX` — the card needs a FAT partition starting at 1 MiB
   (as cards come from the factory). It writes U-Boot at 8 KiB, and the kernel, DTB, initramfs
   and `extlinux.conf` to the FAT partition.
2. Card into the screen, power-cycle it. The installer brings up the network (DHCP plus a fixed
   `192.168.0.199`) and shows its address on the screen; it opens a shell for the PC on port 2323.
   Change `192.168.0.199` in `installer/initramfs/init` if your LAN uses another range.
3. ```bash
   installer/install-screen.sh --net 192.168.0.199 102
   ```
   Same steps as over USB. It writes only to the built-in 4 GB eMMC (it checks the device type and
   size), never to the card.
4. At the end the installer renames the card's `extlinux.conf` to `extlinux.conf.installer`: the
   card's U-Boot then boots the system from the eMMC, so the card can stay in. To reinstall or
   rescue, rename it back on the PC.

## 4. Screens whose DRAM fails with mainline U-Boot

Symptom: `usb_bulk_send() ERROR -7` right after the SPL runs over FEL, black screen from the SD
card. Use `installer/install-screen.sh --boot0 NAME`; see
[dram-boot0-workaround.md](dram-boot0-workaround.md).

## Order of screens

The panel asks "who answers for apartment 1000001?" and rings the screens of the **first** answer.
While original screens remain, the original master screen also answers (with its own list), so a
ring can occasionally skip the Debian screens. Migrate the master early:

1. one secondary screen, full test (ring on every screen, talk, gate, phone app),
2. the master screen — from then on only Debian screens answer, original secondary screens keep
   ringing because they are on `SCREENS`,
3. the remaining screens one by one, with a quick ring test after each.

To change the list of screens later: edit `SCREENS` in `site/site.conf` and run
`installer/provision.sh IP` for every screen.

## Going back to Android

The backup is in `work/backup/meetme-NNN/` (`mmcblk1.img`, `mmcblk1boot0.img`,
`mmcblk1boot1.img`, `SHA256SUMS`). Boot the installer (`tools/fel-boot.sh`, or the SD card), bring
up the network (`meetme-install net`), serve the backup directory over HTTP from the PC
(`python3 -m http.server 8000`), and on the screen:

```
wget -O - http://PC:8000/mmcblk1.img | dd of=/dev/mmcblk1 bs=1M
mmc bootpart enable 1 0 /dev/mmcblk1
```

The second line makes the eMMC boot from its hidden `boot0` partition again, where Android's boot
loader lives (the installer never overwrites `boot0`/`boot1`; their copies are in the backup in
case they get damaged).
