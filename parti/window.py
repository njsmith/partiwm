# Keep track of all information for a single window

import sets
import gobject
import gtk
import gtk.gdk
import parti.wrapped
import parti.util
from parti.error import *
from parti.prop import prop_get, prop_set

# Map
# Withdraw
# Store properties for everyone else
#   title (WM_NAME, _NET_WM_NAME, WM_ICON_NAME, _NET_WM_ICON_NAME)
#   WM_NORMAL_HINTS: flags, max_width/height, width/height_inc, max_aspect,
#     base_width/height, gravity
#     the flags are not actually relevant to us -- except that they say which
#     fields are included?  I can't tell from the specs.
#   WM_HINTS: flags, input model, initial_state, icon_pixmap, icon_window,
#       icon_x, icon_y, icon_mask
#   WM_CLASS: can be ignored, except plugins or whatever might want to peek at
#   WM_TRANSIENT_FOR
#   WM_PROTOCOLS -- maybe WM_TAKE_FOCUS (I don't understand focus yet),
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

class Unmanageable(Exception):
    pass

class Window(parti.util.AutoPropGObjectMixin, gtk.Widget):
    """This represents a managed client window.

    It can be used as a GTK Widget, whose contents are the client window's
    contents."""

    _NET_WM_ALLOWED_ACTIONS = [
        "_NET_WM_ACTION_CLOSE",
        ]

    __gproperties__ = {
        "fixed-size": (gobject.TYPE_BOOLEAN,
                       "Is this client window fixed-size?", "",
                       False,
                       gobject.PARAM_READWRITE),
        "step-params": (gobject.TYPE_PYOBJECT,
                        "Is this a incremental-sizing window?",
                        "None if not, else ((base_width, base_height), (inc_width, inc_height))",
                        gobject.PARAM_READWRITE),
        "class": (gobject.TYPE_STRING,
                  "Classic X 'class'", "",
                  "",
                  gobject.PARAM_READWRITE),
        "instance": (gobject.TYPE_STRING,
                     "Classic X 'instance'", "",
                     "",
                     gobject.PARAM_READWRITE),
        "transient-for": (gobject.TYPE_PYOBJECT,
                          "Transient for (or None)", "",
                          gobject.PARAM_READWRITE),
        "protocols": (gobject.TYPE_PYOBJECT,
                      "Supported WM protocols", "",
                      gobject.PARAM_READWRITE),
        "window-type": (gobject.TYPE_PYOBJECT,
                        "Window type",
                        "NB, most preferred comes first, then fallbacks",
                        gobject.PARAM_READWRITE),
        "pid": (gobject.TYPE_INT,
                "PID of owning process", "",
                -1, 65535, -1,
                gobject.PARAM_READWRITE),
        "client-machine": (gobject.TYPE_PYOBJECT,
                           "Host where client process is running", "",
                           gobject.PARAM_READWRITE),
        "group-leader": (gobject.TYPE_PYOBJECT,
                         "Window group leader", "",
                         gobject.PARAM_READWRITE),
        "urgency-requested": (gobject.TYPE_BOOLEAN,
                              "Urgency hint from client", "",
                              False,
                              gobject.PARAM_READWRITE),
        "omnipresent": (gobject.TYPE_BOOLEAN,
                        "I want to be on every desktop", "",
                        False,
                        gobject.PARAM_READWRITE),
        "iconic": (gobject.TYPE_BOOLEAN,
                   "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
                   False,
                   gobject.PARAM_READWRITE),
        "state": (gobject.TYPE_PYOBJECT,
                  "State, as per _NET_WM_STATE", "",
                  gobject.PARAM_READWRITE),
        "title": (gobject.TYPE_PYOBJECT,
                  "Window title (unicode or None)", "",
                  gobject.PARAM_READWRITE),

        "icon-title": (gobject.TYPE_PYOBJECT,
                       "Icon title (unicode or None)", "",
                       gobject.PARAM_READWRITE),
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
    
    def __init__(self, gdkwindow, start_trays):
        """Register a new client window with the WM.

        Raises an Unmanageable exception if this window should not be
        managed, for whatever reason.  ATM, this mostly means that the window
        died somehow before we could do anything with it."""

        super(Window, self).__init__()
        # The way Gtk.Widget works, we have to make our actual top-level
        # window named "self.window".  And we need to put a window between the
        # rest of Gtk and the client window (so that we can enable
        # SubstructureRedirect on it).  So that means we use self.window for
        # that buffer window, and self.client_window for the actual client
        # window.
        self.client_window = gdkwindow

        def setup_client():
            # Start listening for important property changes
            self.client_window.set_events(self.client_window.get_events()
                                          | gtk.gdk.STRUCTURE_MASK
                                          | gtk.gdk.PROPERTY_CHANGE_MASK)

            # Process properties
            self._read_initial_properties()
            self._write_initial_properties_and_setup()
            # Everything starts out at least temporarily in IconicState, until
            # we get it settled.
            self.set_property("iconic", True)
        try:
            trap.call_unsynced(setup_client)
        except XError, e:
            raise Unmanageable, e

        assert start_trays
        for tray in start_trays:
            tray.add(self)

    def do_client_unmap_event(self, event):
        # The question is, did the window get unmapped because it was
        # withdrawn/destroyed, or did it get unmapped because we unmapped it
        # going into IconicState?
        #
        # We are careful to always set iconic=True before unmapping the window
        # ourselves, so that is one clue.  However, if we receive a
        # *synthetic* UnmapNotify event, that always means that the client has
        # withdrawn it (even if it was not mapped in the first place) --
        # ICCCM section 4.1.4.
        if event.send_event or not self.get_property("iconic"):
            self.unmanage_window()

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
        trap.swallow(self._scrub_withdrawn_window)
        self.emit("unmanaged")
        print "destroying self"
        self.destroy()

    def calc_geometry(self, allocation):
        # FIXME: respect sizing hints (fixed size should left at the same size
        # and centered, constrained sizes should be best-fitted)
        return (0, 0, allocation[2], allocation[3])

    def _handle_ConfigureRequest(self, event):
        # Ignore the request, but as per ICCCM 4.1.5, send back a synthetic
        # ConfigureNotify telling the client that nothing has happened.
        trap.swallow(parti.wrapped.sendConfigureNotify,
                     event.window)
        # FIXME: consider handling attempts to change stacking order here.

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
        # GdkWindow or None
        self.set_property("group-leader", wm_hints.group_leader)
        # FIXME: extract state and input hint
        if wm_hints.urgency:
            self.set_property("urgency-requested", True)

    _property_handlers["WM_HINTS"] = _handle_wm_hints

    def _handle_title_change(self):
        wm_name = prop_get(self.client_window, "WM_NAME", "latin1")
        net_wm_name = prop_get(self.client_window, "_NET_WM_NAME", "utf8")
        if net_wm_name is not None:
            self.set_property("title", net_wm_name)
        else:
            # may be None
            self.set_property("title", wm_name)

    _property_handlers["WM_NAME"] = _handle_title_change
    _property_handlers["_NET_WM_NAME"] = _handle_title_change
    
    def _handle_icon_title_change(self):
        wm_icon_name = prop_get(self.client_window, "WM_ICON_NAME", "latin1")
        net_wm_icon_name = prop_get(self.client_window, "_NET_WM_ICON_NAME", "utf8")
        if net_wm_icon_name is not None:
            self.set_property("icon-title", net_wm_icon_name)
        else:
            # may be None
            self.set_property("icon-title", wm_icon_name)

    _property_handlers["WM_ICON_NAME"] = _handle_icon_title_change
    _property_handlers["_NET_WM_ICON_NAME"] = _handle_icon_title_change

    def _handle_wm_strut(self):
        # FIXME
        pass

    _property_handlers["_NET_WM_STRUT"] = _handle_wm_strut
    _property_handlers["_NET_WM_STRUT_PARTIAL"] = _handle_wm_strut

    def _handle_net_wm_icon(self):
        # FIXME
        pass

    _property_handlers["_NET_WM_ICON"] = _handle_net_wm_icon

    def _read_initial_properties(self):
        # Things that don't change:
        size_hints = prop_get(self.client_window,
                              "WM_NORMAL_HINTS", "wm-size-hints")
        if size_hints and size_hints.max_size and size_hints.min_size \
           and size_hints.max_size == size_hints.min_size:
            self.set_property("fixed-size", True)
        if size_hints and size_hints.base_size and size_hints.resize_inc \
           and not self.get_property("fixed-size"):
            self.set_property("step-params",
                              (size_hints.base_size,
                              size_hints.resize_inc))
        else:
            self.set_property("step-params", None)

        class_instance = prop_get(self.client_window,
                                  "WM_CLASS", "latin1")
        try:
            (c, i, fluff) = class_instance.split("\0")
        except ValueError:
            print "Malformed WM_CLASS, ignoring"
        else:
            self.set_property("class", c)
            self.set_property("instance", i)

        transient_for = prop_get(self.client_window,
                                 "WM_TRANSIENT_FOR", "window")
        # May be None
        self.set_property("transient-for", transient_for)

        protocols = prop_get(self.client_window,
                             "WM_PROTOCOLS", ["atom"])
        #May be None
        self.set_property("protocols", protocols)

        window_types = prop_get(self.client_window,
                                "_NET_WM_WINDOW_TYPE", ["atom"])
        if window_types:
            self.set_property("window-type", window_types)
        else:
            if self.get_property("transient-for"):
                # EWMH says that even if it's transient-for, we MUST check to
                # see if it's override-redirect (and if so treat as NORMAL).
                # But we wouldn't be here if this was override-redirect.
                assume_type = "_NET_WM_TYPE_DIALOG"
            else:
                assume_type = "_NET_WM_WINDOW_TYPE_NORMAL"
            self.set_property("window-type",
                              [gtk.gdk.atom_intern(assume_type)])

        pid = prop_get(self.client_window,
                       "_NET_WM_PID", "u32")
        if pid is not None:
            self.set_property("pid", pid)

        client_machine = prop_get(self.client_window,
                                  "WM_CLIENT_MACHINE", "latin1")
        # May be None
        self.set_property("client-machine", client_machine)
        
        net_wm_state = prop_get(self.client_window,
                                "_NET_WM_STATE", ["atom"])
        if net_wm_state:
            if gtk.gdk.atom_intern("_NET_WM_STATE_DEMANDS_ATTENTION"):
                self.set_property("urgency-requested", True)
            self.set_property("state", sets.ImmutableSet(net_wm_state))
        else:
            self.set_property("state", sets.ImmutableSet())

        for mutable in ["WM_HINTS",
                        "WM_NAME", "_NET_WM_NAME",
                        "WM_ICON_NAME", "_NET_WM_ICON_NAME",
                        "_NET_WM_STRUT", "_NET_WM_STRUT_PARTIAL",
                        "_NET_WM_ICON"]:
            self._handle_property_change(gtk.gdk.atom_intern(mutable))

    ################################
    # Property setting
    ################################
    
    def state_add(self, state_name):
        atom = gtk.gdk.atom_intern(state_name)
        curr = set(self.get_property("state"))
        curr.add(atom)
        self.set_property("state", sets.ImmutableSet(curr))

    def state_remove(self, state_name):
        atom = gtk.gdk.atom_intern(state_name)
        curr = set(self.get_property("state"))
        curr.discard(atom)
        self.set_property("state", sets.ImmutableSet(curr))

    def state_isset(self, state_name):
        return gtk.gdk.atom_intern(state_name) in self.get_property("state")

    def _handle_iconic_update(self, property):
        # FIXME: Need to think carefully about how this should be handled.
        # ATM you cannot _put_ a client into iconic/non-iconic state by
        # setting this property, only by showing/hiding the widget.  Perhaps
        # that is as it should be.
        if self.get_property("iconic"):
            prop_set(self.client_window, "WM_STATE",
                     "u32", parti.wrapped.const["IconicState"])
            self.state_add("_NET_WM_STATE_HIDDEN")
        else:
            prop_set(self.client_window, "WM_STATE",
                     "u32", parti.wrapped.const["NormalState"])
            self.state_remove("_NET_WM_STATE_HIDDEN")

    # There are three ways a window can get urgency = True:
    #   1) _NET_WM_STATE_DEMANDS_ATTENTION in the _initial_ state hints
    #   2) setting the bit WM_HINTS, at _any_ time
    #   3) if we (the wm) decide they should be and set it
    def _handle_urgency_requested(self, *args):
        if self.get_property("urgency-requested"):
            self.state_add("_NET_WM_STATE_DEMANDS_ATTENTION")
        else:
            self.state_remove("_NET_WM_STATE_DEMANDS_ATTENTION")

    def _handle_state(self, *args):
        prop_set(self.client_window, "_NET_WM_STATE",
                 ["atom"], self.get_property("state"))

    def _write_initial_properties_and_setup(self):
        # Things that don't change:
        prop_set(self.client_window, "_NET_WM_ALLOWED_ACTIONS",
                 ["atom"], self._NET_WM_ALLOWED_ACTIONS)
        # FIXME: should set _NET_FRAME_EXTENTS, but to what?
        #prop_set(self.client_window, "_NET_FRAME_EXTENTS",
        #         ["u32"], [0, 0, 0, 0])

        self.connect("notify::urgency-requested",
                     self._handle_urgency_requested)
        # Flush things:
        self._handle_state()
        self._handle_urgency_requested()

    def _scrub_withdrawn_window(self):
        remove = ["WM_STATE",
                  "_NET_WM_STATE",
                  "_NET_FRAME_EXTENTS",
                  "_NET_WM_ALLOWED_ACTIONS",
                  ]
        def doit():
            for prop in remove:
                parti.wrapped.XDeleteProperty(self.client_window, prop)
        trap.swallow(doit)

    ################################
    # Widget stuff:
    ################################
    
    def _flag(self, flag):
        self.set_flags(self.flags() | flag)

    def _unflag(self, flag):
        self.set_flags(self.flags() & ~flag)

    def do_unmap(self):
        # We have to toggle our iconic state *before* actually mapping or
        # unmapping things, or else we will get confused and think that the
        # client has withdrawn the window.  To do this early enough, we have
        # to essentially reimplement the "unmap" signal handler.  (We could
        # call the superclass one, but it's easier to just reimplement...
        if not (self.flags() & gtk.MAPPED):
            return
        print "Unmapping"
        self.set_property("iconic", True)
        self.window.hide()
        self.client_window.hide()
            
    def do_map(self):
        # See notes on do_unmap.
        assert self.flags() & gtk.REALIZED
        if self.flags() & gtk.MAPPED:
            return
        print "Mapping"
        self._flag(gtk.MAPPED)
        self.set_property("iconic", False)
        self.window.show()
        self.client_window.show()

    def do_realize(self):
        print "Realizing (allocation = %r)" % (tuple(self.allocation),)

        self._flag(gtk.REALIZED)
        self.window = gtk.gdk.Window(self.get_parent_window(),
                                     width=self.allocation.width,
                                     height=self.allocation.height,
                                     window_type=gtk.gdk.WINDOW_CHILD,
                                     wclass=gtk.gdk.INPUT_OUTPUT,
                                     # FIXME: any reason not to just zero this
                                     # out?
                                     event_mask=self.get_events())
        self.window.set_user_data(self)
        # Disallow and ignore any attempts by other clients to play with any
        # child windows.  (In particular, this will intercept any attempts by
        # the client to directly resize themselves.)
        parti.wrapped.substructureRedirect(self.window,
                                           None,
                                           self._handle_ConfigureRequest,
                                           None)
        # Give it a nice theme-defined background
        self.style.attach(self.window)
        self.style.set_background(self.window, gtk.STATE_NORMAL)
        self.window.move_resize(*self.allocation)

        # FIXME: respect sizing hints (fixed size should left at the same size
        # and centered, constrained sizes should be best-fitted)

        def setup_child():
            parti.wrapped.XAddToSaveSet(self.client_window)
            self.client_window.reparent(self.window, 0, 0)
            parti.wrapped.configureAndNotify(self.client_window,
                                             *self.calc_geometry(self.allocation))
        trap.swallow(setup_child)

        self.emit("managed")
        print "Realized"

    def do_size_request(self, requisition):
        # Just put something; we generally expect to have a fixed-size
        # container regardless.
        requisition.width = 100
        requisition.height = 100

    def do_unrealize(self):
        print "Unrealizing"
        # Takes care of checking mapped status, issuing signals, calling
        # do_unmap, etc.
        self.unmap()
        
        self._unflag(gtk.REALIZED)

        def reparent_away():
            self.client_window.reparent(gtk.gdk.get_default_root_window(),
                                        0, 0)
            parti.wrapped.sendConfigureNotify(self.client_window)
        trap.swallow(reparent_away)
                
        # Break circular reference
        self.window.set_user_data(None)
        print "Unrealized"

    def do_size_allocate(self, allocation):
        self.allocation = allocation
        print "New allocation = %r" % (tuple(self.allocation),)
        if self.flags() & gtk.REALIZED:
            self.window.move_resize(*allocation)
            trap.swallow(parti.wrapped.configureAndNotify,
                         self.client_window,
                         *self.calc_geometry(self.allocation))

# This is necessary to inform GObject about the new subclass; if it doesn't
# know about the subclass, then it thinks we are trying to instantiate
# GtkWidget directly, which is an abstract base class.
# FIXME: is this necessary?  GObjectMeta claims to take care of that... but
# >>> B
# <class '__main__.B'>
# >>> B()
# Traceback (most recent call last):
#   File "<stdin>", line 1, in ?
# TypeError: cannot create instance of abstract (non-instantiable) type `GtkWidget'
# >>> gobject.type_register(B)
# <class '__main__.B'>
# >>> B()
# <B object (__main__+B) at 0x2ad124756fa0>

gobject.type_register(Window)
