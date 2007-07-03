import gtk
import gtk.gdk
import parti.tray

class SimpleTabTray(parti.tray.Tray):
    def __init__(self, trayset, tag):
        super(SimpleTabTray, self).__init__(trayset, tag)
        self.windows = []

    def add(self, window):
        window.connect("unmanaged", self._handle_window_departure)
        self.windows.add(window)

    def _handle_window_departure(self, window):
        self.windows.remove(window)

    def windows(self):
        return set(self.windows)
