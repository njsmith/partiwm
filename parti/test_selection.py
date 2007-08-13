from parti.test import *
from parti.selection import ManagerSelection, AlreadyOwned
import parti.lowlevel

import struct

class TestSelection(TestWithX):
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

    def test_notification(self):
        m = ManagerSelection(self.display, "WM_S0")
        root1 = self.display.get_default_screen().get_root_window()
        d2 = self.clone_display()
        root2 = d2.get_default_screen().get_root_window()
        root2.set_events(gtk.gdk.ALL_EVENTS_MASK)
        self.client_event = None

        # There is probably a less brute-force way to get this, but whatever.
        def event_handler(event):
            if (event.type == gtk.gdk.CLIENT_EVENT
                and event.window is root2):
                assert self.client_event is None
                self.client_event = event
                gtk.gdk.event_handler_set(gtk.main_do_event)
                gtk.main_quit()
            gtk.main_do_event(event)
        gtk.gdk.event_handler_set(event_handler)

        assert not m.owned()
        assert self.client_event is None
        m.acquire()
        gtk.main()
        assert self.client_event is not None
        assert self.client_event.window is root2
        assert self.client_event.message_type == "MANAGER"
        assert self.client_event.data_format == 32
        # FIXME FILE GDK-BUG: on a 64-bit machine, when data_format==32 the
        # underlying XClientMessageEvent.data ends up with the 5 4-byte
        # integers dumped into 5 8-byte integers.  Then GDK appears to read
        # them out as 20 1-byte characters (or similar), so it chops the
        # actual data in half; in fact self.client_event.data has two and a
        # half longs in it...
        # (This will currently fail on 32-bit systems, just to remind us.)
        assert (struct.unpack("@l", self.client_event.data[8:16])[0]
                == parti.lowlevel.get_xatom(self.display, "WM_S0"))

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
