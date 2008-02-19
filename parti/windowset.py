import gtk
import gobject

from wimpiggy.window import WindowModel, Unmanageable

class WindowSet(gobject.GObject):
    __gsignals__ = {
        "window-list-changed": (gobject.SIGNAL_RUN_LAST,
                                gobject.TYPE_NONE, ()),
        }

    def __init__(self):
        gobject.GObject(self).__init__(self)
        self.l = []
        self.d = {}

    def manage(self, gdkwindow, tray_hint):
        assert not gdkwindow in self
        try:
            window = WindowModel(gtk.gdk.get_default_root_window(), gdkwindow, tray_hint)
        except Unmanageable:
            return
        window.connect("unmanaged", self._handle_removed)
        self.d[window.client_window] = window
        self.l.append(window.client_window)
        self.emit("window-list-changed")
        return window

    def _handle_removed(self, window):
        if window.client_window in self:
            self.remove(window.client_window)

    def remove(self, window):
        del self.d[window]
        self.l.remove(window)
        self.emit("window-list-changed")
        
    def __getitem__(self, gdkwindow):
        return self.d[gdkwindow]

    def __contains__(self, gdkwindow):
        return gdkwindow in self.d
        
    def window_list(self):
        return self.l

gobject.type_register(WindowSet)
