import gobject
import zlib

from wimpiggy.util import dump_exc
from xscreen.bencode import bencode, bdecode

CAPABILITIES = set(["deflate"])

def repr_ellipsized(obj, limit):
    if isinstance(obj, str) and len(obj) > limit:
        return repr(obj[:limit]) + "..."
    else:
        return repr(obj)

def dump_packet(packet):
    return "[" + ", ".join([repr_ellipsized(x, 50) for x in packet]) + "]"

class Protocol(object):
    CONNECTION_LOST = object()

    def __init__(self, sock, process_packet_cb):
        self._sock = sock
        self._process_packet_cb = process_packet_cb
        # Invariant: if .source is None, then _source_has_more == False
        self.source = None
        self._source_has_more = False
        self._accept_packets = False
        self._read_tag = gobject.io_add_watch(self._sock, gobject.IO_IN,
                                              self._socket_readable)
        self._write_tag = None
        self._read_buf = ""
        self._write_buf = ""
        self._compressor = None
        self._decompressor = None

    def source_has_more(self):
        self._source_has_more = True
        self._update_write_watch()

    def _update_write_watch(self):
        want_write = (self._write_buf or self._source_has_more)
        write_armed = (self._write_tag is not None)
        if want_write == write_armed:
            return
        if want_write:
            #print "Arming writes"
            self._write_tag = gobject.io_add_watch(self._sock, gobject.IO_OUT,
                                                   self._socket_writeable)
        else:
            #print "Disarming writes"
            gobject.source_remove(self._write_tag)
            self._write_tag = None

    def _flush_one_packet_into_buffer(self):
        if not self.source:
            return
        packet, self._source_has_more = self.source.next_packet()
        if packet is not None:
            print "sending %s" % (dump_packet(packet),)
            data = bencode(packet)
            if self._compressor is not None:
                self._write_buf += self._compressor.compress(data)
                self._write_buf += self._compressor.flush(zlib.Z_SYNC_FLUSH)
            else:
                self._write_buf += data

    def _socket_writeable(self, *args):
        if not self._write_buf:
            # Underflow: refill buffer from source.
            # We can't get here unless either _write_buf is non-empty, or
            # _source_has_more == True, because of the guard in
            # _update_write_watch.
            assert self._source_has_more
            self._flush_one_packet_into_buffer()
        sent = self._sock.send(self._write_buf)
        self._write_buf = self._write_buf[sent:]
        self._update_write_watch()
        return True

    def _socket_readable(self, *args):
        buf = self._sock.recv(4096)
        if not buf:
            self._accept_packets = False
            self._process_packet_cb(self, [Protocol.CONNECTION_LOST])
            return False
        if self._decompressor is not None:
            buf = self._decompressor.decompress(buf)
        self._read_buf += buf
        while True:
            had_deflate = (self._decompressor is not None)
            consumed = self._consume_packet(self._read_buf)
            self._read_buf = self._read_buf[consumed:]
            if not had_deflate and (self._decompressor is not None):
                # deflate was just enabled: so decompress the data currently
                # waiting in the read buffer
                self._read_buf = self._decompressor.decompress(self._read_buf)
            if consumed == 0:
                break
        return True

    def _consume_packet(self, data):
        try:
            decoded, consumed = bdecode(data)
        except ValueError:
            return 0
        try:
            print "got %s" % (dump_packet(decoded),)
            self._process_packet_cb(self, decoded)
        except KeyboardInterrupt:
            raise
        except:
            print "Unhandled error while processing packet from peer"
            dump_exc()
            # Ignore and continue, maybe things will work out anyway
        return consumed

    def enable_deflate(self):
        assert self._compressor is None and self._decompressor is None
        # Flush everything out of the source
        while self._source_has_more:
            self._flush_one_packet_into_buffer()
        # Now enable compression
        self._compressor = zlib.compressobj()
        self._decompressor = zlib.decompressobj()

    def close(self):
        if self._read_tag is not None:
            gobject.source_remove(self._read_tag)
            self._read_tag = None
        if self._write_tag is not None:
            gobject.source_remove(self._write_tag)
            self._write_tag = None
        self._sock.close()
