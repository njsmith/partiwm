from parti.test import *
import gobject
import parti.util

class TestUtil(object):
    def test_auto_prop_gobject_mixin(self):
        class Foo(parti.util.AutoPropGObjectMixin, gobject.GObject):
            __gproperties__ = {
                "prop1": (gobject.TYPE_PYOBJECT,
                          "blah", "baz", gobject.PARAM_READWRITE),
                }
        gobject.type_register(Foo)
        f = Foo()
        assert f.get_property("prop1") is None
        f.set_property("prop1", "blah")
        assert f.get_property("prop1") == "blah"

    def test_base(self):
        class OldStyle:
            pass
        assert_raises(AssertionError, parti.util.base, OldStyle)
        assert_raises(AssertionError, parti.util.base, OldStyle())
        class NewStyleBase(object):
            pass
        class NewStyleMixin(object):
            pass
        class NewStyle(NewStyleBase, NewStyleMixin):
            pass
        assert_raises(AssertionError, parti.util.base, NewStyle)
        assert parti.util.base(NewStyle()) is NewStyleBase
