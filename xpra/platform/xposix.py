# Platform-specific code for Posix systems with X11 display.

XPRA_LOCAL_SERVERS_SUPPORTED = True
DEFAULT_SSH_CMD = "ssh"

from wimpiggy.keys import grok_modifier_map

def spawn_with_channel_socket(cmd):
    from socket import socketpair
    import subprocess
    import gobject
    (a, b) = socketpair()
    subprocess.Popen(cmd, stdin=b.fileno(), stdout=b.fileno(), bufsize=0)
    b.close()
    return gobject.IOChannel(a.fileno()), a

from xpra.platform.xclipboard import ClipboardProtocolHelper

from xpra.platform.xsettings import XSettingsWatcher
from xpra.platform.xroot_props import XRootPropWatcher
class ClientExtras(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb

    def handshake_complete(self, capabilities):
        self._xsettings_watcher = XSettingsWatcher()
        self._xsettings_watcher.connect("xsettings-changed",
                                        self._handle_xsettings_changed)
        self._handle_xsettings_changed()
        self._root_props_watcher = RootPropWatcher(self.ROOT_PROPS.keys())
        self._root_props_watcher.connect("root-prop-changed",
                                        self._handle_root_prop_changed)
        self._root_props_watcher.notify_all()
        
    def _handle_xsettings_changed(self, *args):
        blob = self._xsettings_watcher.get_settings_blob()
        if blob is not None:
            self.send(["server-settings", {"xsettings-blob": blob}])

    ROOT_PROPS = {
        "RESOURCE_MANAGER": "resource-manager",
        "PULSE_COOKIE": "pulse-cookie",
        "PULSE_ID": "pulse-id",
        "PULSE_SERVER": "pulse-server",
        }
    
    def _handle_root_prop_changed(self, obj, prop, value):
        assert prop in self.ROOT_PROPS
        if value is not None:
            self.send(["server-settings",
                       {self.ROOT_PROPS[prop]: value.encode("utf-8")}])

