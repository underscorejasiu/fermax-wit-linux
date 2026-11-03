# Home Assistant

## Kiosk

The screen shows a Home Assistant dashboard full screen (`cage` + `cog`, WPE WebKit). The browser
talks to nginx on the screen (`http://localhost:8080`), which proxies Home Assistant and injects a
long-lived access token, so the screen never shows a login page and the token never leaves the
screen's root-only files.

1. In HA create a user for the kiosk **without administrator rights**.
2. Log in as that user once, open the profile → Security → *Long-lived access tokens*, create one.
3. Put it in `site/site.conf` as `HA_TOKEN`, set `HA_URL` and `KIOSK_PATH` (the dashboard path,
   e.g. `/dashboard-hall/0`), run `installer/provision.sh SCREEN_IP`.

Design dashboards for 1024×600 (minus an 8 px margin hidden by the bezel). Light dashboards help:
the A33 renders the HA frontend slowly, and the browser is restarted while the screen is blanked
(`kiosk-recycle`) because WebKit grows ~35 MB/h.

### Buttons that talk to the screen itself

Links and `iframe` cards pointing to `http://localhost:8080/meetme/…` reach the screen that shows
them:

| URL | Effect |
| --- | --- |
| `/meetme/monitor` | opens the intercom window with the panel camera (as if someone rang) |
| `/meetme/blank` | turns the backlight off now (touch wakes it) |
| `/meetme/cam.html?camera=camera.front_door` | lightweight camera view (one JPEG per second through HA's camera proxy) with an "Intercom" button; use it in an `iframe` card instead of a picture-entity card |

## Intercom events

With `HA_WEBHOOK_ID` set, every screen posts what happens to a webhook. An automation turns the
posts into `meetme_intercom` events (the kiosk token is not an administrator, so it cannot fire
events directly):

```yaml
alias: "Intercom: events from the screens"
triggers:
  - trigger: webhook
    webhook_id: meetme-REPLACE-WITH-A-LONG-RANDOM-STRING
    allowed_methods: [POST]
    local_only: true
actions:
  - event: meetme_intercom
    event_data:
      type: "{{ trigger.json.type }}"
      screen: "{{ trigger.json.screen }}"
      data: "{{ trigger.json }}"
mode: queued
```

`type` is one of:

| type | When | Extra fields |
| --- | --- | --- |
| `doorbell` | the panel rings (every screen sends it; deduplicate with `mode: single` and a delay) | |
| `answered` | answered on a screen | |
| `monitor` | camera view opened on a screen | |
| `unlock` | gate opened from a screen | `ok` |
| `call_ended` | call or view ended | `kind` (`call`/`monitor`), `reason` (`panel`, `missed`, `rejected`, `timeout`, `screen`), `answered`, `duration` |

Example: a phone notification with a camera snapshot when the doorbell rings:

```yaml
alias: "Intercom: doorbell notification"
triggers:
  - trigger: event
    event_type: meetme_intercom
    event_data:
      type: doorbell
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Doorbell
      message: Someone is at the gate
      data:
        image: /api/camera_proxy/camera.front_door
  - delay: 20
mode: single
```

## Video in the call window

The panel serves its camera over RTSP all the time (`rtsp://admin:123456@PANEL:8554/ch01`, factory
credentials) but does not send video over SIP before the call is answered. A relay keeps the
password off the screens and gives video before answering; e.g. in Frigate's go2rtc:

```yaml
go2rtc:
  streams:
    intercom_panel: rtsp://admin:123456@192.168.1.110:8554/ch01
```

then in `site/site.conf`: `PANEL_VIDEO_URL=rtsp://FRIGATE_HOST:8554/intercom_panel`. `CAMERA_URL`
adds a second camera (e.g. the entrance) next to it; keep it at about 640×480, the H.264 decoder of
the A33 handles two such streams.
