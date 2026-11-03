#!/usr/bin/env python3
# Turns the vendor boot0 (a copy of the screen's mmcblk1boot0) into a FEL program: it initializes DRAM the
# vendor way and returns to FEL mode in the BROM instead of loading u-boot from eMMC.
# Needed on screens where DRAM training in the mainline SPL fails (.103).
# When loading u-boot fails, boot0 jumps to FEL on its own ("Jump to Fel."), so it is enough to
# replace the load call with "failed".
# Usage: installer/make-boot0-fel.py mmcblk1boot0.img boot0-fel.bin
import struct
import sys

LOAD_UBOOT_CALL = 0x3004          # bl 0x338 (load u-boot from eMMC) in boot0 v3.1.0 DNAKE v902
BL_LOAD_UBOOT = 0xebfff4cb
MOV_R0_1 = 0xe3a00001
EGON_STAMP = 0x5F0A6C39

src, dst = sys.argv[1], sys.argv[2]
d = bytearray(open(src, 'rb').read()[:0x8000])
assert d[4:12] == b'eGON.BT0', 'not a boot0'
length = struct.unpack_from('<I', d, 0x10)[0]
assert length == 0x8000, 'unknown boot0 size: %#x' % length
assert struct.unpack_from('<I', d, LOAD_UBOOT_CALL)[0] == BL_LOAD_UBOOT, 'different boot0 version'
struct.pack_into('<I', d, LOAD_UBOOT_CALL, MOV_R0_1)
struct.pack_into('<I', d, 0xc, EGON_STAMP)
struct.pack_into('<I', d, 0xc, sum(struct.unpack_from('<%dI' % (length // 4), d, 0)) & 0xffffffff)
open(dst, 'wb').write(d)
print('written', dst)
