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
        self._accept_packets = False
        self._sock_tag = None
        self._sock_status = None
        self._read_buf = ""
        self._write_buf = ""
        self._compressor = None
        self._decompressor = None
        self._reset_watch()

    def accept_packets(self):
        self._accept_packets = True

    def will_accept_packets(self):
        return self._accept_packets

    def queue_packet(self, packet):
        if self._accept_packets:
            print "sending %s" % (dump_packet(packet),)
            data = bencode(packet)
            if self._compressor is not None:
                data = self._compressor.compress(data)
                data += self._compressor.flush(zlib.Z_SYNC_FLUSH)
            self._write_buf += data
            self._reset_watch()
            self._socket_write()
        else:
            print "not sending %s" (dump_packet(packet),)

    def enable_deflate(self):
        self._compressor = zlib.compressobj()
        self._decompressor = zlib.decompressobj()

    def close(self):
        if self._sock_tag is not None:
            gobject.source_remove(self._sock_tag)
            self._sock_tag = None
        self._sock.close()

    def _reset_watch(self):
        wanted = gobject.IO_IN
        if self._write_buf:
            wanted |= gobject.IO_OUT
        if wanted != self._sock_status:
            if self._sock_tag is not None:
                gobject.source_remove(self._sock_tag)
            self._sock_tag = gobject.io_add_watch(self._sock,
                                                  wanted,
                                                  self._socket_live)
            self._sock_status = wanted

    def _socket_live(self, sock, condition):
        if condition & gobject.IO_IN:
            self._socket_read()
        if condition & gobject.IO_OUT:
            self._socket_write()
        return True

    def _socket_read(self):
        buf = self._sock.recv(4096)
        if not buf:
            self._accept_packets = False
            self._process_packet_cb([Protocol.CONNECTION_LOST, self])
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

    def _consume_packet(self, data):
        try:
            decoded, consumed = bdecode(data)
        except ValueError:
            return 0
        try:
            print "got %s" % (dump_packet(decoded),)
            self._process_packet_cb(decoded)
        except KeyboardInterrupt:
            raise
        except:
            print "Unhandled error while processing packet from peer"
            dump_exc()
            # Ignore and continue, maybe things will work out anyway
        return consumed

    def _socket_write(self):
        sent = self._sock.send(self._write_buf)
        self._write_buf = self._write_buf[sent:]
        self._reset_watch()

class DummyProtocol(object):
    def queue_packet(self, packet):
        pass

    def close(self):
        pass
