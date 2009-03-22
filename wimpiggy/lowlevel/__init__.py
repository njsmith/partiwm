# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.lowlevel.bindings import *

from wimpiggy.log import Logger
log = Logger()

def send_wm_take_focus(target, time):
    log("sending WM_TAKE_FOCUS")
    sendClientMessage(target, False, 0,
                      "WM_PROTOCOLS",
                      "WM_TAKE_FOCUS", time, 0, 0, 0)

def send_wm_delete_window(target):
    log("sending WM_TAKE_FOCUS")
    sendClientMessage(target, False, 0,
                      "WM_PROTOCOLS",
                      "WM_DELETE_WINDOW", const["CurrentTime"], 0, 0, 0)
