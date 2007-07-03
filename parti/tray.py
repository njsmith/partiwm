class Tray(object):
    def __init__(self, trayset, tag, config):
        self.trayset = trayset
        self.tag = tag
        self.config = config

    def windows(self):
        raise NotImplementedError

    def reconfig(self, config):
        self.config = config

# An arbitrarily ordered set, with key-based access.  (Currently just backed
# by an array.)
class TraySet(object):
    def __init__(self):
        self.trays = []

    def tags(self):
        return [tray.tag for tray in self.trays]

    def has_tag(self, tag):
        for tray in self.trays:
            if tray.tag == tag:
                return true
        return false
    __contains__ = exists

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

    def new(self, tag, type, config):
        assert tag not in self
        tray = type(self, tag, config)
        self.trays.append(tray)
        return tray

    def rename(self, tag, newtag):
        self[tag].tag = newtag
