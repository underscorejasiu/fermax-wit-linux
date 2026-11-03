#!/usr/bin/env python3
# Sends a command to the monitor's shell over /dev/ttyACM0 and prints the result.
import os, sys, termios, time, select

dev = os.environ.get("DEV", "/dev/ttyACM0")
cmd = " ".join(sys.argv[1:])
timeout = float(os.environ.get("T", "10"))
fd = os.open(dev, os.O_RDWR | os.O_NOCTTY)
attrs = termios.tcgetattr(fd)
attrs[0] = 0; attrs[1] = 0; attrs[3] = 0  # raw: iflag, oflag, lflag
attrs[2] |= termios.CLOCAL | termios.CREAD
termios.tcsetattr(fd, termios.TCSANOW, attrs)
time.sleep(0.2)
termios.tcflush(fd, termios.TCIOFLUSH)
tag = "%d" % int(time.time())
# The echo is assembled by the shell, so the marker does not appear literally in the command echo.
os.write(fd, ("%s; echo __BE\"GIN\"_%s; echo __EN\"D\"_%s\n" % ("true", tag, tag)).encode())
os.write(fd, ("%s; echo __EN\"D\"_%s\n" % (cmd, tag)).encode())
buf = b""
end = time.time() + timeout
done = ("__END_%s" % tag).encode()
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.3)
    if r:
        buf += os.read(fd, 65536)
        if buf.count(done) >= 2:
            break
out = buf.decode(errors="replace").replace("\r", "")
parts = out.split("__END_%s" % tag)
body = parts[1] if len(parts) > 2 else out
lines = body.split("\n")[2:]  # skip the command echo
print("\n".join(l for l in lines if not l.startswith("~ #")).strip())
