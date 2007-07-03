# Keep track of all information for a single window

import gobject
import gtk
import gtk.gdk
import parti.wrapped
import parti.util
from parti.error import *

# Map
# Withdraw
# Store properties for everyone else
#   XID, for lookup
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

class Window(parti.util.MyGObject):
    __gproperties__ = {
        'title': (gobject.TYPE_PYOBJECT,
                  'Window title (unicode or None)',
                  gobject.PARAM_READWRITE),
        'icon': (gobject.TYPE_PYOBJECT,
                 'Icon (in some yet-to-be-determined format)',
                 gobject.PARAM_READWRITE),
        'strut': (gobject.TYPE_PYOBJECT,
                  'Strut (in some yet-to-be-determined format)',
                  gobject.PARAM_READWRITE),
        }
    __gsignals__ = {
        'mapped': (gobject.SIGNAL_RUN_LAST,
                   gobject.TYPE_NONE, ()),
        # Either withdrawn or removed -- in either case, we're not managing
        # it anymore.  Argument is True for destroyed windows.
        'removed': (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN)),
        }
    
    def __init__(self, gdkwindow):
        parti.util.MyGObject.__init__(self)
        self.window = gdkwindow
        # FIXME: What do we need to select for on the child window?
        # PropertyNotify, also we need to notice if it unmaps itself (perhaps
        # because it crashed, or whatever)...

        # withdraw = any of a real or synthetic UnmapNotify
        # exited/crashed = DestroyNotify
        # can get these from SubstructureNotify or StructureNotify;
        # StructureNotify better because requires less coordination with the
        # ClientAdaptor thingie (which may be reparenting all over the
        # place).

        self.adaptor = ClientWindowAdaptor(self)

    def map_requested(self):
        # Start listening for important property changes
        # Process existing properties

    def do_removed(self, destroyed):
        if not destroyed:
            # FIXME: Scrub properties that should be scrubbed

def _handle_ConfigureRequest(event):
    # Ignore the request, but as per ICCCM 4.1.5, send back a synthetic
    # ConfigureNotify telling the client that nothing has happened.
    parti.wrapped.sendConfigureNotify(event.window)
    # FIXME: consider handling attempts to change stacking order here.

class ClientWindowAdaptor(gtk.Widget):
    """A GTK Widget that simply wraps a client window."""
    # How to write custom widgets, GTK 1.2:
    #   http://developer.gnome.org/doc/GGAD/cha-widget.html
    # python-gtk2-doc/examples/gtk/widget.py
    def __init__(self, window):
        gtk.Widget.__init__(self)
        self.allocation = None
        self.child_window = window

    def do_realize(self):
        self.set_flags(self.flags() | gtk.REALIZED)
        self.window = gtk.gdk.Window(self.get_parent_window(),
                                     width=self.allocation.width,
                                     height=self.allocation.height,
                                     window_type=gtk.gdk.WINDOW_CHILD,
                                     wclass=gdk.INPUT_OUTPUT,
                                     # FIXME: any reason not to just zero this
                                     # out?
                                     event_mask=self.get_events())
        self.window.set_user_data(self)
        # Disallow and ignore any attempts by other clients to play with any
        # child windows.  (In particular, this will intercept any attempts by
        # the child to directly resize themselves.)
        parti.wrapped.substructureRedirect(self.window,
                                           None,
                                           _handle_ConfigureRequest,
                                           None)
        # Give it a nice theme-defined background
        self.style.attach(self.window)
        self.style.set_background(self.window, gtk.STATE_NORMAL)
        self.window.move_resize(*self.allocation)

        # FIXME: respect sizing hints (fixed size should left at the same size
        # and centered, constrained sizes should be best-fitted)

        def setup_child():
            parti.wrapped.XAddToSaveSet(self.child_window.window)
            self.child_window.window.reparent(self.window, 0, 0)
            parti.wrapped.configureAndNotify(self.child_window,
                                             0, 0,
                                             self.allocation[2],
                                             self.allocation[3])
            self.child_window.window.show()
        try:
            trap.call_unsynced(setup_child)
        except XError:
            # FIXME: handle client disappearing
            print "iewaroij"

    def do_size_request(self, requisition):
        # Just put something; we generally expect to have a fixed-size
        # container regardless.
        requisition.width = 100
        requisition.height = 100

    def do_unrealize(self):
        self.set_flags(self.flags() & ~gtk.REALIZED)

        # FIXME: do IconicState stuff, I guess

        self.child_window.window.hide()
        self.child_window.window.reparent(gtk.gdk.get_default_root_window(), 0, 0)
        # Break circular reference
        self.window.set_user_data(None)
        self.window = None

    def do_size_allocate(self, allocation):
        self.allocation = allocation
        if self.flags() & gtk.REALIZED:
            self.window.move_resize(*allocation)
            try:
                trap.call_unsynced(parti.wrapped.configureAndNotify,
                                   self.child_window.window,
                                   0, 0,
                                   self.allocation[2], self.allocation[3])
            except XError:
                # FIXME: handle client disappearing
                print "aewoirijewao"

# This is necessary to inform GObject about the new subclass; if it doesn't
# know about the subclass, then it thinks we are trying to instantiate
# GtkWidget directly, which is an abstract base class.
# FIXME: is this necessary?  GObjectMeta claims to take care of that...
gobject.type_register(ClientWindowAdaptor)
