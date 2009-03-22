# Todo:
#   cursors
#   copy/paste (dnd?)
#   xsync resize stuff
#   shape?
#   icons
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?

import gtk
import gobject
import cairo
import os
import os.path
import subprocess

from wimpiggy.wm import Wm
from wimpiggy.util import LameStruct, one_arg_signal, gtk_main_quit_really
from wimpiggy.lowlevel import (get_rectangle_from_region,
                               xtest_fake_key,
                               xtest_fake_button,
                               is_override_redirect, is_mapped,
                               add_event_receiver,
                               get_children)
from wimpiggy.window import OverrideRedirectWindowModel, Unmanageable
from wimpiggy.keys import grok_modifier_map
from wimpiggy.error import XError, trap

from wimpiggy.log import Logger
log = Logger()

import xpra
from xpra.protocol import Protocol
from xpra.keys import mask_to_names
from xpra.clipboard import ClipboardProtocolHelper

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

    def show_window(self, model):
        self._models[model].shown = True
        model.ownership_election()
        if model.get_property("iconic"):
            model.set_property("iconic", False)

    def configure_window(self, model, x, y, w, h):
        self._models[model].geom = (x, y, w, h)
        model.maybe_recalculate_geometry_for(self)

    def hide_window(self, model):
        if not model.get_property("iconic"):
            model.set_property("iconic", True)
        self._models[model].shown = False
        model.ownership_election()

    def visible(self, model):
        return self._models[model].shown

    def raise_window(self, model):
        if isinstance(model, OverrideRedirectWindowModel):
            model.get_property("client-window").raise_()
        else:
            window = self._models[model].window
            if window is not None:
                window.raise_()

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
            log.warn("Uh-oh, our size doesn't fit window sizing constraints!")
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
        log("damage %s (%s, %s, %s, %s)", id, x, y, w, h)
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
            # It's important to acknowledge changes *before* we extract them,
            # to avoid a race condition.
            window.acknowledge_changes(x, y, w, h)
            pixmap = window.get_property("client-contents")
            if pixmap is None:
                log.error("wtf, pixmap is None?")
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
        # Just in case we somehow end up with damage larger than the pixmap,
        # we don't want to start requesting random chunks of memory (this
        # could happen if a window is resized but we don't throw away our
        # existing damage map):
        assert x >= 0
        assert y >= 0
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

class XpraServer(gobject.GObject):
    __gsignals__ = {
        "wimpiggy-child-map-event": one_arg_signal,
        }

    def __init__(self, clobber, sockets):
        gobject.GObject.__init__(self)
        
        # Do this before creating the Wm object, to avoid clobbering its
        # selecting SubstructureRedirect.
        root = gtk.gdk.get_default_root_window()
        root.set_events(root.get_events() | gtk.gdk.SUBSTRUCTURE_MASK)
        add_event_receiver(root, self)

        ### Create the WM object
        self._wm = Wm("Xpra", clobber)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("quit", lambda _: self.quit(True))

        ### Create our window managing data structures:
        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        ### Load in existing windows:
        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        for window in get_children(root):
            if (is_override_redirect(window) and is_mapped(window)):
                self._add_new_or_window(window)

        ### Set up keymap:
        self._keymap = gtk.gdk.keymap_get_default()
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

        try:
            xmodmap = subprocess.Popen(["xmodmap", "-"], stdin=subprocess.PIPE)
        except OSError, e:
            sys.stderr.write("Error running xmodmap: %s\n" % (e,))
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
                            """
                            # Really stupid hack to force backspace to work.
                            # Remove this once we have real keymap support.
                            + "keycode any = BackSpace")
        self._keyname_for_mod = {
            "shift": "Shift_L",
            "control": "Control_L",
            "meta": "Meta_L",
            "super": "Super_L",
            "hyper": "Hyper_L",
            "alt": "Alt_L",
            }

        ### Clipboard handling:
        self._clipboard_helper = ClipboardProtocolHelper(self._send)

        ### Misc. state:
        self._has_focus = 0
        self._upgrading = False

        ### All right, we're ready to accept customers:
        self._protocol = None
        self._potential_protocols = []
        for sock in sockets:
            self.add_listen_socket(sock)

    def add_listen_socket(self, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def quit(self, upgrading):
        self._upgrading = upgrading
        gtk_main_quit_really()

    def run(self):
        gtk.main()
        return self._upgrading

    def _new_connection(self, listener, *args):
        log.info("New connection received")
        sock, addr = listener.accept()
        self._potential_protocols.append(Protocol(sock, self.process_packet))
        return True

    def _keys_changed(self, *args):
        self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default())

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def do_wimpiggy_child_map_event(self, event):
        raw_window = event.window
        if event.override_redirect:
            self._add_new_or_window(raw_window)

    _window_export_properties = ("title", "size-hints")

    def _add_new_window_common(self, window):
        id = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = id
        self._id_to_window[id] = window
        window.connect("client-contents-changed", self._contents_changed)
        window.connect("unmanaged", self._lost_window)

    def _add_new_window(self, window):
        self._add_new_window_common(window)
        for prop in self._window_export_properties:
            window.connect("notify::%s" % prop, self._update_metadata)
        (x, y, w, h, depth) = window.get_property("client-window").get_geometry()
        self._desktop_manager.add_window(window, x, y, w, h)
        self._send_new_window_packet(window)

    def _add_new_or_window(self, raw_window):
        try:
            window = OverrideRedirectWindowModel(raw_window)
        except Unmanageable, e:
            return
        self._add_new_window_common(window)
        window.connect("notify::geometry", self._or_window_geometry_changed)
        self._send_new_or_window_packet(window)

    def _or_window_geometry_changed(self, window, pspec):
        (x, y, w, h) = window.get_property("geometry")
        id = self._window_to_id[window]
        self._send(["configure-override-redirect", id, x, y, w, h])

    _all_metadata = ("title", "size-hints", "class-instance", "icon")

    def _make_metadata(self, window, propname):
        assert propname in self._all_metadata
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
                if hints is not None and getattr(hints, attr) is not None:
                    hints_metadata[metakey] = getattr(hints, attr)
            return {"size-constraints": hints_metadata}
        elif propname == "class-instance":
            c_i = window.get_property("class-instance")
            if c_i is not None:
                return {"class-instance": [x.encode("utf-8") for x in c_i]}
            else:
                return {}
        elif propname == "icon":
            surf = window.get_property("icon")
            if surf is not None:
                assert surf.get_format() == cairo.FORMAT_ARGB32
                assert surf.get_stride() == 4 * surf.get_width()
                return {"icon": (surf.get_width(), surf.get_height(),
                                 "premult_argb32", str(surf.get_data()))
                        }
            else:
                return {}
        else:
            assert False

    def _keycode(self, keyname):
        keyval = gtk.gdk.keyval_from_name(keyname)
        return self._keymap.get_entries_for_keyval(keyval)[0][0]

    def _make_keymask_match(self, modifier_list):
        (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
        current = set(mask_to_names(current_mask, self._modifier_map))
        wanted = set(modifier_list)
        log.debug("current mask: %s, wanted: %s", current, wanted)
        for modifier in current.difference(wanted):
            keyname = self._keyname_for_mod[modifier]
            log.debug("unpressing %s", keyname)
            xtest_fake_key(gtk.gdk.display_get_default(),
                           self._keycode(keyname),
                           False)
        for modifier in wanted.difference(current):
            keyname = self._keyname_for_mod[modifier]
            log.debug("pressing %s", keyname)
            xtest_fake_key(gtk.gdk.display_get_default(),
                           self._keycode(keyname),
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
        for propname in self._all_metadata:
            metadata.update(self._make_metadata(window, propname))
        self._send(["new-window", id, x, y, w, h, metadata])

    def _send_new_or_window_packet(self, window):
        id = self._window_to_id[window]
        (x, y, w, h) = window.get_property("geometry")
        self._send(["new-override-redirect", id, x, y, w, h, {}])
        self._damage(window, 0, 0, w, h)

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

    def _contents_changed(self, window, event):
        if (isinstance(window, OverrideRedirectWindowModel)
            or self._desktop_manager.visible(window)):
            self._damage(window, event.x, event.y, event.width, event.height)

    def _calculate_capabilities(self, client_capabilities):
        capabilities = {}
        for cap in ("deflate", "__prerelease_version"):
            if cap in client_capabilities:
                capabilities[cap] = client_capabilities[cap]
        return capabilities

    def _process_hello(self, proto, packet):
        (_, client_capabilities) = packet
        log.info("Handshake complete; enabling connection")
        capabilities = self._calculate_capabilities(client_capabilities)
        if capabilities.get("__prerelease_version") != xpra.__version__:
            log.error("Sorry, this pre-release server only works with clients "
                      + "of exactly the same version (v%s)", xpra.__version__)
            proto.close()
            return
        # Okay, things are okay, so let's boot out any existing connection and
        # set this as our new one:
        if self._protocol is not None:
            self._protocol.close()
        self._protocol = proto
        ServerSource(self._protocol)
        self._send(["hello", capabilities])
        if "deflate" in capabilities:
            self._protocol.enable_deflate(capabilities["deflate"])
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        for id in sorted(self._id_to_window.iterkeys()):
            window = self._id_to_window[id]
            if isinstance(window, OverrideRedirectWindowModel):
                self._send_new_or_window_packet(window)
            else:
                self._desktop_manager.hide_window(window)
                self._send_new_window_packet(window)

    def _process_map_window(self, proto, packet):
        (_, id, x, y, width, height) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._desktop_manager.configure_window(window, x, y, width, height)
        self._desktop_manager.show_window(window)
        self._damage(window, 0, 0, width, height)

    def _process_unmap_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._desktop_manager.hide_window(window)
        self._cancel_damage(window)

    def _process_move_window(self, proto, packet):
        (_, id, x, y) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        (_, _, w, h) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)

    def _process_resize_window(self, proto, packet):
        (_, id, w, h) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._cancel_damage(window)
        if self._desktop_manager.visible(window):
            self._damage(window, 0, 0, w, h)
        (x, y, _, _) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)

    def _process_focus(self, proto, packet):
        (_, id) = packet
        self._focus(id)

    def _process_key_action(self, proto, packet):
        (_, id, keyname, depressed, modifiers) = packet
        self._make_keymask_match(modifiers)
        self._focus(id)
        log.debug("now %spressing key %s", depressed, keyname)
        xtest_fake_key(gtk.gdk.display_get_default(),
                       self._keycode(keyname), depressed)

    def _process_button_action(self, proto, packet):
        (_, id, button, depressed, pointer, modifiers) = packet
        self._make_keymask_match(modifiers)
        self._desktop_manager.raise_window(self._id_to_window[id])
        self._move_pointer(pointer)
        try:
            trap.call_unsynced(xtest_fake_button,
                               gtk.gdk.display_get_default(),
                               button, depressed)
        except XError, e:
            log.warn("Failed to pass on (un)press of mouse button %s"
                     + " (perhaps your Xvfb does not support mousewheels?)",
                     button)

    def _process_pointer_position(self, proto, packet):
        (_, id, pointer, modifiers) = packet
        self._make_keymask_match(modifiers)
        self._desktop_manager.raise_window(self._id_to_window[id])
        self._move_pointer(pointer)

    def _process_close_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        window.request_close()

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        proto.close()
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        if proto is self._protocol:
            self._protocol = None

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        self.quit(False)

    _packet_handlers = {
        "hello": _process_hello,
        "map-window": _process_map_window,
        "unmap-window": _process_unmap_window,
        "move-window": _process_move_window,
        "resize-window": _process_resize_window,
        "focus": _process_focus,
        "key-action": _process_key_action,
        "button-action": _process_button_action,
        "pointer-position": _process_pointer_position,
        "close-window": _process_close_window,
        "shutdown-server": _process_shutdown_server,
        # "clipboard-*" packets are handled below:
        Protocol.CONNECTION_LOST: _process_connection_lost,
        }

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        if (isinstance(packet_type, str)
            and packet_type.startswith("clipboard-")):
            self._clipboard_helper.process_clipboard_packet(packet)
        else:
            self._packet_handlers[packet_type](self, proto, packet)

gobject.type_register(XpraServer)
