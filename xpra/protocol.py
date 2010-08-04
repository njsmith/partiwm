# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import socket # for socket.error
import zlib

from xpra.bencode import bencode, IncrBDecode
from xpra.platform import socket_channel

from wimpiggy.log import Logger
log = Logger()

def repr_ellipsized(obj, limit=100):
    if isinstance(obj, str) and len(obj) > limit:
        return repr(obj[:limit]) + "..."
    else:
        return repr(obj)

def dump_packet(packet):
    return "[" + ", ".join([repr_ellipsized(x, 50) for x in packet]) + "]"

# We use two sockets to talk to the child, rather than 1 socket, or 2 pipes,
# because on Windows:
#   1) You can only call select() on sockets
#   2) If you want to pass a socket as a child process's stdin/stdout, then
#      that socket must *not* have WSA_FLAG_OVERLAPPED set.
#   3) plink, sensibly enough given win32's limitations, uses two threads to
#      simultaneously read and write stdin and stdout. But if stdin and stdout
#      refer to the same socket, then this counts as "overlapped IO", which
#      requires that WSA_FLAG_OVERLAPPED *is* set. (Thanks to Simon Tatham for
#      helping me figure this out.)
# Anyway, for all thse reasons, we make two different sockets, one for stdin
# and one for stdout. And for consistency, we do the same on POSIX.
#
# But, reading and writing from the same socket is kind of a pain on win32
# because you can only have one IO watch active per socket:
#     http://faq.pygtk.org/index.py?req=all#20.20
# Yet, sometimes we have to have just one socket, when we're making a
# direct connection, over TCP or Unix domain. So then we have to manage that
# one socket consistently too.
#
# This class abstracts away the win32 nonsense about whether our read socket
# and write socket are actually the same:
class TwoChannels(object):
    ONE = object()
    TWO = object()

    def _setup_channel(self, sock):
        sock.setblocking(0)
        channel = socket_channel(sock)
        channel.set_encoding(None)
        channel.set_buffered(0)
        return channel

    def __init__(self, write_sock, read_sock, watch_cb):
        # The socket objects own the underlying OS socket; so even though we
        # mostly interact with the channel objects, we must keep references
        # to the socket objects around to prevent the underlying sockets from
        # getting closed.
        self._write_sock = write_sock
        self._read_sock = read_sock
        self._watch_cb = watch_cb
        self._write_armed = False
        self._write_watch_tag = None
        if write_sock.fileno() == read_sock.fileno():
            log("one-socket mode (socket=%s)", write_sock.fileno())
            self._mode = self.ONE
            self._channel = self._setup_channel(write_sock)
        else:
            log("two-socket mode (write=%s, read=%s)",
                write_sock.fileno(), read_sock.fileno())
            self._mode = self.TWO
            self._write_channel = self._setup_channel(write_sock)
            self._read_channel = self._setup_channel(read_sock)
            tag = self._read_channel.add_watch(gobject.IO_IN | gobject.IO_HUP,
                                               self._watch_cb)
            self._read_watch_tag = tag
        self.update_write_watch(False, force=True)

    def update_write_watch(self, want_write, force=False):
        log("update_write_watch: want_write=%s (was %s)",
            want_write, self._write_armed)
        if want_write != self._write_armed or force:
            if self._mode is self.ONE:
                flags = gobject.IO_IN | gobject.IO_HUP
                channel = self._channel
            else:
                assert self._mode is self.TWO
                flags = gobject.IO_HUP
                channel = self._write_channel
            if want_write:
                flags |= gobject.IO_OUT
            log("new write channel flags: %s", flags)
            if self._write_watch_tag is not None:
                gobject.source_remove(self._write_watch_tag)
            self._write_watch_tag = channel.add_watch(flags, self._watch_cb)
            self._write_armed = want_write

    def close(self):
        log("TwoChannels: closing")
        self._write_sock.close()
        try:
            self._read_sock.close()
        except (IOError, socket.error):
            pass
        gobject.source_remove(self._write_watch_tag)
        if self._mode is self.TWO:
            gobject.source_remove(self._read_watch_tag)

class Protocol(object):
    CONNECTION_LOST = object()
    GIBBERISH = object()

    def __init__(self, write_sock, read_sock, process_packet_cb):
        self._channels = TwoChannels(write_sock, read_sock,
                                     self._channel_ready)

        self._process_packet_cb = process_packet_cb
        # Invariant: if .source is None, then _source_has_more == False
        self.source = None
        self._source_has_more = False
        self._closed = False
        self._read_decoder = IncrBDecode()
        self._write_buf = ""
        self._compressor = None
        self._decompressor = None

    def source_has_more(self):
        assert self.source is not None
        self._source_has_more = True
        self._update_write_watch()

    def _update_write_watch(self):
        want_write = bool(not self._closed
                          and (self._write_buf or self._source_has_more))
        self._channels.update_write_watch(want_write)

    def _channel_ready(self, channel, flags):
        log("_channel_ready (%s)", flags)
        if flags & gobject.IO_IN:
            self._read_some(channel)
        if flags & gobject.IO_OUT:
            self._write_some(channel)
        if flags & gobject.IO_HUP:
            self._connection_lost()
        return True

    def _read_some(self, channel):
        log("_read_some")
        try:
            buf = channel.read(8192)
        except (socket.error, gobject.GError):
            print "Error reading from socket"
            self._connection_lost()
            return False
        if not buf:
            self._connection_lost()
            return False
        if self._decompressor is not None:
            buf = self._decompressor.decompress(buf)
        self._read_decoder.add(buf)
        while True:
            had_deflate = (self._decompressor is not None)
            # try:
            #     result = self._read_decoder.process()
            # except:
            #     import sys; import pdb; pdb.post_mortem(sys.exc_info()[-1])
            try:
                result = self._read_decoder.process()
            except ValueError:
                # Peek at the data we got, in case we can make sense of it:
                self._process_packet([Protocol.GIBBERISH,
                                      self._read_decoder.unprocessed()])
                # Then hang up:
                self._connection_lost()
                return
            if result is None:
                break
            packet, unprocessed = result
            self._process_packet(packet)
            if not had_deflate and (self._decompressor is not None):
                # deflate was just enabled: so decompress the unprocessed data
                unprocessed = self._decompressor.decompress(unprocessed)
            self._read_decoder = IncrBDecode(unprocessed)

    def _write_some(self, channel):
        log("_write_some")
        if not self._write_buf:
            # Underflow: refill buffer from source.
            # We can't get into this function at all unless either _write_buf
            # is non-empty, or _source_has_more == True, because of the guard
            # in _update_write_watch.
            assert self._source_has_more
            self._flush_one_packet_into_buffer()
        try:
            sent = channel.write(self._write_buf)
            channel.flush()
        except (socket.error, gobject.GError):
            print "Error writing to socket"
            self._connection_lost()
        else:
            self._write_buf = self._write_buf[sent:]
            self._update_write_watch()

    def _flush_one_packet_into_buffer(self):
        if not self.source:
            return
        packet, self._source_has_more = self.source.next_packet()
        if packet is not None:
            log("sending %s", dump_packet(packet), type="raw.send")
            data = bencode(packet)
            if self._compressor is not None:
                self._write_buf += self._compressor.compress(data)
                self._write_buf += self._compressor.flush(zlib.Z_SYNC_FLUSH)
            else:
                self._write_buf += data

    def _connection_lost(self):
        log("_connection_lost")
        if not self._closed:
            self._process_packet_cb(self, [Protocol.CONNECTION_LOST])
            self.close()

    def _process_packet(self, decoded):
        if self._closed:
            log.warn("stray packet received after connection was closed; ignoring")
            return
        try:
            log("got %s", dump_packet(decoded), type="raw.receive")
            self._process_packet_cb(self, decoded)
        except KeyboardInterrupt:
            raise
        except:
            log.warn("Unhandled error while processing packet from peer",
                     exc_info=True)
            # Ignore and continue, maybe things will work out anyway

    def enable_deflate(self, level):
        assert self._compressor is None and self._decompressor is None
        # Flush everything out of the source
        while self._source_has_more:
            self._flush_one_packet_into_buffer()
        self._update_write_watch()
        # Now enable compression
        self._compressor = zlib.compressobj(level)
        self._decompressor = zlib.decompressobj()

    def close(self):
        if not self._closed:
            self._closed = True
            self._channels.close()
