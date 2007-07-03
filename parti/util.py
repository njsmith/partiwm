import gobject

class MyGObject(gobject.GObject):
    "GObject with automagic property support."
    def __init__(self):
        gobject.GObject.__init__(self)
        self._gproperties = {}

    def do_get_property(self, pspec):
        return self._gproperties[pspec]

    def do_set_property(self, pspec, value):
        self._gproperties[pspec] = value
