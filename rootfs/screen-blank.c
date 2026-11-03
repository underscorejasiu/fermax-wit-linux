/*
 * screen-blank: turns the screen backlight off after N seconds without touch.
 *
 * While the screen is blanked, the touchscreen is grabbed exclusively (EVIOCGRAB),
 * so the touch that wakes the screen does not reach the kiosk browser.
 * Touch goes back to the compositor only after the finger is lifted.
 *
 * Manual blanking:
 *  - holding a finger for ~1 s in the bottom-right corner of the screen (a system gesture,
 *    works regardless of what the kiosk is displaying),
 *  - any HTTP request to 127.0.0.1:<port> (default 8099); nginx
 *    exposes it to the kiosk as /meetme/blank.
 *
 * GET /wake on the same port wakes the screen and restarts the idle timer (intercom doorbell;
 * during a call the intercom repeats this request so the screen does not go dark).
 *
 * Usage: screen-blank [-t seconds] [-d device] [-b backlight_dir] [-p port]
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define HOLD_MS		1000	/* czas przytrzymania w rogu */
#define CORNER_PCT	12	/* corner = last 12% of width and height */
#define HOLD_POLL_MS	100

static const char *bl_dir = "/sys/class/backlight/backlight";
static volatile sig_atomic_t stop;

static void on_signal(int sig)
{
	(void)sig;
	stop = 1;
}

static int64_t now_ms(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int write_sysfs(const char *name, const char *val)
{
	char path[256];
	int fd, ret = 0;

	snprintf(path, sizeof(path), "%s/%s", bl_dir, name);
	fd = open(path, O_WRONLY);
	if (fd < 0)
		return -errno;
	if (write(fd, val, strlen(val)) < 0)
		ret = -errno;
	close(fd);
	return ret;
}

/* bl_power: 0 = on, 4 = FB_BLANK_POWERDOWN (backlight off) */
static void set_backlight(int on)
{
	int ret = write_sysfs("bl_power", on ? "0" : "4");

	if (ret)
		fprintf(stderr, "bl_power: %s\n", strerror(-ret));
}

static int listen_local(int port)
{
	struct sockaddr_in addr = {
		.sin_family = AF_INET,
		.sin_port = htons(port),
		.sin_addr.s_addr = htonl(INADDR_LOOPBACK),
	};
	int one = 1, s = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);

	if (s < 0)
		return -1;
	setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
	if (bind(s, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(s, 4) < 0) {
		close(s);
		return -1;
	}
	return s;
}

/*
 * Accept a request and reply with a short 200 OK. Returns 1 for the /wake path (wake the screen and restart
 * the idle timer, e.g. on the intercom doorbell), 0 for any other (blank), -1 on error.
 */
static int answer_request(int srv)
{
	static const char reply[] =
		"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nok";
	char buf[512];
	int c = accept4(srv, NULL, NULL, SOCK_CLOEXEC);
	ssize_t n;

	if (c < 0)
		return -1;
	n = read(c, buf, sizeof(buf) - 1);
	if (n >= 0 && write(c, reply, sizeof(reply) - 1) < 0)
		perror("write");
	close(c);
	if (n < 0)
		return -1;
	buf[n] = 0;
	return strncmp(buf, "GET /wake", 9) == 0;
}

static int abs_max(int fd, int code, int fallback)
{
	struct input_absinfo ai;

	return ioctl(fd, EVIOCGABS(code), &ai) == 0 && ai.maximum > 0 ? ai.maximum : fallback;
}

struct state {
	int blanked;	/* backlight off, touch grabbed */
	int waking;	/* screen woken, waiting for the finger to lift */
	int down;	/* finger on the screen (while the screen is active) */
	int x, y;
	int64_t corner_since;	/* start of the corner hold, 0 = none */
};

static void blank(int fd, struct state *s)
{
	/* Grab touch and turn the backlight off */
	if (ioctl(fd, EVIOCGRAB, 1) < 0)
		perror("EVIOCGRAB");
	set_backlight(0);
	s->blanked = 1;
	s->waking = 0;
	s->corner_since = 0;
}

static void wake(int fd, struct state *s)
{
	/* Give touch back to the compositor right away: we wake without a touch, so there is nothing to swallow */
	if (s->blanked && ioctl(fd, EVIOCGRAB, 0) < 0)
		perror("EVIOCUNGRAB");
	set_backlight(1);
	s->blanked = 0;
	s->waking = 0;
	s->corner_since = 0;
}

int main(int argc, char **argv)
{
	const char *dev = "/dev/input/by-path/platform-1c2ac00.i2c-event";
	int timeout_s = 20, port = 8099, opt, fd, srv, cx, cy;
	struct state s = { 0 };
	int64_t last_activity;

	while ((opt = getopt(argc, argv, "t:d:b:p:")) != -1) {
		switch (opt) {
		case 't': timeout_s = atoi(optarg); break;
		case 'd': dev = optarg; break;
		case 'b': bl_dir = optarg; break;
		case 'p': port = atoi(optarg); break;
		default:
			fprintf(stderr, "usage: %s [-t sec] [-d dev] [-b backlight_dir] [-p port]\n", argv[0]);
			return 2;
		}
	}

	fd = open(dev, O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		perror(dev);
		return 1;
	}
	cx = abs_max(fd, ABS_MT_POSITION_X, 1780) * (100 - CORNER_PCT) / 100;
	cy = abs_max(fd, ABS_MT_POSITION_Y, 1024) * (100 - CORNER_PCT) / 100;
	srv = listen_local(port);
	if (srv < 0)
		perror("listen");

	signal(SIGTERM, on_signal);
	signal(SIGINT, on_signal);
	signal(SIGPIPE, SIG_IGN);
	set_backlight(1);
	last_activity = now_ms();

	while (!stop) {
		struct pollfd pfd[2] = {
			{ .fd = fd, .events = POLLIN },
			{ .fd = srv, .events = POLLIN },
		};
		struct input_event ev[64];
		int64_t now = now_ms();
		int timeout = -1, ret;
		ssize_t n;

		/* A blanked screen waits without a limit; an active one counts idle time and the corner gesture */
		if (!s.blanked) {
			if (s.down)
				last_activity = now;
			timeout = last_activity + timeout_s * 1000 - now;
			if (s.corner_since && timeout > HOLD_POLL_MS)
				timeout = HOLD_POLL_MS;
			if (timeout < 0)
				timeout = 0;
		}

		ret = poll(pfd, srv < 0 ? 1 : 2, timeout);
		if (ret < 0) {
			if (errno == EINTR)
				continue;
			perror("poll");
			break;
		}

		now = now_ms();
		if (!s.blanked) {
			if (s.corner_since && now - s.corner_since >= HOLD_MS)
				blank(fd, &s);
			else if (!s.down && now - last_activity >= timeout_s * 1000)
				blank(fd, &s);
		}

		if (srv >= 0 && (pfd[1].revents & POLLIN)) {
			ret = answer_request(srv);
			if (ret == 1) {
				wake(fd, &s);
				last_activity = now;
			} else if (ret == 0 && !s.blanked) {
				blank(fd, &s);
			}
		}

		if (!(pfd[0].revents & POLLIN))
			continue;

		n = read(fd, ev, sizeof(ev));
		if (n < 0) {
			if (errno == EINTR || errno == EAGAIN)
				continue;
			perror("read");
			break;
		}

		for (size_t i = 0; i < n / sizeof(ev[0]); i++) {
			struct input_event *e = &ev[i];

			if (s.blanked) {
				if (e->type != EV_KEY || e->code != BTN_TOUCH)
					continue;
				if (e->value == 1 && !s.waking) {
					set_backlight(1);
					s.waking = 1;
				} else if (e->value == 0 && s.waking) {
					/* Palec oderwany: oddaj dotyk kompozytorowi */
					if (ioctl(fd, EVIOCGRAB, 0) < 0)
						perror("EVIOCUNGRAB");
					s.blanked = 0;
					s.waking = 0;
					s.down = 0;
					last_activity = now;
				}
				/* Skip the finger lift after the corner gesture (no wake) */
				continue;
			}

			last_activity = now;
			if (e->type == EV_ABS && (e->code == ABS_MT_POSITION_X || e->code == ABS_X))
				s.x = e->value;
			else if (e->type == EV_ABS && (e->code == ABS_MT_POSITION_Y || e->code == ABS_Y))
				s.y = e->value;
			else if (e->type == EV_KEY && e->code == BTN_TOUCH)
				s.down = e->value;
			else if (e->type == EV_SYN && e->code == SYN_REPORT) {
				if (s.down && s.x >= cx && s.y >= cy) {
					if (!s.corner_since)
						s.corner_since = now;
				} else {
					s.corner_since = 0;
				}
			}
		}
	}

	ioctl(fd, EVIOCGRAB, 0);
	set_backlight(1);
	if (srv >= 0)
		close(srv);
	close(fd);
	return 0;
}
