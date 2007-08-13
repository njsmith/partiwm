import unittest
import subprocess
import os
import gtk
import gtk.gdk

# Skip contents of this file when looking for tests
__test__ = False

def assert_raises(exc_class, f, *args, **kwargs):
    try:
        f(*args, **kwargs)
    except exc_class:
        pass
    except:
        raise AssertionError
    else:
        raise AssertionError

class TestWithX(object):
    display_name = ":13"
    display = None

    def setUp(self):
        self._x11 = subprocess.Popen(["Xvfb", self.display_name, "-ac"])
        # This is not a race condition, nor do we need to sleep here, because
        # gtk.gdk.Display is smart enough to silently block until the X server
        # comes up.
        self.display = gtk.gdk.Display(self.display_name)
        gtk.gdk.display_manager_get().get_default_display().close()
        # This line is critical, because many gtk functions (even
        # _for_display/_for_screen functions) actually use the default
        # display, even if only temporarily.  For instance,
        # gtk_clipboard_for_display creates a GtkInvisible, which
        # unconditionally sets its colormap (using the default display) before
        # gtk_clipboard_for_display gets a chance to switch it to the proper
        # display.  So the end result is that we always need a valid default
        # display of some sort:
        gtk.gdk.display_manager_get().set_default_display(self.display)
        print "Opened new display %r" % (self.display,)

    def tearDown(self):
        os.kill(self._x11.pid, 15)
        self._x11.wait()

    def clone_display(self):
        clone = gtk.gdk.Display(self.display.get_name())
        print "Cloned new display %r" % (clone,)
        return clone
