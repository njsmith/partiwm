"""The magic GTK widget that represents a client window.

Most of the gunk required to be a valid window manager (reparenting, synthetic
events, mucking about with properties, etc. etc.) is wrapped up in here."""

import sets
import gobject
import gtk
import gtk.gdk
import cairo
import math
import parti.lowlevel
from parti.util import AutoPropGObjectMixin, base
from parti.error import *
from parti.prop import prop_get, prop_set

# Things to worry about:
# 
# Map
# Withdraw
# Store properties for everyone else
#   title (WM_NAME, _NET_WM_NAME, WM_ICON_NAME, _NET_WM_ICON_NAME)
#   WM_NORMAL_HINTS: flags, max_width/height, width/height_inc, max_aspect,
#     base_width/height, gravity
#   WM_HINTS: flags, input model, initial_state, icon_pixmap, icon_window,
#       icon_x, icon_y, icon_mask
#   WM_CLASS: can be ignored, except plugins or whatever might want to peek at
#   WM_TRANSIENT_FOR
#   WM_PROTOCOLS -- WM_TAKE_FOCUS (I don't understand focus yet),
#       definitely WM_DELETE_WINDOW
#   _NET_WM_WINDOW_TYPE
#   _NET_WM_STATE (modal, demands attention, hidden, fullscreen, etc.)
#   _NET_WM_STRUT, _NET_WM_STRUT_PARTIAL <-- MUST watch for property changes
#       on window
#       (should do this for urgency anyway)
#   _NET_WM_ICON, a collection of images (how is this different from WM_HINTS
#       icons?  these are ARGB, of course.)
#   _NET_WM_PID, WM_CLIENT_MACHINE
#   maybe _NET_WM_USER_TIME (_NET_WM_USER_TIME_WINDOW)
#   colormap handling: ICCCM 4.1.8 requires it, but I don't care.
# There are two sorts of urgency, _NET_WM_STATE_DEMANDS_ATTENTION in
#   _NET_WM_STATE, and a bit in WM_HINTS...
# Update properties:
#   WM_STATE
#   _NET_WM_VISIBLE_NAME, _NET_WM_VISIBLE_ICON_NAME: these are only required
#     if displaying something different than requested
#   _NET_WM_DESKTOP -- supposed to be updated at all times, sigh...
#   _NET_WM_STATE
#   _NET_WM_ALLOWED_ACTIONS
#   _NET_FRAME_EXTENTS

# Todo:
#   client focus hints
#   struts
#   icons

# Okay, we need a block comment to explain the window arrangement that this
# file is working with.
#
#                +--------+
#                | widget |
#                +--------+
#                  /    \
#  <- top         /     -\-        bottom ->
#                /        \
#          +-------+   +---------+
#          | image |   | expose  |
#          +-------+   | catcher |
#                      +---------+
#                           |
#                      +---------+
#                      | corral  |
#                      +---------+
#                           |
#                      +---------+
#                      | client  |
#                      +---------+
#
# Each box in this diagram represents one X/GDK window.  In the common case,
# every window here takes up exactly the same space on the screen (!).  In
# fact, the three windows on the right *always* have exactly the same size and
# location, and the window on the left and the top window also always have
# exactly the same size and position.  However, each window in the diagram
# plays a subtly different role.
#
# The client window is obvious -- this is the window owned by the client,
# which they created and which we have various ICCCM/EWMH-mandated
# responsibilities towards.
#
# The purpose of the 'corral' is to keep the client window maintained -- we
# select for SubstructureRedirect on it, so that the client cannot resize
# etc. without going through the WM.  The corral is also the window that is
# composited (i.e., gdk_window_set_composited is called on it).  One might
# think that one could just make the client composited, and indeed, this would
# work fine in theory, but gtk bug #491309 means that compositing only works
# properly on GDK windows of type GDK_WINDOW_CHILD, and the client window is a
# GDK_WINDOW_FOREIGN.  (This also has the advantage that we can access the
# composited contents of the client window without worrying about it
# disappearing unexpectedly and causing an X error -- one could also use
# the NameWindowPixmap operation in the Composite extension for the same
# thing, but this lets us skip that.
#
# The way GDK's compositing API works, the parent window of a composited
# window is the one that receives information about drawing into the
# composited window.  Since the corral is composited, it needs a parent to
# recieve these events; this is the purpose of the 'expose catcher'.
#
# These first three windows are always managed together, as a unit; an
# invariant of the code is that they always take up exactly the same space on
# the screen.  They get reparented back and forth between widgets, and when
# there are no widgets, they get reparented to a "parking area".  For now,
# we're just using the root window as a parking area, so we also map/unmap the
# expose window depending on whether we are parked or not; the corral and
# client windows are left mapped at all times.
#
# When a particular WindowView controls the underlying client window, then two
# things happen:
#   -- Its size determines the size of the client window.  Ideally they are
#      the same size -- but this is not always the case, because the client
#      may have specified sizing constraints, in which case the client window
#      is the "best fit" to the controlling widget window.
#   -- The stack of client windows is reparented under the widget window, as
#      in the diagram above.  This is necessary to allow mouse events to work
#      -- a WindowView widget can always *look* like the client window is
#      there, through the magic of Composite, but in order for it to *act*
#      like the client window is there in terms of receiving mouse events, it
#      has to actually be there.
#
# Finally, there is the 'image' window.  This is a window that always remains
# in the widget window, and is used to draw what the client currently looks
# like.  It needs to receive endogenous expose events so it knows if it has
# been literally exposed (not just when the window it is displaying has
# changed), and the easiest way to arrange for this is to make it exactly the
# same size as the parent 'widget' window.  Then the widget window never
# receives expose events (because it is occluded), and we can arrange for the
# image window's expose events to be delivered to the WindowView widget, and
# they will be in the right coordinate space.  If the widget is controlling
# the client, then the image window goes on top of the client window.  Why
# don't we just draw onto the widget window?  Because there is no way to ask
# Cairo to use IncludeInferiors drawing mode -- so if we were drawing onto the
# widget window, and the client were present in the widget window, then the
# blank black 'expose catcher' window would obscure the image of the client.
#
# All clear?

class Unmanageable(Exception):
    pass

class _ExposeListenerWidget(gtk.Widget):
    # GTK wants to route events from GdkWindows to GtkWidgets.  We need to
    # receive events (esp. synthetic GDK expose events) on the "corral" window
    # that our client has been reparented into.  Therefore we need to attach a
    # widget to that window, even though that widget will not really go
    # anywhere in the widget hierarchy; it is just a placeholder to receive
    # events.

    def __init__(self, window, recipient):
        base(self).__init__(self)
        self.set_flags(gtk.REALIZED)
        self.recipient = recipient
        self.window = window
        self.window.set_user_data(self)

    def do_expose_event(self, event):
        print "synthetic damage-based expose event!"
        self.recipient._handle_damage(event)

    def do_destroy(self):
        self.window.set_user_data(None)
        self.window = None
        self.recipient = None
        gtk.Widget.do_destroy(self)

gobject.type_register(_ExposeListenerWidget)

class WindowModel(AutoPropGObjectMixin, gobject.GObject):
    """This represents a managed client window.  It allows one to produce
    widgets that view that client window in various ways."""

    _NET_WM_ALLOWED_ACTIONS = [
        "_NET_WM_ACTION_CLOSE",
        ]

    __gproperties__ = {
        # Interesting properties of the client window, that will be
        # automatically kept up to date:
        "attention-requested": (gobject.TYPE_BOOLEAN,
                                "Urgency hint from client, or us", "",
                                False,
                                gobject.PARAM_READWRITE),
        "fullscreen": (gobject.TYPE_BOOLEAN,
                       "Fullscreen-ness of window", "",
                       False,
                       gobject.PARAM_READWRITE),

        "client-window": (gobject.TYPE_PYOBJECT,
                          "GdkWindow representing the client toplevel", "",
                          gobject.PARAM_READABLE),
        "actual-size": (gobject.TYPE_PYOBJECT,
                        "Size of client window (actual (width,height))", "",
                        gobject.PARAM_READABLE),
        "user-friendly-size": (gobject.TYPE_PYOBJECT,
                               "Description of client window size for user", "",
                               gobject.PARAM_READABLE),
        "requested-position": (gobject.TYPE_PYOBJECT,
                               "Client-requested position on screen", "",
                               gobject.PARAM_READABLE),
        "requested-size": (gobject.TYPE_PYOBJECT,
                           "Client-requested size on screen", "",
                           gobject.PARAM_READABLE),
        "size-hints": (gobject.TYPE_PYOBJECT,
                       "Client hints on constraining its size", "",
                       gobject.PARAM_READABLE),
        "strut": (gobject.TYPE_PYOBJECT,
                  "Struts requested by window, or None", "",
                  gobject.PARAM_READABLE),
        "class": (gobject.TYPE_STRING,
                  "Classic X 'class'", "",
                  "",
                  gobject.PARAM_READABLE),
        "instance": (gobject.TYPE_STRING,
                     "Classic X 'instance'", "",
                     "",
                     gobject.PARAM_READABLE),
        "transient-for": (gobject.TYPE_PYOBJECT,
                          "Transient for (or None)", "",
                          gobject.PARAM_READABLE),
        "protocols": (gobject.TYPE_PYOBJECT,
                      "Supported WM protocols", "",
                      gobject.PARAM_READABLE),
        "window-type": (gobject.TYPE_PYOBJECT,
                        "Window type",
                        "NB, most preferred comes first, then fallbacks",
                        gobject.PARAM_READABLE),
        "pid": (gobject.TYPE_INT,
                "PID of owning process", "",
                -1, 65535, -1,
                gobject.PARAM_READABLE),
        "client-machine": (gobject.TYPE_PYOBJECT,
                           "Host where client process is running", "",
                           gobject.PARAM_READABLE),
        "group-leader": (gobject.TYPE_PYOBJECT,
                         "Window group leader (opaque identifier)", "",
                         gobject.PARAM_READABLE),
        "iconic": (gobject.TYPE_BOOLEAN,
                   "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
                   False,
                   gobject.PARAM_READABLE),
        "state": (gobject.TYPE_PYOBJECT,
                  "State, as per _NET_WM_STATE", "",
                  gobject.PARAM_READABLE),
        "title": (gobject.TYPE_PYOBJECT,
                  "Window title (unicode or None)", "",
                  gobject.PARAM_READABLE),
        "icon-title": (gobject.TYPE_PYOBJECT,
                       "Icon title (unicode or None)", "",
                       gobject.PARAM_READABLE),
        "icon": (gobject.TYPE_PYOBJECT,
                 "Icon (Cairo surface)", "",
                 gobject.PARAM_READABLE),
        }
    __gsignals__ = {
        "client-unmap-event": (gobject.SIGNAL_RUN_LAST,
                               # Actually gets a GdkEventMumble
                               gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "client-destroy-event": (gobject.SIGNAL_RUN_LAST,
                                 # Actually gets a GdkEventOwnerChange
                                 gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "client-property-notify-event": (gobject.SIGNAL_RUN_LAST,
                                         # Actually gets a GdkEventProperty
                                         gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "managed": (gobject.SIGNAL_RUN_LAST,
                   gobject.TYPE_NONE, ()),
        "unmanaged": (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE, ()),
        }
        
    def __init__(self, parking_window, client_window, start_trays):
        """Register a new client window with the WM.

        Raises an Unmanageable exception if this window should not be
        managed, for whatever reason.  ATM, this mostly means that the window
        died somehow before we could do anything with it."""

        parti.lowlevel.printFocus(client_window)

        super(WindowModel, self).__init__()
        self.parking_window = parking_window
        self.client_window = client_window
        self._internal_set_property("client-window", client_window)

        # We count how many times we have asked that the child be unmapped, so
        # that when the server tells us that the child has been unmapped, we
        # can make a reasonable guess as to whether we were the ones who did
        # it or not.
        # FIXME: It is possible to do better than this by using Xlib's
        # NextRequest function to find out what sequence number is assigned to
        # our UnmapWindow request, and then ignoring UnmapNotify events that
        # have a matching sequence number.  However, this only really matters
        # for supporting ICCCM-noncompliant clients that withdraw their
        # windows without sending a synthetic UnmapNotify (4.1.4), and
        # metacity gets away with doing things this way, so I'm not going to
        # worry about it too much...
        self.pending_unmaps = 0

        self.connect("notify::iconic", self._handle_iconic_update)

        self.views = set()
        self.controlling_view = None

        # We enable PROPERTY_CHANGE_MASK so that we can call
        # x11_get_server_time on this window.
        self.expose_window = gtk.gdk.Window(self.parking_window,
                                            width=100,
                                            height=100,
                                            window_type=gtk.gdk.WINDOW_CHILD,
                                            wclass=gtk.gdk.INPUT_OUTPUT,
                                            event_mask=gtk.gdk.PROPERTY_CHANGE_MASK
                                                     | gtk.gdk.EXPOSURE_MASK)
        self.expose_listener = _ExposeListenerWidget(self.expose_window,
                                                     self)

        self.corral_window = gtk.gdk.Window(self.expose_window,
                                            width=100,
                                            height=100,
                                            window_type=gtk.gdk.WINDOW_CHILD,
                                            wclass=gtk.gdk.INPUT_OUTPUT,
                                            event_mask=0)
        parti.lowlevel.substructureRedirect(self.corral_window,
                                            None, # FIXME: surely we need
                                            #       MapRequest handling?
                                            self._handle_configure_request)
        self.corral_window.set_composited(True)
        self.corral_window.show_unraised()

        def setup_client():
            # Start listening for important property changes
            self.client_window.set_events(self.client_window.get_events()
                                          | gtk.gdk.STRUCTURE_MASK
                                          | gtk.gdk.PROPERTY_CHANGE_MASK)

            # The child might already be mapped, in case we inherited it from
            # a previous window manager.  If so, we unmap it now, for
            # consistency (otherwise we'd get an unmap event later when we
            # reparent and confuse ourselves).
            if self.client_window.is_visible():
                self.client_window.hide()
                self.pending_unmaps += 1
            
            # Process properties
            self._read_initial_properties()
            self._write_initial_properties_and_setup()

            # For now, we never use the Iconic state at all.
            self._internal_set_property("iconic", False)

            parti.lowlevel.XAddToSaveSet(self.client_window)
            self.client_window.reparent(self.corral_window, 0, 0)
            client_size = self.client_window.get_geometry()[2:4]
            self.corral_window.resize(*client_size)
            self.expose_window.resize(*client_size)
            self.client_window.show_unraised()
        try:
            trap.call(setup_client)
        except XError, e:
            raise Unmanageable, e

        assert start_trays
        for tray in start_trays:
            tray.add(self)

    def do_client_unmap_event(self, event):
        # The client window got unmapped.  The question is, though, was that
        # because it was withdrawn/destroyed, or was it because we unmapped it
        # going into IconicState?
        #
        # We are careful to count how many outstanding unmap requests we have
        # out, so that is one clue.  However, if we receive a *synthetic*
        # UnmapNotify event, that always means that the client has withdrawn
        # it (even if it was not mapped in the first place) -- ICCCM section
        # 4.1.4.
        print ("Client window unmapped: send_event=%s, pending_unmaps=%s"
               % (event.send_event, self.pending_unmaps))
        assert self.pending_unmaps >= 0
        if event.send_event or self.pending_unmaps == 0:
            self.unmanage_window()
        else:
            self.pending_unmaps -= 1

    def do_client_destroy_event(self, event):
        # This is somewhat redundant with the unmap signal, because if you
        # destroy a mapped window, then a UnmapNotify is always generated.
        # However, this allows us to catch the destruction of unmapped
        # ("iconified") windows, and also catch any mistakes we might have
        # made with the annoying unmap heuristics we have to use above.  I
        # love the smell of XDestroyWindow in the morning.  It makes for
        # simple code:
        self.unmanage_window()

    def unmanage_window(self):
        print "unmanaging window"
        def unmanageit():
            self._scrub_withdrawn_window()
            self.client_window.reparent(gtk.gdk.get_default_root_window(),
                                        0, 0)
            parti.lowlevel.sendConfigureNotify(self.client_window)
        trap.swallow(unmanageit)
        self.emit("unmanaged")
        print "destroying self"
        self.destroy()

    def _set_controlling_view(self, view):
        assert view is None or view in self.views
        if self.controlling_view is view:
            return
        if self.controlling_view is not None:
            self.expose_window.hide()
            self.expose_window.reparent(self.parking_window, 0, 0)
        self.controlling_view = view
        if self.controlling_view is not None:
            assert self.controlling_view.flags() & gtk.REALIZED
            # We can reparent to (0, 0), even though that's probably not the
            # right place, because _update_client_geometry will move us to the
            # proper location.
            self.expose_window.reparent(self.controlling_view.window, 0, 0)
            self._update_client_geometry()
            self.expose_window.lower()
            self.expose_window.show_unraised()
        trap.swallow(parti.lowlevel.sendConfigureNotify, self.client_window)

    def _unregister_view(self, view):
        if view.flags() & gtk.MAPPED:
            self._view_unmapped(view)
        self.views.remove(view)

    def _register_view(self, view):
        assert view not in self.views
        self.views.add(view)
        if view.flags() & gtk.MAPPED:
            self._view_mapped(view)

    def new_view(self):
        return WindowView(self)

    def destroy(self):
        for view in list(self.views):
            view.destroy()
        assert not self.views
        assert self.controlling_view is None
        self.expose_listener.destroy()

    def _view_unmapped(self, view):
        assert view in self.views
        if self.controlling_view is view:
            for other in self.views:
                if other.flags() & gtk.MAPPED and other is not view:
                    self._set_controlling_view(other)
                    break
            else:
                self._set_controlling_view(None)

    def _view_mapped(self, view):
        assert view in self.views
        if self.controlling_view is None:
            self._set_controlling_view(view)

    def _view_reallocated(self, view):
        assert view in self.views
        if self.controlling_view is view:
            self._update_client_geometry()

    def _update_client_geometry(self):
        if self.controlling_view is not None:
            (base_x, base_y, allocated_w, allocated_h) = self.controlling_view.allocation
            hints = self.get_property("size-hints")
            size = parti.lowlevel.calc_constrained_size(allocated_w,
                                                        allocated_h,
                                                        hints)
            (w, h, wvis, hvis) = size
            self.corral_window.resize(w, h)
            trap.swallow(parti.lowlevel.configureAndNotify,
                         self.client_window, 0, 0, w, h)
            (x, y) = self.controlling_view._get_offset_for(w, h)
            self.expose_window.move_resize(x, y, w, h)
            self._internal_set_property("actual-size", (w, h))
            self._internal_set_property("user-friendly-size", (wvis, hvis))
            for view in self.views:
                view._invalidate_all()

    def _handle_configure_request(self, event):
        # WARNING: currently the global _handle_root_configure_request method
        # calls this method directly if it receives a configure request for a
        # newly managed window (this can happen if a window maps and then
        # immediately configures, before our reparent has a chance to take
        # affect).

        # Ignore the request, but as per ICCCM 4.1.5, send back a synthetic
        # ConfigureNotify telling the client that nothing has happened.
        trap.swallow(parti.lowlevel.sendConfigureNotify,
                     event.window)

        # Also potentially update our record of what the app has requested:
        (x, y) = self.get_property("requested-position")
        if event.value_mask & parti.lowlevel.const["CWX"]:
            x = event.x
        if event.value_mask & parti.lowlevel.const["CWY"]:
            y = event.y
        self._internal_set_property("requested-position", (x, y))

        (w, h) = self.get_property("requested-size")
        if event.value_mask & parti.lowlevel.const["CWWidth"]:
            w = event.width
        if event.value_mask & parti.lowlevel.const["CWHeight"]:
            h = event.height
        self._internal_set_property("requested-size", (w, h))
        self._update_client_geometry()

        # FIXME: consider handling attempts to change stacking order here.
        # (In particular, I believe that a request to jump to the top is
        # meaningful and should perhaps even be respected.)

    def _handle_damage(self, event):
        print ("received composited expose event: (%s, %s, %s, %s)" %
               (event.area.x, event.area.y, event.area.width, event.area.height))
        for view in self.views:
            if view.flags() & gtk.MAPPED:
                view._handle_damage(event)

    ################################
    # Property reading
    ################################
    
    def do_client_property_notify_event(self, event):
        self._handle_property_change(event.atom)

    _property_handlers = {}

    def _handle_property_change(self, gdkatom):
        name = str(gdkatom)
        if name in self._property_handlers:
            self._property_handlers[name](self)

    def _handle_wm_hints(self):
        wm_hints = prop_get(self.client_window,
                            "WM_HINTS", "wm-hints")
        if wm_hints is not None:
            # GdkWindow or None
            self._internal_set_property("group-leader", wm_hints.group_leader)
            # FIXME: extract state and input hint

            if wm_hints.urgency:
                self.set_property("attention-requested", True)

    _property_handlers["WM_HINTS"] = _handle_wm_hints

    def _handle_wm_normal_hints(self):
        size_hints = prop_get(self.client_window,
                              "WM_NORMAL_HINTS", "wm-size-hints")
        self._internal_set_property("size-hints", size_hints)
        self._update_client_geometry()

    _property_handlers["WM_NORMAL_HINTS"] = _handle_wm_normal_hints

    def _handle_title_change(self):
        wm_name = prop_get(self.client_window, "WM_NAME", "latin1")
        net_wm_name = prop_get(self.client_window, "_NET_WM_NAME", "utf8")
        if net_wm_name is not None:
            self._internal_set_property("title", net_wm_name)
        else:
            # may be None
            self._internal_set_property("title", wm_name)

    _property_handlers["WM_NAME"] = _handle_title_change
    _property_handlers["_NET_WM_NAME"] = _handle_title_change
    
    def _handle_icon_title_change(self):
        wm_icon_name = prop_get(self.client_window, "WM_ICON_NAME", "latin1")
        net_wm_icon_name = prop_get(self.client_window, "_NET_WM_ICON_NAME", "utf8")
        if net_wm_icon_name is not None:
            self._internal_set_property("icon-title", net_wm_icon_name)
        else:
            # may be None
            self._internal_set_property("icon-title", wm_icon_name)

    _property_handlers["WM_ICON_NAME"] = _handle_icon_title_change
    _property_handlers["_NET_WM_ICON_NAME"] = _handle_icon_title_change

    def _handle_wm_strut(self):
        partial = prop_get(self.client_window,
                           "_NET_WM_STRUT_PARTIAL", "strut-partial")
        if partial is not None:
            self._internal_set_property("strut", partial)
            return
        full = prop_get(self.client_window, "_NET_WM_STRUT", "strut")
        # Might be None:
        self._internal_set_property("strut", full)

    _property_handlers["_NET_WM_STRUT"] = _handle_wm_strut
    _property_handlers["_NET_WM_STRUT_PARTIAL"] = _handle_wm_strut

    def _handle_net_wm_icon(self):
        self._internal_set_property("icon",
                                    prop_get(self.client_window,
                                             "_NET_WM_ICON", "icon"))

    _property_handlers["_NET_WM_ICON"] = _handle_net_wm_icon

    def _read_initial_properties(self):
        # Things that don't change:
        geometry = self.client_window.get_geometry()
        self._internal_set_property("requested-position", (geometry[0], geometry[1]))
        self._internal_set_property("requested-size", (geometry[2], geometry[3]))

        class_instance = prop_get(self.client_window,
                                  "WM_CLASS", "latin1")
        if class_instance:
            try:
                (c, i, fluff) = class_instance.split("\0")
            except ValueError:
                print "Malformed WM_CLASS, ignoring"
            else:
                self._internal_set_property("class", c)
                self._internal_set_property("instance", i)

        transient_for = prop_get(self.client_window,
                                 "WM_TRANSIENT_FOR", "window")
        # May be None
        self._internal_set_property("transient-for", transient_for)

        protocols = prop_get(self.client_window,
                             "WM_PROTOCOLS", ["atom"])
        if protocols is None:
            protocols = []
        self._internal_set_property("protocols", protocols)

        window_types = prop_get(self.client_window,
                                "_NET_WM_WINDOW_TYPE", ["atom"])
        if window_types:
            self._internal_set_property("window-type", window_types)
        else:
            if self.get_property("transient-for"):
                # EWMH says that even if it's transient-for, we MUST check to
                # see if it's override-redirect (and if so treat as NORMAL).
                # But we wouldn't be here if this was override-redirect.
                assume_type = "_NET_WM_TYPE_DIALOG"
            else:
                assume_type = "_NET_WM_WINDOW_TYPE_NORMAL"
            self._internal_set_property("window-type",
                              [gtk.gdk.atom_intern(assume_type)])

        pid = prop_get(self.client_window,
                       "_NET_WM_PID", "u32")
        if pid is not None:
            self._internal_set_property("pid", pid)
        else:
            self._internal_set_property("pid", -1)

        client_machine = prop_get(self.client_window,
                                  "WM_CLIENT_MACHINE", "latin1")
        # May be None
        self._internal_set_property("client-machine", client_machine)
        
        # WARNING: have to handle _NET_WM_STATE before we look at WM_HINTS;
        # WM_HINTS assumes that our "state" property is already set.  This is
        # because there are four ways a window can get its urgency
        # ("attention-requested") bit set:
        #   1) _NET_WM_STATE_DEMANDS_ATTENTION in the _initial_ state hints
        #   2) setting the bit WM_HINTS, at _any_ time
        #   3) sending a request to the root window to add
        #      _NET_WM_STATE_DEMANDS_ATTENTION to their state hints
        #   4) if we (the wm) decide they should be and set it
        # To implement this, we generally track the urgency bit via
        # _NET_WM_STATE (since that is under our sole control during normal
        # operation).  Then (1) is accomplished through the normal rule that
        # initial states are read off from the client, and (2) is accomplished
        # by having WM_HINTS affect _NET_WM_STATE.  But this means that
        # WM_HINTS and _NET_WM_STATE handling become intertangled.
        net_wm_state = prop_get(self.client_window,
                                "_NET_WM_STATE", ["atom"])
        if net_wm_state:
            self._internal_set_property("state", sets.ImmutableSet(net_wm_state))
        else:
            self._internal_set_property("state", sets.ImmutableSet())

        for mutable in ["WM_HINTS", "WM_NORMAL_HINTS",
                        "WM_NAME", "_NET_WM_NAME",
                        "WM_ICON_NAME", "_NET_WM_ICON_NAME",
                        "_NET_WM_STRUT", "_NET_WM_STRUT_PARTIAL",
                        "_NET_WM_ICON"]:
            self._handle_property_change(gtk.gdk.atom_intern(mutable))

    ################################
    # Property setting
    ################################
    
    # A few words about _NET_WM_STATE are in order.  Basically, it is a set of
    # flags.  Clients are allowed to set the initial value of this X property
    # to anything they like, when their window is first mapped; after that,
    # though, only the window manager is allowed to touch this property.  So
    # we store its value (our at least, our idea as to its value, the X server
    # in principle could disagree) as the "state" property.  There are
    # basically two things we need to accomplish:
    #   1) Whenever our property is modified, we mirror that modification into
    #      the X server.  This is done by connecting to our own notify::state
    #      signal.
    #   2) As a more user-friendly interface to these state flags, we provide
    #      several boolean properties like "attention-requested".
    #      These are virtual boolean variables; they are actually backed
    #      directly by the "state" property, and reading/writing them in fact
    #      accesses the "state" set directly.  This is done by overriding
    #      do_set_property and do_get_property.
    def _state_add(self, state_name):
        curr = set(self.get_property("state"))
        curr.add(state_name)
        self._internal_set_property("state", sets.ImmutableSet(curr))

    def _state_remove(self, state_name):
        curr = set(self.get_property("state"))
        curr.discard(state_name)
        self._internal_set_property("state", sets.ImmutableSet(curr))

    def _state_isset(self, state_name):
        return state_name in self.get_property("state")

    def _handle_state_changed(self, *args):
        # Sync changes to "state" property out to X property.
        prop_set(self.client_window, "_NET_WM_STATE",
                 ["atom"], self.get_property("state"))

    _state_properties = {
        "attention-requested": "_NET_WM_STATE_DEMANDS_ATTENTION",
        "fullscreen": "_NET_WM_STATE_FULLSCREEN",
        }
    def do_set_property(self, pspec, value):
        if pspec.name in self._state_properties:
            state = self._state_properties[pspec.name]
            if value:
                self._state_add(state)
            else:
                self._state_remove(state)
        else:
            AutoPropGObjectMixin.do_set_property(self, pspec, value)

    def do_get_property(self, pspec):
        if pspec.name in self._state_properties:
            return self._state_isset(self._state_properties[pspec.name])
        else:
            return AutoPropGObjectMixin.do_get_property(self, pspec)


    def _handle_iconic_update(self, *args):
        if self.get_property("iconic"):
            trap.swallow(prop_set, self.client_window, "WM_STATE",
                         ["u32"],
                         [parti.lowlevel.const["IconicState"],
                          parti.lowlevel.const["XNone"]])
            self._state_add("_NET_WM_STATE_HIDDEN")
        else:
            trap.swallow(prop_set, self.client_window, "WM_STATE",
                         ["u32"],
                         [parti.lowlevel.const["NormalState"],
                          parti.lowlevel.const["XNone"]])
            self._state_remove("_NET_WM_STATE_HIDDEN")

    def _write_initial_properties_and_setup(self):
        # Things that don't change:
        prop_set(self.client_window, "_NET_WM_ALLOWED_ACTIONS",
                 ["atom"], self._NET_WM_ALLOWED_ACTIONS)
        prop_set(self.client_window, "_NET_FRAME_EXTENTS",
                 ["u32"], [0, 0, 0, 0])

        self.connect("notify::state", self._handle_state_changed)
        # Flush things:
        self._handle_state_changed()

    def _scrub_withdrawn_window(self):
        remove = ["WM_STATE",
                  "_NET_WM_STATE",
                  "_NET_FRAME_EXTENTS",
                  "_NET_WM_ALLOWED_ACTIONS",
                  ]
        def doit():
            for prop in remove:
                parti.lowlevel.XDeleteProperty(self.client_window, prop)
        trap.swallow(doit)

    

    ################################
    # Focus handling:
    ################################
    
    def give_client_focus(self):
        """The focus manager has decided that our client should recieve X
        focus.  See world_window.py for details."""
        print "Giving focus to client"
        # Have to fetch the time, not just use CurrentTime, both because ICCCM
        # says that WM_TAKE_FOCUS must use a real time and because there are
        # genuine race conditions here (e.g. suppose the client does not
        # actually get around to requesting the focus until after we have
        # already changed our mind and decided to give it to someone else).
        now = gtk.gdk.x11_get_server_time(self.expose_window)
        if "WM_TAKE_FOCUS" in self.get_property("protocols"):
            print "... using WM_TAKE_FOCUS"
            trap.swallow(parti.lowlevel.send_wm_take_focus,
                         self.client_window, now)
        else:
            print "... using XSetInputFocus"
            trap.swallow(parti.lowlevel.XSetInputFocus,
                         self.client_window, now)

gobject.type_register(WindowModel)

# There may be many views for the same window.  Only one can actually work
# (receive mouse events).  We assign this to the "highest priority" widget,
# where the following give widgets priority, from most to least:
#   -- has focus (or has mouse-over?)
#   -- is visible in a tray/other window, and the tray/other window is visible
#      -- and is focusable
#      -- and is not focusable
#   -- is visible in a tray, and the tray/other window is not visible
#      -- and is focusable
#      -- and is not focusable
#   -- is not visible
# Ties are broken by the size of the widget.
#
# Unmapped views cannot own the client.
#
# Widget.get_ancestor(my.Tray) will give us the nearest ancestor that
# isinstance(my.Tray), if any...
#
# FIXME: AS A HACK, instead for now I am just saying that there is an explicit
# call for a widget to steal control, and when the widget that has control
# disappears, it is given to some other random widget.  We should actually
# implement the above, or something like it.  Let's see what happens with tray
# layout stuff first.

class WindowView(gtk.Widget):
    def __init__(self, model):
        base(self).__init__(self)
        
        self._image_window = None
        self.model = model

        # Standard GTK double-buffering is useless for us, because it's on our
        # "official" window, and we don't draw to that.
        self.set_double_buffered(False)
        # FIXME: make this dependent on whether the client accepts input focus
        self.set_property("can-focus", True)

        self.model._register_view(self)

    def do_destroy(self):
        self.model._unregister_view(self)
        self.model = None
        gtk.Widget.destroy(self)

    def steal_control(self):
        self.model._set_controlling_view(self)

    def _invalidate_all(self):
        self._image_window.invalidate_rect(gtk.gdk.Rectangle(width=100000,
                                                             height=10000),
                                           False)

    def _get_transform_matrix(self):
        m = cairo.Matrix()
        size = self.model.get_property("actual-size")
        if self.model.controlling_view is self:
            m.translate(*self._get_offset_for(*size))
        else:
            scale_factor = min(self.allocation[2] * 1.0 / size[0],
                               self.allocation[3] * 1.0 / size[1])
            if 0.95 < scale_factor:
                scale_factor = 1
            # FIXME: Disable translation for now, because at least the
            # following X servers have (different) bugs handling scaling +
            # translation for composited windows:
            #   Xephyr with XAA
            #   Xephyr with -fakexa
            #   intel with XAA
            # Intel with EXA is known to work.
            #
            # See, for instance:
            #   https://bugs.freedesktop.org/show_bug.cgi?id=13115
            #   https://bugs.freedesktop.org/show_bug.cgi?id=13116
            #   https://bugs.freedesktop.org/show_bug.cgi?id=13117
            # I bet everyone else has bugs in this too, though.
            #
            # Using NameWindowPixmap and then compositing the pixmap instead
            # of the window directly might or might not be a workaround --
            # have to try it to find out.
            # 
            #offset = self._get_offset_for(size[0] * scale_factor,
            #                              size[1] * scale_factor)
            #m.translate(*offset)
            m.scale(scale_factor, scale_factor)
        return m

    def _handle_damage(self, event):
        m = self._get_transform_matrix()
        # This is the right way to convert an integer-space bounding box into
        # another integer-space bounding box:
        (x1, y1) = m.transform_point(event.area.x, event.area.y)
        (x2, y2) = m.transform_point(event.area.x + event.area.width,
                                     event.area.y + event.area.height)
        x1i = int(math.floor(x1))
        y1i = int(math.floor(y1))
        x2i = int(math.ceil(x2))
        y2i = int(math.ceil(y2))
        transformed = gtk.gdk.Rectangle(x1i, y1i, x2i - x1i, y2i - y1i)
        print ("damage (%s, %s, %s, %s) -> expose on (%s, %s, %s, %s)" %
               (event.area.x, event.area.y, event.area.width, event.area.height,
                transformed.x, transformed.y, transformed.width, transformed.height))
        self._image_window.invalidate_rect(transformed, False)
        
    def do_expose_event(self, event):
        if not self.flags() & gtk.MAPPED:
            return

        debug = False

        print ("redrawing rectangle at (%s, %s, %s, %s)"
               % (event.area.x, event.area.y,
                  event.area.width, event.area.height))

        # Blit the client window in as our image of ourself.
        cr = self._image_window.cairo_create()
        if not debug:
            cr.rectangle(event.area)
            cr.clip()

        # Create a temporary buffer and draw onto that.  It might in some
        # vague sense be cleaner (and perhaps slightly less code) to just call
        # begin_paint_rect and end_paint on our target window, but this works
        # well *and* for some reason gives us a workaround for:
        #   https://bugs.freedesktop.org/show_bug.cgi?id=12996
        # Apparently push_group forces a Render-based "slow" path.
        #
        # Note about push_group():
        #   "<cworth> njs: It's [the temporary buffer push_group allocates] as
        #             large as the current clip region.
        #    <cworth> njs: And yes, you'll get a server-side Pixmap when
        #             targeting an xlib surface."
        # Both of which are exactly what we want for double-buffering.
        cr.save()
        cr.push_group()

        # Random grey background:
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgb(0.5, 0.5, 0.5)
        cr.paint()
        cr.restore()
        
        cr.save()
        cr.set_matrix(self._get_transform_matrix())
        # FIXME: This doesn't work, because of pygtk bug #491256:
        #cr.set_source_pixmap(self.model.client_window, 0, 0)
        # Hacky workaround.  Note that we have to hold on to a handle to the
        # cairo context we create, because once it is destructed the surface
        # we got might stop working (I'm actually not sure whether it will or
        # not).
        source_cr = self.model.corral_window.cairo_create()
        source = source_cr.get_target()

        cr.set_source_surface(source, 0, 0)
        # Super slow (copies everything out of the server and then back
        # again), but an option for working around Cairo/X bugs:
        #tmpsrf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
        #                            source.get_width(), source.get_height())
        #tmpcr = cairo.Context(tmpsrf)
        #tmpcr.set_source_surface(source)
        #tmpcr.set_operator(cairo.OPERATOR_SOURCE)
        #tmpcr.paint()
        #cr.set_source_surface(tmpsrf, 0, 0)
        
        cr.paint()

        icon = self.model.get_property("icon")
        if icon is not None:
            cr.set_source_pixmap(icon, 0, 0)
            cr.paint_with_alpha(0.3)

        if debug:
            # Overlay a blue square to show where the origin of the
            # transformed coordinates is
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.rectangle(0, 0, 10, 10)
            cr.set_source_rgba(0, 0, 1, 0.2)
            cr.fill()
        cr.restore()

        cr.pop_group_to_source()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        cr.restore()

        if debug:
            # Overlay a green rectangle to show the damaged area
            cr.save()
            cr.rectangle(event.area)
            cr.set_source_rgba(0, 1, 0, 0.2)
            cr.fill()
            cr.restore()


    def do_size_request(self, requisition):
        # FIXME if we ever need to do automatic layout of these sorts of
        # widgets.  For now the assumption is that we're pretty much always
        # going to get a size imposed on us, so no point in spending excessive
        # effort figuring out what requisition means in this context.
        (requisition.width, requisition.height) = (100, 100)

    def do_size_allocate(self, allocation):
        self.allocation = allocation
        print "New allocation = %r" % (tuple(self.allocation),)
        if self.flags() & gtk.REALIZED:
            self.window.move_resize(*allocation)
            self._image_window.resize(allocation.width, allocation.height)
            self._image_window.input_shape_combine_region(gtk.gdk.Region(),
                                                          0, 0)
        self.model._view_reallocated(self)
    
    def do_realize(self):
        print "Realizing (allocation = %r)" % (tuple(self.allocation),)

        self.set_flags(gtk.REALIZED)
        self.window = gtk.gdk.Window(self.get_parent_window(),
                                     width=self.allocation.width,
                                     height=self.allocation.height,
                                     window_type=gtk.gdk.WINDOW_CHILD,
                                     wclass=gtk.gdk.INPUT_OUTPUT,
                                     event_mask=0)
        self.window.set_user_data(self)

        # Give it a nice theme-defined background
        #self.style.attach(self.window)
        #self.style.set_background(self.window, gtk.STATE_NORMAL)
        self.window.move_resize(*self.allocation)

        self._image_window = gtk.gdk.Window(self.window,
                                            width=self.allocation.width,
                                            height=self.allocation.height,
                                            window_type=gtk.gdk.WINDOW_CHILD,
                                            wclass=gtk.gdk.INPUT_OUTPUT,
                                            event_mask=gtk.gdk.EXPOSURE_MASK)
        self._image_window.input_shape_combine_region(gtk.gdk.Region(),
                                                      0, 0)
        self._image_window.set_user_data(self)
        self._image_window.show()

        print "Realized"

    def do_map(self):
        assert self.flags() & gtk.REALIZED
        if self.flags() & gtk.MAPPED:
            return
        print "Mapping"
        self.set_flags(gtk.MAPPED)
        self.model._view_mapped(self)
        self.window.show_unraised()
        print "Mapped"

    def do_unmap(self):
        if not (self.flags() & gtk.MAPPED):
            return
        print "Unmapping"
        self.unset_flags(gtk.MAPPED)
        self.window.hide()
        self.model._view_unmapped(self)
        print "Unmapped"
            
    def do_unrealize(self):
        print "Unrealizing"
        # Takes care of checking mapped status, issuing signals, calling
        # do_unmap, etc.
        self.unmap()
        
        assert self.model.controlling_view is not self
        self.unset_flags(gtk.REALIZED)
        # Break circular reference
        self.window.set_user_data(None)
        self.window = None
        self._image_window = None
        print "Unrealized"

    def _get_offset_for(self, w, h):
        assert self.flags() & gtk.REALIZED
        # These can come out negative; that's okay.
        return ((self.allocation.width - w) // 2,
                (self.allocation.height - h) // 2)
            
gobject.type_register(WindowView)
