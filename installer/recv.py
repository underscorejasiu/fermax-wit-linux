#!/usr/bin/env python3
# Receives a single TCP stream into a file (eMMC copy from the installer: dd | nc). Exits when the sender
# closes the connection; prints the byte count and SHA-256. Usage: recv.py port file [timeout_s]
import hashlib, socket, sys

port, path = int(sys.argv[1]), sys.argv[2]
timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 1800
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", port))
srv.listen(1)
srv.settimeout(timeout)
conn, addr = srv.accept()
conn.settimeout(60)            # no data for a minute = broken connection
h, n = hashlib.sha256(), 0
with open(path, "wb") as f:
    while True:
        b = conn.recv(1 << 20)
        if not b:
            break
        f.write(b)
        h.update(b)
        n += len(b)
print(n, h.hexdigest())
