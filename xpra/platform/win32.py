XPRA_LOCAL_SERVERS_SUPPORTED = False
DEFAULT_SSH_CMD = "plink"

def grok_modifier_map(display_source):
    modifier_map = {
        "shift": 1 << 0,
        "lock": 1 << 1,
        "control": 1 << 2,
        "mod1": 1 << 3,
        "mod2": 1 << 4,
        "mod3": 1 << 5,
        "mod4": 1 << 6,
        "mod5": 1 << 7,
        "scroll": 0,
        "num": 0,
        "meta": 0,
        "super": 0,
        "hyper": 0,
        "alt": 0,
        }
    modifier_map["nuisance"] = (modifier_map["lock"]
                                | modifier_map["scroll"]
                                | modifier_map["num"])
    return modifier_map

from xpra.platform.win32pipe import spawn_with_channel_socket

class ClipboardProtocolHelper(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb

    def send_all_tokens(self):
        pass

    def process_clipboard_packet(self, packet):
        packet_type = packet[0]
        if packet_type == "clipboard_request":
            (_, request_id, selection, target) = packet
            self.send(["clipboard-contents-none", request_id, selection])

class ClientExtras(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb

    def handshake_complete(self, capabilities):
        pass
