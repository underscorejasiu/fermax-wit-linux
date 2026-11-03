#!/usr/bin/env python3
# Test of stopping the meetme-intercom audio pipeline: start, 4 s, stop. On a hang,
# faulthandler prints the stack after 8 s. Packets go to 127.0.0.1, not to the panel.
import faulthandler, importlib.util, sys, time
from importlib.machinery import SourceFileLoader

loader = SourceFileLoader("intercom", "/usr/local/bin/meetme-intercom")
spec = importlib.util.spec_from_loader("intercom", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
m.Gst.init(None)
import subprocess
for mic in (False, True):
    media = m.Media()
    media.start_audio(("127.0.0.1", 6000), mic=mic)
    # "panel": PCMU 20 ms to the receive port, as in a real call
    panel = subprocess.Popen(["gst-launch-1.0", "-q", "audiotestsrc", "is-live=true", "!", "audio/x-raw,rate=8000,channels=1",
                              "!", "mulawenc", "!", "rtppcmupay", "!", "udpsink", "host=127.0.0.1", "port=6100"])
    time.sleep(4)
    faulthandler.dump_traceback_later(8, exit=True)
    t = time.time()
    media.stop()
    faulthandler.cancel_dump_traceback_later()
    print("mic=%s: stop in %.2f s" % (mic, time.time() - t), flush=True)
    panel.kill()
