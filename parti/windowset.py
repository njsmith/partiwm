import gobject

from parti.window import Window, Unmanageable

class WindowSet(gobject.GObject):
    __gsignals__ = {
        "window-list-changed": (gobject.SIGNAL_RUN_LAST,
                                gobject.TYPE_NONE, ()),
        }

    def __init__(self):
        super(WindowSet, self).__init__()
        self.l = []
        self.d = {}

    def maybe_manage(self, gdkwindow, tray_hint):
        try:
            window = Window(gdkwindow, tray_hint)
        except Unmanageable:
            return
        window.connect("removed", self._handle_removed)
        self.d[window.client_window] = window
        self.l.append(window.client_window)
        self.emit("window-list-changed")
        return window

    def _handle_removed(self, window):
        if window.client_window in self:
            self.remove(window.client_window)

    def remove(self, window):
        del self.d[window.client_window]
        self.l.remove(window.client_window)
        self.emit("window-list-changed")
        
    def __get__(self, gdkwindow):
        return self.d[gdkwindow]

    def __contains__(self, gdkwindow):
        return gdkwindow in self.d
        
    def window_list(self):
        return self.l

gobject.type_register(WindowSet)
