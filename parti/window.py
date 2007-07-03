# Keep track of all information for a single window

import gobject
import gtk
import gtk.gdk
import parti.wrapped

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

# Emit signals on:
#   name changes
#   icon change
#   strut change
#   ->NORMAL state transition
#   ->WITHDRAWN (or just closed) state transition

class Window(object):
    def __init__(self, gdkwindow):
        self.window = gdkwindow
        
    def 

class ClientWindowAdaptor(gtk.Widget):
    """A GTK Widget that simply wraps a client window."""
    # How to write custom widgets, GTK 1.2:
    #   http://developer.gnome.org/doc/GGAD/cha-widget.html
    # python-gtk2-doc/examples/gtk/widget.py
    def __init__(self, gdkwindow):
        gtk.Widget.__init__(self)
        self.allocation = None
        self.child_window = gdkwindow

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
        # Give it a nice theme-defined background
        self.style.attach(self.window)
        self.style.set_background(self.window, gtk.STATE_NORMAL)
        self.window.move_resize(*self.allocation)

        # FIXME: be smarter about positioning and size calculations (e.g.,
        # borders).  We are allowed to set borders to 0.

        # FIXME: respect sizing hints (fixed size should left at the same size
        # and centered, constrained sizes should be best-fitted)

        # FIXME: Send a synthetic ConfigureNotify
        # (We might have to use TranslateCoordinates to figure out where
        # the heck we actually are.  In fact, we should send a ConfigureNotify
        # every time we move or are resized?)

        # FIXME: I think we have to select for SubstructureRedirect on our new
        # parent window, too?
        parti.wrapped.XAddToSaveSet(self.child_window)
        self.child_window.reparent(self.window, 0, 0)
        self.child_window.resize(*self.allocation[2:4])
        self.child_window.show()

    def do_size_request(self, requisition):
        # Just put something; we generally expect to have a fixed-size
        # container regardless.
        requisition.width = 100
        requisition.height = 100

    def do_unrealize(self):
        self.child_window.hide()
        self.child_window.reparent(gtk.gdk.get_default_root_window(), 0, 0)
        # Break circular reference
        self.window.set_user_data(None)
        self.window = None

    def do_size_allocate(self, allocation):
        self.allocation = allocation
        if self.flags() & gtk.REALIZED:
            self.window.move_resize(*allocation)
            # FIXME: synthetic ConfigureNotify processing
            self.child_window.resize(*self.allocation[2:4])

    def do_expose_event(self, event):
        pass

# This is necessary to inform GObject about the new subclass; if it doesn't
# know about the subclass, then it thinks we are trying to instantiate
# GtkWidget directly, which is an abstract base class.
gobject.type_register(ClientWindowAdaptor)
