# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import os
import socket

import sys

from wimpiggy.log import Logger
log = Logger()

class ChannelProxy(gobject.GObject):
    """Copies bytes from 'readfd' to 'writefd'.

    This is performed efficiently (i.e., with no busy-waiting) and with
    minimal buffering (i.e., we transfer backpressure from writefd to
    readfd).

    Closes both fds when done."""

    READ = "READ"
    WRITE = "WRITE"
    DONE = "DONE"

    __gsignals__ = {
        "done": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
        }

    def __init__(self, readfd, writefd):
        gobject.GObject.__init__(self)
        self._readfd = readfd
        self._writefd = writefd
        self._tag = None
        self._writebuf = ""
        self._definitely_readable = False
        self._state = None
        self._set_state(self.READ)
        gobject.io_add_watch(self._readfd, gobject.IO_ERR | gobject.IO_HUP,
                             self._uhoh)
        gobject.io_add_watch(self._writefd, gobject.IO_ERR | gobject.IO_HUP,
                             self._uhoh)

    def _set_state(self, state):
        # Set up new state
        log("%s: state: %s -> %s", id(self), self._state, state)
        if self._state is state:
            return
        # Clear old state
        if self._tag is not None:
            gobject.source_remove(self._tag)
        if state is self.READ:
            self._tag = gobject.io_add_watch(self._readfd, gobject.IO_IN,
                                             self._readable)
        elif state is self.WRITE:
            self._tag = gobject.io_add_watch(self._writefd, gobject.IO_OUT,
                                             self._writeable)
        elif state is self.DONE:
            os.close(self._readfd)
            os.close(self._writefd)
            self.emit("done")
        else:
            assert False
        self._state = state

    def _readable(self, *args):
        #sys.stderr.write("%s: %s readable\n" % (id(self), self._readfd))
        self._definitely_readable = True
        self._set_state(self.WRITE)
        return True

    def _writeable(self, *args):
        #sys.stderr.write("%s: %s writeable\n" % (id(self), self._writefd))
        if not self._writebuf:
            self._writebuf = os.read(self._readfd, 8192)
            if not self._writebuf and self._definitely_readable:
                # if an fd signals readable with nothing in it, that means EOF
                self._set_state(self.DONE)
                return True
            self._definitely_readable = False
        wrote = os.write(self._writefd, self._writebuf)
        if not wrote:
            self._set_state(self.DONE)
            return True
        self._writebuf = self._writebuf[wrote:]
        if not self._writebuf:
            self._set_state(self.READ)
        return True

    def _uhoh(self, *args):
        self._set_state(self.DONE)
        return False

gobject.type_register(ChannelProxy)

class XpraProxy(object):
    def __init__(self, readfd, writefd, server_conn):
        serverfd1 = os.dup(server_conn.fileno())
        serverfd2 = os.dup(server_conn.fileno())

        self._toserver = ChannelProxy(readfd, serverfd1)
        self._toserver.connect("done", self._quit)
        self._fromserver = ChannelProxy(serverfd2, writefd)
        self._fromserver.connect("done", self._quit)

        self._mainloop = gobject.MainLoop()

    def run(self):
        self._mainloop.run()

    def _quit(self, *args):
        log("exiting main loop")
        self._mainloop.quit()
