import os
import os.path
import socket
import errno

def sockdir():
    dir = os.path.expanduser("~/.xpra")
    if not os.path.exists(dir):
        os.mkdir(dir, 0700)
    return dir

def normalize_display_name(display_name):
    if not display_name.startswith(":"):
        display_name = ":" + display_name
    if "." in display_name:
        display_name = display_name[:display_name.rindex(".")]
    return display_name

def sockpath(display_name):
    display_name = normalize_display_name(display_name)
    return os.path.join(sockdir(), display_name)

class ServerSockInUse(Exception):
    pass

LIVE = "LIVE"
DEAD = "DEAD"
UNKNOWN = "UNKNOWN"
def server_state(path):
    if not os.path.exists(path):
        return DEAD
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.connect(path)
    except socket.error, e:
        err = e.args[0]
        if err in (errno.ECONNREFUSED, errno.ENOENT):
            return DEAD
    else:
        sock.close()
        return LIVE
    return UNKNOWN

def server_sock(display_name, clobber):
    path = sockpath(display_name)
    state = server_state(path)
    if state is not DEAD and not clobber:
        raise ServerSockInUse, (state, path)
    if os.path.exists(path):
        os.unlink(path)
    return path

