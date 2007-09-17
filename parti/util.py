import cgitb
import sys
import types

class AutoPropGObjectMixin(object):
    """Mixin for automagic property support in GObjects.

    Make sure this is the first entry on your parent list, so super().__init__
    will work right."""
    def __init__(self):
        super(AutoPropGObjectMixin, self).__init__()
        self._gproperties = {}

    def do_get_property(self, pspec):
        return self._gproperties.get(pspec.name)

    def do_set_property(self, pspec, value):
        self._internal_set_property(pspec.name, value)

    # Exposed for subclasses that wish to set readonly properties --
    # .set_property (the public api) will fail, but the property can still be
    # modified via this method.
    def _internal_set_property(self, name, value):
        self._gproperties[name] = value
        self.notify(name)


def dump_exc():
    """Call this from a except: clause to print a nice traceback."""
    print cgitb.text(sys.exc_info())


# A little utility to make it slightly terser to call base class methods
# without always running into bugs after tweaking the base class.
# Usage:
#   class Foo(Bar):
#     def foo(self, arg):
#       # Equivalent to: Bar.foo(self, arg)
#       base(self).foo(self, arg)
# This is like a simple version of super, without all the weird magic
# (http://fuhm.net/super-harmful/), the PyGtk bugs (#315079, #351566), etc.
def base(obj):
    # For now disallow base(Foo).<whatever>
    assert not isinstance(obj, type)
    # New-style classes only
    assert not isinstance(obj, types.ClassType)
    assert not isinstance(obj.__class__, types.ClassType)
    return obj.__class__.__base__
