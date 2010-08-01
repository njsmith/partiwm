XPRA_LOCAL_SERVERS_SUPPORTED = True
DEFAULT_SSH_CMD = "ssh"

def spawn_with_channel_socket(cmd):
    from socket import socketpair
    import subprocess
    import gobject
    (a, b) = socketpair()
    subprocess.Popen(cmd, stdin=b.fileno(), stdout=b.fileno(), bufsize=0)
    b.close()
    return gobject.IOChannel(a.fileno()), a
