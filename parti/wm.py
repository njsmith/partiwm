import sys

import pygtk
pygtk.require('2.0')
import gtk
import gtk.gdk

# gdk_window_set_composited() (2.12+ only)

import parti.selection
import parti.wrapped
from parti.prop import prop_set

from parti.windowset import WindowSet
from parti.tray import TraySet
from parti.trays.simpletab import SimpleTabTray

class Wm(object):
    NAME = "Parti"

    _NET_SUPPORTED = [
        "_NET_SUPPORTING_WM_CHECK",
        "_NET_WM_FULL_PLACEMENT",
        "_NET_WM_HANDLED_ICONS",
        "_NET_CLIENT_LIST",
        "_NET_CLIENT_LIST_STACKING",
        "WM_NAME", "_NET_WM_NAME",
        "WM_ICON_NAME", "_NET_WM_ICON_NAME",
        "WM_CLASS",
        "WM_PROTOCOLS",
        "_NET_WM_PID",
        "WM_CLIENT_MACHINE",
        "WM_STATE",

        "_NET_WM_ALLOWED_ACTIONS",
        "_NET_WM_ACTION_CLOSE",

        # We don't actually use _NET_WM_USER_TIME at all (yet), but it is
        # important to say we support the _NET_WM_USER_TIME_WINDOW property,
        # because this tells applications that they do not need to constantly
        # ping any pagers etc. that might be running -- see EWMH for details.
        "_NET_WM_USER_TIME",
        "_NET_WM_USER_TIME_WINDOW",
        # Not fully:
        "WM_HINTS",
        "WM_NORMAL_HINTS",
        "WM_TRANSIENT_FOR",

        "_NET_WM_WINDOW_TYPE",
        "_NET_WM_WINDOW_TYPE_NORMAL",

        "_NET_WM_STATE",
        "_NET_WM_STATE_DEMANDS_ATTENTION",

        # Not at all yet:
        #"_NET_WM_STRUT", "_NET_WM_STRUT_PARTIAL"
        #"_NET_WM_ICON",
        #"_NET_FRAME_EXTENTS",
        ]

    def __init__(self):
        self._windows = WindowSet()
        self._windows.connect("window-list-changed", self._update_window_list)

        self._trays = TraySet()

        self._real_root = gtk.gdk.get_default_root_window()
        self._ewmh_window = None
        
        # Start snooping on the raw GDK event stream
        gtk.gdk.event_handler_set(self._dispatchgdk_event)

        # Become the Official Window Manager of this year's game:
        self._wm_selection = parti.selection.ManagerSelection("WM_S0")
        self._wm_selection.connect("selection-lost", self._lost_wm_selection)
        if self._wm_selection.owned():
            print "A window manager is already running; exiting"
            sys.exit()
        self._wm_selection.acquire()
        # (If we become a compositing manager, then we will want to do the
        # same thing with the _NET_WM_CM_S0 selection (says EWMH).)

        # Set up the necessary EWMH properties on the root window.
        self._setup_ewmh_window()
        prop_set(self._real_root, "_NET_SUPPORTED",
                 ["atom"], self._NET_SUPPORTED)
        prop_set(self._real_root, "_NET_DESKTOP_VIEWPORT",
                 ["u32"], [0, 0])
        self._update_window_list()

        # FIXME: be less stupid
        self.trays.new("default", SimpleTabTray)

        # Okay, ready to select for SubstructureRedirect and then load in all
        # the existing clients.
        parti.wrapped.substructureRedirect(self._real_root,
                                           self._handle_root_map_request,
                                           None,
                                           None)
        for w in parti.wrapped.get_children(self._real_root):
            if parti.wrapped.is_mapped(w):
                self._maybe_manage_client(w)

        # FIXME:

        # Need to watch for screen geometry changes to update
        #   _NET_DESKTOP_GEOMETRY, also _NET_WORKAREA
        # Need to watch TraySet to update _NET_NUMBER_OF_DESKTOPS,
        #   _NET_DESKTOP_NAMES
        # Need viewport abstraction for _NET_CURRENT_DESKTOP...
        # Tray's need to provide info for _NET_ACTIVE_WINDOW and _NET_WORKAREA

        # Need to listen for:
        #   _NET_CLOSE_WINDOW
        #   _NET_ACTIVE_WINDOW
        #   _NET_CURRENT_DESKTOP
        #   _NET_REQUEST_FRAME_EXTENTS
        # Maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_DESKTOP
        #   _NET_WM_STATE

    def _lost_wm_selection(self, selection):
        print "Lost WM selection, exiting"
        self.quit()

    def quit(self):
        gtk.main_quit()

    def mainloop(self):
        gtk.main()

    def _update_window_list(self, *args):
        prop_set(self._real_root, "_NET_CLIENT_LIST",
                 ["window"], self._windows.window_list())
        # This is a lie, but we don't maintain a stacking order, so...
        prop_set(self._real_root, "_NET_CLIENT_LIST_STACKING",
                 ["window"], self._windows.window_list())

    def _dispatch_gdk_event(self, event, user_data):
        # This function is called for every event GDK sees.  Most of them we
        # want to just pass on to GTK, but some we are especially interested
        # in...
        handlers = {
            gtk.gdk.PROPERTY_NOTIFY: self._dispatch_property_notify,
            gtk.gdk.DESTROY: self._dispatch_destroy,
            gtk.gdk.UNMAP: self._dispatch_unmap,
            gtk.gdk.CLIENT_EVENT: self._dispatch_client_event,
            # I can get CONFIGURE and MAP, but actually I don't care...
            # gtk.gdk.GDK_MAP: self._dispatch_map,
            #gtk.gdk.GDK_CONFIGURE: self._dispatch_configure
            }
        if event.type in handlers:
            handlers[event.type](event)
        gtk.main_do_event(event)

    def _maybe_manage_client(self, gdkwindow):
        # FIXME: totally lame tray setting
        self._windows.maybe_manage(gdkwindow, [self._trays.trays[0]])

    def _handle_root_map_request(self, event):
        self._maybe_manage_client(event.window)

    def _dispatch_property_notify(self, event):
        if event.window in self._windows:
            self._windows[event.window].emit("property-notify-event", event)

    def _dispatch_destroy(self, event):
        if event.window in self._windows:
            self._windows[event.window].emit("destroy-event", event)

    def _dispatch_unmap(self, event):
        if event.window in self._windows:
            self._windows[event.window].emit("unmap-event", event)

    def _setup_ewmh_window(self):
        # Set up a 1x1 invisible unmapped window, with which to participate in
        # EWMH's _NET_SUPPORTING_WM_CHECK protocol.  The only important things
        # about this window are the _NET_SUPPORTING_WM_CHECK property, and
        # its title (which is supposed to be the name of the window manager).

        # NB, GDK will do strange things to this window.  We don't want to use
        # it for anything.  (In particular, it will call XSelectInput on it,
        # which is fine normally when GDK is running in a client, but since it
        # happens to be using the same connection as we the WM, it will
        # clobber any XSelectInput calls that *we* might have wanted to make
        # on this window.)  Also, GDK might silently swallow all events that
        # are detected on it, anyway.
        self._ewmh_window = gtk.gdk.Window(gtk.gdk.get_default_root_window(),
                                           width=1,
                                           height=1,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask=0, # event mask
                                           wclass=gtk.gdk.INPUT_ONLY,
                                           title=self.NAME)
        prop_set(self._ewmh_window, "_NET_SUPPORTING_WM_CHECK",
                 "window", self.ewmh_window)
        prop_set(self._real_root, "_NET_SUPPORTING_WM_CHECK",
                 "window", self.ewmh_window)
