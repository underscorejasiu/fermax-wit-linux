#!/usr/bin/env python3
# Prints SIP and XML (port 8400) messages from a pcap file, skipping screen heartbeats and attempts
# to reach the nonexistent server 10.0.0.200. Usage: sipdump.py file.pcap [-v]
import socket, struct, sys, time

SKIP = ("/slave/heartbeat", "/msg/hearbeat", "<active>discover</active>", "10.0.0.200")


def packets(path):
    f = open(path, "rb")
    magic = f.read(24)[:4]
    endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    while True:
        h = f.read(16)
        if len(h) < 16:
            return
        sec, usec, incl, _ = struct.unpack(endian + "IIII", h)
        yield sec + usec / 1e6, f.read(incl)


def udp(frame):
    if len(frame) < 14 or frame[12:14] != b"\x08\x00":
        return None
    ip = frame[14:]
    ihl = (ip[0] & 15) * 4
    if ip[9] != 17:
        return None
    sp, dp = struct.unpack("!HH", ip[ihl:ihl + 4])
    return socket.inet_ntoa(ip[12:16]), sp, socket.inet_ntoa(ip[16:20]), dp, ip[ihl + 8:]


verbose = "-v" in sys.argv
pending = {}  # heartbeat transactions to skip (Call-ID)
for ts, frame in packets(sys.argv[1]):
    u = udp(frame)
    if not u or not ({u[1], u[3]} & {5060, 8400, 8420}):
        continue
    src, sp, dst, dp, data = u
    text = data.decode(errors="replace")
    callid = next((l for l in text.splitlines() if l.lower().startswith("call-id")), "")
    if any(s in text for s in SKIP) or dst.startswith("192.255") or dst == "238.9.9.1":
        pending[callid] = True
        continue
    if callid and callid in pending:
        continue
    first = text.splitlines()[0] if text else ""
    stamp = time.strftime("%H:%M:%S", time.localtime(ts)) + ".%03d" % (ts % 1 * 1000)
    print("=== %s  %s:%d -> %s:%d  %s" % (stamp, src, sp, dst, dp, first))
    if verbose:
        print(text.strip())
        print()
