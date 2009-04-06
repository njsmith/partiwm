import gtk
import gobject
from wimpiggy.util import one_arg_signal
from wimpiggy.lowlevel import add_event_receiver

from wimpiggy.log import Logger
log = Logger()

class RootPropWatcher(gobject.GObject):
    __gsignals__ = {
        "root-prop-changed": one_arg_signal,

        "wimpiggy-property-notify-event": one_arg_signal,
        }

    def __init__(self, props):
        gobject.GObject.__init__(self)
        self._props = props
        self._root = gtk.gdk.get_default_root_window()
        add_event_receiver(self._root, self)

    def do_wimpiggy_property_notify_event(self, event):
        if event.atom in self._props:
            self.emit("root-prop-changed", event.atom)

gobject.type_register(RootPropWatcher)
