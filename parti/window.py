"""The magic GTK widget that represents a client window.

Most of the gunk required to be a valid window manager (reparenting, synthetic
events, mucking about with properties, etc. etc.) is wrapped up in here."""

import sets
import gobject
import gtk
import gtk.gdk
import cairo
import math
import os
from socket import gethostname
import parti.lowlevel
from parti.util import (AutoPropGObjectMixin,
                        one_arg_signal, n_arg_signal, list_accumulator)
from parti.error import *
from parti.prop import prop_get, prop_set
from parti.composite import CompositeHelper

# Todo:
#   client focus hints
#   _NET_WM_SYNC_REQUEST
#   root window requests (pagers, etc. requesting to change client states)
#   _NET_WM_PING/detect window not responding (also a root window message)

# Okay, we need a block comment to explain the window arrangement that this
# file is working with.
#
#                +--------+
#                | widget |
#                +--------+
#                  /    \
#  <- top         /     -\-        bottom ->
#                /        \
#          +-------+       |     
#          | image |  +---------+
#          +-------+  | corral  |
#                     +---------+
#                          |     
#                     +---------+
#                     | client  |
#                     +---------+
#
# Each box in this diagram represents one X/GDK window.  In the common case,
# every window here takes up exactly the same space on the screen (!).  In
# fact, the two windows on the right *always* have exactly the same size and
# location, and the window on the left and the top window also always have
# exactly the same size and position.  However, each window in the diagram
# plays a subtly different role.
#
# The client window is obvious -- this is the window owned by the client,
# which they created and which we have various ICCCM/EWMH-mandated
# responsibilities towards.  It is also composited.
#
# The purpose of the 'corral' is to keep the client window managed -- we
# select for SubstructureRedirect on it, so that the client cannot resize
# etc. without going through the WM.
#
# These two windows are always managed together, as a unit; an invariant of
# the code is that they always take up exactly the same space on the screen.
# They get reparented back and forth between widgets, and when there are no
# widgets, they get reparented to a "parking area".  For now, we're just using
# the root window as a parking area, so we also map/unmap the corral window
# depending on whether we are parked or not; the corral and client windows are
# left mapped at all times.
#
# When a particular WindowView controls the underlying client window, then two
# things happen:
#   -- Its size determines the size of the client window.  Ideally they are
#      the same size -- but this is not always the case, because the client
#      may have specified sizing constraints, in which case the client window
#      is the "best fit" to the controlling widget window.
#   -- The client window and its corral are reparented under the widget
#      window, as in the diagram above.  This is necessary to allow mouse
#      events to work -- a WindowView widget can always *look* like the client
#      window is there, through the magic of Composite, but in order for it to
#      *act* like the client window is there in terms of receiving mouse
#      events, it has to actually be there.
#
# Finally, there is the 'image' window.  This is a window that always remains
# in the widget window, and is used to draw what the client currently looks
# like.  It needs to receive expose events so it knows if it has been exposed
# (not just when the window it is displaying has changed), and the easiest way
# to arrange for this is to make it exactly the same size as the parent
# 'widget' window.  Then the widget window never receives expose events
# (because it is occluded), and we can arrange for the image window's expose
# events to be delivered to the WindowView widget, and they will be in the
# right coordinate space.  If the widget is controlling the client, then the
# image window goes on top of the client window.  Why don't we just draw onto
# the widget window?  Because there is no way to ask Cairo to use
# IncludeInferiors drawing mode -- so if we were drawing onto the widget
# window, and the client were present in the widget window, then the blank
# black 'expose catcher' window would obscure the image of the client.
#
# All clear?

# We should also have a block comment describing how to create a
# view/"controller" for a WindowModel.
#
# Viewing a WindowModel is easy.  Connect to the redraw-needed signal.  Every
# time the window contents is updated, you'll get a message.  This message is
# passed a single object e, which has useful members:
#   e.x, e.y, e.width, e.height:
#      The part of the client window that was modified, and needs to be
#      redrawn.
#   e.pixmap_handle:
#      A "handle" for the window contents.  So long as you hold a reference to
#      this object, the window contents will be available in...
#   e.pixmap_handle.pixmap:
#      ...this gtk.gdk.Pixmap object.  This object will be destroyed as soon
#      as pixmap_handle passes out of scope, so if you want do anything fancy,
#      hold onto pixmap_handle, not just the pixmap itself.
#
# But what if you'd like to do more than just look at your pretty composited
# windows?  Maybe you'd like to, say, *interact* with them?  Then life is a
# little more complicated.  To make a view "live", we have to move the actual
# client window to be a child of your view window and position it correctly.
# Obviously, only one view can be live at any given time, so we have to figure
# out which one that is.  Supposing we have a WindowModel called "model" and
# a view called "view", then the following pieces come into play:
#   The "ownership-election" signal on window:
#     If a view wants the chance to become live, it must connect to this
#     signal.  When the signal is emitted, its handler should return a tuple
#     of the form:
#       (votes, my_view)
#     Just like a real election, everyone votes for themselves.  The view that
#     gives the highest value to 'votes' becomes the new owner.  However, a
#     view with a negative (< 0) votes value will never become the owner.
#   model.ownership_election():
#     This method (distinct from the ownership-election signal!) triggers an
#     election.  All views MUST call this method whenever they decide their
#     number of votes has changed.  All views MUST call this method when they
#     are destructing themselves (ideally after disconnecting from the
#     ownership-election signal).
#   The "owner" property on window:
#     This records the view that currently owns the window (i.e., the winner
#     of the last election), or None if no view is live.
#   view.take_window(model, window):
#     This method is called on 'view' when it becomes owner of 'model'.  It
#     should reparent 'window' into the appropriate place, and put it at the
#     appropriate place in its window stack.  (The x,y position, however, does
#     not matter.)
#   view.window_size(model):
#     This method is called when the model needs to know how much space it is
#     allocated.  It should return the maximum (width, height) allowed.
#     (However, the model may choose to use less than this.)
#   view.window_position(mode, width, height):
#     This method is called when the model needs to know where it should be
#     located (relative to the parent window the view placed it in).  'width'
#     and 'height' are the size the model window will actually be.  It should
#     return the (x, y) position desired.
#   model.maybe_recalculate_geometry_for(view):
#     This method (potentially) triggers a resize/move of the client window
#     within the view.  If 'view' is not the current owner, is a no-op, which
#     means that views can call it without worrying about whether they are in
#     fact the current owner.
#
# The actual method for choosing 'votes' is not really determined yet.
# Probably it should take into account at least the following factors:
#   -- has focus (or has mouse-over?)
#   -- is visible in a tray/other window, and the tray/other window is visible
#      -- and is focusable
#      -- and is not focusable
#   -- is visible in a tray, and the tray/other window is not visible
#      -- and is focusable
#      -- and is not focusable
#      (NB: Widget.get_ancestor(my.Tray) will give us the nearest ancestor
#      that isinstance(my.Tray), if any.)
#   -- is not visible
#   -- the size of the widget (as a final tie-breaker)

class Unmanageable(Exception):
    pass

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
                          "gtk.gdk.Window representing the client toplevel", "",
                          gobject.PARAM_READABLE),
        # NB "notify" signal never fires for the client-contents properties:
        "client-contents": (gobject.TYPE_PYOBJECT,
                            "gtk.gdk.Pixmap containing the window contents", "",
                            gobject.PARAM_READABLE),
        "client-contents-handle": (gobject.TYPE_PYOBJECT,
                                   "", "",
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
        # Toggling this property does not actually make the window iconified,
        # i.e. make it appear or disappear from the screen -- it merely
        # updates the various window manager properties that inform the world
        # whether or not the window is iconified.
        "iconic": (gobject.TYPE_BOOLEAN,
                   "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
                   False,
                   gobject.PARAM_READWRITE),
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

        "owner": (gobject.TYPE_PYOBJECT,
                  "Owner", "",
                  gobject.PARAM_READABLE),
        }
    __gsignals__ = {
        "redraw-needed": one_arg_signal,
        "ownership-election": (gobject.SIGNAL_RUN_LAST,
                               gobject.TYPE_PYOBJECT, (), list_accumulator),
        "unmanaged": one_arg_signal,

        "map-request-event": one_arg_signal,
        "configure-request-event": one_arg_signal,
        "parti-property-notify-event": one_arg_signal,
        "parti-unmap-event": one_arg_signal,
        "parti-destroy-event": one_arg_signal,
        }
        
    def __init__(self, parking_window, client_window):
        """Register a new client window with the WM.

        Raises an Unmanageable exception if this window should not be
        managed, for whatever reason.  ATM, this mostly means that the window
        died somehow before we could do anything with it."""

        parti.lowlevel.printFocus(client_window)

        super(WindowModel, self).__init__()
        self.parking_window = parking_window
        self.client_window = client_window
        self._internal_set_property("client-window", client_window)
        self.client_window.set_data("parti-route-events-to", self)

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

        # We enable PROPERTY_CHANGE_MASK so that we can call
        # x11_get_server_time on this window.
        self.corral_window = gtk.gdk.Window(self.parking_window,
                                            width=100,
                                            height=100,
                                            window_type=gtk.gdk.WINDOW_CHILD,
                                            wclass=gtk.gdk.INPUT_OUTPUT,
                                            event_mask=gtk.gdk.PROPERTY_CHANGE_MASK)
        parti.lowlevel.substructureRedirect(self.corral_window)

        def setup_client():
            # Start listening for important events
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
            self.client_window.show_unraised()

            # Keith Packard says that composite state is undefined following a
            # reparent, so let's be cautious and wait to turn on compositing
            # until here:
            self._composite = CompositeHelper(self.client_window, False)
            h = self._composite.connect("redraw-needed", self._damage_forward)
            self._damage_forward_handle = h
        try:
            trap.call(setup_client)
        except XError, e:
            raise Unmanageable, e

    def _damage_forward(self, obj, event):
        self.emit("redraw-needed", event)

    def do_get_property_client_contents(self, name):
        return self.get_property("client-contents-handle").pixmap

    def do_get_property_client_contents_handle(self, name):
        return self._composite.get_property("window-contents-handle")

    def do_map_request_event(self, event):
        # If we get a MapRequest then it might mean that someone tried to map
        # this window multiple times in quick succession, before we actually
        # mapped it (so that several MapRequests ended up queued up; FSF Emacs
        # 22.1.50.1 does this, at least).  It alternatively might mean that
        # the client is naughty and tried to map their window which is
        # currently not displayed.  In either case, we should just ignore the
        # request.
        pass

    def do_parti_unmap_event(self, event):
        assert event.window is self.client_window
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
            self.unmanage()
        else:
            self.pending_unmaps -= 1

    def do_parti_destroy_event(self, event):
        assert event.window is self.client_window
        # This is somewhat redundant with the unmap signal, because if you
        # destroy a mapped window, then a UnmapNotify is always generated.
        # However, this allows us to catch the destruction of unmapped
        # ("iconified") windows, and also catch any mistakes we might have
        # made with the annoying unmap heuristics we have to use above.  I
        # love the smell of XDestroyWindow in the morning.  It makes for
        # simple code:
        self.unmanage()

    def unmanage(self, exiting=False):
        self.emit("unmanaged", exiting)

    def do_unmanaged(self, exiting):
        print "unmanaging window"
        self._internal_set_property("owner", None)
        def unmanageit():
            self._scrub_withdrawn_window()
            self.client_window.reparent(gtk.gdk.get_default_root_window(),
                                        0, 0)
            parti.lowlevel.sendConfigureNotify(self.client_window)
            if exiting:
                self.client_window.show_unraised()
        trap.swallow(unmanageit)
        print "destroying self"
        self.client_window.set_data("parti-route-events-to", None)
        self._composite.disconnect(self._damage_forward_handle)
        self._composite.destroy()

    def ownership_election(self):
        candidates = self.emit("ownership-election")
        if candidates:
            rating, winner = sorted(candidates)[-1]
            if rating < 0:
                winner = None
        else:
            winner = None
        old_owner = self.get_property("owner")
        if old_owner is winner:
            return
        if old_owner is not None:
            self.corral_window.hide()
            self.corral_window.reparent(self.parking_window, 0, 0)
        self._internal_set_property("owner", winner)
        if winner is not None:
            winner.take_window(self, self.corral_window)
            self._update_client_geometry()
            self.corral_window.show_unraised()
        trap.swallow(parti.lowlevel.sendConfigureNotify, self.client_window)

    def maybe_recalculate_geometry_for(self, maybe_owner):
        if maybe_owner and self.get_property("owner") is maybe_owner:
            self._update_client_geometry()

    def _update_client_geometry(self):
        owner = self.get_property("owner")
        if owner is not None:
            (allocated_w, allocated_h) = owner.window_size(self)
            hints = self.get_property("size-hints")
            size = parti.lowlevel.calc_constrained_size(allocated_w,
                                                        allocated_h,
                                                        hints)
            (w, h, wvis, hvis) = size
            (x, y) = owner.window_position(self, w, h)
            self.corral_window.move_resize(x, y, w, h)
            trap.swallow(parti.lowlevel.configureAndNotify,
                         self.client_window, 0, 0, w, h)
            self._internal_set_property("actual-size", (w, h))
            self._internal_set_property("user-friendly-size", (wvis, hvis))

    def do_configure_request_event(self, event):
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

    ################################
    # Property reading
    ################################
    
    def do_parti_property_notify_event(self, event):
        assert event.window is self.client_window
        self._handle_property_change(str(event.atom))

    _property_handlers = {}

    def _handle_property_change(self, name):
        print "Property changed on %s: %s" % (self.client_window.xid, name)
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
        print "_NET_WM_ICON changed on %s, re-reading" % (self.client_window.xid,)
        self._internal_set_property("icon",
                                    prop_get(self.client_window,
                                             "_NET_WM_ICON", "icon"))

        print "icon is now %r" % (self.get_property("icon"),)
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
            self._handle_property_change(mutable)

    ################################
    # Property setting
    ################################
    
    # A few words about _NET_WM_STATE are in order.  Basically, it is a set of
    # flags.  Clients are allowed to set the initial value of this X property
    # to anything they like, when their window is first mapped; after that,
    # though, only the window manager is allowed to touch this property.  So
    # we store its value (or at least, our idea as to its value, the X server
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
    _state_properties = {
        "attention-requested": "_NET_WM_STATE_DEMANDS_ATTENTION",
        "fullscreen": "_NET_WM_STATE_FULLSCREEN",
        }

    _state_properties_reversed = {}
    for k, v in _state_properties.iteritems():
        _state_properties_reversed[v] = k

    def _state_add(self, state_name):
        curr = set(self.get_property("state"))
        if state_name not in curr:
            curr.add(state_name)
            self._internal_set_property("state", sets.ImmutableSet(curr))
            if state_name in self._state_properties_reversed:
                self.notify(self._state_properties_reversed[state_name])

    def _state_remove(self, state_name):
        curr = set(self.get_property("state"))
        if state_name in curr:
            curr.discard(state_name)
            self._internal_set_property("state", sets.ImmutableSet(curr))
            if state_name in self._state_properties_reversed:
                self.notify(self._state_properties_reversed[state_name])

    def _state_isset(self, state_name):
        return state_name in self.get_property("state")

    def _handle_state_changed(self, *args):
        # Sync changes to "state" property out to X property.
        prop_set(self.client_window, "_NET_WM_STATE",
                 ["atom"], self.get_property("state"))

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
        now = gtk.gdk.x11_get_server_time(self.corral_window)
        if "WM_TAKE_FOCUS" in self.get_property("protocols"):
            print "... using WM_TAKE_FOCUS"
            trap.swallow(parti.lowlevel.send_wm_take_focus,
                         self.client_window, now)
        else:
            print "... using XSetInputFocus"
            trap.swallow(parti.lowlevel.XSetInputFocus,
                         self.client_window, now)

    ################################
    # Killing clients:
    ################################
    
    def request_close(self):
        if "WM_DELETE_WINDOW" in self.get_property("protocols"):
            trap.swallow(parti.lowlevel.send_wm_delete_window,
                         self.client_window)
        else:
            # You don't wanna play ball?  Then no more Mr. Nice Guy!
            self.force_quit()

    def force_quit(self):
        pid = self.get_property("pid")
        machine = self.get_property("client-machine")
        localhost = gethostname()
        if pid > 0 and machine is not None and machine == localhost:
            try:
                os.kill(pid, 9)
            except OSError:
                print "failed to kill() client with pid %s" % (pid,)
        trap.swallow(parti.lowlevel.XKillClient, self.client_window)

gobject.type_register(WindowModel)


class WindowView(gtk.Widget):
    def __init__(self, model):
        gtk.Widget.__init__(self)
        
        self._image_window = None
        self.model = model
        self._redraw_handle = self.model.connect("redraw-needed",
                                                  self._redraw_needed)
        self._election_handle = self.model.connect("ownership-election",
                                                    self._vote_for_pedro)

        # Standard GTK double-buffering is useless for us, because it's on our
        # "official" window, and we don't draw to that.
        self.set_double_buffered(False)
        # FIXME: make this dependent on whether the client accepts input focus
        self.set_property("can-focus", True)


    def do_destroy(self):
        self.model.disconnect(self._redraw_handle)
        self.model.disconnect(self._election_handle)
        self.model = None
        gtk.Widget.do_destroy(self)

    def _invalidate_all(self):
        self._image_window.invalidate_rect(gtk.gdk.Rectangle(width=100000,
                                                             height=10000),
                                           False)

    def _get_transform_matrix(self):
        m = cairo.Matrix()
        size = self.model.get_property("actual-size")
        if self.model.get_property("owner") is self:
            m.translate(*self.window_position(self.model, *size))
        else:
            scale_factor = min(self.allocation[2] * 1.0 / size[0],
                               self.allocation[3] * 1.0 / size[1])
            if 0.95 < scale_factor:
                scale_factor = 1
            offset = self.window_position(self.model,
                                          size[0] * scale_factor,
                                          size[1] * scale_factor)
            m.translate(*offset)
            m.scale(scale_factor, scale_factor)
        return m

    def _vote_for_pedro(self, model):
        if self.flags() & gtk.MAPPED:
            return (self.allocation.width * self.allocation.height, self)
        else:
            return (-1, self)

    def _redraw_needed(self, model, event):
        if not self.flags() & gtk.MAPPED:
            return
        m = self._get_transform_matrix()
        # This is the right way to convert an integer-space bounding box into
        # another integer-space bounding box:
        (x1, y1) = m.transform_point(event.x, event.y)
        (x2, y2) = m.transform_point(event.x + event.width,
                                     event.y + event.height)
        x1i = int(math.floor(x1))
        y1i = int(math.floor(y1))
        x2i = int(math.ceil(x2))
        y2i = int(math.ceil(y2))
        transformed = gtk.gdk.Rectangle(x1i, y1i, x2i - x1i, y2i - y1i)
#        print ("damage (%s, %s, %s, %s) -> expose on (%s, %s, %s, %s)" %
#               (event.area.x, event.area.y, event.area.width, event.area.height,
#                transformed.x, transformed.y, transformed.width, transformed.height))
        self._image_window.invalidate_rect(transformed, False)
        
    def do_expose_event(self, event):
        if not self.flags() & gtk.MAPPED:
            return

        debug = False

        if debug:
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
        # fine.
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

        cr.set_source_pixmap(self.model.get_property("client-contents"),
                             0, 0)
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

    def window_position(self, model, w, h):
        assert self.flags() & gtk.REALIZED
        # These can come out negative; that's okay.
        return ((self.allocation.width - w) // 2,
                (self.allocation.height - h) // 2)

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
        self.model.ownership_election()
        self.model.maybe_recalculate_geometry_for(self)
    
    def window_size(self, model):
        assert self.flags() & gtk.REALIZED
        return (self.allocation.width, self.allocation.height)

    def take_window(self, model, window):
        assert self.flags() & gtk.REALIZED
        window.reparent(self.window, 0, 0)
        window.lower()

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
        self.model.ownership_election()
        self.window.show_unraised()
        print "Mapped"

    def do_unmap(self):
        if not (self.flags() & gtk.MAPPED):
            return
        print "Unmapping"
        self.unset_flags(gtk.MAPPED)
        self.window.hide()
        self.model.ownership_election()
        print "Unmapped"
            
    def do_unrealize(self):
        print "Unrealizing"
        # Takes care of checking mapped status, issuing signals, calling
        # do_unmap, etc.
        self.unmap()
        
        self.unset_flags(gtk.REALIZED)
        # Break circular reference
        if self.window:
            self.window.set_user_data(None)
        self._image_window = None
        print "Unrealized"
            
gobject.type_register(WindowView)
