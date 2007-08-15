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
                             # WINDOW_CHILD is sort of bogus, but it reduces
                             # the amount of magic that GDK will do (e.g.,
                             # WINDOW_TOPLEVELs automatically get a child
                             # window to be used in focus management).
                             window_type=gtk.gdk.WINDOW_CHILD,
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

        assert_raises(TypeError, l.get_pywindow, self.display, 0)

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

    def test_get_children_and_reparent(self):
        d2 = self.clone_display()
        w1 = self.window(self.display)
        w2 = self.window(d2)
        gtk.gdk.flush()

        assert not l.get_children(w1)
        children = l.get_children(self.root())
        xchildren = map(l.get_xwindow, children)
        xwins = map(l.get_xwindow, [w1, w2])
        # GDK creates an invisible child of the root window on each
        # connection, so there are some windows we don't know about:
        for known in xwins:
            assert known in xchildren

        w1.reparent(l.get_pywindow(w1, l.get_xwindow(w2)), 0, 0)
        gtk.gdk.flush()
        assert map(l.get_xwindow, l.get_children(w2)) == [l.get_xwindow(w1)]

    def test_save_set(self):
        w1 = self.window(self.display)
        w2 = self.window(self.display)
        gtk.gdk.flush()
        
        import os
        def do_child(disp_name, xwindow1, xwindow2):
            d2 = gtk.gdk.Display(disp_name)
            w1on2 = l.get_pywindow(d2, xwindow1)
            w2on2 = l.get_pywindow(d2, xwindow2)
            mywin = self.window(d2)
            print "mywin == %s" % l.get_xwindow(mywin)
            w1on2.reparent(mywin, 0, 0)
            w2on2.reparent(mywin, 0, 0)
            gtk.gdk.flush()
            l.XAddToSaveSet(w1on2)
            gtk.gdk.flush()
            # But we don't XAddToSaveSet(w2on2)
        pid = os.fork()
        if not pid:
            # Child
            try:
                do_child(self.display.get_name(), l.get_xwindow(w1), l.get_xwindow(w2))
            finally:
                os._exit(0)
        # Parent
        os.waitpid(pid, 0)
        # Is there a race condition here, where the child exits but the X
        # server doesn't notice until after we send our commands?
        print map(l.get_xwindow, [w1, w2])
        print map(l.get_xwindow, l.get_children(self.root()))
        assert w1 in l.get_children(self.root())
        assert w2 not in l.get_children(self.root())

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
