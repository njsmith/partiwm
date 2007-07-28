import cgitb
import sys

class AutoPropGObjectMixin(object):
    """Mixin for automagic property support in GObjects.

    Make sure this is the first entry on your parent list, so super().__init__
    will work right."""
    def __init__(self):
        super(AutoPropGObjectMixin, self).__init__()
        self._gproperties = {}

    def do_get_property(self, pspec):
        return self._gproperties.get(pspec)

    def do_set_property(self, pspec, value):
        self._gproperties[pspec] = value


def dump_exc():
    print cgitb.text(sys.exc_info())
