#!/usr/bin/env python3
# Runs a command in the installer shell over the network (SD card boot: nc -ll -p 2323 -e /bin/sh).
# Counterpart of sercmd.py for the USB console. Usage: NETCMD=IP[:port] T=seconds netcmd.py command...
import os, socket, sys, time

host, _, port = os.environ.get("NETCMD", "192.168.0.199").partition(":")
timeout = float(os.environ.get("T", "30"))
cmd = " ".join(sys.argv[1:])
tag = "__END_%d__" % int(time.time() * 1000)
s = socket.create_connection((host, int(port or 2323)), timeout=10)
s.settimeout(1)
s.sendall(("%s 2>&1; echo %s\n" % (cmd, tag)).encode())
buf, end = b"", time.time() + timeout
while time.time() < end:
    try:
        d = s.recv(65536)
    except socket.timeout:
        continue
    if not d:
        break
    buf += d
    if tag.encode() in buf:
        break
s.close()
sys.stdout.write(buf.decode(errors="replace").split(tag)[0])
