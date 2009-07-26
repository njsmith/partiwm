# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

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
import socket

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

def xpra_runner_shell_script(xpra_file, starting_dir):
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
    script.append("cd %s\n" % sh_quotemeta(starting_dir))
    script.append("_XPRA_PYTHON=%s\n" % (sh_quotemeta(sys.executable),))
    script.append("_XPRA_SCRIPT=%s\n" % (sh_quotemeta(xpra_file),))
    script.append("""
if which "$_XPRA_PYTHON" > /dev/null && [ -e "$_XPRA_SCRIPT" ]; then
    # Happypath:
    exec "$_XPRA_PYTHON" "$_XPRA_SCRIPT" "$@"
else
    cat >&2 <<END
    Could not find one or both of '$_XPRA_PYTHON' and '$_XPRA_SCRIPT'
    Perhaps your environment has changed since the xpra server was started?
    I'll just try executing 'xpra' with current PATH, and hope...
END
    exec xpra "$@"
fi
""")
    return "".join(script)

def create_unix_domain_socket(display_name, upgrading):
    dotxpra = DotXpra()
    sockpath = dotxpra.server_socket_path(display_name, upgrading)
    listener = socket.socket(socket.AF_UNIX)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(sockpath)
    return listener

def create_tcp_socket(parser, spec):
    if ":" not in spec:
        parser.error("TCP port must be specified as [HOST]:PORT")
    (host, port) = spec.split(":", 1)
    if host == "":
        host = "127.0.0.1"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((host, int(port)))
    return listener

def run_local_server(parser, opts, mode, xpra_file, display_desc):
    assert display_desc["type"] == "unix-domain"
    display_name = display_desc["display"]

    if opts.exit_with_children and not opts.children:
        print "--exit-with-children specified without any children to spawn; exiting immediately"
        return

    atexit.register(run_cleanups)
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    assert mode in ("start", "upgrade")
    upgrading = (mode == "upgrade")

    dotxpra = DotXpra()

    # This used to be given a display-specific name, but now we give it a
    # single fixed name and if multiple servers are started then the last one
    # will clobber the rest.  This isn't great, but the tradeoff is that it
    # makes it possible to use bare 'ssh:hostname' display names and
    # autodiscover the proper numeric display name when only one xpra server
    # is running on the remote host.  Might need to revisit this later if
    # people run into problems or autodiscovery turns out to be less useful
    # than expected.
    scriptpath = os.path.join(dotxpra.dir(), "run-xpra")

    # Save the starting dir now, because we'll lose track of it when we
    # daemonize:
    starting_dir = os.getcwd()

    # Daemonize:
    if opts.daemon:
        logpath = dotxpra.server_socket_path(display_name, upgrading) + ".log"
        sys.stderr.write("Entering daemon mode; "
                         + "any further errors will be reported to:\n"
                         + ("  %s\n" % logpath))
        # Do some work up front, so any errors don't get lost.
        if os.path.exists(logpath):
            os.rename(logpath, logpath + ".old")
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
    open(scriptpath, "w").write(xpra_runner_shell_script(xpra_file,
                                                         starting_dir))
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
        try:
            xvfb = subprocess.Popen(["Xvfb-for-Xpra-%s" % display_name,
                                     display_name,
                                     "-auth", xauthority,
                                     "+extension", "Composite",
                                     # Biggest easily available monitors are
                                     # 1920x1200. This is 1920*2 x 1920:
                                     "-screen", "0", "3840x1920x24+32",
                                     "-once"],
                                    executable="Xvfb")
        except OSError, e:
            sys.stderr.write("Error starting Xvfb: %s\n" % (e,))
        raw_cookie = os.urandom(16)
        baked_cookie = raw_cookie.encode("hex")
        try:
            assert not subprocess.call(["xauth", "add", display_name,
                                        "MIT-MAGIC-COOKIE-1", baked_cookie])
        except OSError, e:
            sys.stderr.write("Error running xauth: %s\n" % e)

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

    sockets = []
    sockets.append(create_unix_domain_socket(display_name, upgrading))
    if opts.bind_tcp:
        sockets.append(create_tcp_socket(parser, opts.bind_tcp))

    # This import is delayed because the module depends on gtk:
    import xpra.server
    app = xpra.server.XpraServer(upgrading, sockets)
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
            try:
                children_pids.add(subprocess.Popen(child_cmd, shell=True).pid)
            except OSError, e:
                sys.stderr.write("Error spawning child '%s': %s\n"
                                 % (child_cmd, e))
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
