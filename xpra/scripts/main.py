# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import sys
import os
import socket
import subprocess
import time
from optparse import OptionParser
import logging

import xpra
from xpra.bencode import bencode
from xpra.dotxpra import DotXpra

def nox():
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]
    # This is an error on Fedora/RH, so make it an error everywhere so it will
    # be noticed:
    import warnings
    warnings.filterwarnings("error", "could not open display")

def main(script_file, cmdline):
    #################################################################
    ## NOTE NOTE NOTE
    ##
    ## If you modify anything here, then remember to update the man page
    ## (xpra.1) as well!
    ##
    ## NOTE NOTE NOTE
    #################################################################
    parser = OptionParser(version="xpra v%s" % xpra.__version__,
                          usage=("\n"
                                 + "\t%prog start DISPLAY\n"
                                 + "\t%prog attach [DISPLAY]\n"
                                 + "\t%prog stop [DISPLAY]\n"
                                 + "\t%prog list\n"
                                 + "\t%prog upgrade DISPLAY"))
    parser.add_option("--start-child", action="append",
                      dest="children", metavar="CMD",
                      help="program to spawn in new server (may be repeated)")
    parser.add_option("--exit-with-children", action="store_true",
                      dest="exit_with_children", default=False,
                      help="Terminate server when --start-child command(s) exit")
    parser.add_option("--no-daemon", action="store_false",
                      dest="daemon", default=True,
                      help="Don't daemonize when running as a server")
    parser.add_option("--bind-tcp", action="store",
                      dest="bind_tcp", default=None,
                      metavar="[HOST]:PORT",
                      help="Listen for connections over TCP (insecure)")
    parser.add_option("--remote-xpra", action="store",
                      dest="remote_xpra", default=None, metavar="CMD",
                      help="How to run 'xpra' on the remote host")
    parser.add_option("-d", "--debug", action="store",
                      dest="debug", default=None, metavar="FILTER1,FILTER2,...",
                      help="List of categories to enable debugging for (or \"all\")")
    (options, args) = parser.parse_args(cmdline[1:])

    if not args:
        parser.error("need a mode")

    logging.root.setLevel(logging.INFO)
    if options.debug is not None:
        categories = options.debug.split(",")
        for cat in categories:
            if cat == "all":
                logger = logging.root
            else:
                logger = logging.getLogger(cat)
            logger.setLevel(logging.DEBUG)
    logging.root.addHandler(logging.StreamHandler(sys.stderr))

    mode = args.pop(0)
    if mode in ("start", "upgrade"):
        nox()
        from xpra.scripts.server import run_server
        run_server(parser, options, mode, script_file, args)
    elif mode == "attach":
        run_client(parser, options, args)
    elif mode == "stop":
        nox()
        run_stop(parser, options, args)
    elif mode == "list":
        run_list(parser, options, args)
    elif mode == "_proxy":
        nox()
        run_proxy(parser, options, args)
    else:
        parser.error("invalid mode '%s'" % mode)

def pick_display(parser, extra_args):
    if len(extra_args) == 0:
        # Pick a default server
        sockdir = DotXpra()
        servers = sockdir.sockets()
        live_servers = [display
                        for (state, display) in servers
                        if state is DotXpra.LIVE]
        if len(live_servers) == 0:
            parser.error("cannot find a live server to connect to")
        elif len(live_servers) == 1:
            return live_servers[0]
        else:
            parser.error("there are multiple servers running, please specify")
    elif len(extra_args) == 1:
        return extra_args[0]
    else:
        parser.error("too many arguments")

def client_sock(parser, opts, display_name):
    if display_name.startswith("ssh:"):
        sshspec = display_name[len("ssh:"):]
        if ":" in sshspec:
            (host, display) = sshspec.split(":", 1)
            display_args = [":" + display]
        else:
            host = sshspec
            display_args = []
        (a, b) = socket.socketpair()
        if opts.remote_xpra is not None:
            remote_xpra = opts.remote_xpra.split()
        else:
            remote_xpra = ["$HOME/.xpra/run-xpra"]
        
        p = subprocess.Popen(["ssh", host, "-e", "none"]
                             + remote_xpra + ["_proxy"] + display_args,
                             stdin=b.fileno(), stdout=b.fileno(),
                             bufsize=0)
        return a, False
    elif display_name.startswith(":"):
        sockdir = DotXpra()
        sock = socket.socket(socket.AF_UNIX)
        sock.connect(sockdir.socket_path(display_name))
        return sock, True
    elif display_name.startswith("tcp:"):
        host_spec = display_name[4:]
        (host, port) = host_spec.split(":", 1)
        if host == "":
            host = "127.0.0.1"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, int(port)))
        return sock, True
    else:
        parser.error("unknown format for display name")
        

def run_client(parser, opts, extra_args):
    from xpra.client import XpraClient
    sock, local = client_sock(parser, opts, pick_display(parser, extra_args))
    app = XpraClient(sock)
    sys.stdout.write("Attached\n")
    app.run()

def run_proxy(parser, opts, extra_args):
    from xpra.proxy import XpraProxy
    app = XpraProxy(0, 1, client_sock(parser, opts, pick_display(parser, extra_args))[0])
    app.run()

def run_stop(parser, opts, extra_args):
    magic_string = bencode(["hello", []]) + bencode(["shutdown-server"])

    display_name = pick_display(parser, extra_args)
    sock, local = client_sock(parser, opts, display_name)
    sock.sendall(magic_string)
    while sock.recv(4096):
        pass
    if local:
        sockdir = DotXpra()
        for i in xrange(6):
            final_state = sockdir.server_state(display_name)
            if final_state is DotXpra.LIVE:
                time.sleep(0.5)
            else:
                break
        if final_state is DotXpra.DEAD:
            print "xpra at %s has exited." % display_name
            sys.exit(0)
        elif final_state is DotXpra.UNKNOWN:
            print ("How odd... I'm not sure what's going on with xpra at %s"
                   % display_name)
            sys.exit(1)
        elif final_state is DotXpra.LIVE:
            print "Failed to shutdown xpra at %s" % display_name
            sys.exit(1)
        else:
            assert False
    else:
        print "Sent shutdown command"

def run_list(parser, opts, extra_args):
    if extra_args:
        parser.error("too many arguments for mode")
    sockdir = DotXpra()
    results = sockdir.sockets()
    if not results:
        sys.stdout.write("No xpra sessions found\n")
    else:
        sys.stdout.write("Found the following xpra sessions:\n")
        for state, display in results:
            sys.stdout.write("\t%s session at %s" % (state, display))
            if state is DotXpra.DEAD:
                try:
                    os.unlink(sockdir.socket_path(display))
                except OSError:
                    pass
                else:
                    sys.stdout.write(" (cleaned up)")
            sys.stdout.write("\n")
