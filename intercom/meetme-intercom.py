#!/usr/bin/env python3
"""
Fermax MEET intercom on Debian: replaces the DNAKE app from the original Android.

- answers the panel's discover with the list of the apartment's screens (SCREENS) so the panel rings
  all screens; this replaces the original main screen,
- call from the panel: ringing, video already while ringing, answering, a call with echo cancellation,
- camera view of the panel on demand (GET http://127.0.0.1:8098/monitor),
- opening the gate (SIP MESSAGE /talk/unlock).

The GTK window exists only for the duration of a call; cage shows it over the kiosk, and when it closes
the browser is back. Protocol: captures/PROTOKOL.md. Configuration: /etc/default/meetme-intercom.
"""
import json, os, random, socket, sys, threading, time, urllib.request

import gi
gi.require_version("Gst", "1.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gst, Gtk, Gdk

E = os.environ.get
PANEL_IP = E("PANEL_IP", "192.168.1.110")
# The apartment's screens (IPs) that we answer the panel with on a ring, plus extra SIP addresses
# (the Fermax cloud app account; the panel itself registers with the cloud). The same list on every
# screen. Empty: the list is fetched from the original main screen MASTER_IP with this screen added.
SCREENS = E("SCREENS", "").split()
EXTRA_URLS = E("EXTRA_URLS", "").split()
MASTER_IP = E("MASTER_IP", "192.168.1.100")
DCODE = E("DCODE", "5")
SYNC = E("SYNC", "123456")
ROOM = E("ROOM", "1000001")             # SIP user of all the apartment's screens
PANEL_USER = E("PANEL_USER", "10001000001")
BUILD, UNIT, FLOOR, FAMILY = E("BUILD", "1"), E("UNIT", "0"), E("FLOOR", "0"), E("FAMILY", "1")
# Second camera in the call window (RTSP, H.264 up to ~720p); empty = panel video only
CAMERA_URL = E("CAMERA_URL", "")
CAMERA_LATENCY = int(E("CAMERA_LATENCY", "100"))
# Panel video in the window from RTSP (e.g. a go2rtc relay of the panel stream); empty = video from SIP
PANEL_VIDEO_URL = E("PANEL_VIDEO_URL", "")
RING = E("RING", "/usr/local/share/meetme/ring4.wav")
RING_VOLUME = float(E("RING_VOLUME", "0.5"))     # 1.0 = volume of the original file
WAKE_URL = E("WAKE_URL", "http://127.0.0.1:8099/wake")
# HA webhook for intercom events (http://HA:8123/api/webhook/<id>); empty = no events
HA_WEBHOOK = E("HA_WEBHOOK", "")
HTTP_PORT = int(E("HTTP_PORT", "8098"))
# The main screen (newer firmware than in the copy from .105) answers our heartbeat with 480, so it is
# off by default; ringing works through the answer to the panel's discover
HEARTBEAT = E("HEARTBEAT", "0") == "1"
DISCOVER_GROUP, DISCOVER_PORT = "238.9.9.1", 8400
SIP_PORT, AUDIO_PORT, VIDEO_PORT = 5060, 6100, 6200
RING_TIMEOUT, TALK_TIMEOUT, MONITOR_TIMEOUT = 45, 180, 60

# A33 codec (sun8i-codec): mono playback hangs stream shutdown (alsasink does not return
# from set_state(NULL), the whole application stalls). Stereo works, so the speaker always gets 2 channels.
SPEAKER = "audio/x-raw,rate=48000,channels=2 ! alsasink"
# Capture and playback share one clock in the codec: the microphone must run at the same
# rate as the speaker, otherwise alsasink cannot set its parameters
MIC = "audio/x-raw,rate=48000,channels=2"
# Latency: jitter buffers (ms) and the ALSA buffer (µs), both directions
VIDEO_LATENCY = int(E("VIDEO_LATENCY", "60"))
AUDIO_LATENCY = int(E("AUDIO_LATENCY", "40"))
ALSA_BUFFER = "buffer-time=40000 latency-time=10000"
# Microphone processing. With AGC and the default AEC the call fell into ~2.2 kHz feedback (loop
# speaker -> microphone -> panel -> speaker): AEC in delay-agnostic mode, no AGC.
DSP = E("DSP", "echo-cancel=true delay-agnostic=true extended-filter=true high-pass-filter=true"
               " noise-suppression=true gain-control=false")
PANEL = (PANEL_IP, SIP_PORT)
PANEL_URI = "sip:%s@%s:%d" % (PANEL_USER, PANEL_IP, SIP_PORT)
UA = "DnakeVoip v1.0"


def log(*a):
    print(*a, flush=True)


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(PANEL)
    ip = s.getsockname()[0]
    s.close()
    return ip


IP = local_ip()
ME = "sip:%s@%s:%d" % (ROOM, IP, SIP_PORT)
ME_HDR = '"M-%s-%s-%03d-" <%s>' % (BUILD, UNIT, int(FAMILY), ME)


def rnd():
    return str(random.randint(10**8, 2 * 10**9))


def parse(data):
    text = data.decode(errors="replace")
    head, _, body = text.partition("\r\n\r\n")
    lines = head.split("\r\n")
    hdr = {}
    for line in lines[1:]:
        k, _, v = line.partition(":")
        hdr.setdefault(k.strip().lower(), v.strip())
    return lines[0], hdr, body


def build(first, headers, body="", ctype=None):
    lines = [first] + ["%s: %s" % kv for kv in headers]
    lines.append("User-Agent: " + UA)
    if ctype:
        lines.append("Content-Type: " + ctype)
    lines.append("Content-Length: %d" % len(body.encode()))
    return ("\r\n".join(lines) + "\r\n\r\n" + body).encode()


def sdp(audio_payloads="0 101"):
    t = int(time.time())
    return "\r\n".join([
        "v=0", "o=dnake %d %d IN IP4 %s" % (t, t, IP), "s=dnake", "c=IN IP4 %s" % IP, "t=0 0",
        "m=audio %d RTP/AVP %s" % (AUDIO_PORT, audio_payloads),
        "a=rtpmap:0 PCMU/8000/1", "a=rtpmap:101 telephone-event/8000/1", "a=fmtp:101 0-11", "a=sendrecv",
        "m=video %d RTP/AVP 102" % VIDEO_PORT,
        "a=rtpmap:102 H264/90000", "a=fmtp:102 profile-level-id=42001F; packetization-mode=1", "a=sendrecv",
        ""])


def remote_audio(body):
    """(ip, port) of the panel's audio from its SDP; default as in the captures: panel:6000."""
    ip, port = PANEL_IP, 6000
    for line in body.split("\r\n"):
        if line.startswith("c=IN IP4 "):
            ip = line.split()[-1]
        elif line.startswith("m=audio "):
            port = int(line.split()[1])
    return ip, port


def ha_event(event, **data):
    """
    A meetme_intercom event in Home Assistant (e.g. for a notification automation), through the webhook
    of an HA automation that fires the event (docs/home-assistant.md); the kiosk token is not an
    administrator, so /api/events is out. In a separate thread: HA must not block the intercom.
    """
    if not HA_WEBHOOK:
        return
    data.update(type=event, screen=IP)
    req = urllib.request.Request(HA_WEBHOOK, json.dumps(data).encode(), {"Content-Type": "application/json"})

    def send():
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except OSError as e:
            log("event meetme_%s did not reach HA: %s" % (event, e))
    threading.Thread(target=send, daemon=True).start()


def wake_screen():
    try:
        urllib.request.urlopen(WAKE_URL, timeout=0.5).read()
    except OSError as e:
        log("wake:", e)


def watch(pipeline, name):
    """Pipeline errors and warnings to the log."""
    def on_msg(_bus, msg):
        err, dbg = msg.parse_error() if msg.type == Gst.MessageType.ERROR else msg.parse_warning()
        log("%s: %s %s (%s)" % (name, "ERROR" if msg.type == Gst.MessageType.ERROR else "warning",
                                err.message, (dbg or "").split("\n")[0][:160]))
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message::error", on_msg)
    bus.connect("message::warning", on_msg)


def first_packet(element, text):
    """One-time log entry when data passes through the element (its sink/src pad)."""
    pad = element.get_static_pad("sink") or element.get_static_pad("src")

    def probe(_pad, _info):
        log(text)
        return Gst.PadProbeReturn.REMOVE
    pad.add_probe(Gst.PadProbeType.BUFFER, probe)


class Media:
    """H.264 video (cedrus) to a GTK widget, PCMU audio both ways with echo cancellation."""

    def __init__(self):
        self.video = self.audio = self.camera = None
        self.socks = []
        self.vsock = None

    def _udp(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        self.socks.append(s)
        return s, Gio.Socket.new_from_fd(os.dup(s.fileno()))

    def open_video_port(self, count=16):
        """
        Like the original screen: a burst of empty RTP packets (PT 102, payload 0xff) to the panel's video port,
        then one every ~3 s (punch()). Without this the panel does not send video before the call is answered.
        """
        if not self.vsock:
            self.vsock = self._udp(VIDEO_PORT)
            self.vssrc = random.getrandbits(32).to_bytes(4, "big")
            self.vseq = 0
        for _ in range(count):
            self.punch()

    def punch(self):
        if self.vsock:
            self.vsock[0].sendto(bytes([0x80, 0xe6]) + self.vseq.to_bytes(2, "big") + bytes(4) + self.vssrc
                                 + b"\xff" * 12, (PANEL_IP, VIDEO_PORT))
            self.vseq = (self.vseq + 1) & 0xffff
        return True

    def start_video(self):
        """Returns the video widget."""
        if not self.vsock:
            self.open_video_port()
        if PANEL_VIDEO_URL:
            # The panel does not send video over SIP before the call is answered (and it varied in the
            # original system), so the panel video comes from its RTSP via Frigate; port 6200 stays open
            # so that SIP video after answering does not bounce back to the panel as ICMP "port unreachable"
            self.video = self.rtsp(PANEL_VIDEO_URL, "panel video")
            return self.video.get_by_name("sink").get_property("widget")
        gsock = self.vsock[1]
        self.video = Gst.parse_launch(
            "udpsrc name=src close-socket=false"
            " caps=application/x-rtp,media=video,encoding-name=H264,payload=102,clock-rate=90000"
            " ! rtpjitterbuffer latency=%d drop-on-latency=true ! rtph264depay ! h264parse ! v4l2slh264dec"
            " ! videoconvert ! gtkwaylandsink name=sink sync=false" % VIDEO_LATENCY)
        src = self.video.get_by_name("src")
        src.set_property("socket", gsock)
        watch(self.video, "video")
        first_packet(src, "video: first packet from the panel")
        first_packet(self.video.get_by_name("sink"), "video: first frame on screen")
        # Play only in play_video(), once the widget sits in our window: otherwise
        # gtkwaylandsink creates its own window and moves the widget there
        return self.video.get_by_name("sink").get_property("widget")

    def rtsp(self, url, label):
        """Video from RTSP (e.g. go2rtc in Frigate), same hardware decoder; video only."""
        p = Gst.parse_launch(
            "rtspsrc name=r protocols=tcp latency=%d r. ! application/x-rtp,media=video"
            " ! rtph264depay ! h264parse ! v4l2slh264dec ! videoconvert ! gtkwaylandsink name=sink sync=false"
            % CAMERA_LATENCY)
        p.get_by_name("r").set_property("location", url)
        watch(p, label)
        first_packet(p.get_by_name("sink"), label + ": first frame on screen")
        return p

    def start_camera(self):
        """Second camera (entrance). Returns a widget, or None when not configured."""
        if not CAMERA_URL:
            return None
        self.camera = self.rtsp(CAMERA_URL, "entrance camera")
        return self.camera.get_by_name("sink").get_property("widget")

    def play_video(self):
        for p in (self.video, self.camera):
            if p:
                p.set_state(Gst.State.PLAYING)

    def start_audio(self, remote, mic=True):
        _, gsock = self._udp(AUDIO_PORT)
        self.audio = Gst.parse_launch(
            # receive: panel -> speaker; the echo probe sees what the speaker plays
            "udpsrc name=src close-socket=false"
            " caps=application/x-rtp,media=audio,encoding-name=PCMU,payload=0,clock-rate=8000"
            " ! rtpjitterbuffer latency=%d ! rtppcmudepay ! mulawdec ! audioconvert ! audioresample"
            " ! audio/x-raw,rate=16000,channels=1 ! webrtcechoprobe name=probe"
            " ! audioconvert ! audioresample ! %s %s sync=false " % (AUDIO_LATENCY, SPEAKER, ALSA_BUFFER) +
            # transmit: microphone -> echo and noise removal -> (mute) -> panel
            "alsasrc %s ! %s ! audioconvert ! audioresample ! audio/x-raw,rate=16000,channels=1" % (ALSA_BUFFER, MIC) +
            " ! webrtcdsp probe=probe %s" % DSP +
            " ! volume name=mic ! audioconvert ! audioresample ! audio/x-raw,rate=8000,channels=1"
            " ! mulawenc ! rtppcmupay pt=0 min-ptime=20000000 max-ptime=20000000"
            " ! udpsink name=sink sync=false async=false")
        self.audio.get_by_name("src").set_property("socket", gsock)
        watch(self.audio, "audio")
        sink = self.audio.get_by_name("sink")
        sink.set_property("socket", gsock)
        sink.set_property("host", remote[0])
        sink.set_property("port", remote[1])
        self.set_mic(mic)
        self.audio.set_state(Gst.State.PLAYING)

    def set_mic(self, on):
        """Mute instead of interrupting the stream: the panel gets silence, the call continues."""
        if self.audio:
            self.audio.get_by_name("mic").set_property("mute", not on)

    def stop(self):
        for p in (self.video, self.audio, self.camera):
            if p:
                p.set_state(Gst.State.NULL)
        self.video = self.audio = self.camera = self.vsock = None
        for s in self.socks:
            s.close()
        self.socks = []


class Ringer:
    """Ringtone from the original Fermax (ring4.wav), looped."""

    def __init__(self):
        self.p = None

    def start(self):
        if os.path.exists(RING):
            src = "filesrc location=%s ! wavparse" % RING
        else:
            # No ring tone from the original firmware (tools/extract-vendor-files.py): a generated chime
            log("no %s, ringing with a generated tone" % RING)
            src = "audiotestsrc name=tone wave=sine freq=880 ! audio/x-raw,rate=48000,channels=2 ! volume name=gate"
        self.p = Gst.parse_launch("%s ! audioconvert ! volume volume=%s ! audioresample ! %s"
                                  % (src, RING_VOLUME, SPEAKER))
        tone, gate = self.p.get_by_name("tone"), self.p.get_by_name("gate")
        if tone:
            # Every 200 ms: 880 Hz, 660 Hz, then 600 ms of silence
            step = [0]

            def tick():
                if not self.p:
                    return False
                n = step[0] = (step[0] + 1) % 5
                gate.set_property("volume", 0.6 if n < 2 else 0.0)
                tone.set_property("freq", 880 if n == 0 else 660)
                return True
            GLib.timeout_add(200, tick)
        self.p.get_bus().add_signal_watch()
        self.p.get_bus().connect("message::eos", lambda *a: self.p and self.p.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH, 0))
        self.p.set_state(Gst.State.PLAYING)

    def stop(self):
        if self.p:
            self.p.set_state(Gst.State.NULL)
            self.p = None


CSS = b"""
window { background: #000; }
.bar { background: #161616; padding: 12px 16px; }
.status { color: #fff; font: 26px sans-serif; }
.sub { color: #aaa; font: 18px sans-serif; }
button { font: bold 24px sans-serif; color: #fff; border-radius: 14px; min-height: 110px; min-width: 200px;
         background: #333; border: none; box-shadow: none; text-shadow: none; -gtk-icon-shadow: none; }
button.answer { background: #2e7d32; }
button.hangup { background: #c62828; }
button.unlock { background: #1565c0; }
button:active { opacity: 0.7; }
"""


class CallWindow(Gtk.Window):
    """Video from the panel at the top and (optionally) from the entrance camera next to it, status and buttons at the bottom."""

    def __init__(self, video_widgets, app):
        super().__init__(title="Intercom")
        self.app = app
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        videos = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
        for w in video_widgets:
            w.set_hexpand(True)
            w.set_vexpand(True)
            videos.pack_start(w, True, True, 0)
        root.pack_start(videos, True, True, 0)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        bar.get_style_context().add_class("bar")
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("status")
        self.sub = Gtk.Label(xalign=0)
        self.sub.get_style_context().add_class("sub")
        texts.pack_start(self.status, False, False, 0)
        texts.pack_start(self.sub, False, False, 0)
        bar.pack_start(texts, True, True, 0)
        self.buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        bar.pack_end(self.buttons, False, False, 0)
        root.pack_start(bar, False, False, 0)
        self.add(root)
        self.fullscreen()
        self.show_all()

    def set_buttons(self, spec):
        for b in self.buttons.get_children():
            self.buttons.remove(b)
        for label, cls, cb in spec:
            b = Gtk.Button(label=label)
            b.get_style_context().add_class(cls)
            b.connect("clicked", lambda _b, cb=cb: cb())
            self.buttons.pack_start(b, False, False, 0)
        self.buttons.show_all()


class Call:
    """A single call with the panel (incoming or a camera view)."""

    def __init__(self, incoming, call_id, local_hdr, remote_hdr, invite=None):
        self.incoming = incoming
        self.call_id = call_id
        self.local_hdr = local_hdr      # From in our requests
        self.remote_hdr = remote_hdr    # To in our requests
        self.invite = invite            # (first line, headers, body) of the INVITE from the panel
        self.cseq = 20
        self.state = "ringing" if incoming else "calling"
        self.acked = False
        self.started = time.time()
        self.answered_at = None
        self.reason = None             # end reason for the meetme_call_ended event


class App:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", SIP_PORT))
        GLib.io_add_watch(self.sock.fileno(), GLib.IO_IN, self.on_sip)
        self.call = None
        self.win = None
        self.media = Media()
        self.ringer = Ringer()
        self.pending = {}           # Call-IDs of our out-of-dialog requests -> reply handler
        self.members = None
        self.timers = []
        self.http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.http.bind(("127.0.0.1", HTTP_PORT))
        self.http.listen(4)
        GLib.io_add_watch(self.http.fileno(), GLib.IO_IN, self.on_http)
        # On a ring the panel asks via multicast who handles the apartment; we answer ourselves
        self.disc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.disc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.disc.bind(("0.0.0.0", DISCOVER_PORT))
        self.disc.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(DISCOVER_GROUP) + socket.inet_aton(IP))
        GLib.io_add_watch(self.disc.fileno(), GLib.IO_IN, self.on_discover)
        self.master_ack = None
        if SCREENS:
            log("list for the panel from the configuration:", " ".join(self.screen_urls()))
        else:
            self.ask_master()
            GLib.timeout_add_seconds(30, self.ask_master)
        if HEARTBEAT:
            self.heartbeat()
            GLib.timeout_add_seconds(5, self.heartbeat)
        log("intercom ready: %s, panel %s, list %s" % (ME, PANEL_IP, "from SCREENS" if SCREENS else "from " + MASTER_IP))

    def screen_urls(self):
        return ["sip:%s@%s:%d" % (ROOM, ip, SIP_PORT) for ip in SCREENS] + EXTRA_URLS

    def static_ack(self):
        """
        Reply in the main screen's format: <url> is the first screen from SCREENS, <slaveN> the rest and
        EXTRA_URLS (e.g. the Fermax cloud app account). Every Debian screen answers with the same
        list, so it does not matter which one is first, and no main screen is needed.
        """
        urls = self.screen_urls()
        slaves = "".join("\t<slave%d>%s</slave%d>\n" % (i, u, i) for i, u in enumerate(urls[1:]))
        return ("<event>\n\t<active>discover</active>\n\t<type>ack</type>\n\t<fermax>1</fermax>\n"
                "\t<url>%s</url>\n\t<name></name>\n\t<build>%s</build>\n%s</event>\n" % (urls[0], BUILD, slaves))

    def discover_req(self):
        return ("<event>\n\t<active>discover</active>\n\t<type>req</type>\n\t<id>%s</id>\n\t<version>1</version>\n"
                "\t<fermax>1</fermax>\n</event>\n" % ROOM).encode()

    def ask_master(self):
        """The apartment's screen list from the main screen: the same query the panel sends."""
        self.disc.sendto(self.discover_req(), (MASTER_IP, DISCOVER_PORT))
        return True

    def merged_ack(self):
        """
        Reply for the panel. The panel rings only the screens from the first reply it gets,
        and ours arrives before the main screen's. So we send back the main screen's list
        (<url> = it, <slaveN> = the other screens and the Fermax cloud) with this screen appended.
        """
        ack = self.master_ack
        if not ack:
            return ("<event>\n\t<active>discover</active>\n\t<type>ack</type>\n\t<fermax>1</fermax>\n"
                    "\t<url>%s</url>\n\t<name></name>\n\t<build>%s</build>\n</event>\n" % (ME, BUILD))
        if ME in ack:
            return ack
        n = 0
        while "<slave%d>" % n in ack:
            n += 1
        return ack.replace("</event>", "\t<slave%d>%s</slave%d>\n</event>" % (n, ME, n), 1)

    def on_discover(self, *_):
        data, addr = self.disc.recvfrom(4096)
        text = data.decode(errors="replace")
        if addr[0] == MASTER_IP and "<type>ack</type>" in text:
            if text != self.master_ack:
                log("screen list from the main screen:", " ".join(
                    l.split(">")[1].split("<")[0] for l in text.split("\n") if l.strip().startswith(("<url", "<slave"))))
            self.master_ack = text
            return True
        # The panel's query about our apartment
        if addr[0] == PANEL_IP and "<type>req</type>" in text and "<id>%s</id>" % ROOM in text:
            ack = self.static_ack() if SCREENS else self.merged_ack()
            self.disc.sendto(ack.encode(), (addr[0], DISCOVER_PORT))
            log("panel asks about the apartment: answered with the list %s" % ("from the configuration" if SCREENS else "with this screen"))
        return True

    # --- SIP: sending ---

    def send(self, data, addr=PANEL):
        self.sock.sendto(data, addr)

    def via(self):
        return ("Via", "SIP/2.0/UDP %s:%d;rport;branch=z9hG4bK%s" % (IP, SIP_PORT, rnd()))

    def message(self, to_uri, addr, body, on_reply=None):
        """MESSAGE outside a dialog (heartbeat, opening the gate)."""
        cid = rnd()
        if on_reply:
            if len(self.pending) > 50:      # the recipient is not answering: do not collect indefinitely
                self.pending.clear()
            self.pending[cid] = on_reply
        self.send(build("MESSAGE %s SIP/2.0" % to_uri, [
            self.via(), ("From", "<%s>;tag=%s" % (ME, rnd())), ("To", "<%s>" % to_uri),
            ("Call-ID", cid), ("CSeq", "20 MESSAGE"), ("Max-Forwards", "70")], body, "text/plain"), addr)

    def in_dialog(self, method):
        c = self.call
        c.cseq += 1
        self.send(build("%s %s SIP/2.0" % (method, PANEL_URI), [
            self.via(), ("From", c.local_hdr), ("To", c.remote_hdr), ("Call-ID", c.call_id),
            ("CSeq", "%d %s" % (c.cseq, method)), ("Contact", "<%s>" % ME), ("Max-Forwards", "70")]))

    def respond(self, req, code, text, to_tag=None, body="", ctype=None, contact=False):
        _, h, _ = req
        to = h.get("to", "")
        if to_tag and "tag=" not in to:
            to += ";tag=" + to_tag
        headers = [("Via", h.get("via", "")), ("From", h.get("from", "")), ("To", to),
                   ("Call-ID", h.get("call-id", "")), ("CSeq", h.get("cseq", ""))]
        if contact:
            headers.append(("Contact", "<%s>" % ME))
        self.send(build("SIP/2.0 %d %s" % (code, text), headers, body, ctype))

    def heartbeat(self):
        body = ("<params>\n\t<app>slave</app>\n\t<event>heartbeat</event>\n"
                "\t<event_url>/slave/heartbeat</event_url>\n\t<dcode>%s</dcode>\n\t<sync>%s</sync>\n</params>\n"
                % (DCODE, SYNC))
        self.message("sip:%s@%s:%d" % (ROOM, MASTER_IP, SIP_PORT), (MASTER_IP, SIP_PORT), body, self.on_heartbeat)
        return True

    def on_heartbeat(self, first, h, body):
        members = sorted(l.split(">")[1].split("<")[0] for l in body.split("\n") if l.strip().startswith("<url"))
        if members != self.members:
            log("apartment screens according to the main screen:", ", ".join(members) or "(none)",
                "" if any(IP + ":" in m for m in members) else "- THIS SCREEN IS NOT ON THE LIST")
            self.members = members

    def unlock(self):
        body = ("<params>\n\t<app>talk</app>\n\t<event>unlock</event>\n\t<event_url>/talk/unlock</event_url>\n"
                "\t<index>0</index>\n\t<host>%s</host>\n\t<build>%s</build>\n\t<unit>%s</unit>\n"
                "\t<floor>%s</floor>\n\t<family>%s</family>\n</params>\n" % (ROOM, BUILD, UNIT, FLOOR, FAMILY))
        log("opening the gate")
        self.message(PANEL_URI, PANEL, body, self.on_unlock)

    def on_unlock(self, first, h, body):
        ok = first.startswith("SIP/2.0 200") and "<resultCode>200" in body
        log("furtka:", "opened" if ok else "error: " + first)
        ha_event("unlock", ok=ok)
        if self.win:
            self.win.sub.set_text("Gate opened" if ok else "Could not open")

    # --- SIP: receiving ---

    def on_sip(self, *_):
        data, addr = self.sock.recvfrom(65535)
        try:
            msg = parse(data)
        except Exception as e:
            log("bad SIP packet from %s: %s" % (addr, e))
            return True
        first, h, body = msg
        if first.startswith("SIP/2.0"):
            self.on_response(msg)
            return True
        method = first.split()[0]
        cid = h.get("call-id")
        mine = self.call and self.call.call_id == cid
        if method == "INVITE":
            self.on_invite(msg, addr)
        elif method == "ACK":
            if mine:
                self.call.acked = True
                if self.call.state == "rejecting":
                    self.hangup()
        elif method == "CANCEL":
            self.respond(msg, 200, "OK")
            if mine and self.call.state == "ringing":
                self.respond(self.call.invite, 487, "Request Terminated", self.call.local_hdr.split("tag=")[-1])
                log("panel stopped ringing")
                self.end("missed")
        elif method == "BYE":
            # The panel retries BYE for old calls too: we acknowledge each one, end only our own
            self.respond(msg, 200, "OK")
            if mine:
                log("panel hung up")
                self.end("panel")
        else:
            # MESSAGE/OPTIONS/NOTIFY from the main screen or the panel: just acknowledge
            if method == "MESSAGE" and "<event_url>" in body:
                log("MESSAGE from %s: %s" % (addr[0], body.split("<event_url>")[1].split("<")[0]))
            self.respond(msg, 200, "OK")
        return True

    def on_response(self, msg):
        first, h, body = msg
        cid = h.get("call-id")
        method = h.get("cseq", " ").split()[-1]
        code = int(first.split()[1])
        if cid in self.pending:
            if code >= 200:
                self.pending.pop(cid)(first, h, body)
            return
        c = self.call
        if not c or c.call_id != cid:
            return
        if method == "INVITE" and code == 200:
            # camera view: the panel answered; ACK also for a repeated 200 OK
            c.remote_hdr = h.get("to", c.remote_hdr)
            self.send(build("ACK %s SIP/2.0" % PANEL_URI, [
                self.via(), ("From", c.local_hdr), ("To", c.remote_hdr), ("Call-ID", c.call_id),
                ("CSeq", "%d ACK" % c.cseq), ("Contact", "<%s>" % ME), ("Max-Forwards", "70")]))
            if c.state == "calling":
                # camera view: the panel is audible, microphone muted until "Talk" is pressed
                c.state = "monitor"
                self.media.start_audio(remote_audio(body), mic=False)
                self.update_ui()
        elif method == "INVITE" and code >= 300:
            log("panel rejected the camera view:", first)
            self.end()

    def on_invite(self, msg, addr):
        first, h, body = msg
        if addr[0] != PANEL_IP:
            self.respond(msg, 403, "Forbidden")
            return
        if self.call:
            if self.call.call_id == h.get("call-id"):
                return              # repeated INVITE, already ringing
            self.respond(msg, 486, "Busy Here")
            return
        tag = rnd()
        self.call = Call(True, h.get("call-id"), h.get("to") + ";tag=" + tag, h.get("from"), msg)
        # Order as on the original screen: 100, 101 with tag, packets to the video port, 180
        self.respond(msg, 100, "Trying")
        self.respond(msg, 101, "Dialog Establishement", tag, contact=True)
        self.media.open_video_port()
        self.respond(msg, 180, "Ringing", tag, contact=True)
        log("doorbell from the panel")
        ha_event("doorbell")
        wake_screen()
        self.ringer.start()
        self.open_window()
        self.after(RING_TIMEOUT, self.ring_timeout)

    # --- user actions ---

    def answer(self):
        c = self.call
        if not c or c.state != "ringing":
            return
        self.ringer.stop()
        c.state = "talk"
        c.started = time.time()
        tag = c.local_hdr.split("tag=")[-1]

        def send_ok(n=[0]):
            if not self.call or self.call is not c or c.acked or n[0] >= 6:
                return False
            n[0] += 1
            self.respond(c.invite, 200, "OK", tag, sdp(), "application/sdp", contact=True)
            return True
        send_ok()
        GLib.timeout_add(500, send_ok)
        self.media.start_audio(remote_audio(c.invite[2]))
        log("answered")
        c.answered_at = time.time()
        ha_event("answered")
        self.cancel_timers()
        self.after(TALK_TIMEOUT, self.hangup)
        self.update_ui()

    def ring_timeout(self):
        if self.call:
            self.call.reason = "timeout"
        self.reject()

    def reject(self):
        """Like the original screen: 200 OK and an immediate BYE (the panel does not know 486/603)."""
        c = self.call
        if not c:
            return
        if c.state == "ringing":
            self.ringer.stop()
            c.state = "rejecting"
            self.respond(c.invite, 200, "OK", c.local_hdr.split("tag=")[-1], sdp(), "application/sdp", contact=True)
            log("rejected")
            c.reason = c.reason or "rejected"
            # BYE after the ACK (in on_sip); if the ACK never arrives, we end anyway
            GLib.timeout_add(1500, lambda: self.call is c and self.hangup() and False)
        else:
            self.hangup()

    def hangup(self):
        if self.call and self.call.state != "calling":
            self.in_dialog("BYE")
            log("hung up")
        self.end()

    def monitor(self):
        if self.call:
            return False
        cid, tag = rnd(), rnd()
        self.call = Call(False, cid, "%s;tag=%s" % (ME_HDR, tag), "<%s>" % PANEL_URI)
        self.send(build("INVITE %s SIP/2.0" % PANEL_URI, [
            self.via(), ("From", self.call.local_hdr), ("To", self.call.remote_hdr), ("Call-ID", cid),
            ("CSeq", "%d INVITE" % self.call.cseq), ("Contact", "<%s>" % ME), ("Max-Forwards", "70")],
            sdp("0 8 101").replace("a=rtpmap:0 PCMU/8000/1", "a=rtpmap:0 PCMU/8000/1\r\na=rtpmap:8 PCMA/8000/1"),
            "application/sdp"))
        log("camera view")
        ha_event("monitor")
        wake_screen()
        self.open_window()
        self.after(MONITOR_TIMEOUT, self.hangup)
        return True

    # --- window and state ---

    def open_window(self):
        widgets = [self.media.start_video()]
        cam = self.media.start_camera()
        if cam:
            widgets.append(cam)
        self.win = CallWindow(widgets, self)
        self.media.play_video()
        self.update_ui()
        GLib.timeout_add_seconds(10, self.keep_awake)
        GLib.timeout_add_seconds(3, self.keep_video)

    def keep_awake(self):
        if not self.call:
            return False
        wake_screen()
        return True

    def keep_video(self):
        """Keep-alive packet for the video every 3 s, like the original screen."""
        if not self.call:
            return False
        return self.media.punch()

    def update_ui(self):
        c, w = self.call, self.win
        if not (c and w):
            return
        unlock = ("Open gate", "unlock", self.unlock)
        if c.state == "ringing":
            w.status.set_text("Ringing")
            w.set_buttons([("Answer", "answer", self.answer), unlock, ("Decline", "hangup", self.reject)])
        elif c.state == "talk":
            w.status.set_text("In call")
            w.set_buttons([unlock, ("Hang up", "hangup", self.hangup)])
        elif c.state == "monitor":
            w.status.set_text("Camera view")
            w.set_buttons([("Talk", "answer", self.talk), unlock, ("Close", "hangup", self.hangup)])
        else:
            w.status.set_text("Connecting…")
            w.set_buttons([("Close", "hangup", self.hangup)])

    def talk(self):
        """Camera view -> call: turn the microphone on."""
        if self.call and self.call.state == "monitor":
            self.call.state = "talk"
            self.media.set_mic(True)
            self.cancel_timers()
            self.after(TALK_TIMEOUT, self.hangup)
            self.update_ui()

    def after(self, seconds, fn):
        call = self.call

        def fire():
            if self.call is call:
                fn()
            return False
        self.timers.append(GLib.timeout_add_seconds(seconds, fire))

    def cancel_timers(self):
        for t in self.timers:
            GLib.source_remove(t)
        self.timers = []

    def end(self, reason=None):
        """
        End of a call. reason: panel (the panel hung up), missed (the panel stopped ringing, nobody
        answered), rejected, timeout, screen (hung up on the screen).
        """
        c = self.call
        if c:
            ha_event("call_ended", kind="call" if c.incoming else "monitor",
                     reason=reason or c.reason or "screen", answered=c.answered_at is not None,
                     duration=round(time.time() - (c.answered_at or c.started)))
        self.ringer.stop()
        self.cancel_timers()
        self.media.stop()
        if self.win:
            self.win.destroy()
            self.win = None
        self.call = None

    # --- local control (dashboard button via nginx) ---

    def on_http(self, *_):
        c, _ = self.http.accept()
        c.settimeout(1)
        try:
            req = c.recv(1024).decode(errors="replace").split(" ")
            path = req[1] if len(req) > 1 else ""
            if path.startswith("/monitor"):
                ok = self.monitor()
            elif path.startswith("/talk"):
                ok = bool(self.call and self.call.state == "monitor")
                self.talk()
            elif path.startswith("/hangup"):
                ok = bool(self.call)
                self.hangup()
            else:
                ok = False
            c.sendall(("HTTP/1.0 %s\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\n%s"
                       % (("200 OK", "ok") if ok else ("409 Conflict", "no"))).encode())
        except OSError:
            pass
        c.close()
        return True


def main():
    Gst.init(None)
    Gtk.init(None)
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    App()
    Gtk.main()


if __name__ == "__main__":
    sys.exit(main())
