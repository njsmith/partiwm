import gtk
import gobject

from sets import ImmutableSet

from wimpiggy.error import *
import wimpiggy.selection
from wimpiggy.world_window import WorldWindow
import wimpiggy.lowlevel
from wimpiggy.prop import prop_set
from wimpiggy.util import no_arg_signal, one_arg_signal

from wimpiggy.window import WindowModel, Unmanageable

class Wm(gobject.GObject):
    _NET_SUPPORTED = [
        "_NET_SUPPORTED", # a bit redundant, perhaps...
        "_NET_SUPPORTING_WM_CHECK",
        "_NET_WM_FULL_PLACEMENT",
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
        "_NET_WM_STRUT",
        "_NET_WM_STRUT_PARTIAL"
        "_NET_WM_ICON",

        # These aren't supported in any particularly meaningful way, but hey.
        "_NET_FRAME_EXTENTS",

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
        "_NET_WM_STATE_SKIP_TASKBAR",
        "_NET_WM_STATE_SKIP_PAGER",
        "_NET_WM_STATE_HIDDEN",
        "_NET_WM_STATE_FULLSCREEN",
        # _NET_WM_STATE_ABOVE,
        # _NET_WM_STATE_BELOW,

        # Not at all yet:
        #"_NET_REQUEST_FRAME_EXTENTS",
        #"_NET_CLOSE_WINDOW",
        #"_NET_CURRENT_DESKTOP",
        #"_NET_RESTACK_WINDOW",
        #"_NET_WM_DESKTOP",
        ]

    __gproperties__ = {
        "windows": (gobject.TYPE_PYOBJECT,
                    "Set of managed windows (as WindowModels)", "",
                    gobject.PARAM_READABLE),
        "toplevel": (gobject.TYPE_PYOBJECT,
                     "Toplevel container widget for the display", "",
                     gobject.PARAM_READABLE),
        }
    __gsignals__ = {
        # Public use:
        # A new window has shown up:
        "new-window": one_arg_signal,
        # You can emit this to cause the WM to quit, or the WM may
        # spontaneously raise it if another WM takes over the display:
        "quit": no_arg_signal,
        # Emit this when the list of desktop names has changed:
        "desktop-list-changed": one_arg_signal,

        # Mostly intended for internal use:
        "child-map-request-event": one_arg_signal,
        "child-configure-request-event": one_arg_signal,
        "wimpiggy-focus-in-event": one_arg_signal,
        "wimpiggy-focus-out-event": one_arg_signal,
        "wimpiggy-client-message-event": one_arg_signal,
        }

    def __init__(self, name, replace_other_wm, display=None):
        gobject.GObject.__init__(self)

        self._name = name
        if display is None:
            display = gtk.gdk.display_manager_get().get_default_display()
        self._display = display
        self._alt_display = gtk.gdk.Display(self._display.get_name())
        self._root = self._display.get_default_screen().get_root_window()
        self._ewmh_window = None
        
        self._windows = {}
        # EWMH says we have to know the order of our windows oldest to
        # youngest...
        self._windows_in_order = []

        # Become the Official Window Manager of this year's display:
        self._wm_selection = wimpiggy.selection.ManagerSelection(self._display, "WM_S0")
        self._wm_selection.connect("selection-lost", self._lost_wm_selection)
        # May throw AlreadyOwned:
        if replace_other_wm:
            mode = self._wm_selection.FORCE
        else:
            mode = self._wm_selection.IF_UNOWNED
        self._wm_selection.acquire(mode)
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

        # Load up our full-screen widget
        self._world_window = WorldWindow()
        self.notify("toplevel")
        self._world_window.show_all()

        # Okay, ready to select for SubstructureRedirect and then load in all
        # the existing clients.
        wimpiggy.lowlevel.add_event_receiver(self._root, self)
        wimpiggy.lowlevel.substructureRedirect(self._root)

        for w in wimpiggy.lowlevel.get_children(self._root):
            # Checking for FOREIGN here filters out anything that we've
            # created ourselves (like, say, the world window), and checking
            # for mapped filters out any withdrawn windows.
            if (w.get_window_type() == gtk.gdk.WINDOW_FOREIGN
                and not wimpiggy.lowlevel.is_override_redirect(w)
                and wimpiggy.lowlevel.is_mapped(w)):
                print "Wm managing pre-existing child"
                self._manage_client(w)

        # Also watch for focus change events on the root window
        wimpiggy.lowlevel.selectFocusChange(self._root)

        # FIXME:
        # Need viewport abstraction for _NET_CURRENT_DESKTOP...
        # Tray's need to provide info for _NET_ACTIVE_WINDOW and _NET_WORKAREA
        # (and notifications for both)

    def do_get_property(self, pspec):
        if pspec.name == "windows":
            return ImmutableSet(self._windows.itervalues())
        elif pspec.name == "toplevel":
            return self._world_window
        else:
            assert False

    # This is in some sense the key entry point to the entire WM program.  We
    # have detected a new client window, and start managing it:
    def _manage_client(self, gdkwindow):
        assert gdkwindow not in self._windows
        try:
            win = WindowModel(self._root, gdkwindow)
        except Unmanageable:
            print "Window disappeared on us, never mind"
            return
        win.connect("unmanaged", self._handle_client_unmanaged)
        self._windows[gdkwindow] = win
        self._windows_in_order.append(gdkwindow)
        self.notify("windows")
        self._update_window_list()
        self.emit("new-window", win)

    def _handle_client_unmanaged(self, window, wm_exiting):
        gdkwindow = window.get_property("client-window")
        assert gdkwindow in self._windows
        del self._windows[gdkwindow]
        self._windows_in_order.remove(gdkwindow)
        self._update_window_list()
        self.notify("windows")

    def _update_window_list(self, *args):
        # Ignore errors because not all the windows may still exist; if so,
        # then it's okay to leave the lists out of date for a moment, because
        # in a moment we'll get a signal telling us about the window that
        # doesn't exist anymore, will remove it from the list, and then call
        # _update_window_list again.
        trap.swallow(prop_set, self._root, "_NET_CLIENT_LIST",
                     ["window"], self._windows_in_order)
        # This is a lie, but we don't maintain a stacking order, so...
        trap.swallow(prop_set, self._root, "_NET_CLIENT_LIST_STACKING",
                     ["window"], self._windows_in_order)

    def do_wimpiggy_client_message_event(self, event):
        # FIXME
        # Need to listen for:
        #   _NET_CLOSE_WINDOW
        #   _NET_ACTIVE_WINDOW
        #   _NET_CURRENT_DESKTOP
        #   _NET_REQUEST_FRAME_EXTENTS
        #   _NET_WM_PING responses
        # and maybe:
        #   _NET_RESTACK_WINDOW
        #   _NET_WM_DESKTOP
        #   _NET_WM_STATE
        pass

    def _lost_wm_selection(self, selection):
        print "Lost WM selection, exiting"
        self.emit("quit")

    def do_quit(self):
        for win in list(self._windows.itervalues()):
            win.unmanage(True)

    def do_child_map_request_event(self, event):
        print "Found a potential client"
        self._manage_client(event.window)

    def do_child_configure_request_event(self, event):
        # The point of this method is to handle configure requests on
        # withdrawn windows.  We simply allow them to move/resize any way they
        # want.  This is harmless because the window isn't visible anyway (and
        # apps can create unmapped windows with whatever coordinates they want
        # anyway, no harm in letting them move existing ones around), and it
        # means that when the window actually gets mapped, we have more
        # accurate info on what the app is actually requesting.
        if event.window in self._windows:
            return
        print "Reconfigure on withdrawn window"
        trap.swallow(wimpiggy.lowlevel.configureAndNotify,
                     event.window, event.x, event.y,
                     event.width, event.height,
                     event.value_mask)

    def do_wimpiggy_focus_in_event(self, event):
        # The purpose of this function is to detect when the focus mode has
        # gone to PointerRoot or None, so that it can be given back to
        # something real.  This is easy to detect -- a FocusIn event with
        # detail PointerRoot or None is generated on the root window.
        if event.detail in (wimpiggy.lowlevel.const["NotifyPointerRoot"],
                            wimpiggy.lowlevel.const["NotifyDetailNone"]):
            self._world_window.reset_x_focus()

    def do_wimpiggy_focus_out_event(self, event):
        wimpiggy.lowlevel.printFocus(self._display)

    def do_desktop_list_changed(self, desktops):
        prop_set(self._root, "_NET_NUMBER_OF_DESKTOPS", "u32", len(desktops))
        prop_set(self._root, "_NET_DESKTOP_NAMES", ["utf8"], desktops)

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

gobject.type_register(Wm)
