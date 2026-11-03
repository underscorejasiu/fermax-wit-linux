#!/usr/bin/env python3
# PCMU audio statistics from a pcap: RMS and peak level (dBFS), clipping, noise floor
# (quietest 10% of 20 ms frames), inter-packet gaps. Also writes a WAV for each direction.
# Usage: rtpstats.py file.pcap [wav_dir]
import math, os, socket, struct, sys, wave


def ulaw(b):
    b = ~b & 0xff
    sign, exp, mant = b & 0x80, (b >> 4) & 7, b & 15
    v = ((mant << 3) + 0x84) << exp
    v -= 0x84
    return -v if sign else v


TABLE = [ulaw(i) for i in range(256)]


def packets(path):
    f = open(path, "rb")
    hdr = f.read(24)
    linktype = struct.unpack("<I", hdr[20:24])[0]
    while True:
        h = f.read(16)
        if len(h) < 16:
            return
        sec, usec, incl, _ = struct.unpack("<IIII", h)
        fr = f.read(incl)
        ip = fr[16:] if linktype == 113 else fr[14:]   # 113 = Linux cooked (tcpdump -i any)
        if len(ip) < 28 or ip[9] != 17:
            continue
        ihl = (ip[0] & 15) * 4
        sp, dp = struct.unpack("!HH", ip[ihl:ihl + 4])
        yield sec + usec / 1e6, socket.inet_ntoa(ip[12:16]), sp, dp, ip[ihl + 8:]


flows = {}
for ts, src, sp, dp, data in packets(sys.argv[1]):
    if len(data) > 12 and data[0] >> 6 == 2 and data[1] & 0x7f == 0:
        flows.setdefault("%s:%d->%d" % (src, sp, dp), []).append((ts, data[12:]))

out = sys.argv[2] if len(sys.argv) > 2 else None
for name, pkts in flows.items():
    samples = [TABLE[b] for _, p in pkts for b in p]
    frames = [samples[i:i + 160] for i in range(0, len(samples) - 159, 160)]
    rms = sorted(math.sqrt(sum(s * s for s in fr) / 160) for fr in frames)
    db = lambda x: 20 * math.log10(max(x, 1) / 32768)
    total = math.sqrt(sum(s * s for s in samples) / len(samples))
    clip = sum(1 for s in samples if abs(s) >= 32000)
    gaps = [b[0] - a[0] for a, b in zip(pkts, pkts[1:])]
    print("%-28s %4d packets %.1fs | RMS %5.1f dBFS, peak %5.1f dBFS, clipped %.2f%%, noise %5.1f dBFS,"
          " loud frames %5.1f dBFS | max gap %3.0f ms"
          % (name, len(pkts), pkts[-1][0] - pkts[0][0], db(total), db(max(abs(s) for s in samples)),
             100.0 * clip / len(samples), db(rms[len(rms) // 10]), db(rms[len(rms) * 9 // 10]), 1000 * max(gaps)))
    if out:
        os.makedirs(out, exist_ok=True)
        w = wave.open(os.path.join(out, name.replace(":", "_").replace(">", "") + ".wav"), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<%dh" % len(samples), *samples))
        w.close()
