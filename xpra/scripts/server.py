import gtk
import subprocess
import sys
import os
import os.path
import atexit
import signal

from wimpiggy.prop import prop_set, prop_get

from xpra.server import XpraServer
from xpra.address import server_sock

_cleanups = []
def run_cleanups():
    for c in _cleanups:
        try:
            c()
        except:
            pass

def deadly_signal(signum, frame):
    print "got signal %s, exiting" % signum
    run_cleanups()
    # This works fine in tests, but for some reason if I use it here, then I
    # get bizarre behavior where the signal handler runs, and then I get a
    # KeyboardException (?!?), and the KeyboardException is handled normally
    # and exits the program (causing the cleanup handlers to be run again):
    #signal.signal(signum, signal.SIG_DFL)
    #kill(os.getpid(), signum)
    os._exit(128 + signum)

def save_pid(pid):
    prop_set(gtk.gdk.get_default_root_window(),
             "_XPRA_SERVER_PID", "u32", pid)
             
def get_pid():
    return prop_get(gtk.gdk.get_default_root_window(),
                    "_XPRA_SERVER_PID", "u32")

def run_server(parser, opts, mode, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    display_name = extra_args[0]

    atexit.register(run_cleanups)
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    sockpath = server_sock(display_name, False)
    logpath = sockpath + ".log"

    # Daemonize:
    if opts.daemon:
        # Do some work up front, so any errors don't get lost.
        logfd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0666)
        assert logfd > 2
        for display in gtk.gdk.display_manager_get().list_displays():
            display.close()
        os.chdir("/")

        if os.fork():
            os._exit(0)
        os.setsid()
        if os.fork():
            os._exit(0)
        if os.path.exists("/proc/self/fd"):
            for fd_str in os.listdir("/proc/self/fd"):
                try:
                    fd = int(fd_str)
                    if fd != logfd:
                        os.close(fd)
                except OSError:
                    # This exception happens inevitably, because the fd used
                    # by listdir() is already closed.
                    pass
        else:
            print "Uh-oh, can't close fds, please port me to your system..."
        fd0 = os.open("/dev/null", os.O_RDONLY)
        if fd0 != 0:
            os.dup2(fd0, 0)
            os.close(fd0)
        os.dup2(logfd, 1)
        os.dup2(logfd, 2)
        os.close(logfd)
        # Make these line-buffered:
        sys.stdout = os.fdopen(1, "w", 1)
        sys.stderr = os.fdopen(2, "w", 1)

    if mode == "start":
        # We need to set up a new server environment
        xauthority = os.environ.get("XAUTHORITY",
                                    os.path.expanduser("~/.Xauthority"))
        xvfb = subprocess.Popen(["Xvfb-for-Xpra", display_name,
                                 "-auth", xauthority,
                                 "+extension", "Composite",
                                 "-screen", "0", "2048x2048x24+32",
                                 "-once"],
                                executable="Xvfb")

        raw_cookie = os.urandom(16)
        baked_cookie = raw_cookie.encode("hex")
        assert not subprocess.call(["xauth", "add", display_name,
                                    "MIT-MAGIC-COOKIE-1", baked_cookie])

    # Whether we spawned our server or not, it is now running, and we can
    # connect to it.
    os.environ["DISPLAY"] = display_name
    display = gtk.gdk.Display(display_name)
    manager = gtk.gdk.display_manager_get()
    default_display = manager.get_default_display()
    if default_display is not None:
        default_display.close()
    manager.set_default_display(display)

    if mode == "start":
        xvfb_pid = xvfb.pid
    else:
        assert mode == "upgrade"
        xvfb_pid = get_pid()

    def kill_xvfb():
        # Close our display(s) first, so the server dying won't kill us.
        for display in gtk.gdk.display_manager_get().list_displays():
            display.close()
        os.kill(xvfb_pid, signal.SIGTERM)
    _cleanups.append(kill_xvfb)

    save_pid(xvfb_pid)

    app = XpraServer(sockpath, False)
    def cleanup_socket(self):
        print "removing socket"
        try:
            os.unlink(sockpath)
        except:
            pass
    _cleanups.append(cleanup_socket)
    if app.run():
        # Upgrading, so leave X server running
        _cleanups.remove(kill_xvfb)
