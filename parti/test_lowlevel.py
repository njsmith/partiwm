# This is so incomplete...

from parti.test import *
import parti.lowlevel as l
import gtk

class TestLowlevel(TestWithSession):
    def root(self, disp=None):
        if disp is None:
            disp = self.display
        return disp.get_default_screen().get_root_window()

    def window(self, disp=None):
        if disp is None:
            disp = self.display
        win = gtk.gdk.Window(self.root(disp), width=10, height=10,
                             window_type=gtk.gdk.WINDOW_TOPLEVEL,
                             wclass=gtk.gdk.INPUT_OUTPUT,
                             event_mask=0)
        return win

    def test_get_xwindow_pywindow(self):
        d2 = self.clone_display()
        r1 = self.root()
        r2 = self.root(d2)
        assert r1 is not r2
        assert l.get_xwindow(r1) == l.get_xwindow(r2)
        win = self.window()
        assert l.get_xwindow(r1) != l.get_xwindow(win)
        assert l.get_pywindow(r2, l.get_xwindow(r1)) is r2

    def test_get_display_for(self):
        assert l.get_display_for(self.display) is self.display
        win = self.window()
        assert l.get_display_for(win) is self.display
        assert_raises(TypeError, l.get_display_for, None)
        widg = gtk.Window()
        assert l.get_display_for(widg) is self.display
        clipboard = gtk.Clipboard(self.display, "PRIMARY")
        assert l.get_display_for(clipboard) is self.display

    def test_get_xatom_pyatom(self):
        d2 = self.clone_display()
        asdf1 = l.get_xatom(self.display, "ASDF")
        asdf2 = l.get_xatom(d2, "ASDF")
        ghjk1 = l.get_xatom(self.display, "GHJK")
        ghjk2 = l.get_xatom(d2, "GHJK")
        assert asdf1 == asdf2
        assert ghjk1 == ghjk2
        assert l.get_pyatom(self.display, asdf2) == "ASDF"
        assert l.get_pyatom(d2, ghjk1) == "GHJK"
        
    def test_property(self):
        r = self.root()
        data = "\x01\x02\x03\x04\x05\x06\x07\x08"
        assert_raises(l.NoSuchProperty,
                      l.XGetWindowProperty, r, "ASDF", "ASDF")
        l.XChangeProperty(r, "ASDF", ("GHJK", 32, data))
        assert_raises(l.BadPropertyType,
                      l.XGetWindowProperty, r, "ASDF", "ASDF")
        assert l.XGetWindowProperty(r, "ASDF", "GHJK") == data
        
        l.XDeleteProperty(r, "ASDF")
        assert_raises(l.NoSuchProperty,
                      l.XGetWindowProperty, r, "ASDF", "GHJK")

        badwin = self.window()
        badwin.destroy()
        assert_raises(l.PropertyError,
                      l.XGetWindowProperty, badwin, "ASDF", "ASDF")

        # Giant massive property
        l.XChangeProperty(r, "ASDF",
                          ("GHJK", 32, "\x00" * 512 * (2 ** 10)))
        assert_raises(PropertyOverflow,
                      l.XGetWindowProperty, r, "ASDF", "GHJK")

    def test_add_to_save_set_and_get_children_and_reparent(self):
        d2 = self.clone_display()
        w1 = self.window(self.display)
        w2 = self.window(d2)
        w1on2 = l.get_pywindow(w2, l.get_xwindow(w1))
        w2on1 = l.get_pywindow(w1, l.get_xwindow(w2))

        assert not l.get_children(w1)
        children = l.get_children(self.root())
        xchildren = map(l.get_xwindow, children)
        xwins = map(l.get_xwindow, [w1, w2])
        assert sorted(xchildren) == sorted(xwins)

        w1.reparent(w2on1, 0, 0)
        assert l.get_children(w2)[0] == w1on2
        l.XAddToSaveSet(w1on2)
        d2.close()
        assert l.get_children(self.root())[0] is w1

    def test_is_mapped(self):
        win = self.window()
        assert not l.is_mapped(win)
        win.map()
        assert l.is_mapped(win)

    # TODO:
    #   XSetInputFocus
    #   selectFocusChange
    #   myGetSelectionOwner
    #   sendClientMessage
    #   sendConfigureNotify
    #   configureAndNotify
    #   addXSelectInput
    #   substructureRedirect
    #   send_wm_take_focus
