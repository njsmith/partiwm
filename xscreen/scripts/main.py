import gtk
from optparse import OptionParser

import xscreen
from xscreen.server import XScreenServer
from xscreen.client import XScreenClient
from xscreen.proxy import XScreenProxy

# FIXME: make this UI more screen-like?
# FIXME: add ssh support
# FIXME: make the server mode spawn an Xvfb

def main(cmdline):
    parser = OptionParser(version="XScreen v%s" % xscreen.__version__,
                          usage=("%prog serve DISPLAY\n"
                                 + "%prog connect DISPLAY"))
    (options, args) = parser.parse_args(cmdline[1:])

    if not args:
        parser.error("need a mode")

    mode = args[0]
    if mode == "serve":
        app = make_server(parser, options, args[1:])
    elif mode == "connect":
        app = make_client(parser, options, args[1:])
    elif mode == "_proxy":
        app = make_proxy(parser, options, args[:1])
    else:
        parser.error("invalid mode '%s'" % mode)

    gtk.main()

def make_server(parser, opts, extra_args):
    if len(extra_args) != 0:
        parser.error("too many arguments for mode")
    return XScreenServer(True)

def make_client(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    return XScreenClient(extra_args[0])

def make_proxy(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    return XScreenProxy(0, 1, extra_args[0])
