"""D-Bus support.  This file would be called dbus.py, except then python's
import mechanism breaks, blah."""

_NAME = "org.vorpus.Parti"
_INTERFACE = "org.vorpus.Parti"
_ROOT = "/org/vorpus/Parti"

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

class PartiDBusService(dbus.service.Object):
    def __init__(self, wm):
        self._wm = wm
        self._bus = dbus.SessionBus(mainloop=DBusGMainLoop())
        self._bus_name = dbus.service.BusName(_NAME, bus=self._bus)
        dbus.service.Object.__init__(self, self._bus_name, _ROOT)

    @dbus.service.method(_INTERFACE,
                         in_signature="", out_signature="")
    def SpawnReplWindow(self):
        self._wm.spawn_repl_window()

def get_parti_proxy():
    bus = dbus.SessionBus(mainloop=DBusGMainLoop())
    obj_proxy = bus.get_object(_NAME, _ROOT)
    iface_proxy = dbus.Interface(obj_proxy, _INTERFACE)
    return iface_proxy