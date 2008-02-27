import gtk
import gobject
import cairo
import os
import os.path

from wimpiggy.util import one_arg_signal
from wimpiggy.prop import prop_get
from wimpiggy.keys import grok_modifier_map
from wimpiggy.lowlevel import add_event_receiver, remove_event_receiver

from xpra.protocol import Protocol, CAPABILITIES
from xpra.keys import mask_to_names

class ClientSource(object):
    def __init__(self, protocol):
        self._ordinary_packets = []
        self._mouse_position = None
        self._protocol = protocol
        self._protocol.source = self

    def queue_ordinary_packet(self, packet):
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def queue_positional_packet(self, packet):
        self.queue_ordinary_packet(packet)
        self._mouse_position = None

    def queue_mouse_position_packet(self, packet):
        self._mouse_position = packet
        self._protocol.source_has_more()

    def next_packet(self):
        if self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
            return packet, (bool(self._ordinary_packets)
                            or self._mouse_position is not None)
        elif self._mouse_position is not None:
            packet = self._mouse_position
            self._mouse_position = None
            return packet, False
        else:
            return None, False

class ClientWindow(gtk.Window):
    def __init__(self, client, id, x, y, w, h, metadata, override_redirect):
        if override_redirect:
            type = gtk.WINDOW_POPUP
        else:
            type = gtk.WINDOW_TOPLEVEL
        gtk.Window.__init__(self, type)
        self._client = client
        self._id = id
        self._pos = (-1, -1)
        self._size = (1, 1)
        self._backing = None
        self._metadata = {}
        self._override_redirect = override_redirect
        self._new_backing(w, h)
        self.update_metadata(metadata)
        
        self.set_app_paintable(True)
        self.add_events(gtk.gdk.STRUCTURE_MASK
                        | gtk.gdk.KEY_PRESS_MASK | gtk.gdk.KEY_RELEASE_MASK
                        | gtk.gdk.POINTER_MOTION_MASK
                        | gtk.gdk.BUTTON_PRESS_MASK
                        | gtk.gdk.BUTTON_RELEASE_MASK)

        self.move(x, y)
        self.set_default_size(w, h)

        self.connect("notify::has-toplevel-focus", self._focus_change)

    def update_metadata(self, metadata):
        self._metadata.update(metadata)
        
        self.set_title(u"%s (via xpra)"
                       % self._metadata.get("title",
                                            "<untitled window>"
                                            ).decode("utf-8"))

        if "size-constraints" in self._metadata:
            size_metadata = self._metadata["size-constraints"]
            hints = {}
            for (a, h1, h2) in [
                ("maximum-size", "max_width", "max_height"),
                ("minimum-size", "min_width", "min_height"),
                ("base-size", "base_width", "base_height"),
                ("increment", "width_inc", "height_inc"),
                ]:
                if a in self._metadata["size-constraints"]:
                    hints[h1], hints[h2] = size_metadata[a]
            for (a, h) in [
                ("minimum-aspect", "min_aspect_ratio"),
                ("maximum-aspect", "max_aspect_ratio"),
                ]:
                if a in self._metadata:
                    hints[h] = size_metadata[a][0] * 1.0 / size_metadata[a][1]
            self.set_geometry_hints(None, **hints)

    def _new_backing(self, w, h):
        old_backing = self._backing
        self._backing = gtk.gdk.Pixmap(gtk.gdk.get_default_root_window(),
                                       w, h)
        cr = self._backing.cairo_create()
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_pixmap(old_backing, 0, 0)
            cr.paint()
            old_w, old_h = old_backing.get_size()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def draw(self, x, y, width, height, rgb_data):
        assert len(rgb_data) == width * height * 3
        (my_width, my_height) = self.window.get_size()
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

    def _geometry(self):
        (x, y) = self.window.get_origin()
        (_, _, w, h, _) = self.window.get_geometry()
        return (x, y, w, h)

    def do_map_event(self, event):
        print "Got map event"
        gtk.Window.do_map_event(self, event)
        if not self._override_redirect:
            x, y, w, h = self._geometry()
            self._client.send(["map-window", self._id, x, y, w, h])
            self._pos = (x, y)
            self._size = (w, h)

    def do_configure_event(self, event):
        print "Got configure event"
        gtk.Window.do_configure_event(self, event)
        if not self._override_redirect:
            x, y, w, h = self._geometry()
            if (x, y) != self._pos:
                self._pos = (x, y)
                self._client.send(["move-window", self._id, x, y])
            if (w, h) != self._size:
                self._size = (w, h)
                self._client.send(["resize-window", self._id, w, h])
                self._new_backing(w, h)

    def move_resize(self, x, y, w, h):
        assert self._override_redirect
        self.window.move_resize(x, y, w, h)
        self._new_backing(w, h)

    def do_unmap_event(self, event):
        if not self._override_redirect:
            self._client.send(["unmap-window", self._id])

    def do_delete_event(self, event):
        self._client.send(["close-window", self._id])
        return True

    def _key_action(self, event, depressed):
        modifiers = self._client.mask_to_names(event.state)
        name = gtk.gdk.keyval_name(event.keyval)
        self._client.send(["key-action", self._id, name, depressed, modifiers])

    def do_key_press_event(self, event):
        self._key_action(event, True)

    def do_key_release_event(self, event):
        self._key_action(event, False)

    def _pointer_modifiers(self, event):
        pointer = (int(event.x_root), int(event.y_root))
        modifiers = self._client.mask_to_names(event.state)
        return pointer, modifiers

    def do_motion_notify_event(self, event):
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_mouse_position(["pointer-position", pointer,
                                          modifiers])
        
    def _button_action(self, event, depressed):
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_positional(["button-action", event.button,
                                      depressed, pointer, modifiers])

    def do_button_press_event(self, event):
        self._button_action(event, True)

    def do_button_release_event(self, event):
        self._button_action(event, False)

    def _focus_change(self, *args):
        self._client.update_focus(self._id,
                                  self.get_property("has-toplevel-focus"))

gobject.type_register(ClientWindow)

class XpraClient(gobject.GObject):
    __gsignals__ = {
        "wimpiggy-property-notify-event": one_arg_signal,
        }

    def __init__(self, sock):
        gobject.GObject.__init__(self)
        self._window_to_id = {}
        self._id_to_window = {}
        self._stacking = []

        if not gtk.gdk.net_wm_supports("_NET_CLIENT_LIST_STACKING"):
            assert False, "this program requires an EWMH-compliant window manager"

        root = gtk.gdk.get_default_root_window()
        root.set_events(root.get_events() | gtk.gdk.PROPERTY_NOTIFY)
        add_event_receiver(root, self)

        self._protocol = Protocol(sock, self.process_packet)
        ClientSource(self._protocol)
        self.send(["hello", list(CAPABILITIES)])

        self._keymap = gtk.gdk.keymap_get_default()
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

        self._focused = None

    def _keys_changed(self):
        self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default())

    def update_focus(self, id, gotit):
        if gotit and self._focused is not id:
            self.send(["focus", id])
            self._focused = id
        if not gotit and self._focused is id:
            self.send(["focus", 0])
            self._focused = None

    def mask_to_names(self, mask):
        return mask_to_names(mask, self._modifier_map)

    def send(self, packet):
        self._protocol.source.queue_ordinary_packet(packet)

    def send_positional(self, packet):
        self._protocol.source.queue_positional_packet(packet)

    def send_mouse_position(self, packet):
        self._protocol.source.queue_mouse_position_packet(packet)

    def do_wimpiggy_property_notify_event(self, event):
        root = gtk.gdk.get_default_root_window()
        assert event.window is root
        if str(event.atom) == "_NET_CLIENT_LIST_STACKING":
            print "_NET_CLIENT_LIST_STACKING changed"
            stacking = prop_get(root, "_NET_CLIENT_LIST_STACKING", ["window"])
            our_windows = dict([(w.window, id)
                                for (w, id) in self._window_to_id.iteritems()])
            if None in our_windows:
                del our_windows[None]
            our_stacking = [our_windows[win]
                            for win in stacking
                            if win in our_windows]
            if self._stacking != our_stacking and len(our_stacking) > 1:
                self.send(["window-order", our_stacking])
            self._stacking = our_stacking

    def _process_hello(self, packet):
        (_, capabilities) = packet
        if "deflate" in capabilities:
            self._protocol.enable_deflate()

    def _process_new_common(self, packet, override_redirect):
        (_, id, x, y, w, h, metadata) = packet
        window = ClientWindow(self, id, x, y, w, h, metadata,
                              override_redirect)
        self._id_to_window[id] = window
        self._window_to_id[window] = id
        window.show_all()

    def _process_new_window(self, packet):
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet):
        self._process_new_common(packet, True)

    def _process_draw(self, packet):
        (_, id, x, y, width, height, coding, data) = packet
        window = self._id_to_window[id]
        assert coding == "rgb24"
        window.draw(x, y, width, height, data)

    def _process_window_metadata(self, packet):
        (_, id, metadata) = packet
        window = self._id_to_window[id]
        window.update_metadata(metadata)

    def _process_override_redirect_order(self, packet):
        (_, order) = packet
        try:
            gtk.gdk.x11_grab_server()
            for id in order:
                window = self._id_to_window[id]
                window.window.raise_()
        finally:
            gtk.gdk.x11_ungrab_server()

    def _process_configure_override_redirect(self, packet):
        (_, id, x, y, w, h) = packet
        window = self._id_to_window[id]
        window.move_resize(x, y, w, h)

    def _process_lost_window(self, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        del self._id_to_window[id]
        del self._window_to_id[window]
        window.destroy()

    def _process_connection_lost(self, packet):
        print "Connection lost"
        gtk.main_quit()

    _packet_handlers = {
        "hello": _process_hello,
        "new-window": _process_new_window,
        "new-override-redirect": _process_new_override_redirect,
        "draw": _process_draw,
        "window-metadata": _process_window_metadata,
        "override-redirect-order": _process_override_redirect_order,
        "configure-override-redirect": _process_configure_override_redirect,
        "lost-window": _process_lost_window,
        Protocol.CONNECTION_LOST: _process_connection_lost,
        }
    
    def process_packet(self, proto, packet):
        packet_type = packet[0]
        self._packet_handlers[packet_type](self, packet)

gobject.type_register(XpraClient)
