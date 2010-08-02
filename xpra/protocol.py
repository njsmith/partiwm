# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import socket # for socket.error
import zlib
import struct

from xpra.bencode import bencode, IncrBDecode
from xpra.platform import socket_channel

from wimpiggy.log import Logger
log = Logger()

def repr_ellipsized(obj, limit):
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
#   4) Also, reading and writing from the same socket is kind of a pain on
#      win32 anyway, because you can only have one IO watch active per socket:
#        http://faq.pygtk.org/index.py?req=all#20.20
#      So using two sockets simplifies the IO watch code.
# Anyway, for all thse reasons, we make two different sockets, one for stdin
# and one for stdout. And for consistency, we do the same on POSIX.

class Protocol(object):
    CONNECTION_LOST = object()
    GIBBERISH = object()

    def __init__(self, write_sock, read_sock, process_packet_cb):
        # The socket objects own the underlying OS socket; so even though we
        # mostly interact with the channel objects, we must keep references
        # to the socket objects around to prevent the underlying sockets from
        # getting closed.
        self._write_sock = write_sock
        self._write_sock.setblocking(False)
        self._write_channel = socket_channel(write_sock)
        self._write_channel.set_encoding(None)
        self._write_channel.set_buffered(0)

        self._read_sock = read_sock
        self._read_sock.setblocking(False)
        self._read_channel = socket_channel(read_sock)
        self._read_channel.set_encoding(None)
        self._read_channel.set_buffered(0)

        self._process_packet_cb = process_packet_cb
        # Invariant: if .source is None, then _source_has_more == False
        self.source = None
        self._source_has_more = False
        self._closed = False
        self._read_decoder = IncrBDecode()
        self._write_buf = ""
        self._compressor = None
        self._decompressor = None
        self._read_watch_tag = self._read_channel.add_watch(gobject.IO_IN
                                                            | gobject.IO_HUP,
                                                            self._read_ready)
        self._write_armed = False
        self._write_watch_tag = None
        self._update_write_watch(force=True)

    def source_has_more(self):
        assert self.source is not None
        self._source_has_more = True
        self._update_write_watch()

    def _update_write_watch(self, force=False):
        want_write = bool(not self._closed
                          and (self._write_buf or self._source_has_more))
        log("updating watch: want_write=%s (was %s)",
            want_write, self._write_armed)
        if want_write == self._write_armed and not force:
            return
        flags = gobject.IO_HUP
        if want_write:
            flags |= gobject.IO_OUT
        if self._write_watch_tag is not None:
            gobject.source_remove(self._write_watch_tag)
        self._write_watch_tag = self._write_channel.add_watch(flags,
                                                              self._write_ready)
        self._write_armed = want_write

    def _read_ready(self, source, flags):
        log("_read_ready")
        if flags & gobject.IO_IN:
            self._read_some()
        assert not (flags & gobject.IO_OUT)
        if flags & gobject.IO_HUP:
            self._connection_lost()
        return True

    def _write_ready(self, source, flags):
        log("_write_ready")
        assert not (flags & gobject.IO_IN)
        if flags & gobject.IO_OUT:
            self._write_some()
        if flags & gobject.IO_HUP:
            self._connection_lost()
        return True

    def _read_some(self):
        log("_read_some")
        try:
            buf = self._read_channel.read(4096)
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

    def _write_some(self):
        log("_write_some")
        if not self._write_buf:
            # Underflow: refill buffer from source.
            # We can't get into this function at all unless either _write_buf
            # is non-empty, or _source_has_more == True, because of the guard
            # in _update_write_watch.
            assert self._source_has_more
            self._flush_one_packet_into_buffer()
        try:
            sent = self._write_channel.write(self._write_buf)
            #self._write_channel.flush()
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
            data_payload = bencode(packet)
            data_header = struct.pack(">I", len(data_payload))
            #data = data_header + data_payload
            data = data_payload
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
            if self._read_watch_tag is not None:
                gobject.source_remove(self._read_watch_tag)
                self._read_watch_tag = None
            if self._write_watch_tag is not None:
                gobject.source_remove(self._write_watch_tag)
                self._write_watch_tag = None
            self._closed = True
            self._read_sock.close()
            self._write_sock.close()
