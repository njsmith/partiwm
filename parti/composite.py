import gobject
from parti.util import one_arg_signal, AutoPropGObjectMixin
from parti.error import *
from parti.lowlevel import (xcomposite_redirect_window,
                            xcomposite_unredirect_window,
                            xcomposite_name_window_pixmap,
                            xdamage_start,
                            xdamage_stop)

class CompositeHelper(AutoPropGObjectMixin, gobject.GObject):
    __gsignals__ = {
        "redraw-needed": one_arg_signal,

        "parti-damage-event": one_arg_signal,
        "parti-map-event": one_arg_signal,
        "parti-configure-event": one_arg_signal,
        }

    __gproperties__ = {
        "window-contents-handle": (gobject.TYPE_PYOBJECT,
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
        self._window.set_data("parti-route-damage-to", self)

    def destroy(self):
        if not self._already_composited:
            trap.swallow(xcomposite_unredirect_window, self._window)
        trap.swallow(xdamage_stop, self._window, self._damage_handle)
        self._internal_set_property("window-contents-handle", None)
        self._window.set_data("parti-route-damage-to", None)

    def refresh_pixmap(self):
        handle = trap.swallow(xcomposite_name_window_pixmap, self._window)
        self._internal_set_property("window-contents-handle", handle)

    def do_parti_map_event(self):
        self.refresh_pixmap()

    def do_parti_configure_event(self):
        self.refresh_pixmap()

    def do_parti_damage_event(self, event):
        event.pixmap_handle = self.get_property("window-contents-handle")
        self.emit("redraw-needed", event)

gobject.type_register(CompositeHelper)
