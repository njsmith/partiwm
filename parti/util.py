import gobject

class AutoPropGObject(gobject.GObject):
    """GObject with automagic property support.

    Can also be used as a mixin if inheriting from an existing GObject
    subclass.  If so, put this one first in the parent list, so
    super().__init__ will work right."""
    def __init__(self):
        super(MyGObject, self).__init__()
        self._gproperties = {}

    def do_get_property(self, pspec):
        return self._gproperties[pspec]

    def do_set_property(self, pspec, value):
        self._gproperties[pspec] = value
