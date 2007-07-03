import gtk
import gtk.gdk
import parti.tray

class SimpleTabTray(parti.tray.Tray):
    def __init__(self, trayset, tag, config):
        super(SimpleTabTray, self).__init__(trayset, tag, config)
        self.windows = []

    def windows(self):
        return set(self.windows)
