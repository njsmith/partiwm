import gtk
from optparse import OptionParser

import xscreen

# FIXME: make this UI more screen-like?
# FIXME: add ssh support

def main(cmdline):
    parser = OptionParser(version="XScreen v%s" % xscreen.__version__,
                          usage=("%prog serve DISPLAY\n"
                                 + "%prog connect DISPLAY"))
    parser.add_option("--no-daemon", action="store_false",
                      dest="daemon", default=True,
                      help="Don't daemonize in server mode")
    (options, args) = parser.parse_args(cmdline[1:])

    if not args:
        parser.error("need a mode")

    mode = args[0]
    if mode == "serve":
        run_server(parser, options, args[1:])
    elif mode == "connect":
        run_client(parser, options, args[1:])
    elif mode == "_proxy":
        run_proxy(parser, options, args[:1])
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
