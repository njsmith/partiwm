from parti.test import *
from parti.error import *
# Need a way to generate X errors...
import parti.lowlevel

import gtk.gdk

class TestError(TestWithSession):
    def cause_badwindow(self):
        root = self.display.get_default_screen().get_root_window()
        win = gtk.gdk.Window(root, width=10, height=10,
                             window_type=gtk.gdk.WINDOW_TOPLEVEL,
                             wclass=gtk.gdk.INPUT_OUTPUT,
                             event_mask=0)
        win.destroy()
        parti.lowlevel.XAddToSaveSet(win)

    def test_call(self):
        trap.call(lambda: 1)
        try:
            trap.call(self.cause_badwindow)
        except XError, e:
            assert e.args == (parti.lowlevel.const["BadWindow"],)

    def test_swallow(self):
        trap.swallow(lambda: 1)
        trap.swallow(self.cause_badwindow)

    def test_assert_out(self):
        def foo():
            assert_raises(AssertionError, trap.assert_out)
        trap.call(foo)
