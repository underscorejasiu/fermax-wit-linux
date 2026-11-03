#!/usr/bin/env python3
# One-shot heartbeat test towards the main screen: hbtest.py dcode [dcode...]
# Sends one MESSAGE /slave/heartbeat from an ephemeral port per dcode and prints the reply.
import os, random, socket, sys

MASTER = (os.environ.get("MASTER_IP", "192.168.1.100"), 5060)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
if os.environ.get("SRC"):
    s.bind((os.environ["SRC"], 0))
s.connect(MASTER)
ip, port = s.getsockname()
s.settimeout(2)
for dcode in sys.argv[1:]:
    body = ("<params>\n\t<app>slave</app>\n\t<event>heartbeat</event>\n\t<event_url>/slave/heartbeat</event_url>\n"
            "\t<dcode>%s</dcode>\n\t<sync>123456</sync>\n</params>\n" % dcode)
    msg = ("MESSAGE sip:1000001@%s:5060 SIP/2.0\r\n"
           "Via: SIP/2.0/UDP %s:%d;rport;branch=z9hG4bK%d\r\n"
           "From: <sip:1000001@%s:%d>;tag=%d\r\n"
           "To: <sip:1000001@%s:5060>\r\n"
           "Call-ID: %d\r\nCSeq: 20 MESSAGE\r\nContent-Type: text/plain\r\nMax-Forwards: 70\r\n"
           "User-Agent: DnakeVoip v1.0\r\nContent-Length:   %d\r\n\r\n%s"
           % (MASTER[0], ip, port, random.getrandbits(30), ip, port, random.getrandbits(30), MASTER[0],
              random.getrandbits(30), len(body), body))
    s.send(msg.encode())
    try:
        r = s.recv(65535).decode(errors="replace")
        print("dcode", dcode, "->", r.split("\r\n")[0], "|", " ".join(l.strip() for l in r.split("\r\n\r\n", 1)[1].split("\n") if "<url" in l or "resultCode" in l))
    except socket.timeout:
        print("dcode", dcode, "-> no reply")
