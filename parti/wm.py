import gtk
import gtk.gdk

import parti.selection
import parti.lowlevel
from parti.prop import prop_set
from parti.util import AutoPropGObjectMixin, one_arg_signal

class Wm(AutoPropGObjectMixin, gobject.GObject):
    _NET_SUPPORTED = [
        "_NET_SUPPORTED", # a bit redundant, perhaps...
        "_NET_SUPPORTING_WM_CHECK",
        "_NET_WM_FULL_PLACEMENT",
        "_PARTI_WM_HAS_TABS",
        "_NET_WM_HANDLED_ICONS",
        "_NET_CLIENT_LIST",
        "_NET_CLIENT_LIST_STACKING",
        "_NET_DESKTOP_VIEWPORT",
        "_NET_DESKTOP_GEOMETRY",
        "_NET_NUMBER_OF_DESKTOPS",
        "_NET_DESKTOP_NAMES",
        #FIXME: "_NET_WORKAREA",
        "_NET_ACTIVE_WINDOW",

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
        # (Though it's not clear that any applications actually take advantage
        # of this yet.)
        "_NET_WM_USER_TIME",
        "_NET_WM_USER_TIME_WINDOW",
        # Not fully:
        "WM_HINTS",
        "WM_NORMAL_HINTS",
        "WM_TRANSIENT_FOR",

        # This isn't supported in any particularly meaningful way, but hey.
        "_NET_REQUEST_FRAME_EXTENTS",

        "_NET_WM_WINDOW_TYPE",
        "_NET_WM_WINDOW_TYPE_NORMAL",
        # "_NET_WM_WINDOW_TYPE_DESKTOP",
        # "_NET_WM_WINDOW_TYPE_DOCK",
        # "_NET_WM_WINDOW_TYPE_TOOLBAR",
        # "_NET_WM_WINDOW_TYPE_MENU",
        # "_NET_WM_WINDOW_TYPE_UTILITY",
        # "_NET_WM_WINDOW_TYPE_SPLASH",
        # "_NET_WM_WINDOW_TYPE_DIALOG",
        # "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
        # "_NET_WM_WINDOW_TYPE_POPUP_MENU",
        # "_NET_WM_WINDOW_TYPE_TOOLTIP",
        # "_NET_WM_WINDOW_TYPE_NOTIFICATION",
        # "_NET_WM_WINDOW_TYPE_COMBO",
        # "_NET_WM_WINDOW_TYPE_DND",
        # "_NET_WM_WINDOW_TYPE_NORMAL",

        "_NET_WM_STATE",
        "_NET_WM_STATE_DEMANDS_ATTENTION",
        # More states to support:
        # _NET_WM_STATE_MODAL,
        # _NET_WM_STATE_STICKY,
        # _NET_WM_STATE_MAXIMIZED_VERT,
        # _NET_WM_STATE_MAXIMIZED_HORZ,
        # _NET_WM_STATE_SHADED,
        # _NET_WM_STATE_SKIP_TASKBAR,
        # _NET_WM_STATE_SKIP_PAGER,
        # _NET_WM_STATE_HIDDEN,
        "_NET_WM_STATE_FULLSCREEN",
        # _NET_WM_STATE_ABOVE,
        # _NET_WM_STATE_BELOW,

        # Not at all yet:
        #"_NET_WM_STRUT", "_NET_WM_STRUT_PARTIAL"
        #"_NET_WM_ICON",
        #"_NET_FRAME_EXTENTS",
        #"_NET_CLOSE_WINDOW",
        #"_NET_ACTIVE_WINDOW",
        #"_NET_CURRENT_DESKTOP",
        #"_NET_RESTACK_WINDOW",
        #"_NET_WM_DESKTOP",
        ]

    __gproperties__ = {
        "windows": (gobject.TYPE_PYOBJECT,
                    "Tuple of managed windows (as WindowModels)", "",
                    gobject.PARAM_READABLE),
        }
    __gsignals__ = {
        "new-window": one_arg_signal,
        "child-map-request-event": one_arg_signal,
        "child-configure-request-event": one_arg_signal,
        }

    def __init__(self, name, display=None):
        self._name = name
        if display is None:
            display = gtk.gdk.display_manager_get().get_default_display()
        self._display = display
        self._alt_display = gtk.gdk.Display(self._display.get_name())
        self._root = self._display.get_default_screen().get_root_window()
        self._ewmh_window = None
        
        # Become the Official Window Manager of this year's display:
        self._wm_selection = parti.selection.ManagerSelection(self._display, "WM_S0")
        self._wm_selection.connect("selection-lost", self._lost_wm_selection)
        # May throw AlreadyOwned:
        self._wm_selection.acquire()
        # (If we become a compositing manager, then we will want to do the
        # same thing with the _NET_WM_CM_S0 selection (says EWMH).  AFAICT
        # this basically will just be used by clients to know that they can
        # use RGBA visuals.)

        # Set up the necessary EWMH properties on the root window.
        self._setup_ewmh_window()
        prop_set(self._root, "_NET_SUPPORTED",
                 ["atom"], self._NET_SUPPORTED)
        prop_set(self._root, "_NET_DESKTOP_VIEWPORT",
                 ["u32"], [0, 0])

        # Okay, ready to select for SubstructureRedirect and then load in all
        # the existing clients.
        self._root.set_data("parti-route-events-to", self)
        parti.lowlevel.substructureRedirect(self._root)

        for w in parti.lowlevel.get_children(self._root):
            # Checking for FOREIGN here filters out anything that we've
            # created ourselves (like, say, the world window), and checking
            # for mapped filters out any withdrawn windows.
            if (w.get_window_type() == gtk.gdk.WINDOW_FOREIGN
                and parti.lowlevel.is_mapped(w)):
                self._manage_client(w)

        # FIXME:

        # Need viewport abstraction for _NET_CURRENT_DESKTOP...
        # Tray's need to provide info for _NET_ACTIVE_WINDOW and _NET_WORKAREA
        # (and notifications for both)

        # Need to listen for:
        #   _NET_CLOSE_WINDOW
        #   _NET_ACTIVE_WINDOW
        #   _NET_CURRENT_DESKTOP
        #   _NET_REQUEST_FRAME_EXTENTS
        # Maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_DESKTOP
        #   _NET_WM_STATE

    # This is the key function, where we have detected a new client window,
    # and start managing it.
    def _manage_client(self, gdkwindow):
        if gdkwindow in self._windows:
            # This can happen if a window sends two map requests in quick
            # succession, so that the second MapRequest arrives before we have
            # reparented the window.  FSF Emacs 22.1.50.1 does this, at least.
            print "Cannot manage the same window twice, ignoring"
            return
        # FIXME: totally lame tray setting
        self._windows.manage(gdkwindow, [self._trays.trays[0]])

    def _handle_root_client_message(self, event):
        # FIXME
        pass

    def _lost_wm_selection(self, selection):
        print "Lost WM selection, exiting"
        self.quit()

    def quit(self):
        gtk.main_quit()

    def mainloop(self):
        gtk.main()

    def _handle_root_map_request(self, event):
        print "Found a potential client"
        self._manage_client(event.window)

    def _handle_root_configure_request(self, event):
        # The point of this method is to handle configure requests on
        # withdrawn windows.  We simply allow them to move/resize any way they
        # want.  This is harmless because the window isn't visible anyway (and
        # apps can create unmapped windows with whatever coordinates they want
        # anyway, no harm in letting them move existing ones around), and it
        # means that when the window actually gets mapped, we have more
        # accurate info on what the app is actually requesting.
        if event.window in self._windows:
            self._windows[event.window]._handle_configure_request(event)

        if event.window not in self._windows:
            print "Reconfigure on withdrawn window"
            parti.lowlevel.configureAndNotify(event.window,
                                              event.x, event.y,
                                              event.width, event.height,
                                              event.value_mask)

    def _update_window_list(self, *args):
        prop_set(self._root, "_NET_CLIENT_LIST",
                 ["window"], self._windows.window_list())
        # This is a lie, but we don't maintain a stacking order, so...
        prop_set(self._root, "_NET_CLIENT_LIST_STACKING",
                 ["window"], self._windows.window_list())

    def _update_desktop_list(self, *args):
        prop_set(self._root, "_NET_NUMBER_OF_DESKTOPS",
                 "u32", len(self._trays))
        prop_set(self._root, "_NET_DESKTOP_NAMES",
                 ["utf8"], self._trays.tags())

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
        self._ewmh_window = gtk.gdk.Window(self._root,
                                           width=1,
                                           height=1,
                                           window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                           event_mask=0, # event mask
                                           wclass=gtk.gdk.INPUT_ONLY,
                                           title=self._name)
        prop_set(self._ewmh_window, "_NET_SUPPORTING_WM_CHECK",
                 "window", self._ewmh_window)
        prop_set(self._root, "_NET_SUPPORTING_WM_CHECK",
                 "window", self._ewmh_window)

    # Other global actions:

    def _make_window_pseudoclient(self, win):
        "Used by PseudoclientWindow, only."
        win.set_screen(self._alt_display.get_default_screen())

    def spawn_repl_window(self):
        spawn_repl_window(self,
                          {"wm": self,
                           "windows": self._windows,
                           "trays": self._trays,
                           "lowlevel": parti.lowlevel})

