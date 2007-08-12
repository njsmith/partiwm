import unittest
import subprocess
import os
import gtk.gdk

class TestWithX(unittest.TestCase):
    display_name = ":13"

    def _close_all_displays(self):
        manager = gtk.gdk.display_manager_get()
        for disp in manager.list_displays():
            disp.close()

    def setUp(self):
        self._close_all_displays()
        self._x11 = subprocess.Popen(["Xvfb", self.display_name, "-ac"])
        

    def tearDown(self):
        os.kill(self._x11.pid)
        self._x11.wait()
        manager = gtk.gdk.display_manager_get()
        manager.set_default_display(self._old_display)
