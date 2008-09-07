# DO NOT IMPORT GTK HERE: see http://partiwm.org/ticket/34
# (also do not import anything that imports gtk)
import gobject
import subprocess
import sys
import os
import os.path
import atexit
import signal
import time

from xpra.wait_for_x_server import wait_for_x_server
from xpra.dotxpra import DotXpra

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

# Note that this class has async subtleties -- e.g., it is possible for a
# child to exit and us to receive the SIGCHLD before our fork() returns (and
# thus before we even know the pid of the child).  So be careful:
class ChildReaper(object):
    def __init__(self, app, exit_with_children):
        self._app = app
        self._children_pids = None
        self._dead_pids = set()
        self._exit_with_children = exit_with_children

    def set_children_pids(self, children_pids):
        assert self._children_pids is None
        self._children_pids = children_pids
        self.check()

    def check(self):
        if (self._children_pids
            and self._exit_with_children
            and self._children_pids.issubset(self._dead_pids)):
            print "all children have exited and --survive-children was not specified, exiting"
            self._app.quit(False)

    def __call__(self, signum, frame):
        while 1:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except OSError:
                break
            if pid == 0:
                break
            self._dead_pids.add(pid)
            self.check()

def save_pid(pid):
    import gtk
    import wimpiggy.prop
    wimpiggy.prop.prop_set(gtk.gdk.get_default_root_window(),
                           "_XPRA_SERVER_PID", "u32", pid)
             
def get_pid():
    import gtk
    import wimpiggy.prop
    return wimpiggy.prop.prop_get(gtk.gdk.get_default_root_window(),
                                  "_XPRA_SERVER_PID", "u32")

def sh_quotemeta(s):
    safe = ("abcdefghijklmnopqrstuvwxyz"
            + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            + "0123456789"
            + "/._:,-+")
    quoted_chars = []
    for char in s:
        if char not in safe:
            quoted_chars.append("\\")
        quoted_chars.append(char)
    return "\"%s\"" % ("".join(quoted_chars),)

def xpra_runner_shell_script(xpra_file):
    script = []
    script.append("#!/bin/sh\n")
    for var, value in os.environ.iteritems():
        # :-separated envvars that people might change while their server is
        # going:
        if var in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH"):
            script.append("%s=%s:\"$%s\"; export %s\n"
                          % (var, sh_quotemeta(value), var, var))
        else:
            script.append("%s=%s; export %s\n"
                          % (var, sh_quotemeta(value), var))
    # We ignore failures in cd'ing, b/c it's entirely possible that we were
    # started from some temporary directory and all paths are absolute.
    script.append("cd %s\n" % sh_quotemeta(os.getcwd()))
    script.append("_XPRA_PYTHON=%s\n" % (sh_quotemeta(sys.executable),))
    script.append("_XPRA_SCRIPT=%s\n" % (sh_quotemeta(xpra_file),))
    script.append("""
if which "$_XPRA_PYTHON" > /dev/null && [ -e "$_XPRA_SCRIPT" ]; then
    # Happypath:
    exec "$_XPRA_PYTHON" "$_XPRA_SCRIPT" "$@"
else
    cat >2 <<END
    Could not find one or both of '$_XPRA_PYTHON' and '$_XPRA_SCRIPT'
    Perhaps your environment has changed since the xpra server was started?
    I'll just try executing 'xpra' with current PATH, and hope...
END
    exec xpra "$@"
fi
""")
    return "".join(script)

def run_server(parser, opts, mode, xpra_file, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    display_name = extra_args.pop(0)

    if opts.exit_with_children and not opts.children:
        print "--exit-with-children specified without any children to spawn; exiting immediately"
        return

    atexit.register(run_cleanups)
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    assert mode in ("start", "upgrade")
    upgrading = (mode == "upgrade")
    sockdir = DotXpra()
    sockpath = sockdir.server_socket_path(display_name, upgrading)
    logpath = sockpath + ".log"
    # This used to be given a display-specific name, but now we give it a
    # single fixed name and if multiple servers are started then the last one
    # will clobber the rest.  This isn't great, but the tradeoff is that it
    # makes it possible to use bare 'ssh:hostname' display names and
    # autodiscover the proper numeric display name when only one xpra server
    # is running on the remote host.  Might need to revisit this later if
    # people run into problems or autodiscovery turns out to be less useful
    # than expected.
    scriptpath = os.path.join(sockdir.dir(), "run-xpra")

    # Daemonize:
    if opts.daemon:
        # Do some work up front, so any errors don't get lost.
        if os.path.exists(logpath):
            os.unlink(logpath)
        logfd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0666)
        assert logfd > 2
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

    # Write out a shell-script so that we can start our proxy in a clean
    # environment:
    open(scriptpath, "w").write(xpra_runner_shell_script(xpra_file))
    # Unix is a little silly sometimes:
    umask = os.umask(0)
    os.umask(umask)
    os.chmod(scriptpath, 0777 & ~umask)

    # Do this after writing out the shell script:
    os.environ["DISPLAY"] = display_name

    if not upgrading:
        # We need to set up a new server environment
        xauthority = os.environ.get("XAUTHORITY",
                                    os.path.expanduser("~/.Xauthority"))
        xvfb = subprocess.Popen(["Xvfb-for-Xpra-%s" % display_name,
                                 display_name,
                                 "-auth", xauthority,
                                 "+extension", "Composite",
                                 "-screen", "0", "2048x2048x24+32",
                                 "-once"],
                                executable="Xvfb")

        raw_cookie = os.urandom(16)
        baked_cookie = raw_cookie.encode("hex")
        assert not subprocess.call(["xauth", "add", display_name,
                                    "MIT-MAGIC-COOKIE-1", baked_cookie])

    # Whether we spawned our server or not, it is now running -- or at least
    # starting.  First wait for it to start up:
    wait_for_x_server(display_name, 3) # 3s timeout
    # Now we can safely load gtk and connect:
    import gtk
    display = gtk.gdk.Display(display_name)
    manager = gtk.gdk.display_manager_get()
    default_display = manager.get_default_display()
    if default_display is not None:
        default_display.close()
    manager.set_default_display(display)

    if upgrading:
        xvfb_pid = get_pid()
    else:
        xvfb_pid = xvfb.pid

    def kill_xvfb():
        # Close our display(s) first, so the server dying won't kill us.
        for display in gtk.gdk.display_manager_get().list_displays():
            display.close()
        if xvfb_pid is not None:
            os.kill(xvfb_pid, signal.SIGTERM)
    _cleanups.append(kill_xvfb)

    if xvfb_pid is not None:
        save_pid(xvfb_pid)

    # This import is delayed because the module depends on gtk:
    import xpra.server
    app = xpra.server.XpraServer(sockpath, upgrading)
    def cleanup_socket(self):
        print "removing socket"
        try:
            os.unlink(sockpath)
        except:
            pass
    _cleanups.append(cleanup_socket)

    child_reaper = ChildReaper(app, opts.exit_with_children)
    # Always register the child reaper, because even if exit_with_children is
    # false, we still need to reap them somehow to avoid zombies:
    signal.signal(signal.SIGCHLD, child_reaper)
    if opts.exit_with_children:
        assert opts.children
    if opts.children:
        children_pids = set()
        for child_cmd in opts.children:
            children_pids.add(subprocess.Popen(child_cmd, shell=True).pid)
        child_reaper.set_children_pids(children_pids)
    # Check once after the mainloop is running, just in case the exit
    # conditions are satisfied before we even enter the main loop.
    # (Programming with unix the signal API sure is annoying.)
    def check_once():
        child_reaper.check()
        return False # Only call once
    gobject.timeout_add(0, check_once)

    if app.run():
        # Upgrading, so leave X server running
        _cleanups.remove(kill_xvfb)
