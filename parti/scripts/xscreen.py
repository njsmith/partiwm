# Todo:
#   separate map, unmap, move, resize (map, resize require refills)
#   stacking order
#   keycode mapping
#   button press, motion events, mask
#   override-redirect windows
#   xsync resize stuff

import gtk
import gobject
import cairo
import array
import socket
import os
import os.path
import zlib
import struct

from parti.wm import Wm
from parti.world_window import WorldWindow
from parti.util import dump_exc, LameStruct
from parti.lowlevel import xtest_fake_button, xtest_fake_key

from bencode import bencode, bdecode

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

class DesktopManager(gtk.Widget):
    def __init__(self):
        gtk.Widget.__init__(self)
        self.set_property("can-focus", True)
        self.set_flags(gtk.NO_WINDOW)
        self._models = {}

    ## For communicating with the main WM:
    def add_window(self, model, x, y, w, h):
        assert self.flags() & gtk.REALIZED
        s = LameStruct()
        s.shown = False
        s.geom = (x, y, w, h)
        s.window = None
        self._models[model] = s
        model.connect("unmanaged", self._unmanaged)
        model.connect("ownership-election", self._elect_me)
        model.ownership_election()

    def window_geometry(self, model):
        return self._models[model].geom

    def show_window(self, model, x, y, w, h):
        self._models[model].shown = True
        self._models[model].geom = (x, y, w, h)
        model.ownership_election()
        model.maybe_recalculate_geometry_for(self)

    def hide_window(self, model):
        self._models[model].shown = False
        model.ownership_election()

    def reorder_windows(self, models_bottom_to_top):
        for model in models_bottom_to_top:
            win = self._models[model].window
            if win is not None:
                win.raise_()

    ## For communicating with WindowModels:
    def _unmanaged(self, model, wm_exiting):
        del self._models[model]

    def _elect_me(self, model):
        if self._models[model]:
            return (1, self)
        else:
            return (-1, self)

    def take_window(self, model, window):
        window.reparent(self.window, 0, 0)
        self._models[model].window = window

    def window_size(self, model):
        (x, y, w, h) = self._models[model].geom
        return (w, h)

    def window_position(self, model, w, h):
        (x, y, w0, h0) = self._models[model].geom
        if (w0, h0) != (w, h):
            print "Uh-oh, our size doesn't fit window sizing constraints!"
        return (x, y)

gobject.type_register(DesktopManager)

class XScreenServer(object):

    def __init__(self, replace_other_wm):
        self._wm = Wm("XScreen", replace_other_wm)
        self._wm.connect("focus-got-dropped", self._focus_dropped)
        self._wm.connect("new-window", self._new_window_signaled)

        self._world_window = WorldWindow()
        self._desktop_manager = DesktopManager()
        self._world_window.add(self._desktop_manager)
        self._world_window.show_all()

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        self._protocol = DummyProtocol()

        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        name = gtk.gdk.display_get_default().get_name()
        if name.startswith(":"):
            name = name[1:]
        sockdir = os.path.expanduser("~/.xscreen")
        if not os.path.exists(sockdir):
            os.mkdir(sockdir, 0700)
        sockpath = os.path.join(sockdir, name)
        if os.path.exists(sockpath) and replace_other_wm:
            os.unlink(sockpath)
        self._listener = socket.socket(socket.AF_UNIX)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(sockpath)
        self._listener.listen(5)
        gobject.io_add_watch(self._listener, gobject.IO_IN,
                             self._new_connection)

    def _new_connection(self, *args):
        # Just drop any existing connection
        self._protocol.close()
        sock, addr = self._listener.accept()
        self._protocol = Protocol(sock, self.process_packet)
        return True

    def _focus_dropped(self, *args):
        self._world_window.reset_x_focus()

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def _add_new_window(self, window):
        id = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = id
        self._id_to_window[id] = window
        window.connect("redraw-needed", self._redraw_needed)
        window.connect("unmanaged", self._lost_window)
        (x, y, w, h, depth) = window.get_property("client-window").get_geometry()
        self._desktop_manager.add_window(window, x, y, w, h)
        self._send_new_window_packet(window)
            
    def _send_new_window_packet(self, window):
        id = self._window_to_id[window]
        attrs = {}
        (x, y, w, h) = self._desktop_manager.window_geometry(window)
        attrs.update({"x": x, "y": y, "width": w, "height": h})
        attrs["title"] = window.get_property("title").encode("utf-8")
        hints = window.get_property("size-hints")
        if hints.max_size is not None:
            attrs["size-constraint:maximum-size"] = hints.max_size
        if hints.min_size is not None:
            attrs["size-constraint:minimum-size"] = hints.min_size
        if hints.base_size is not None:
            attrs["size-constraint:base-size"] = hints.base_size
        if hints.resize_inc is not None:
            attrs["size-constraint:increment"] = hints.resize_inc
        if hints.min_aspect is not None:
            # Need a way to send doubles, or recover the original integer
            # fractional form.
            print "FIXME: ignoring aspect ratio constraint, things will likely break"
        self._protocol.queue_packet(["new-window", id, attrs])

    def _lost_window(self, window, wm_exiting):
        id = self._window_to_id[window]
        self._protocol.queue_packet(["lost-window", id])
        del self._window_to_id[window]
        del self._id_to_window[id]

    def _redraw_needed(self, window, event):
        self._send_draw_packet(window,
                                 event.x, event.y, event.width, event.height)

    def _send_draw_packet(self, window, x, y, width, height):
        id = self._window_to_id[window]
        pixmap = window.get_property("client-contents")
        # Originally this used Cairo and an ImageSurface, but for some reason
        # the resulting surface basically always contained nonsense.  This is
        # actually less code, too:
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, width, height)
        pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(),
                                 x, y, 0, 0, width, height)
        raw_data = pixbuf.get_pixels()
        rowwidth = width * 3
        rowstride = pixbuf.get_rowstride()
        if rowwidth == rowstride:
            data = raw_data
        else:
            rows = []
            for i in xrange(height):
                rows.append(raw_data[i*rowstride : i*rowstride+rowwidth])
            data = "".join(rows)
        packet = ["draw", id, x, y, width, height, "rgb24", data]
        self._protocol.queue_packet(packet)

    def _process_hello(self, packet):
        client_capabilities = set(packet[1])
        capabilities = CAPABILITIES.intersection(client_capabilities)
        self._protocol.accept_packets()
        self._protocol.queue_packet(["hello", list(capabilities)])
        if "deflate" in capabilities:
            self._protocol.enable_deflate()
        for window in self._window_to_id.keys():
            self._desktop_manager.hide_window(window)
            self._send_new_window_packet(window)

    def _process_configure_window(self, packet):
        (_, id, x, y, width, height) = packet
        window = self._id_to_window[id]
        self._desktop_manager.show_window(window, x, y, width, height)
        self._send_draw_packet(window, 0, 0, width, height)

    def _process_window_order(self, packet):
        (_, ids_bottom_to_top) = packet
        windows_bottom_to_top = [self._id_to_window[id]
                                 for id in ids_bottom_to_top]
        self._desktop_manager.reorder_windows(windows_bottom_to_top)

    def _process_close_window(self, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        window.request_close()

    def _process_mouse_position(self, packet):
        (_, x, y) = packet
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _process_button_event(self, packet):
        (_, button, pressed) = packet
        xtest_fake_button(gtk.gdk.display_get_default(), button, pressed)

    def _process_connection_lost(self, packet):
        (_, protocol) = packet
        if protocol is self._protocol:
            self._protocol.close()
            self._protocol = DummyProtocol()
        else:
            print "stale connection lost message"

    _packet_handlers = {
        "hello": _process_hello,
        "configure-window": _process_configure_window,
        "window-order": _process_window_order,
        "close-window": _process_close_window,
        "mouse-position": _process_mouse_position,
        "button-event": _process_button_event,
        Protocol.CONNECTION_LOST: _process_connection_lost,
        }

    def process_packet(self, packet):
        packet_type = packet[0]
        self._packet_handlers[packet_type](self, packet)


class ClientWindow(gtk.Window):
    def __init__(self, client, id, attrs):
        gtk.Window.__init__(self)
        self._client = client
        self._id = id
        self._new_backing(1, 1)

        if "title" in attrs:
            self.set_title(attrs["title"].decode("utf-8"))
        else:
            self.set_title("XScreen forwarded window %s" % self._id)
        hints = {}
        for (a, h1, h2) in [
            ("size-constraint:maximum-size", "max_width", "max_height"),
            ("size-constraint:minimum-size", "min_width", "min_height"),
            ("size-constraint:base-size", "base_width", "base_height"),
            ("size-constraint:increment", "width_inc", "height_inc"),
            ]:
            if a in attrs:
                hints[h1], hints[h2] = attrs[a]
        if hints:
            self.set_geometry_hints(None, **hints)
        self.set_default_size(attrs["width"], attrs["height"])
        self._geometry = (-1, -1, -1, -1)

        self.set_app_paintable(True)

    def _new_backing(self, w, h):
        self._backing = gtk.gdk.Pixmap(gtk.gdk.get_default_root_window(),
                                       w, h)

    def draw(self, x, y, width, height, rgb_data):
        assert len(rgb_data) == width * height * 3
        gc = self._backing.new_gc()
        self._backing.draw_rgb_image(gc, x, y, width, height,
                                     gtk.gdk.RGB_DITHER_NONE, rgb_data)
        self.window.invalidate_rect(gtk.gdk.Rectangle(x, y, width, height),
                                    False)

    def do_expose_event(self, event):
        if not self.flags() & gtk.MAPPED:
            return
        cr = self.window.cairo_create()
        cr.rectangle(event.area)
        cr.clip()
        cr.set_source_pixmap(self._backing, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        return False

    def do_map_event(self, event):
        print "Got map event"
        gtk.Window.do_map_event(self, event)
        self._maybe_send_configure(True)

    def _maybe_send_configure(self, force):
        (x, y) = self.window.get_origin()
        (_, _, w, h, _) = self.window.get_geometry()
        if (x, y, w, h) != self._geometry or force:
            self._client.send_configure_window_packet(self, x, y, w, h)
        self._geometry = (x, y, w, h)

    def do_configure_event(self, event):
        print "Got configure event"
        gtk.Window.do_configure_event(self, event)
        if (event.width, event.height) != (self._geometry[2], self._geometry[3]):
            self._new_backing(event.width, event.height)
        self._maybe_send_configure(False)

    def do_delete_event(self, event):
        self._client.send_close_window_packet(self)
        return True

gobject.type_register(ClientWindow)

class XScreenClient(object):
    def __init__(self, name):
        self._window_to_id = {}
        self._id_to_window = {}

        address = os.path.expanduser("~/.xscreen/%s" % (name,))
        sock = socket.socket(socket.AF_UNIX)
        sock.connect(address)
        print "Connected"
        self._protocol = Protocol(sock, self.process_packet)
        self._protocol.accept_packets()
        self._protocol.queue_packet(["hello", list(CAPABILITIES)])

    def send_configure_window_packet(self, window, x, y, w, h):
        id = self._window_to_id[window]
        self._protocol.queue_packet(["configure-window", id, x, y, w, h])

    def send_close_window_packet(self, window):
        id = self._window_to_id[window]
        self._protocol.queue_packet(["close-window", id])

    def _process_hello(self, packet):
        (_, capabilities) = packet
        if "deflate" in capabilities:
            self._protocol.enable_deflate()

    def _process_new_window(self, packet):
        (_, id, attrs) = packet
        window = ClientWindow(self, id, attrs)
        self._id_to_window[id] = window
        self._window_to_id[window] = id
        window.show_all()

    def _process_lost_window(self, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        del self._id_to_window[id]
        del self._window_to_id[window]
        window.destroy()

    def _process_draw(self, packet):
        (_, id, x, y, width, height, coding, data) = packet
        window = self._id_to_window[id]
        assert coding == "rgb24"
        window.draw(x, y, width, height, data)

    def _process_connection_lost(self, packet):
        gtk.main_quit()

    _packet_handlers = {
        "hello": _process_hello,
        "draw": _process_draw,
        "new-window": _process_new_window,
        "lost-window": _process_lost_window,
        Protocol.CONNECTION_LOST: _process_connection_lost,
        }
    
    def process_packet(self, packet):
        packet_type = packet[0]
        self._packet_handlers[packet_type](self, packet)


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "serve":
        app = XScreenServer(True)
    elif sys.argv[1] == "connect":
        app = XScreenClient(sys.argv[2])
    else:
        print "Huh?"
        sys.exit(2)
    gtk.main()
