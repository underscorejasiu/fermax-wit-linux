# Screens whose DRAM only the vendor boot0 can train

## Symptoms

- Over FEL, `sunxi-fel spl` / `uboot` reports `usb_bulk_send() ERROR -7` right after
  "Executing the SPL… done"; the screen stays black and FEL stops answering.
- Booting the SD-card installer gives a black screen as well (the same SPL).
- Android on the same screen runs fine.

## Cause

Diagnosed on one screen out of six by bisecting the SPL with markers in the RTC general-purpose
registers (readable over FEL) and testing RAM over FEL:

- USB, the SoC (same SID prefix and revision), SRAM A1/A2 and the PMIC were fine; the vendor
  `boot0` is byte-identical on every screen.
- Mainline U-Boot (`dram_sun8i_a33.c`) detects 512 MB, but DQS gate training always fails on one
  of the two 8-bit byte lanes and the PHY disables it: at 552 MHz the CPU hangs on the first DRAM
  access, at 360 MHz every other byte reads 0.
- Not fixed by: DRAM at 360/408 MHz, CPU at 816 MHz, 1.2 V CPU rail, keeping all AXP rails on,
  copying the vendor DX delay registers, turning off the DRAM PLL spread spectrum, MBUS at 400 MHz.
  The controller registers after the vendor init are almost identical to mainline's; the difference
  is in the training sequence of the closed-source boot0.

## Workaround: let the vendor boot0 do the DRAM

boot0, after training the DRAM, loads the vendor U-Boot from the eMMC; when that fails it prints
"Jump to Fel." and jumps to the boot ROM's FEL mode **with the DRAM still running**. Everything
else is ordinary mainline:

1. **`vendor/boot0-fel.bin`** (`installer/make-boot0-fel.py`): a copy of your boot0 with one
   instruction changed: the call that loads the vendor U-Boot (`bl` at `0x3004` in boot0 v3.1.0 of
   these screens) becomes "failed". Run over FEL or from an SD card it trains the DRAM and returns
   to FEL. The script checks the instruction and refuses other boot0 versions.
2. **`u-boot-nodram`** (`u-boot/0002-…patch`): the normal U-Boot with an SPL that skips DRAM init
   and assumes 512 MB. It still sets clocks, pins and the PMIC.
3. **`work/out/boot0-payload.bin`** (`installer/make-boot0-payload.sh`, `installer/boot0-stub.S`):
   a file in the format boot0 expects in place of the vendor U-Boot at eMMC sector 38192 (header
   `uboot`, eGON checksum; boot0 overwrites bytes 0x30–0xb0 and 0xe4 with its DRAM parameters, so
   the code starts at 0x400). It copies the no-DRAM SPL into SRAM, marks the eGON header as booted
   from eMMC and jumps to it.

Install with `installer/install-screen.sh --boot0 NAME`. It makes `vendor/boot0-fel.bin` from the
screen's boot0 over ADB, boots the installer through boot0, and on the eMMC:

- keeps booting from the eMMC boot partition (`PARTITION_CONFIG 0x48`, vendor boot0 untouched),
- writes `u-boot-nodram` at 8 KiB and `boot0-payload.bin` at sector 38192.

Boot chain: vendor boot0 (DRAM) → boot0-payload → SPL without DRAM init → U-Boot from eMMC →
Debian. Kernel and U-Boot updates on such a screen must keep `u-boot-nodram` at 8 KiB.

## Rescue without Android

`installer/make-sd.sh boot0 /dev/sdX` writes `vendor/boot0-fel.bin` to a card. The boot ROM
starts it before the eMMC: the screen ends in FEL with working DRAM. Then:

```bash
DRAM_READY=1 installer/fel-boot-boot0.sh
```

boots the installer (do not run boot0 a second time in the same FEL session: it hangs). Remove
the card before the next normal boot.

## FEL notes

- After boot0 jumps to FEL the USB link comes up at full speed: loading the kernel takes ~2 min.
- `sunxi-fel spl` must get `spl/sunxi-spl.bin`, not `u-boot-sunxi-with-spl.bin`.
- Do not write to SRAM `0x1800–0x2000` or `0x5C00–0x8000` over FEL: the boot ROM keeps its
  stacks there and FEL dies (it looks like a USB problem, but is not).
- A screen hung in FEL can take a PC's xHCI controller down with it; rebind it with
  `echo <pci-id> | sudo tee /sys/bus/pci/drivers/xhci_hcd/{unbind,bind}`.

## Limits

- The workaround boots the installer over USB (FEL). A screen with both this DRAM problem **and**
  a dead USB port is not covered: the SD-card installer uses the mainline SPL. It would need an
  SD card that chains boot0-fel → no-DRAM SPL → U-Boot from the card; not implemented.
- `make-boot0-fel.py` checks the exact instruction it patches and refuses other boot0 versions.
  boot0 was byte-identical on all six screens of the tested installation, so a copy from any
  screen of the same model works (e.g. from a backup in `work/backup/*/mmcblk1boot0.img`).
