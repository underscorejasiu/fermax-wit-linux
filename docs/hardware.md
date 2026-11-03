# Hardware

The Fermax MEET ME 10" monitor is made by DNAKE. Fermax firmware calls the platform "WIT"
(`WIT_Android4_…` update packages); the Android build calls the board `v902`.

## Board

| Part | Value |
| --- | --- |
| Board label | `mio wit monitor 10inch v03.00V usb paset`, silkscreen `E131175`, sticker `DN0483-61` |
| SoC | Allwinner A33, 4× Cortex-A7 @ 1.2 GHz, Mali-400 MP2 (lima), Cedrus video decoder |
| RAM | one DDR3 chip, 512 MB (SK hynix H5TQ4G63EFR-RDC, 4 Gbit x16), 16-bit bus |
| eMMC | 4 GB (`mmcblk1`; hidden boot partitions `boot0`/`boot1` hold the vendor boot loader) |
| PMIC | X-Powers AXP223 (RSB) |
| Display | 1024×600 RGB666 parallel LCD, PWM backlight |
| Touch | Silead GSL3680 on I²C (firmware from the vendor Android driver, see below) |
| Audio | A33 internal codec: speaker on the headphone output, electret mic on MIC1 |
| Network | two USB 10/100 Ethernet chips behind an on-board USB hub (see variants) |
| MCU | a small microcontroller on UART that powers the USB hub; it expects a heartbeat |
| USB | mini-USB OTG port (ADB under Android, FEL and a serial console under Linux) |
| microSD | slot on the board; the A33 boot ROM tries it **before** the eMMC |

### Variants seen in one installation of six screens

| Difference | Most screens | Some screens |
| --- | --- | --- |
| Ethernet chips | CoreChips SR9900 (`0fe6:9900`), driven by `r8152` with an extra USB ID (kernel patch) | Davicom DM9621 (`0a46:9621`), `dm9601` driver, factory MAC `00:00:ff:ff:00:00` |
| mini-USB | works (ADB, FEL) | one screen: no data lines at all, install from an SD card |
| DRAM training | mainline U-Boot trains the DRAM | one screen: mainline training always loses a byte lane; only the vendor boot0 works ([dram-boot0-workaround.md](dram-boot0-workaround.md)) |

Android assigns the MAC addresses (`BC:F8:11:…` / `BC:F8:12:…` in `sys_net.xml`); the chips have
factory addresses. The installer copies Android's MAC into systemd `.link` files so DHCP
reservations and the panel's view of the network stay the same.

## Original software

- Android 4.4 (Allwinner "lichee" kernel 3.4) with the DNAKE apps under `/dnake` (partition 13).
- Partitions: Allwinner layout in an MBR + extended partition; `system` is partition 7, `/dnake`
  13, `syscfg` 14 (`sys_lan.xml`, `sys_net.xml`: IP, gateway, DNS, MAC).
- Boot: boot ROM → `boot0` from the eMMC boot partition (`PARTITION_CONFIG 0x48`) → vendor U-Boot
  2011 at sector 38192 → Android. `adb shell reboot efex` reboots into the boot ROM's USB
  download mode (FEL).
- Fermax updates only replace the apps (`udata/`, `app/` zip packages pushed over the LAN); they
  never contain a boot loader or kernel, and no full firmware image is published.

## Vendor files used by Debian

Not in this repository; `tools/extract-vendor-files.py` takes them from your own Android backup:

- **Touch firmware.** The GSL3680 needs a register table uploaded at every start. Android has it
  compiled into `/vendor/modules/gslX680.ko` as the array `GSL3680B_FW_s3` — a list of
  (register, value) pairs, exactly the format the mainline `silead` driver loads from
  `/usr/lib/firmware/silead/gsl3680-fermax-meetme.fw`.
- **Ring tone.** `/dnake/ringtone/ring4.wav`, the sound of the original screens. Optional: without
  it the intercom rings with a generated two-tone chime.

## Boot paths under Linux

```
normal screens:   boot ROM → U-Boot SPL (eMMC, 8 KiB) → U-Boot → extlinux → Linux
DRAM workaround:  boot ROM → vendor boot0 (eMMC boot0) → boot0-payload (sector 38192)
                  → U-Boot SPL without DRAM init → U-Boot → extlinux → Linux
installer:        FEL over USB, or an SD card (the boot ROM tries the card first)
```

## RAM upgrade (untested)

The A33 has a 16-bit DDR3 controller with 2 ranks and address lines A0–A15. One x16 chip is one
rank, so the largest single chip is 8 Gbit x16 = **1 GB** (e.g. Micron MT41K512M16HA-125, DDR3L
works at 1.5 V; FBGA96). 2 GB would need two ranks, which this board is not wired for.

- The current 4 Gbit chip uses A0–A14. An 8 Gbit chip also needs **A15**; on 4 Gbit chips that
  ball is NC, so check that its pad is routed to the A33 before soldering. Without it the new chip
  works as 512 MB.
- There are no memory-size straps: mainline U-Boot detects rows, columns, ranks and bus width at
  every boot (`DRAM: 1 GiB` on the UART). The vendor boot0 uses `dram_para1` from `sys_config.fex`
  and would need changing to go back to Android.
- The only memory resistors are the standard DDR3 ZQ (240 Ω 1%) and VREF divider.
- After the swap: `memtester 900M 3` and a few hours of kiosk use; lower `CONFIG_DRAM_CLK` in
  U-Boot (552 MHz) on errors.

Vendor DRAM settings (`sys_config.fex`, `[dram_para]`): `dram_clk=552`, `dram_type=3`,
`dram_zq=0x3bbb`, `dram_odt_en=1`, `dram_para1=0x10F20000`, `dram_mr0=0x1840`, `dram_mr1=0x40`,
`dram_mr2=0x8`, `dram_tpr0=0x48a192`, `dram_tpr1=0x1b1b18d`, `dram_tpr2=0x76052`,
`dram_tpr12=0xa8`, `dram_tpr13=0x900`.

References: [A33 datasheet 1.0](https://linux-sunxi.org/A33) (DRAM chapter),
`arch/arm/mach-sunxi/dram_sun8i_a33.c` in U-Boot.
