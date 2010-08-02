# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display.

XPRA_LOCAL_SERVERS_SUPPORTED = True
DEFAULT_SSH_CMD = "ssh"
GOT_PASSWORD_PROMPT_SUGGESTION = "Perhaps you need to set up your ssh agent?\n"

from wimpiggy.keys import grok_modifier_map

def spawn_with_sockets(cmd):
    from socket import socketpair, SHUT_RD, SHUT_WR
    import subprocess
    stdin_child, stdin_parent = socketpair()
    stdout_child, stdout_parent = socketpair()
    subprocess.Popen(cmd, stdin=stdin_child, stdout=stdout_child)
    stdin_child.close()
    stdout_child.close()
    stdin_parent.shutdown(SHUT_RD)
    stdout_parent.shutdown(SHUT_WR)
    return stdin_parent, stdout_parent

def socket_channel(sock):
    import gobject
    return gobject.IOChannel(sock.fileno())

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
        self._root_props_watcher = XRootPropWatcher(self.ROOT_PROPS.keys())
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

