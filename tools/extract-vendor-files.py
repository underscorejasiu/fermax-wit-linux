#!/usr/bin/env python3
"""Extract the vendor files the screens need from a backup of the original Android eMMC.

These files belong to Fermax/DNAKE and are not part of this repository; every user takes them
from their own screen (installer/install-screen.sh saves the backup to work/backup/<name>/):

  silead/gsl3680-fermax-meetme.fw  touchscreen firmware: the GSL3680B_FW_s3 table of the
                                   Android touch driver /vendor/modules/gslX680.ko (system, p7)
  ring4.wav                        ring tone of the original screen (/dnake partition, p13)

Usage: tools/extract-vendor-files.py work/backup/meetme-101/mmcblk1.img [vendor/]
Needs: sfdisk, debugfs (e2fsprogs).
"""
import json
import os
import struct
import subprocess
import sys
import tempfile

SYSTEM_PART, DNAKE_PART = 7, 13          # Android cmdline: system@mmcblk0p7, dnake@mmcblk0p13
TOUCH_SYMBOL = 'GSL3680B_FW_s3'


def partitions(img):
    out = subprocess.run(['sfdisk', '-J', img], check=True, capture_output=True, text=True).stdout
    parts = {}
    for p in json.loads(out)['partitiontable']['partitions']:
        num = int(p['node'][len(img):])
        parts[num] = p['start'] * 512
    return parts


def dump(img, offset, path, dest):
    subprocess.run(['debugfs', '-R', f'dump {path} {dest}', f'{img}?offset={offset}'],
                   check=True, capture_output=True)
    if not os.path.getsize(dest):
        sys.exit(f'{path} not found in the partition at offset {offset}')


def elf_symbol(data, name):
    """Bytes of a symbol from a 32-bit little-endian ELF relocatable (the kernel module)."""
    assert data[:4] == b'\x7fELF' and data[4] == 1 and data[5] == 1, 'not an ELF32 LE file'
    shoff, = struct.unpack_from('<I', data, 0x20)
    shentsize, shnum = struct.unpack_from('<HH', data, 0x2e)
    sections = [struct.unpack_from('<IIIIIIIIII', data, shoff + i * shentsize) for i in range(shnum)]
    for sh in sections:
        if sh[1] != 2:                            # SHT_SYMTAB
            continue
        strtab = sections[sh[6]]
        for off in range(sh[4], sh[4] + sh[5], 16):
            st_name, st_value, st_size, _, _, st_shndx = struct.unpack_from('<IIIBBH', data, off)
            s = data[strtab[4] + st_name:data.index(b'\0', strtab[4] + st_name)].decode()
            if s == name:
                start = sections[st_shndx][4] + st_value
                return data[start:start + st_size]
    sys.exit(f'symbol {name} not found')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    img = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), '..', 'vendor')
    parts = partitions(img)
    os.makedirs(os.path.join(out, 'silead'), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        ko = os.path.join(tmp, 'gslX680.ko')
        dump(img, parts[SYSTEM_PART], '/vendor/modules/gslX680.ko', ko)
        fw = elf_symbol(open(ko, 'rb').read(), TOUCH_SYMBOL)
    # The table is a list of (register, value) u32 pairs: exactly what the mainline silead driver loads
    assert len(fw) % 8 == 0, 'unexpected firmware table size'
    open(os.path.join(out, 'silead', 'gsl3680-fermax-meetme.fw'), 'wb').write(fw)
    dump(img, parts[DNAKE_PART], '/ringtone/ring4.wav', os.path.join(out, 'ring4.wav'))
    print(f'{out}: silead/gsl3680-fermax-meetme.fw ({len(fw)} B), ring4.wav')


if __name__ == '__main__':
    main()
