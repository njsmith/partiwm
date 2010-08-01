XPRA_LOCAL_SERVERS_SUPPORTED = False
DEFAULT_SSH_CMD = "plink"

from xpra.platform.win32pipe import spawn_with_channel

from xpra.platform.win32clipboard import ClipboardProtocolHelper

class ClientExtras(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb

    def handshake_complete(self, capabilities):
        pass
