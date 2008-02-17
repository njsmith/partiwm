from optparse import OptionParser

import xscreen
from xscreen.server import XScreenServer
from xscreen.client import XScreenClient

# FIXME: make this UI more screen-like?
# FIXME: add ssh support
# FIXME: make the server mode spawn an Xvfb

def main(cmdline):
    parser = OptionParser(version="XScreen v%s" % xscreen.__version__,
                          usage=("%prog serve --display=DISPLAY\n"
                                 + "%prog connect DISPLAY"))
    (options, args) = parser.parse_args(cmdline[1:])

    if not args:
        parser.error("need a mode")
    if args[0] == "serve":
        if len(args) != 1:
            parser.error("too many arguments")
        app = XScreenServer(True)
    elif args[0] == "connect":
        if len(args) < 2:
            parser.error("connect to what?")
        elif len(args) == 2:
            app = XScreenClient(args[1])
        else:
            parser.error("too many arguments")
    gtk.main()
