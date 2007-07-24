import gobject
import gtk

class Tray(gtk.Window):
    def __init__(self, trayset, tag):
        super(Tray, self).__init__()
        self.trayset = trayset
        self.tag = tag

    # Pure virtual methods, for children to implement:
    def add(self, window):
        raise NotImplementedError

    def windows(self):
        raise NotImplementedError

    def take_focus(self):
        raise NotImplementedError

    # Magic to interact with X, GTK+, the rest of Parti
    def do_focus_in_event(self, event):
        pass

    def do_focus_out_event(self, event):
        pass

    def do_focus(self):
        pass

# An arbitrarily ordered set, with key-based access.  (Currently just backed
# by an array.)
class TraySet(gobject.GObject):
    __gsignals__ = {
        "tray-set-changed": (gobject.SIGNAL_RUN_LAST,
                             gobject.TYPE_NONE, ()),
        }

    def __init__(self):
        super(TraySet, self).__init__()
        self.trays = []

    def tags(self):
        return [tray.tag for tray in self.trays]

    def has_tag(self, tag):
        for tray in self.trays:
            if tray.tag == tag:
                return true
        return False
    __contains__ = has_tag

    def __getitem__(self, tag):
        tray = self.get(tag)
        if tray is None:
            raise KeyError, tag
        return tag

    def get(self, tag):
        try:
            return self[tag]
        except KeyError:
            return None

    def remove(self, tag):
        for i in range(len(self.trays)):
            if self.trays[i] == tag:
                del self.trays[i]
                self.emit("tray-set-changed")

    def index(self, tag):
        for i in range(len(self.trays)):
            if self.trays[i] == tag:
                return i
        raise KeyError, tag

    def __len__(self):
        return len(self.trays)

    def move(self, tag, newidx):
        assert newidx < len(self)
        oldidx = self.index(tag)
        tray = self.trays.pop(oldidx)
        self.trays.insert(newidx, tray)
        self.emit("tray-set-changed")

    def new(self, tag, type):
        assert tag not in self
        assert isinstance(tag, unicode)
        tray = type(self, tag)
        self.trays.append(tray)
        self.emit("tray-set-changed")
        return tray

    def rename(self, tag, newtag):
        self[tag].tag = newtag
        self.emit("tray-set-changed")

gobject.type_register(TraySet)
