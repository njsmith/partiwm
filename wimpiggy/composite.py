import gobject
from wimpiggy.util import one_arg_signal, AutoPropGObjectMixin
from wimpiggy.error import *
from wimpiggy.lowlevel import (xcomposite_redirect_window,
                               xcomposite_unredirect_window,
                               xcomposite_name_window_pixmap,
                               xdamage_start, xdamage_stop,
                               add_event_receiver, remove_event_receiver)

class CompositeHelper(AutoPropGObjectMixin, gobject.GObject):
    __gsignals__ = {
        "contents-changed": one_arg_signal,

        "wimpiggy-damage-event": one_arg_signal,
        "wimpiggy-map-event": one_arg_signal,
        "wimpiggy-configure-event": one_arg_signal,
        }

    __gproperties__ = {
        "contents": (gobject.TYPE_PYOBJECT,
                     "", "", gobject.PARAM_READABLE),
        "contents-handle": (gobject.TYPE_PYOBJECT,
                            "", "", gobject.PARAM_READABLE),
        }        

    def __init__(self, window, already_composited):
        super(CompositeHelper, self).__init__()
        self._window = window
        self._already_composited = already_composited
        if not self._already_composited:
            xcomposite_redirect_window(window)
        self.refresh_pixmap()
        self._damage_handle = xdamage_start(window)

        add_event_receiver(self._window, self)

    def destroy(self):
        if not self._already_composited:
            trap.swallow(xcomposite_unredirect_window, self._window)
        trap.swallow(xdamage_stop, self._window, self._damage_handle)
        self._internal_set_property("window-contents-handle", None)
        remove_event_receiver(self._window, self)

    def refresh_pixmap(self):
        def set_pixmap():
            handle = xcomposite_name_window_pixmap(self._window)
            self._internal_set_property("contents-handle", handle)
        trap.swallow(set_pixmap)

    def do_get_property_contents(self, name):
        handle = self.get_property("contents-handle")
        if handle is None:
            return None
        else:
            return handle.pixmap

    def do_wimpiggy_map_event(self, *args):
        self.refresh_pixmap()

    def do_wimpiggy_configure_event(self, *args):
        self.refresh_pixmap()

    def do_wimpiggy_damage_event(self, event):
        event.pixmap_handle = self.get_property("contents-handle")
        self.emit("contents-changed", event)

gobject.type_register(CompositeHelper)
