# According to ICCCM 2.8/4.3, a window manager for screen N is a client which
# acquires the selection WM_S<N>.  If another client already has this
# selection, we can either abort or steal it.  Once we have it, if someone
# else steals it, then we should exit.

import gobject
import gtk
import gtk.gdk
from struct import pack, unpack
import time

from wimpiggy.util import no_arg_signal, one_arg_signal
from wimpiggy.lowlevel import (get_xatom, get_pywindow, sendClientMessage,
                               myGetSelectionOwner, const,
                               add_event_receiver)

class AlreadyOwned(Exception):
    pass

class ManagerSelection(gobject.GObject):
    __gsignals__ = {
        "selection-lost": no_arg_signal,

        "wimpiggy-destroy-event": one_arg_signal,
        }

    def __init__(self, display, selection):
        gobject.GObject.__init__(self)
        self.atom = selection
        self.clipboard = gtk.Clipboard(display, selection)
        self.rloop = gobject.MainLoop()

    def _owner(self):
        return myGetSelectionOwner(self.clipboard,self.atom)

    def owned(self):
        "Returns True if someone owns the given selection."
        return self._owner() != const["XNone"]

    # If the selection is already owned, then raise AlreadyOwned rather
    # than stealing it.
    IF_UNOWNED = "if_unowned"
    # If the selection is already owned, then steal it, and then block until
    # the previous owner has signaled that they are done cleaning up.
    FORCE = "force"
    # If the selection is already owned, then steal it and return immediately.
    # Created for the use of tests.
    FORCE_AND_RETURN = "force_and_return"
    def acquire(self, when):
        old_owner = self._owner()
        if when is IF_UNOWNED and old_owner != const["XNone"]:
            raise AlreadyOwned
        self.clipboard.set_with_data([("VERSION", 0, 0)],
                                     self._get,
                                     self._clear,
                                     None)

        # Having acquired the selection, we have to announce our existence
        # (ICCCM 2.8, still).  The details here probably don't matter too
        # much; I've never heard of an app that cares about these messages,
        # and metacity actually gets the format wrong in several ways (no
        # MANAGER or owner_window atoms).  But might as well get it as right
        # as possible.

        # To announce our existence, we need:
        #   -- the timestamp we arrived at
        #   -- the manager selection atom
        #   -- the window that registered the selection
        # Of course, because Gtk is doing so much magic for us, we have to do
        # some weird tricks to get at these.

        # Ask ourselves when we acquired the selection:
        ts_data = self.clipboard.wait_for_contents("TIMESTAMP").data
        ts_num = unpack("@i", ts_data[:4])[0]
        # Calculate the X atom for this selection:
        selection_xatom = get_xatom(self.clipboard, self.atom)
        # Ask X what window we used:
        owner_window = myGetSelectionOwner(self.clipboard, self.atom)
        
        root = self.clipboard.get_display().get_default_screen().get_root_window()
        sendClientMessage(root, False, const["StructureNotifyMask"],
                          "MANAGER",
                          ts_num, selection_xatom, owner_window, 0, 0)

        if old_owner != const["XNone"] and when is FORCE:
            # Block in a recursive mainloop until the previous owner has
            # cleared out.
            window = get_pywindow(old_owner)
            add_event_receiver(window, self)
            self.rloop.run()
            remove_event_receiver(window, self)

    def do_wimpiggy_destroy_event(self, *args):
        if self.rloop.is_running():
            self.rloop.quit()

    def _get(self, clipboard, outdata, which, userdata):
        # We are compliant with ICCCM version 2.0 (see section 4.3)
        outdata.set("INTEGER", 32, pack("@ii", 2, 0))

    def _clear(self, clipboard, userdata):
        self.emit("selection-lost")

gobject.type_register(ManagerSelection)
