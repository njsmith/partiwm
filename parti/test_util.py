from parti.test import *
import gobject
import parti.util

class TestUtil(object):
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

class APTestClass(parti.util.AutoPropGObjectMixin, gobject.GObject):
    __gproperties__ = {
        "readwrite": (gobject.TYPE_PYOBJECT,
                      "blah", "baz", gobject.PARAM_READWRITE),
        "readonly": (gobject.TYPE_PYOBJECT,
                      "blah", "baz", gobject.PARAM_READABLE),
        }
gobject.type_register(APTestClass)

class TestAutoPropMixin(object):
    def test_main(self):
        obj = APTestClass()
        assert obj.get_property("readwrite") is None
        def setit(o):
            o.set_property("readwrite", "blah")
        assert_emits(setit, obj, "notify::readwrite")
        assert obj.get_property("readwrite") == "blah"

    def test_readonly(self):
        obj = APTestClass()
        assert obj.get_property("readonly") is None
        assert_raises(TypeError,
                      obj.set_property, "readonly", "blah")
        def setit(o):
            o._internal_set_property("readonly", "blah")
        assert_emits(setit, obj, "notify::readonly")
        assert obj.get_property("readonly") == "blah"
