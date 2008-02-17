from parti.test import *
from parti.selection import ManagerSelection, AlreadyOwned
import parti.lowlevel

import struct

class TestSelection(TestWithSession, MockEventReceiver):
    def test_acquisition_stealing(self):
        d1 = self.clone_display()
        d2 = self.clone_display()
        
        m1 = ManagerSelection(d1, "WM_S0")
        m2 = ManagerSelection(d2, "WM_S0")

        selection_lost_fired = {m1: False, m2: False}
        def cb(manager):
            selection_lost_fired[manager] = True
        m1.connect("selection-lost", cb)
        m2.connect("selection-lost", cb)

        assert not m1.owned()
        assert not m2.owned()
        m1.acquire()
        assert m1.owned()
        assert m2.owned()

        assert_raises(AlreadyOwned, m2.acquire)

        assert not selection_lost_fired[m1]
        assert not selection_lost_fired[m2]
        m2.acquire(force=True)
        assert selection_lost_fired[m1]
        assert not selection_lost_fired[m2]

    def do_parti_client_message_event(self, event):
        self.event = event
        gtk.main_quit()
    def test_notification(self):
        m = ManagerSelection(self.display, "WM_S0")
        root1 = self.display.get_default_screen().get_root_window()
        d2 = self.clone_display()
        root2 = d2.get_default_screen().get_root_window()
        root2.set_events(gtk.gdk.STRUCTURE_MASK)
        root2.set_data("parti-route-events-to", self)
        d2.flush()
        self.event = None

        assert not m.owned()
        assert self.event is None
        m.acquire()
        gtk.main()
        assert self.event is not None
        assert self.event.window is root2
        assert self.event.message_type == "MANAGER"
        assert self.event.format == 32
        # FIXME: is there any sensible way to check data[0] (timestamp) and
        # data[2] (window id)?
        # 0 = timestamp
        # FIXME: how to check this?
        # 1 = manager atom
        assert self.event.data[1] == parti.lowlevel.get_xatom(root2, "WM_S0")
        # 2 = window belonging to manager.  We just check that it really is a
        # window.
        assert parti.lowlevel.get_pywindow(root2, self.event.data[2]) is not None
        assert parti.lowlevel.myGetSelectionOwner(root2, "WM_S0") == self.event.data[2]
        # 3, 4 = 0
        assert self.event.data[3] == 0
        assert self.event.data[4] == 0

    def test_conversion(self):
        m = ManagerSelection(self.display, "WM_S0")
        m.acquire()

        d2 = self.clone_display()
        clipboard = gtk.Clipboard(d2, "WM_S0")
        targets = sorted(clipboard.wait_for_targets())
        assert targets == ["MULTIPLE", "TARGETS", "TIMESTAMP", "VERSION"]
        v_data = clipboard.wait_for_contents("VERSION").data
        assert len(v_data) == 8
        assert struct.unpack("@ii", v_data) == (2, 0)
