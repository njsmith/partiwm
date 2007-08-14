import os
import gtk
from parti.test import *

class TestTest(object):
    def test_test_with_session(self):
        assert "DBUS_SESSION_BUS_ADDRESS" not in os.environ
        t = TestWithSession()
        t.setUp()
        assert t.display
        assert gtk.gdk.display_manager_get().get_default_display() is t.display
        c = t.clone_display()
        assert c is not t.display
        assert "DBUS_SESSION_BUS_ADDRESS" in os.environ

    def test_assert_raises(self):
        class FooError(Exception):
            pass
        class BarError(Exception):
            pass
        def raises_foo():
            raise FooError, "aiiieee"
        def raises_bar():
            raise BarError, "arrrggghhh"
        def raises_nothing():
            pass
        def wants_args_raises_foo(*args, **kwargs):
            assert args == (1, 2)
            assert kwargs == {"a": 3, "b": 4}
            raise FooError, "blearrghhh"
        # No exception:
        assert_raises(FooError, raises_foo)
        try:
            # Should raise AssertionError:
            assert_raises(FooError, raises_bar)
            raise FooError
        except AssertionError:
            pass
        try:
            # Should raise AssertionError:
            assert_raises(FooError, raises_nothing)
            raise FooError
        except AssertionError:
            pass
        # No exception:
        assert_raises(FooError, wants_args_raises_foo, 1, 2, a=3, b=4)
        assert_raises(AssertionError, wants_args_raises_foo)
        
