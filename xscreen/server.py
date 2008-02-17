# Todo:
#   write queue management
#   stacking order
#   keycode mapping
#   button press, motion events, mask
#   override-redirect windows
#   xsync resize stuff

import gtk
import gobject
import os
import os.path
import socket

from wimpiggy.wm import Wm
from wimpiggy.world_window import WorldWindow
from wimpiggy.util import LameStruct
from wimpiggy.lowlevel import xtest_fake_button, xtest_fake_key

from xscreen.protocol import Protocol

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
        if model.get_property("iconic"):
            model.set_property("iconic", False)

    def hide_window(self, model):
        if not model.get_property("iconic"):
            model.set_property("iconic", True)
        self._models[model].shown = False
        model.ownership_election()

    def visible(self, model):
        return self._models[model].shown

    def reorder_windows(self, models_bottom_to_top):
        for model in models_bottom_to_top:
            win = self._models[model].window
            if win is not None:
                win.raise_()

    ## For communicating with WindowModels:
    def _unmanaged(self, model, wm_exiting):
        del self._models[model]

    def _elect_me(self, model):
        if self.visible(model):
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

    _window_export_properties = ("title", "size-hints")

    def _add_new_window(self, window):
        id = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = id
        self._id_to_window[id] = window
        window.connect("redraw-needed", self._redraw_needed)
        window.connect("unmanaged", self._lost_window)
        for prop in self._window_export_properties:
            window.connect("notify::%s" % prop, self._update_metadata)
        (x, y, w, h, depth) = window.get_property("client-window").get_geometry()
        self._desktop_manager.add_window(window, x, y, w, h)
        self._send_new_window_packet(window)
            
    def _make_metadata(self, window, propname):
        if propname == "title":
            if window.get_property("title") is not None:
                return {"title": window.get_property("title").encode("utf-8")}
            else:
                return {}
        elif propname == "size-hints":
            metadata = {}
            hints = window.get_property("size-hints")
            for attr, metakey in [
                ("max_size", "size-constraint:maximum-size"),
                ("min_size", "size-constraint:minimum-size"),
                ("base_size", "size-constraint:base-size"),
                ("resize_inc", "size-constraint:increment"),
                ]:
                if getattr(hints, attr) is not None:
                    metadata[metakey] = getattr(hints, attr)
            if hints.min_aspect is not None:
                # Need a way to send doubles, or recover the original integer
                # fractional form.
                print "FIXME: ignoring aspect ratio constraint, things will likely break"
            return metadata
        else:
            assert False

    def _send_new_window_packet(self, window):
        id = self._window_to_id[window]
        (x, y, w, h) = self._desktop_manager.window_geometry(window)
        metadata = {}
        metadata.update(self._make_metadata(window, "title"))
        metadata.update(self._make_metadata(window, "size-hints"))
        self._protocol.queue_packet(["new-window", id, x, y, w, h, metadata])

    def _update_metadata(self, window, pspec):
        id = self._window_to_id[window]
        metadata = self._make_metadata(window, pspec.name)
        self._protocol.queue_packet(["window-metadata", id, metadata])

    def _lost_window(self, window, wm_exiting):
        id = self._window_to_id[window]
        self._protocol.queue_packet(["lost-window", id])
        del self._window_to_id[window]
        del self._id_to_window[id]

    def _redraw_needed(self, window, event):
        if self._desktop_manager.visible(window):
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

    def _process_map_window(self, packet):
        (_, id, x, y, width, height) = packet
        window = self._id_to_window[id]
        self._desktop_manager.show_window(window, x, y, width, height)
        self._send_draw_packet(window, 0, 0, width, height)

    def _process_unmap_window(self, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        self._desktop_manager.hide_window(window)

    def _process_move_window(self, packet):
        (_, id, x, y) = packet
        window = self._id_to_window[id]
        (_, _, w, h) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.show_window(window, x, y, w, h)

    def _process_resize_window(self, packet):
        (_, id, w, h) = packet
        window = self._id_to_window[id]
        (x, y, _, _) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.show_window(window, x, y, w, h)

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
        "map-window": _process_map_window,
        "unmap-window": _process_unmap_window,
        "move-window": _process_move_window,
        "resize-window": _process_resize_window,
        "window-order": _process_window_order,
        "close-window": _process_close_window,
        "mouse-position": _process_mouse_position,
        "button-event": _process_button_event,
        Protocol.CONNECTION_LOST: _process_connection_lost,
        }

    def process_packet(self, packet):
        packet_type = packet[0]
        self._packet_handlers[packet_type](self, packet)
