import gobject
import msvcrt
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

# Returns two socket ids; first is WSASocket-compliant
def socketpair():
    client = WSASocket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                       None, 0, 0)
    if client == ~0:
        raise OSError, "WSASocket: %s" % (WSAGetLastError(),)
    try:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        addr = sockaddr_in()
        addr.sin_family = socket.AF_INET
        addr.sin_port = socket.htons(listener.getsockname()[1])
        addr.sin_addr = socket.htonl(0x7f000001) # 127.0.0.1
        if connect(client, byref(addr), sizeof(addr)):
            raise OSError, "connect: %s" % (WSAGetLastError(),)
        server, (peer_host, peer_port) = listener.accept()
        assert peer_host == "127.0.0.1"
        used_addr = sockaddr_in()
        used_addr_size = c_int(sizeof(sockaddr_in))
        if getsockname(client, byref(used_addr), byref(used_addr_size)):
            raise OSError, "getsockname: %s" % (WSAGetLastError(),)
        assert used_addr_size.value <= sizeof(sockaddr_in)
        assert used_addr.sin_port == socket.htons(peer_port)
        return (client, server.fileno(), server)
    except:
        closesocket(client)
        raise

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

def spawn_with_channel_socket(cmd):
    (child_sock, parent_sock, parent_pysock) = socketpair()
    child_fd = msvcrt.open_osfhandle(child_sock, 0)
    child = subprocess.Popen(cmd, stdin=child_fd, stdout=child_fd, bufsize=0)
    closesocket(child_sock)
    channel = gobject.IOChannel.__new__(gobject.IOChannel)
    channel_c = PyGIOChannel.from_address(id(channel))
    channel_c.channel = g_io_channel_win32_new_socket(parent_sock)
    return channel, parent_pysock

def try_spawn_with_channel():
    mainloop = gobject.MainLoop()
    channel, ref = spawn_with_channel(["cmd.exe"])
    to_write = ["dir\nexit\n"]
    def event(source, flags):
        if flags & gobject.IO_OUT:
            print "writing"
            to_write[0] = to_write[0][channel.write(to_write[0]):]
            channel.flush()
            print "still to write: ", to_write[0]
            if not to_write[0]:
                channel.add_watch(gobject.IO_IN | gobject.IO_HUP, event)
                return False
        if flags & gobject.IO_IN:
            print "Got data: %s" % channel.read(100)
        elif flags & gobject.IO_HUP:
            print "Connection lost"
            mainloop.quit()
        return True
    channel.add_watch(gobject.IO_OUT | gobject.IO_IN | gobject.IO_HUP,
                      event)
    mainloop.run()
    channel.close()

if __name__ == "__main__":
    try_spawn_with_channel_socket()
