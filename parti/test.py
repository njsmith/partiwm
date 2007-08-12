import unittest
import subprocess
import os
import gtk.gdk

from nose.tools import *

class TestWithX(unittest.TestCase):
    display_name = ":13"
    display = None

    # Just to make sure we never get into any stupid situations with stale
    # handles.
    def _close_all_displays(self):
        manager = gtk.gdk.display_manager_get()
        for disp in manager.list_displays():
            print "Closing display %r" % (disp,)
            disp.close()

    def setUp(self):
        self._close_all_displays()
        self._x11 = subprocess.Popen(["Xvfb", self.display_name, "-ac"])
        # This is not a race condition, nor do we need to sleep here, because
        # gtk.gdk.Display is smart enough to silently block until the X server
        # comes up.
        self.display = gtk.gdk.Display(self.display_name)
        print "Opened new display %r" % (self.display,)

    def tearDown(self):
        self._close_all_displays()
        os.kill(self._x11.pid, 15)
        self._x11.wait()

    def clone_display(self):
        clone = gtk.gdk.Display(self.display.get_name())
        print "Cloned new display %r" % (clone,)
        return clone
