import gobject
import os
import socket
from xscreen.address import client_sock

# Basic strategy:
#   There are two pairs of (read -> write) sockets that we shuffle data
#   between.

class ChannelProxy(object):
    """Copies bytes from 'readfd' to 'writefd'.

    This is performed efficiently (i.e., with no busy-waiting) and with
    minimal buffering (i.e., we transfer backpressure from writefd to readfd.)

    Closes both fds when done."""

    READ = "READ"
    WRITE = "WRITE"
    DONE = "DONE"

    def __init__(self, readfd, writefd):
        self._readfd = readfd
        self._writefd = writefd
        self._tag = None
        self._writebuf = ""
        self._definitely_readable = False
        self._state = None
        self._set_state(self.READ)

    def _set_state(self, state):
        if self._state is state:
            return
        # Clear old state
        if self._tag is not None:
            gobject.source_remove(self._tag)
        # Set up new state
        if state is self.READ:
            self._tag = gobject.io_add_watch(self._readfd, gobject.IO_IN,
                                             self._readable)
        elif state is self.WRITE:
            self._tag = gobject.io_add_watch(self._writefd, gobject.IO_OUT,
                                             self._writeable)
        elif state is self.DONE:
            os.close(self._readfd)
            os.close(self._writefd)
        else:
            assert False

    def _readable(self, *args):
        self._definitely_readable = True
        self._set_state(self.WRITE)
        return True

    def _writeable(self, *args):
        if self._writebuf:
            wrote = os.write(self._writefd, self._writebuf)
            if not wrote:
                self._set_state(self.DONE)
            self._writebuf = self._writebuf[wrote:]
        else:
            self._writebuf = os.read(self._readfd, 8192)
            if not self._writebuf:
                if self._definitely_readable:
                    # if an fd signals readable with nothing in it, that means
                    # EOF
                    self._set_state(self.DONE)
                else:
                    self._set_state(self.READ)
            self._definitely_readable = False
        return True

class XScreenProxy(object):
    def __init__(self, readfd, writefd, name):
        server_conn = client_sock(name)
        serverfd1 = server_conn.fileno()
        serverfd2 = os.dup(serverfd1)

        self._toserver = ChannelProxy(readfd, serverfd1)
        self._fromserver = ChannelProxy(serverfd2, writefd)
