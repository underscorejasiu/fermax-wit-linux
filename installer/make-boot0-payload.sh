#!/bin/bash
# A payload for the vendor boot0 in place of its u-boot (eMMC, sector 38192): "uboot" header with a
# checksum, boot0-stub.S at 0x400 and the SPL from u-boot-nodram/ at 0x1000. For screens where the
# mainline SPL does not train DRAM (.103): boot0 sets up DRAM, the rest is as on other screens.
# Output: work/out/boot0-payload.bin
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
W="${WORK:-$B/work}"
SPL="$W/u-boot-nodram/spl/sunxi-spl.bin"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
arm-linux-gnueabihf-gcc -nostdlib -march=armv7-a -mfpu=vfpv3-d16 -Wl,-Ttext=0x4a000400 -o "$T/stub.elf" "$B/installer/boot0-stub.S"
arm-linux-gnueabihf-objcopy -O binary -j .text "$T/stub.elf" "$T/stub.bin"
mkdir -p "$W/out"
python3 - "$T/stub.bin" "$SPL" "$W/out/boot0-payload.bin" <<'EOF'
import struct, sys
stub = open(sys.argv[1], 'rb').read()
spl = open(sys.argv[2], 'rb').read()
assert spl[4:12] == b'eGON.BT0' and len(stub) <= 0xc00
size = (0x1000 + len(spl) + 511) // 512 * 512
d = bytearray(size)
struct.pack_into('<I', d, 0, 0xea000000 | ((0x400 - 8) // 4))   # b 0x400
d[4:12] = b'uboot\0\0\0'
struct.pack_into('<I', d, 0x10, 0x4000)                          # align_size
struct.pack_into('<I', d, 0x14, size)                            # length (multiple of 512)
d[0x400:0x400 + len(stub)] = stub
d[0x1000:0x1000 + len(spl)] = spl
struct.pack_into('<I', d, 0xc, 0x5F0A6C39)
struct.pack_into('<I', d, 0xc, sum(struct.unpack_from('<%dI' % (size // 4), d, 0)) & 0xffffffff)
open(sys.argv[3], 'wb').write(d)
print('boot0-payload.bin: %d B' % size)
EOF
