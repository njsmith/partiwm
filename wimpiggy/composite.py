import gobject
from wimpiggy.util import one_arg_signal, AutoPropGObjectMixin
from wimpiggy.error import *
from wimpiggy.lowlevel import (xcomposite_redirect_window,
                               xcomposite_unredirect_window,
                               xcomposite_name_window_pixmap,
                               xdamage_start, xdamage_stop,
                               xdamage_acknowledge,
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
        self.invalidate_pixmap()
        self._damage_handle = xdamage_start(window)

        add_event_receiver(self._window, self)

    def destroy(self):
        if not self._already_composited:
            trap.swallow(xcomposite_unredirect_window, self._window)
        trap.swallow(xdamage_stop, self._window, self._damage_handle)
        self._damage_handle = None
        self._contents_handle = None
        remove_event_receiver(self._window, self)
        self._window = None

    def acknowledge_changes(self, x, y, w, h):
        if self._damage_handle is not None:
            xdamage_acknowledge(self._window, self._damage_handle,
                                x, y, w, h)

    def invalidate_pixmap(self):
        print "invalidating named pixmap"
        self._contents_handle = None

    def do_get_property_contents_handle(self, name):
        if self._contents_handle is None:
            print "refreshing named pixmap"
            def set_pixmap():
                handle = xcomposite_name_window_pixmap(self._window)
                self._contents_handle = handle
            trap.swallow(set_pixmap)
        return self._contents_handle

    def do_get_property_contents(self, name):
        handle = self.get_property("contents-handle")
        if handle is None:
            return None
        else:
            return handle.pixmap

    def do_wimpiggy_map_event(self, *args):
        self.invalidate_pixmap()

    def do_wimpiggy_configure_event(self, *args):
        self.invalidate_pixmap()

    def do_wimpiggy_damage_event(self, event):
        self.emit("contents-changed", event)

gobject.type_register(CompositeHelper)
