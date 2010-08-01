XPRA_LOCAL_SERVERS_SUPPORTED = False
DEFAULT_SSH_CMD = "plink"

from xpra.platform.win32pipe import spawn_with_channel

from xpra.platform.win32clipboard import ClipboardProtocolHelper
