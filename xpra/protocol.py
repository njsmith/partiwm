# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import socket # for socket.error
import zlib
import struct

from xpra.bencode import bencode, IncrBDecode

from wimpiggy.log import Logger
log = Logger()

def repr_ellipsized(obj, limit):
    if isinstance(obj, str) and len(obj) > limit:
        return repr(obj[:limit]) + "..."
    else:
        return repr(obj)

def dump_packet(packet):
    return "[" + ", ".join([repr_ellipsized(x, 50) for x in packet]) + "]"

class Protocol(object):
    CONNECTION_LOST = object()

    # Taking both a channel and a socket (which are two python objects both
    # representing the same underlying OS object) is a little silly, but:
    #   1) On Win32, correctly turning a socket into a channel requires black
    #      magic.
    #   2) Everywhere, we have to make sure the underlying socket is not
    #      closed until we are ready for it to be closed. The Python socket
    #      object owns the underlying socket; the Python channel object does
    #      not. So we need to keep a reference.
    #   3) In general, this way we avoid depending on pygobject to handle
    #      Win32 stuff correctly, like using the correct close syscall... I
    #      trust Python's socket module more.
    def __init__(self, channel, sock, process_packet_cb):
        self._channel = channel
        self._sock = sock
        self._process_packet_cb = process_packet_cb
        # Invariant: if .source is None, then _source_has_more == False
        self.source = None
        self._source_has_more = False
        self._accept_packets = False
        self._closed = False
        self._write_armed = False
        self._read_decoder = IncrBDecode()
        self._write_buf = ""
        self._compressor = None
        self._decompressor = None
        self._watch_tag = None
        self._update_watch(force=True)

    def source_has_more(self):
        self._source_has_more = True
        self._update_watch()

    def _update_watch(self, force=False):
        # It would perhaps be simpler to use two separate watches, one for
        # reading and one for writing, but that doesn't work on Win32:
        #   http://faq.pygtk.org/index.py?req=all#20.20
        # Win32 also requires we watch for IO_HUP.
        if self._closed:
            return
        want_write = bool(self._write_buf or self._source_has_more)
        if not force and want_write == self._write_armed:
            return
        flags = gobject.IO_IN | gobject.IO_HUP
        if want_write:
            flags |= gobject.IO_OUT
        if self._watch_tag is not None:
            gobject.source_remove(self._watch_tag)
        self._watch_tag = self._channel.add_watch(flags, self._socket_ready)
        self._write_armed = want_write

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

    def _socket_ready(self, source, flags):
        if flags & gobject.IO_IN:
            self._socket_readable()
        if flags & gobject.IO_OUT:
            self._socket_writeable()
        if flags & gobject.IO_HUP:
            self._connection_lost()
        return True

    def _connection_lost(self):
        if not self._closed:
            self._accept_packets = False
            self._process_packet_cb(self, [Protocol.CONNECTION_LOST])
            self.close()

    def _socket_writeable(self):
        if not self._write_buf:
            # Underflow: refill buffer from source.
            # We can't get into this function at all unless either _write_buf
            # is non-empty, or _source_has_more == True, because of the guard
            # in _update_watch.
            assert self._source_has_more
            self._flush_one_packet_into_buffer()
        try:
            sent = self._sock.send(self._write_buf)
        except socket.error:
            print "Error writing to socket"
            self._connection_lost()
        else:
            self._write_buf = self._write_buf[sent:]
            self._update_watch()

    def _socket_readable(self):
        try:
            buf = self._sock.recv(4096)
        except socket.error:
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
            result = self._read_decoder.process()
            if result is None:
                break
            packet, unprocessed = result
            self._process_packet(packet)
            if not had_deflate and (self._decompressor is not None):
                # deflate was just enabled: so decompress the unprocessed data
                unprocessed = self._decompressor.decompress(unprocessed)
            self._read_decoder = IncrBDecode(unprocessed)

    def _process_packet(self, decoded):
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
        self._update_watch()
        # Now enable compression
        self._compressor = zlib.compressobj(level)
        self._decompressor = zlib.decompressobj()

    def close(self):
        if not self._closed:
            if self._watch_tag is not None:
                gobject.source_remove(self._watch_tag)
                self._watch_tag = None
            self._closed = True
            self._sock.close()
