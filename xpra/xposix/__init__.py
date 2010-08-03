# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display.

XPRA_LOCAL_SERVERS_SUPPORTED = True
DEFAULT_SSH_CMD = "ssh"
GOT_PASSWORD_PROMPT_SUGGESTION = "Perhaps you need to set up your ssh agent?\n"

from socket import socketpair, SHUT_RD, SHUT_WR
import subprocess
import gobject

def spawn_with_sockets(cmd):
    stdin_child, stdin_parent = socketpair()
    stdout_child, stdout_parent = socketpair()
    subprocess.Popen(cmd, stdin=stdin_child, stdout=stdout_child)
    stdin_child.close()
    stdout_child.close()
    stdin_parent.shutdown(SHUT_RD)
    stdout_parent.shutdown(SHUT_WR)
    return stdin_parent, stdout_parent

def socket_channel(sock):
    return gobject.IOChannel(sock.fileno())

