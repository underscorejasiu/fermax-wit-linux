#!/usr/bin/env python3
# Sends a file to the monitor over the /dev/ttyACM0 console (gzip + base64 + heredoc).
import base64, gzip, os, sys, termios, time

src, dst = sys.argv[1], sys.argv[2]
dev = os.environ.get("DEV", "/dev/ttyACM0")
data = base64.encodebytes(gzip.compress(open(src, "rb").read(), 9)).decode()
fd = os.open(dev, os.O_RDWR | os.O_NOCTTY)
attrs = termios.tcgetattr(fd)
attrs[0] = 0; attrs[1] = 0; attrs[3] = 0
termios.tcsetattr(fd, termios.TCSANOW, attrs)
os.write(fd, ("stty -echo; base64 -d << 'B64EOF' | zcat > %s\n" % dst).encode())
for i in range(0, len(data), 4096):
    os.write(fd, data[i:i + 4096].encode())
    time.sleep(0.01)
os.write(fd, ("B64EOF\nchmod +x %s; stty echo\n" % dst).encode())
time.sleep(1)
termios.tcflush(fd, termios.TCIFLUSH)
print("sent", src, "->", dst, len(data), "b64 bytes")
