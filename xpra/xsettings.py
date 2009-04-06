import gobject
import gtk
from wimpiggy.error import *
from wimpiggy.util import no_arg_signal, one_arg_signal
from wimpiggy.selection import ManagerSelection
from wimpiggy.prop import prop_set, prop_get
from wimpiggy.lowlevel import (myGetSelectionOwner, const, get_pywindow,
                               add_event_receiver, remove_event_receiver,
                               get_xatom)
from wimpiggy.log import Logger
log = Logger()

class XSettingsManager(object):
    def __init__(self, settings_blob):
        self._selection = ManagerSelection(gtk.gdk.display_get_default(),
                                           "_XSETTINGS_S0")
        # Technically I suppose ICCCM says we should use FORCE, but it's not
        # like a window manager where you have to wait for the old wm to clean
        # things up before you can do anything... as soon as the selection is
        # gone, the settings are gone. (Also, if we're stealing from
        # ourselves, we probably don't clean up the window properly.)
        self._selection.acquire(self._selection.FORCE_AND_RETURN)
        self._window = self._selection.window()
        self._set_blob_in_place(settings_blob)

    # This is factored out as a separate function to make it easier to test
    # XSettingsWatcher:
    def _set_blob_in_place(self, settings_blob):
        prop_set(self._window, "_XSETTINGS_SETTINGS", "xsettings-settings",
                 settings_blob)

class XSettingsWatcher(gobject.GObject):
    __gsignals__ = {
        "xsettings-changed": no_arg_signal,

        "wimpiggy-property-notify-event": one_arg_signal,
        "wimpiggy-client-message-event": one_arg_signal,
        }
    def __init__(self):
        gobject.GObject.__init__(self)
        self._clipboard = gtk.Clipboard(gtk.gdk.display_get_default(),
                                        "_XSETTINGS_S0")
        self._current = None
        self._root = self._clipboard.get_display().get_default_screen().get_root_window()
        add_event_receiver(self._root, self)
        self._add_watch()
        
    def _owner(self):
        owner_x = myGetSelectionOwner(self._clipboard, "_XSETTINGS_S0")
        if owner_x == const["XNone"]:
            return None
        try:
            return trap.call(get_pywindow, self._clipboard, owner_x)
        except XError:
            log("X error while fetching owner of XSettings data; ignored")
            return None

    def _add_watch(self):
        owner = self._owner()
        if owner is not None:
            add_event_receiver(owner, self)

    def do_wimpiggy_client_message_event(self, event):
        if (event.window is self._root
            and event.message_type == "MANAGER"
            and event.data[1] == get_xatom(event.window, "_XSETTINGS_S0")):
            log("XSettings manager changed")
            self._add_watch()
            self.emit("xsettings-changed")

    def do_wimpiggy_property_notify_event(self, event):
        if event.atom == "_XSETTINGS_SETTINGS":
            log("XSettings property value changed")
            self.emit("xsettings-changed")

    def _get_settings_blob(self):
        owner = self._owner()
        if owner is None:
            return None
        blob = prop_get(owner, "_XSETTINGS_SETTINGS", "xsettings-settings")
        return blob

    def get_settings_blob(self):
        log("Fetching current XSettings data")
        try:
            return trap.call(self._get_settings_blob)
        except XError, e:
            log("X error while fetching XSettings data; ignored")
            return None
        
gobject.type_register(XSettingsWatcher)
