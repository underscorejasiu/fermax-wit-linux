#!/usr/bin/env python3
# Prototype camera viewer for the Fermax MEET panel (protocol in captures/PROTOKOL.md).
# Sends INVITE to the panel, receives H.264 video (cedrus hardware decoder) and PCMU audio
# for the given time, saves the last 3 frames as JPEG (number = frame count) and the audio as WAV,
# then ends the call with BYE.
# Usage: sipmon.py [seconds] [output_dir]
import os, random, socket, subprocess, sys, time

PANEL = (os.environ.get("PANEL_IP", "192.168.1.110"), 5060)
PANEL_URI = "sip:10001000001@%s:5060" % PANEL[0]
USER = "1000001"
AUDIO_PORT, VIDEO_PORT = 6100, 6200
duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10
out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/sipmon"
os.makedirs(out, exist_ok=True)


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(PANEL)
    ip = s.getsockname()[0]
    s.close()
    return ip


IP = local_ip()
ME = "sip:%s@%s:5060" % (USER, IP)
call_id = str(random.randint(10**8, 10**9))
tag = str(random.randint(10**8, 10**9))
sdp = "\r\n".join([
    "v=0",
    "o=dnake %d %d IN IP4 %s" % (int(time.time()), int(time.time()), IP),
    "s=dnake",
    "c=IN IP4 %s" % IP,
    "t=0 0",
    "m=audio %d RTP/AVP 0 101" % AUDIO_PORT,
    "a=rtpmap:0 PCMU/8000/1",
    "a=rtpmap:101 telephone-event/8000/1",
    "a=fmtp:101 0-11",
    "a=sendrecv",
    "m=video %d RTP/AVP 102" % VIDEO_PORT,
    "a=rtpmap:102 H264/90000",
    "a=fmtp:102 profile-level-id=42001F; packetization-mode=1",
    "a=sendrecv",
    ""])


def request(method, cseq, to_tag=None, body="", ctype=None):
    to = "<%s>" % PANEL_URI + (";tag=%s" % to_tag if to_tag else "")
    lines = [
        "%s %s SIP/2.0" % (method, PANEL_URI),
        "Via: SIP/2.0/UDP %s:5060;rport;branch=z9hG4bK%d" % (IP, random.randint(10**8, 10**9)),
        'From: "M-1-0-001-" <%s>;tag=%s' % (ME, tag),
        "To: %s" % to,
        "Call-ID: %s" % call_id,
        "CSeq: %d %s" % (cseq, method),
        "Contact: <%s>" % ME,
        "Max-Forwards: 70",
        "User-Agent: DnakeVoip v1.0",
    ]
    if ctype:
        lines.append("Content-Type: %s" % ctype)
    lines.append("Content-Length: %d" % len(body))
    return ("\r\n".join(lines) + "\r\n\r\n" + body).encode()


def header(msg, name):
    for line in msg.split("\r\n"):
        if line.lower().startswith(name.lower() + ":"):
            return line.split(":", 1)[1].strip()
    return ""


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 5060))
sock.settimeout(0.5)

# Media starts before INVITE so the first frames (SPS/PPS) are not lost
video = ("udpsrc port=%d caps=application/x-rtp,media=video,encoding-name=H264,payload=102,clock-rate=90000"
         " ! rtpjitterbuffer latency=100 ! rtph264depay ! h264parse ! v4l2slh264dec ! videoconvert"
         " ! jpegenc quality=70 ! multifilesink max-files=3 location=%s/frame%%04d.jpg"
         % (VIDEO_PORT, out))
audio = ("udpsrc port=%d caps=application/x-rtp,media=audio,encoding-name=PCMU,payload=0,clock-rate=8000"
         " ! rtpjitterbuffer latency=60 ! rtppcmudepay ! mulawdec ! wavenc ! filesink location=%s/audio.wav"
         % (AUDIO_PORT, out))
procs = [subprocess.Popen(["gst-launch-1.0", "-q", "-e"] + p.split()) for p in (video, audio)]
time.sleep(1)

sock.sendto(request("INVITE", 20, body=sdp, ctype="application/sdp"), PANEL)
to_tag, end = None, time.time() + 5
while time.time() < end:
    try:
        data, addr = sock.recvfrom(65535)
    except socket.timeout:
        continue
    msg = data.decode(errors="replace")
    print("<-", msg.split("\r\n")[0])
    if msg.startswith("SIP/2.0 200") and "INVITE" in header(msg, "CSeq"):
        to_tag = header(msg, "To").split("tag=")[-1]
        sock.sendto(request("ACK", 20, to_tag), PANEL)
        print("-> ACK; receiving %.0f s" % duration)
        break
    if msg.startswith("SIP/2.0") and int(msg.split()[1]) >= 300:
        break

def reply_ok(msg):
    """200 OK to a panel request (e.g. BYE): Via/From/To/Call-ID/CSeq headers copied over."""
    lines = ["SIP/2.0 200 OK"] + ["%s: %s" % (h, header(msg, h)) for h in ("Via", "From", "To", "Call-ID", "CSeq")]
    sock.sendto(("\r\n".join(lines + ["Content-Length: 0"]) + "\r\n\r\n").encode(), PANEL)


if to_tag:
    # Like the original screen: a few empty RTP packets to the panel's video port (PT 102, payload 0xff)
    punch = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    punch.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ssrc = random.getrandbits(32)
    for seq in range(3):
        punch.sendto(bytes([0x80, 0xe6, 0, seq, 0, 0, 0, 0]) + ssrc.to_bytes(4, "big") + b"\xff" * 12,
                     (PANEL[0], VIDEO_PORT))
    t0, hung_up = time.time(), False
    while time.time() - t0 < duration:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        msg = data.decode(errors="replace")
        print("<- +%.1fs" % (time.time() - t0), msg.split("\r\n")[0])
        # The panel retries BYE for old, unclosed calls; we acknowledge each one,
        # but only end our own
        if msg.startswith("BYE"):
            reply_ok(msg)
            if header(msg, "Call-ID") == call_id:
                hung_up = True
                break
    if not hung_up:
        sock.sendto(request("BYE", 21, to_tag), PANEL)
        print("-> BYE after %.1f s" % (time.time() - t0))
        try:
            print("<-", sock.recvfrom(65535)[0].decode(errors="replace").split("\r\n")[0])
        except socket.timeout:
            print("no reply to BYE")
else:
    print("panel did not answer")

for p in procs:
    p.send_signal(2)  # SIGINT + -e: finalize files (WAV header)
for p in procs:
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        p.kill()
print("saved:", sorted(os.listdir(out)))
