import gobject
from parti.util import one_arg_signal
from parti.error import *
from parti.lowlevel import (xcomposite_redirect_window,
                            xcomposite_unredirect_window,
                            xcomposite_name_window_pixmap,
                            xdamage_start,
                            xdamage_stop)

class CompositeHelper(gobject.GObject):
    __gsignals__ = {
        "redraw-needed": one_arg_signal,

        "parti-damage-event": one_arg_signal,
        "parti-map-event": one_arg_signal,
        "parti-configure-event": one_arg_signal,
        }

    def __init__(self, window, already_composited):
        gobject.GObject.__init__(self)
        self._window = window
        self._already_composited = already_composited
        if not self.already_composited:
            xcomposite_redirect_window(window)
        self._pixmap_handle = None
        self._damage_handle = xdamage_start(window)
        self._window.set_data("parti-route-damage-to", self)

    def destroy(self):
        if not self.already_composited:
            trap.swallow(xcomposite_unredirect_window, self._window)
        trap.swallow(xdamage_stop, self._window, self._damage_handle)
        self._pixmap_handle.destroy()
        self._window.set_data("parti-route-damage-to", None)

    def refresh_pixmap(self):
        if self._pixmap_handle is not None:
            self._pixmap_handle.destroy()
        self._pixmap_handle = trap.swallow(xcomposite_name_window_pixmap,
                                           window)

    def do_parti_map_event(self):
        self.refresh_pixmap()

    def do_parti_configure_event(self):
        self.refresh_pixmap()

    def do_parti_damage_event(self, event):
        event.pixmap = self._pixmap_handle.pixmap
        self.emit("redraw-needed", event)

gobject.type_register(CompositeHelper)
