#!/usr/bin/env python3
# Runs a command in the Debian shell on the monitor over /dev/ttyACM0 and prints the result.
# The output goes through a temp file and base64 so terminal echo and bash escape codes do not mix with the data.
import base64, os, re, select, sys, termios, time

dev = os.environ.get("DEV", "/dev/ttyACM0")
timeout = float(os.environ.get("T", "20"))
cmd = " ".join(sys.argv[1:])
tag = "%d" % int(time.time() * 1000)
fd = os.open(dev, os.O_RDWR | os.O_NOCTTY)
a = termios.tcgetattr(fd)
a[0] = 0; a[1] = 0; a[3] = 0
termios.tcsetattr(fd, termios.TCSANOW, a)
termios.tcflush(fd, termios.TCIOFLUSH)
enc = base64.b64encode(cmd.encode()).decode()
line = ("bind 'set enable-bracketed-paste off' 2>/dev/null; stty -echo; "
        "{ echo %s | base64 -d | bash; } > /tmp/.o 2>&1; "
        "echo ==B%s==; base64 -w0 /tmp/.o; echo; echo ==E%s==\n") % (enc, tag, tag)
os.write(fd, line.encode())
buf = b""
end = time.time() + timeout
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.3)
    if r:
        buf += os.read(fd, 65536)
        if ("==E%s==" % tag).encode() in buf.split(("==B%s==" % tag).encode(), 1)[-1]:
            break
txt = buf.decode(errors="replace")
m = re.search(r"==B%s==\s*([A-Za-z0-9+/=]*)\s*==E%s==" % (tag, tag), txt)
if m:
    sys.stdout.write(base64.b64decode(m.group(1)).decode(errors="replace"))
else:
    sys.stdout.write("[no reply]\n" + txt[-500:])
