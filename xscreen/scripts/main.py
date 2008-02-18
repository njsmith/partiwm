import gtk
import sys
import os
import stat
from optparse import OptionParser

import xscreen

# FIXME: make this UI more screen-like?
# FIXME: add ssh support

def main(cmdline):
    parser = OptionParser(version="xscreen v%s" % xscreen.__version__,
                          usage=("\n"
                                 + "\t%prog serve DISPLAY\n"
                                 + "\t%prog connect DISPLAY\n"
                                 + "\t%prog shutdown DISPLAY\n"
                                 + "\t%prog list"))
    parser.add_option("--no-daemon", action="store_false",
                      dest="daemon", default=True,
                      help="Don't daemonize when running as a server")
    (options, args) = parser.parse_args(cmdline[1:])

    if not args:
        parser.error("need a mode")

    mode = args[0]
    if mode == "serve":
        run_server(parser, options, args[1:])
    elif mode == "connect":
        run_client(parser, options, args[1:])
    elif mode == "shutdown":
        run_shutdown(parser, options, args[1:])
    elif mode == "list":
        run_list(parser, options, args[1:])
    elif mode == "_proxy":
        run_proxy(parser, options, args[1:])
    else:
        parser.error("invalid mode '%s'" % mode)

from xscreen.scripts.server import run_server

from xscreen.client import XScreenClient
def run_client(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    app = XScreenClient(extra_args[0])
    gtk.main()

from xscreen.proxy import XScreenProxy
def run_proxy(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    app = XScreenProxy(0, 1, extra_args[0])
    gtk.main()

from xscreen.bencode import bencode
from xscreen.address import (client_sock,
                             sockdir, sockpath,
                             server_state, LIVE, DEAD, UNKNOWN)
def run_shutdown(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    display_name = extra_args[0]
    magic_string = bencode(["hello", []]) + bencode(["shutdown-server"])

    initial_state = server_state(sockpath(display_name))
    if initial_state is DEAD:
        print "No xscreen running at %s; doing nothing" % display_name
        sys.exit(0)

    sock = client_sock(display_name)
    sock.sendall(magic_string)
    while sock.recv(4096):
        pass
    final_state = server_state(display_name)
    if final_state is DEAD:
        print "xscreen at %s has exited." % display_name
        sys.exit(0)
    elif final_state is UNKNOWN:
        print ("How odd... I'm not sure what's going on with xscreen at %s"
               % display_name)
        sys.exit(1)
    elif final_state is LIVE:
        print "Failed to shutdown xscreen at %s" % display_name
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
        sys.stdout.write("No xscreen sessions found\n")
    else:
        sys.stdout.write("Found the following xscreen sessions:\n")
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
