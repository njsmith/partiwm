import gtk
import gtk.gdk
import parti.lowlevel

# FIXME: use this or remove it

_alternate_connection = None

class PseudoclientWindow(gtk.Window):
    """A gtk.Window that acts like an ordinary client.

    All the wm-magic that would normally accrue to a window created within our
    process is removed."""
    
    # The trick is that we create a second connection to the X server, and use
    # that.
    def __init__(self, *args, **kwargs):
        super(PseudoclientWindow, self).__init__(*args, **kwargs)

        global _alternate_connection
        if _alternate_connection is None:
            name = gtk.gdk.display_get_default().get_name()
            _alternate_connection = parti.lowlevel.gdk_display_open(name)
        self.set_screen(_alternate_connection.get_default_screen())
