from wimpiggy.test import *
import gobject
import wimpiggy.util

class TestUtil(object):
    def test_base(self):
        class OldStyle:
            pass
        assert_raises(AssertionError, wimpiggy.util.base, OldStyle)
        assert_raises(AssertionError, wimpiggy.util.base, OldStyle())
        class NewStyleBase(object):
            pass
        class NewStyle(NewStyleBase):
            pass
        class NewStyleMixin(object):
            pass
        class NewStyleMixed(NewStyleBase, NewStyleMixin):
            pass
        assert_raises(AssertionError, wimpiggy.util.base, NewStyle)
        assert wimpiggy.util.base(NewStyle()) is NewStyleBase
        assert_raises(AssertionError, wimpiggy.util.base, NewStyleMixed())

class APTestClass(wimpiggy.util.AutoPropGObjectMixin, gobject.GObject):
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

    def test_custom_getset(self):
        class C(APTestClass):
            def __init__(self):
                APTestClass.__init__(self)
                self.custom = 10
            def do_set_property_readwrite(self, name, value):
                assert name == "readwrite"
                self.custom = value
            def do_get_property_readwrite(self, name):
                assert name == "readwrite"
                return self.custom
        gobject.type_register(C)

        c = C()
        assert c.get_property("readwrite") == 10
        c.set_property("readwrite", 3)
        assert c.custom == 3
        assert c.get_property("readwrite") == 3
        def setit(obj):
            obj._internal_set_property("readwrite", 12)
        assert_emits(setit, c, "notify::readwrite")
        assert c.get_property("readwrite") == 12
        c.custom = 15
        assert c.get_property("readwrite") == 15
