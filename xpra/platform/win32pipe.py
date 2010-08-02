# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import msvcrt
import os
import subprocess
from ctypes import (windll, CDLL, Structure, byref, sizeof, POINTER,
                    c_char, c_short, c_ushort, c_int, c_uint, c_ulong,
                    c_void_p)
from ctypes.wintypes import HANDLE, DWORD
# This also implicitly initializes Winsock:
import socket

WSAGetLastError = windll.Ws2_32.WSAGetLastError
WSAGetLastError.argtypes = ()
WSAGetLastError.restype = c_int

SOCKET = c_int

WSASocket = windll.Ws2_32.WSASocketA
WSASocket.argtypes = (c_int, c_int, c_int, c_void_p, c_uint, DWORD)
WSASocket.restype = SOCKET

closesocket = windll.Ws2_32.closesocket
closesocket.argtypes = (SOCKET,)
closesocket.restype = c_int

class sockaddr_in(Structure):
    _fields_ = [
        ("sin_family", c_short),
        ("sin_port", c_ushort),
        ("sin_addr", c_ulong),
        ("sin_zero", c_char * 8),
        ]

connect = windll.Ws2_32.connect
connect.argtypes = (SOCKET, c_void_p, c_int)
connect.restype = c_int

getsockname = windll.Ws2_32.getsockname
getsockname.argtypes = (SOCKET, c_void_p, POINTER(c_int))
getsockname.restype = c_int

# Returns two sockets; first is WSASocket-compliant and returned as a raw fd,
# second is a Python socket object.
def socketpair_fd_obj():
    client_fd = WSASocket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                       None, 0, 0)
    if client_fd == ~0:
        raise OSError, "WSASocket: %s" % (WSAGetLastError(),)
    try:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        addr = sockaddr_in()
        addr.sin_family = socket.AF_INET
        addr.sin_port = socket.htons(listener.getsockname()[1])
        addr.sin_addr = socket.htonl(0x7f000001) # 127.0.0.1
        if connect(client_fd, byref(addr), sizeof(addr)):
            raise OSError, "connect: %s" % (WSAGetLastError(),)
        server, (peer_host, peer_port) = listener.accept()
        assert peer_host == "127.0.0.1"
        used_addr = sockaddr_in()
        used_addr_size = c_int(sizeof(sockaddr_in))
        if getsockname(client_fd, byref(used_addr), byref(used_addr_size)):
            raise OSError, "getsockname: %s" % (WSAGetLastError(),)
        assert used_addr_size.value <= sizeof(sockaddr_in)
        assert used_addr.sin_port == socket.htons(peer_port)
        return (client_fd, server)
    except:
        closesocket(client_fd)
        raise

def spawn_with_sockets(cmd):
    (stdin_child_sock_fd, stdin_parent) = socketpair_fd_obj()
    stdin_child_fd = msvcrt.open_osfhandle(stdin_child_sock_fd, 0)
    (stdout_child_sock_fd, stdout_parent) = socketpair_fd_obj()
    stdout_child_fd = msvcrt.open_osfhandle(stdout_child_sock_fd, 0)
    subprocess.Popen(cmd, stdin=stdin_child_fd, stdout=stdout_child_fd)
    os.close(stdin_child_fd)
    closesocket(stdin_child_sock_fd)
    os.close(stdout_child_fd)
    closesocket(stdout_child_sock_fd)
    stdin_parent.shutdown(socket.SHUT_RD)
    stdout_parent.shutdown(socket.SHUT_WR)
    return stdin_parent, stdout_parent

GIOChannel = c_void_p

class PyGIOChannel(Structure):
    _fields_ = [
        ("HEAD", c_char * object.__basicsize__),
        ("channel", GIOChannel),
        ("softspace", c_int),
        ]
assert sizeof(PyGIOChannel) == gobject.IOChannel.__basicsize__

glib = CDLL("libglib-2.0-0.dll")
g_io_channel_win32_new_socket = glib.g_io_channel_win32_new_socket
g_io_channel_win32_new_socket.argtypes = (SOCKET,)
g_io_channel_win32_new_socket.restype = GIOChannel

# See: https://bugzilla.gnome.org/show_bug.cgi?id=592992
def socket_channel(sock):
    channel = gobject.IOChannel.__new__(gobject.IOChannel)
    channel_c = PyGIOChannel.from_address(id(channel))
    channel_c.channel = g_io_channel_win32_new_socket(sock.fileno())
    return channel

def try_spawn_with_sockets():
    write_sock, read_sock = spawn_with_sockets(["plink", "-pw", "XXX",
                                                "-t", "njs@192.168.122.1"])
    to_write = ["cat /dev/urandom\n"]

    while True:
        import select
        if to_write[0]:
            (r, w, e) = select.select([read_sock], [write_sock], [read_sock])
        else:
            (r, w, e) = select.select([read_sock], [], [read_sock])
        print (r, w, e)
        if r:
            print repr(read_sock.recv(4096))
        if w:
            to_write[0] = to_write[0][write_sock.send(to_write[0]):]

def try_spawn_with_sockets_gobject():
    mainloop = gobject.MainLoop()
    write_sock, read_sock = spawn_with_sockets(["plink", "-pw", "XXX",
                                                "-t", "njs@192.168.122.1"])
    to_write = ["cat /dev/urandom\n"]

    write_channel = socket_channel(write_sock)
    write_channel.set_encoding(None)
    write_channel.set_buffered(False)
    read_channel = socket_channel(read_sock)
    read_channel.set_encoding(None)
    read_channel.set_buffered(False)
    def event(source, flags):
        if flags & gobject.IO_OUT:
            print "writing"
            to_write[0] = to_write[0][write_channel.write(to_write[0]):]
            #channel.flush()
            print "still to write: ", to_write[0]
            if not to_write[0]:
                return False
        if flags & gobject.IO_IN:
            print "Got data: %s" % repr(read_channel.read(100))
        elif flags & gobject.IO_HUP:
            print "Connection lost"
            mainloop.quit()
        return True
    write_channel.add_watch(gobject.IO_OUT | gobject.IO_HUP,
                            event)
    read_channel.add_watch(gobject.IO_IN | gobject.IO_HUP,
                           event)
    mainloop.run()
    read_channel.close()
    write_channel.close()

if __name__ == "__main__":
    try_spawn_with_sockets_gobject()
