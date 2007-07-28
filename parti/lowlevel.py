from parti._lowlevel import *

def send_wm_take_focus(target, time):
    print "sending WM_TAKE_FOCUS"
    sendClientMessage(target, False, 0,
                      "WM_PROTOCOLS",
                      "WM_TAKE_FOCUS", time, 0, 0, 0)
