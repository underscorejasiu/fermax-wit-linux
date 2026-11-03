# Fermax MEET (DNAKE) intercom protocol: door panel ↔ screens

Reverse-engineered from packet captures of original Android screens talking to a Fermax MEET door
panel: a camera preview started from a screen, and a call from the panel that was declined, then
answered, followed by "open gate" and hang-up. `intercom/tools/sipdump.py capture.pcap [-v]` prints
the SIP and port 8400 messages of a capture without the noise (heartbeats, discovery).

Addresses below are examples; use your own (the original screens keep them in `/dnake/cfg/sys.xml`).

## Devices and addresses

| Device | Example IP | SIP user | Name in `From`/`To` |
|---|---|---|---|
| Door panel | 192.168.1.110 | `10001000001` | `F-1-0-001-` |
| Master screen (dcode 0) | 192.168.1.100 | `1000001` | `M-1-0-001-` |
| Slave screens (dcode 1–4) | .101–.104 | `1000001` | `M-1-0-001-` |

`1000001` = building 1, unit 0, floor 0, apartment 01. All screens of an apartment share the same
user; only the IP tells them apart. Panel = `1` + `0001` + `000001`.

Everything is SIP over UDP 5060 with **no REGISTER, no server and no authentication**.
`User-Agent`: screen `DnakeVoip v1.0`, panel `FermaxVoip v1.0`.

## Apartment membership (heartbeat to the master screen)

Every ~5 s each slave screen sends the master an out-of-dialog `MESSAGE`
(`Content-Type: text/plain`):

```xml
<params>
	<app>slave</app>
	<event>heartbeat</event>
	<event_url>/slave/heartbeat</event_url>
	<dcode>4</dcode>
	<sync>…sync password from sys.xml…</sync>
</params>
```

The master answers `200 OK` with the list of screens (`text/xml`):
`<url0>sip:1000001@192.168.1.100:5060</url0> … <url4>sip:1000001@192.168.1.104:5060</url4>`,
`<event_url>/slave/heartbeat</event_url>`, `<resultCode>200</resultCode>`.

A new screen's heartbeat is rejected (`480`, `DnakeHost::heartBeat err` in the master's logcat)
whatever dcode, MAC or port it uses, so a Debian screen does not join this way — see discovery below.

## Discovery: who rings

When someone presses the button, the panel sends to `238.9.9.1:8400` (multicast) and
`255.255.255.255:8400`:

```xml
<event><active>discover</active><type>req</type><id>1000001</id><version>1</version><fermax>1</fermax></event>
```

The master screen answers with a unicast to port 8400 of the panel:

```xml
<event><active>discover</active><type>ack</type><fermax>1</fermax>
<url>sip:1000001@192.168.1.100:5060</url><name></name><build>1</build>
<slave0>sip:1000001@192.168.1.101:5060</slave0> … <slave3>sip:1234567@sip.fermax.com</slave3></event>
```

The list is built from heartbeats (a screen that is switched off disappears), plus the Fermax
cloud account of the apartment (`ex_slv_url0` in the master's configuration).

- **The panel only rings the screens from the first answer it gets.** The Debian screens answer
  with a fixed list (`SCREENS` + `EXTRA_URLS` in `site/site.conf`), the same on every screen, so it
  does not matter which one is first.
- **The Fermax phone app rings only if its `sip:…@sip.fermax.com` account is on that list.** The
  panel keeps its own registration with the cloud, but without the entry the phone stays silent.
  Copy the account from the master screen's discover answer (capture it, or read `ex_slv_url0`).

## Call from the panel

1. Discovery as above, then `INVITE sip:1000001@<screen IP>:5060` to every screen on the list.
2. Screen: `100 Trying`, `101 Dialog Establishement` (sic, with a tag), `180 Ringing` (no SDP).
3. Answer: `200 OK` with SDP, panel `ACK`.
4. **Decline** is also `200 OK`, immediately followed by a `BYE` from the screen (not `486`/`603`).
5. Hang-up: the screen sends `BYE`, the panel `200 OK`.
6. ~0.6 s later the panel sends `broadcast_data` `/fermax/hostInfo` to `238.9.9.1:8400` (event id,
   `host 10001000001`, `sendTime`), probably for the cloud app.
7. The panel retries `BYE` every ~4 s for old, half-closed calls: acknowledge every one.

**Video before answering:** the panel only starts sending video after RTP reaches it. The screen
answers `100` and `101`, sends 16 empty RTP packets to the panel's port 6200, then `180`, and one
packet every ~3 s after that. The panel starts sending ~1 s after the burst. With only 3 packets
after `180` there was no video before answering. In practice the panel's own RTSP stream is
more reliable (see below).

## Camera preview from a screen (monitoring)

1. The screen sends a discover `req` with `<id>1009901</id>` to the multicast address; the panel
   answers by unicast: `<type>ack</type><url>sip:10001000001@192.168.1.110:5060</url><build>1</build><fermax>1</fermax>`.
2. `INVITE sip:10001000001@192.168.1.110:5060` from `sip:1000001@<screen IP>` with the SDP below;
   panel `100`, `180` (with SDP), `200 OK`, `ACK`; `BYE` to end.

## SDP and media

```
m=audio 6100 RTP/AVP 0 8 101      (screen; panel: 6000)
a=rtpmap:0 PCMU/8000/1
a=rtpmap:8 PCMA/8000/1
a=rtpmap:101 telephone-event/8000/1
a=fmtp:101 0-11
m=video 6200 RTP/AVP 102          (6200 on both sides)
a=rtpmap:102 H264/90000
a=fmtp:102 profile-level-id=42001F; packetization-mode=1
a=ex_fmtp:102 2CIF=1              (screen only)
```

- The panel picks PCMU. Audio RTP every 20 ms (172 B), RTCP on port +1.
- Video only flows panel → screen: H.264 Baseline 3.1 (SPS `67 42 00 1f`), 640×480 at ~18 fps,
  FU-A packets ≤ 1312 B, SPS/PPS repeated every ~2 s. Right after connecting the screen sends a few
  12-byte RTP packets (PT 102, payload `ff…`) to 6200 to open the path; the panel gets no video.
- The panel also serves the camera over RTSP at all times:
  `rtsp://admin:123456@<panel>:8554/ch01` (factory credentials, H.264 640×480). Relaying it through
  go2rtc/Frigate gives video before the call is answered and keeps the password off the screens.

## Opening the gate

Out-of-dialog `MESSAGE sip:10001000001@192.168.1.110:5060` (its own `Call-ID`), `text/plain`:

```xml
<params>
	<app>talk</app>
	<event>unlock</event>
	<event_url>/talk/unlock</event_url>
	<index>0</index>
	<host>1000001</host>
	<build>1</build>
	<unit>0</unit>
	<floor>0</floor>
	<family>1</family>
</params>
```

Panel: `200 OK`, `<params><event_url>/talk/unlock</event_url><resultCode>200</resultCode></params>`.
`<index>` is the relay number (0 = gate; 1 = second relay, not verified).

## Security

The panel accepts `INVITE` and `MESSAGE /talk/unlock` from any host on the LAN without a password.
Any device on that network can watch the camera and **open the gate with a single UDP packet**.
Put the panel and the screens in their own VLAN, or behind a firewall rule that only lets the
screens talk to the panel.

## Open questions

- What the panel sends to the other screens when one answers (`CANCEL`?).
- Whether the master screen notifies the slaves when it rings (`/control/slaves/ringing`).
- `index` 1 when unlocking (second door?), the purpose of `/fermax/hostInfo`.
