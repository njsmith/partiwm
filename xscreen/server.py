# Todo:
#   override-redirect windows
#   cursors
#   copy/paste (dnd?)
#   xsync resize stuff
#   icons
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?
# kill base()
# use gtk.gdk.Window.get_pointer()

import gtk
import gobject
import os
import os.path
import socket
import subprocess

from wimpiggy.wm import Wm
from wimpiggy.util import LameStruct
from wimpiggy.lowlevel import (get_rectangle_from_region,
                               get_current_keyboard_mask,
                               xtest_fake_key,
                               xtest_fake_button)
from wimpiggy.keys import grok_modifier_map

from xscreen.address import server_sock
from xscreen.protocol import Protocol, CAPABILITIES
from xscreen.keys import mask_to_names

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

class ServerSource(object):
    # Strategy: if we have ordinary packets to send, send those.  When we
    # don't, then send window updates.
    def __init__(self, protocol):
        self._ordinary_packets = []
        self._protocol = protocol
        self._damage = {}
        protocol.source = self
        if self._have_more():
            protocol.source_has_more()

    def _have_more(self):
        return bool(self._ordinary_packets) or bool(self._damage)

    def queue_ordinary_packet(self, packet):
        assert self._protocol
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def cancel_damage(self, id):
        if id in self._damage:
            del self._damage[id]
        
    def damage(self, id, window, x, y, w, h):
        window, region = self._damage.setdefault(id,
                                                 (window, gtk.gdk.Region()))
        region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
        self._protocol.source_has_more()

    def next_packet(self):
        if self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        elif self._damage:
            id, (window, damage) = self._damage.items()[0]
            (x, y, w, h) = get_rectangle_from_region(damage)
            rect = gtk.gdk.Rectangle(x, y, w, h)
            damage.subtract(gtk.gdk.region_rectangle(rect))
            if damage.empty():
                del self._damage[id]
            pixmap = window.get_property("client-contents")
            if pixmap is None:
                packet = None
            else:
                (x2, y2, w2, h2, data) = self._get_rgb_data(pixmap, x, y, w, h)
                if not w2 or not h2:
                    packet = None
                else:
                    packet = ["draw", id, x2, y2, w2, h2, "rgb24", data]
        else:
            packet = None
        return packet, self._have_more()

    def _get_rgb_data(self, pixmap, x, y, width, height):
        pixmap_w, pixmap_h = pixmap.get_size()
        if x + width > pixmap_w:
            width = pixmap_w - x
        if y + height > pixmap_h:
            height = pixmap_h - y
        if width <= 0 or height <= 0:
            return (0, 0, 0, 0, "")
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
        return (x, y, width, height, data)

class XScreenServer(object):
    def __init__(self, socketpath, clobber):
        self._wm = Wm("XScreen", clobber)
        self._wm.connect("focus-got-dropped", self._focus_dropped)
        self._wm.connect("new-window", self._new_window_signaled)

        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        self._protocol = None
        self._maybe_protocols = []

        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        self._socketpath = socketpath
        self._listener = socket.socket(socket.AF_UNIX)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        print self._socketpath
        self._listener.bind(self._socketpath)
        self._listener.listen(5)
        gobject.io_add_watch(self._listener, gobject.IO_IN,
                             self._new_connection)

        self._keymap = gtk.gdk.keymap_get_default()
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

        xmodmap = subprocess.Popen(["xmodmap", "-"], stdin=subprocess.PIPE)
        xmodmap.communicate("""clear Lock
                               clear Shift
                               clear Control
                               clear Mod1
                               clear Mod2
                               clear Mod3
                               clear Mod4
                               clear Mod5
                               keycode any = Shift_L
                               keycode any = Control_L
                               keycode any = Meta_L
                               keycode any = Alt_L
                               keycode any = Hyper_L
                               keycode any = Super_L
                               add Shift = Shift_L Shift_R
                               add Control = Control_L Control_R
                               add Mod1 = Meta_L Meta_R
                               add Mod2 = Alt_L Alt_R
                               add Mod3 = Hyper_L Hyper_R
                               add Mod4 = Super_L Super_R
                            """)
        self._keyname_for_mod = {
            "shift": "Shift_L",
            "control": "Control_L",
            "meta": "Meta_L",
            "super": "Super_L",
            "hyper": "Hyper_L",
            "alt": "Alt_L",
            }

        self._has_focus = 0

    def _new_connection(self, *args):
        print "New connection received"
        sock, addr = self._listener.accept()
        self._maybe_protocols.append(Protocol(sock, self.process_packet))
        return True

    def _keys_changed(self, *args):
        self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default())

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
            hints_metadata = {}
            hints = window.get_property("size-hints")
            for attr, metakey in [
                ("max_size", "maximum-size"),
                ("min_size", "minimum-size"),
                ("base_size", "base-size"),
                ("resize_inc", "increment"),
                ("min_aspect_ratio", "minimum-aspect"),
                ("max_aspect_ratio", "maximum-aspect"),
                ]:
                if getattr(hints, attr) is not None:
                    hints_metadata[metakey] = getattr(hints, attr)
            return {"size-constraints": hints_metadata}
        else:
            assert False

    def _keycode(self, keyname):
        keyval = gtk.gdk.keyval_from_name(keyname)
        return self._keymap.get_entries_for_keyval(keyval)[0][0]

    def _make_keymask_match(self, modifier_list):
        current_mask = get_current_keyboard_mask(gtk.gdk.display_get_default())
        current = set(mask_to_names(current_mask, self._modifier_map))
        wanted = set(modifier_list)
        for modifier in current.difference(wanted):
            xtest_fake_key(gtk.gdk.display_get_default(),
                           self._keycode(self._keyname_for_mod[modifier]),
                           False)
        for modifier in wanted.difference(current):
            xtest_fake_key(gtk.gdk.display_get_default(),
                           self._keycode(self._keyname_for_mod[modifier]),
                           True)

    def _focus(self, id):
        if self._has_focus != id:
            if id == 0:
                # FIXME: kind of a hack:
                self._wm.get_property("toplevel").reset_x_focus()
            else:
                window = self._id_to_window[id]
                window.give_client_focus()
            self._has_focus = id

    def _move_pointer(self, pos):
        (x, y) = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _send(self, packet):
        if self._protocol is not None:
            self._protocol.source.queue_ordinary_packet(packet)

    def _damage(self, window, x, y, width, height):
        if self._protocol is not None and self._protocol.source is not None:
            id = self._window_to_id[window]
            self._protocol.source.damage(id, window, x, y, width, height)
        
    def _cancel_damage(self, window):
        if self._protocol is not None and self._protocol.source is not None:
            id = self._window_to_id[window]
            self._protocol.source.cancel_damage(id)
            
    def _send_new_window_packet(self, window):
        id = self._window_to_id[window]
        (x, y, w, h) = self._desktop_manager.window_geometry(window)
        metadata = {}
        metadata.update(self._make_metadata(window, "title"))
        metadata.update(self._make_metadata(window, "size-hints"))
        self._send(["new-window", id, x, y, w, h, metadata])

    def _update_metadata(self, window, pspec):
        id = self._window_to_id[window]
        metadata = self._make_metadata(window, pspec.name)
        self._send(["window-metadata", id, metadata])

    def _lost_window(self, window, wm_exiting):
        id = self._window_to_id[window]
        self._send(["lost-window", id])
        self._cancel_damage(window)
        del self._window_to_id[window]
        del self._id_to_window[id]

    def _redraw_needed(self, window, event):
        if self._desktop_manager.visible(window):
            self._damage(window, event.x, event.y, event.width, event.height)

    def _process_hello(self, proto, packet):
        print "Handshake complete; enabling connection"
        # Drop any existing protocol
        if self._protocol is not None:
            self._protocol.close()
        self._protocol = proto
        ServerSource(self._protocol)
        client_capabilities = set(packet[1])
        capabilities = CAPABILITIES.intersection(client_capabilities)
        self._send(["hello", list(capabilities)])
        if "deflate" in capabilities:
            self._protocol.enable_deflate()
        for window in self._window_to_id.keys():
            self._desktop_manager.hide_window(window)
            self._send_new_window_packet(window)

    def _process_map_window(self, proto, packet):
        (_, id, x, y, width, height) = packet
        window = self._id_to_window[id]
        self._desktop_manager.show_window(window, x, y, width, height)
        self._damage(window, 0, 0, width, height)

    def _process_unmap_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        self._desktop_manager.hide_window(window)
        self._cancel_damage(window)

    def _process_move_window(self, proto, packet):
        (_, id, x, y) = packet
        window = self._id_to_window[id]
        (_, _, w, h) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.show_window(window, x, y, w, h)

    def _process_resize_window(self, proto, packet):
        (_, id, w, h) = packet
        window = self._id_to_window[id]
        self._cancel_damage(window)
        self._damage(window, 0, 0, w, h)
        (x, y, _, _) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.show_window(window, x, y, w, h)

    def _process_window_order(self, proto, packet):
        (_, ids_bottom_to_top) = packet
        windows_bottom_to_top = [self._id_to_window[id]
                                 for id in ids_bottom_to_top]
        self._desktop_manager.reorder_windows(windows_bottom_to_top)

    def _process_focus(self, proto, packet):
        (_, id) = packet
        self._focus(id)

    def _process_key_action(self, proto, packet):
        (_, id, keyname, depressed, modifiers) = packet
        self._make_keymask_match(modifiers)
        self._focus(id)
        xtest_fake_key(gtk.gdk.display_get_default(),
                       self._keycode(keyname), depressed)

    def _process_button_action(self, proto, packet):
        (_, button, depressed, pointer, modifiers) = packet
        self._make_keymask_match(modifiers)
        self._move_pointer(pointer)
        xtest_fake_button(gtk.gdk.display_get_default(), button, depressed)

    def _process_pointer_position(self, proto, packet):
        (_, pointer, modifiers) = packet
        self._make_keymask_match(modifiers)
        self._move_pointer(pointer)

    def _process_close_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        window.request_close()

    def _process_connection_lost(self, proto, packet):
        print "Connection lost"
        proto.close()
        if proto in self._maybe_protocols:
            self._maybe_protocols.remove(proto)
        if proto is self._protocol:
            self._protocol = None

    def _process_shutdown_server(self, proto, packet):
        print "Shutting down in response to request"
        gtk.main_quit()

    _packet_handlers = {
        "hello": _process_hello,
        "map-window": _process_map_window,
        "unmap-window": _process_unmap_window,
        "move-window": _process_move_window,
        "resize-window": _process_resize_window,
        "window-order": _process_window_order,
        "focus": _process_focus,
        "key-action": _process_key_action,
        "button-action": _process_button_action,
        "pointer-position": _process_pointer_position,
        "close-window": _process_close_window,
        "shutdown-server": _process_shutdown_server,
        Protocol.CONNECTION_LOST: _process_connection_lost,
        }

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        self._packet_handlers[packet_type](self, proto, packet)
