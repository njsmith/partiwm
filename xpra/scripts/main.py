import gobject
import sys
import os
import stat
import socket
import subprocess
from optparse import OptionParser

import xpra
from xpra.bencode import bencode
from xpra.address import (sockdir, sockpath,
                          server_state, LIVE, DEAD, UNKNOWN)

def nox():
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]
    import warnings
    warnings.filterwarnings("ignore", "could not open display")

def main(cmdline):
    parser = OptionParser(version="xpra v%s" % xpra.__version__,
                          usage=("\n"
                                 + "\t%prog start DISPLAY\n"
                                 + "\t%prog attach DISPLAY\n"
                                 + "\t%prog stop DISPLAY\n"
                                 + "\t%prog list\n"
                                 + "\t%prog upgrade DISPLAY"))
    parser.add_option("--no-daemon", action="store_false",
                      dest="daemon", default=True,
                      help="Don't daemonize when running as a server")
    parser.add_option("--remote-xpra", action="store",
                      dest="remote_xpra", default="xpra",
                      help="How to run 'xpra' on the remote host")
    (options, args) = parser.parse_args(cmdline[1:])

    if not args:
        parser.error("need a mode")

    mode = args[0]
    if mode in ("start", "upgrade"):
        nox()
        from xpra.scripts.server import run_server
        run_server(parser, options, mode, args[1:])
    elif mode == "attach":
        run_client(parser, options, args[1:])
    elif mode == "stop":
        nox()
        run_stop(parser, options, args[1:])
    elif mode == "list":
        run_list(parser, options, args[1:])
    elif mode == "_proxy":
        nox()
        run_proxy(parser, options, args[1:])
    else:
        parser.error("invalid mode '%s'" % mode)

def client_sock(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("connect to what?")
    display_name = extra_args[0]
    if display_name.startswith("ssh:"):
        (_, host, display) = display_name.split(":", 2)
        display = ":" + display
        (a, b) = socket.socketpair()
        remote_xpra = opts.remote_xpra.split()
        p = subprocess.Popen(["ssh", host, "-e", "none"]
                             + remote_xpra + ["_proxy", display],
                             stdin=b.fileno(), stdout=b.fileno(),
                             bufsize=0)
        return a
    else:
        path = sockpath(display_name)
        sock = socket.socket(socket.AF_UNIX)
        sock.connect(path)
        return sock

def run_client(parser, opts, extra_args):
    from xpra.client import XpraClient
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    sock = client_sock(parser, opts, extra_args)
    app = XpraClient(sock)
    sys.stdout.write("Attached\n")
    app.run()

def run_proxy(parser, opts, extra_args):
    from xpra.proxy import XpraProxy
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    app = XpraProxy(0, 1, client_sock(parser, opts, extra_args))
    app.run()

def run_stop(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    display_name = extra_args[0]
    magic_string = bencode(["hello", []]) + bencode(["shutdown-server"])

    sock = client_sock(parser, opts, extra_args)
    sock.sendall(magic_string)
    while sock.recv(4096):
        pass
    final_state = server_state(display_name)
    if final_state is DEAD:
        print "xpra at %s has exited." % display_name
        sys.exit(0)
    elif final_state is UNKNOWN:
        print ("How odd... I'm not sure what's going on with xpra at %s"
               % display_name)
        sys.exit(1)
    elif final_state is LIVE:
        print "Failed to shutdown xpra at %s" % display_name
        sys.exit(1)
    else:
        assert False

def run_list(parser, opts, extra_args):
    if extra_args:
        parser.error("too many arguments for mode")
    results = []
    potential_socket_leafs = os.listdir(sockdir())
    for leaf in potential_socket_leafs:
        full = os.path.join(sockdir(), leaf)
        if stat.S_ISSOCK(os.stat(full).st_mode):
            state = server_state(full)
            results.append((state, leaf))
    if not results:
        sys.stdout.write("No xpra sessions found\n")
    else:
        sys.stdout.write("Found the following xpra sessions:\n")
        for state, leaf in results:
            sys.stdout.write("\t%s session at %s" % (state, leaf))
            if state is DEAD:
                try:
                    os.unlink(os.path.join(sockdir(), leaf))
                except OSError:
                    pass
                else:
                    sys.stdout.write(" (cleaned up)")
            sys.stdout.write("\n")
