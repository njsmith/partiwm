import traceback
import sys
import types
import gobject

class AutoPropGObjectMixin(object):
    """Mixin for automagic property support in GObjects.

    Make sure this is the first entry on your parent list, so super().__init__
    will work right."""
    def __init__(self):
        super(AutoPropGObjectMixin, self).__init__()
        self._gproperties = {}

    def _munge_property_name(self, name):
        return name.replace("-", "_")

    def do_get_property(self, pspec):
        getter = "do_get_property_" + self._munge_property_name(pspec.name)
        if hasattr(self, getter):
            return getattr(self, getter)(pspec.name)
        return self._gproperties.get(pspec.name)

    def do_set_property(self, pspec, value):
        self._internal_set_property(pspec.name, value)

    # Exposed for subclasses that wish to set readonly properties --
    # .set_property (the public api) will fail, but the property can still be
    # modified via this method.
    def _internal_set_property(self, name, value):
        setter = "do_set_property_" + self._munge_property_name(name)
        if hasattr(self, setter):
            getattr(self, setter)(name, value)
        else:
            self._gproperties[name] = value
        self.notify(name)


def dump_exc():
    """Call this from a except: clause to print a nice traceback."""
    print "".join(traceback.format_exception(*sys.exc_info()))


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
    # base() has no magic to support multiple inheritance, so blow up instead
    # of silently doing the wrong thing.  (Sorry, using MI means you have to
    # think, not just use utilities.)
    assert len(obj.__class__.__bases__) == 1
    return obj.__class__.__base__


# A simple little class whose instances we can stick random bags of attributes
# on.
class LameStruct(object):
    def __repr__(self):
        return ("<%s object, contents: %r>"
                % (type(self).__name__, self.__dict__))

def n_arg_signal(n):
    return (gobject.SIGNAL_RUN_LAST,
            gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,) * n)
no_arg_signal = n_arg_signal(0)
one_arg_signal = n_arg_signal(1)


def list_accumulator(ihint, return_accu, handler_return):
    if return_accu is None:
        return_accu = []
    return True, return_accu + [handler_return]
