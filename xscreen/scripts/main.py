import gtk
from optparse import OptionParser
import subprocess
import os
import os.path
import socket

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
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    display_name = extra_args[0]

    # FIXME: Should daemonize, then spawn Xvfb etc. in our process group, then
    # add an atexit() to clean off everything in our process group.

    xauthority = os.environ.get("XAUTHORITY",
                                os.path.expanduser("~/.Xauthority"))
    xvfb = subprocess.Popen(["Xvfb-for-XScreen", display_name,
                             "-auth", xauthority,
                             "+extension", "Composite",
                             "-screen", "0", "2048x2048x24+32"],
                            executable="Xvfb")

    raw_cookie = os.urandom(16)
    baked_cookie = raw_cookie.encode("hex")
    assert not subprocess.call(["xauth", "add", display_name,
                                "MIT-MAGIC-COOKIE-1", baked_cookie])

    os.environ["DISPLAY"] = display_name
    display = gtk.gdk.Display(display_name)
    manager = gtk.gdk.display_manager_get()
    default_display = manager.get_default_display()
    if default_display is not None:
        default_display.close()
    manager.set_default_display(display)

    return XScreenServer(False)

def make_client(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    return XScreenClient(extra_args[0])

def make_proxy(parser, opts, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    return XScreenProxy(0, 1, extra_args[0])
