from parti.test import *
from parti.selection import ManagerSelection, AlreadyOwned

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

        print m1.owned()
        assert not m1.owned()
        assert not m2.owned()
        m1.acquire()
        print m1.owned()
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
        d2 = self.clone_display()
        root2 = d2.get_default_screen().get_root_window()
        root2.set_events(gtk.gdk.ALL_EVENTS_MASK)
        client_event = None

        # There is probably a less brute-force way to get this, but whatever.
        def event_handler(event):
            if event.type == gtk.gdk.CLIENT_EVENT:
                assert client_event is None
                client_event = event
                gtk.gdk.event_handler_set(gtk.main_do_event)
                gtk.main_quit()
            gtk.main_do_event(event)
        gtk.gdk.event_handler_set(event_handler)
            
        assert not m.owned()
        assert client_event is None
        m.acquire()
        gtk.main()
        assert client_event is not None
        assert client_event.window is root2
