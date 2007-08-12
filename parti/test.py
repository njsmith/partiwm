import unittest
import subprocess
import os
import gtk.gdk

class TestWithX(unittest.TestCase):
    display_name = ":13"
    display = None

    # Just to make sure we never get into any stupid situations with stale
    # handles.
    def _close_all_displays(self):
        manager = gtk.gdk.display_manager_get()
        for disp in manager.list_displays():
            disp.close()

    def setUp(self):
        self._close_all_displays()
        self._x11 = subprocess.Popen(["Xvfb", self.display_name, "-ac"])
        # This is not a race condition, nor do we need to sleep here, because
        # gtk.gdk.Display is smart enough to silently block until the X server
        # comes up.
        self.display = gtk.gdk.Display(self.display_name)

    def tearDown(self):
        os.kill(self._x11.pid)
        self._x11.wait()
        self._close_all_displays()
