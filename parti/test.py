import unittest
import subprocess
import sys
import os
import traceback
import gtk
import gtk.gdk

# Skip contents of this file when looking for tests
__test__ = False

def assert_raises(exc_class, f, *args, **kwargs):
    # exc_class can be a tuple.
    try:
        value = f(*args, **kwargs)
    except exc_class:
        pass
    except:
        (cls, e, tb) = sys.exc_info()
        raise AssertionError, (("unexpected exception: %s: %s\n"
                               + "Original traceback:\n%s")
                               % (cls, e, traceback.format_exc()))
    else:
        raise AssertionError, \
              "wanted exception, got normal return (%r)" % (value,)

class TestWithSession(object):
    "A test that runs with its own isolated X11 and D-Bus session."
    display_name = ":13"
    display = None

    def setUp(self):
        self._x11 = subprocess.Popen(["Xvfb-for-parti", self.display_name,
                                      "-ac",
                                      "-audit", "10",
                                      "+extension", "Composite"],
                                     executable="Xvfb")
        # This is not a race condition, nor do we need to sleep here, because
        # gtk.gdk.Display is smart enough to silently block until the X server
        # comes up.
        self.display = gtk.gdk.Display("127.0.0.1" + self.display_name)
        default_display = gtk.gdk.display_manager_get().get_default_display()
        if default_display is not None:
            default_display.close()
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

        self._dbus = subprocess.Popen(["dbus-daemon-for-parti", "--session",
                                       "--nofork", "--print-address"],
                                      executable="dbus-daemon",
                                      stdout=subprocess.PIPE)
        self._dbus_address = self._dbus.stdout.readline().strip()
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = self._dbus_address
        print "Started session D-Bus at %s" % self._dbus_address

    def tearDown(self):
        os.kill(self._x11.pid, 15)
        os.kill(self._dbus.pid, 15)
        self._x11.wait()
        self._dbus.wait()
        # Could do more cleanup here (close X11 connections, unset
        # os.environ["DBUS_SESSION_BUS_ADDRESS"], etc.), but our test runner
        # runs us in a forked off process that will exit immediately after
        # this, so who cares?

    def clone_display(self):
        clone = gtk.gdk.Display(self.display.get_name())
        print "Cloned new display %r" % (clone,)
        return clone
