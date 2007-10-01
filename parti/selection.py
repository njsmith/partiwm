# According to ICCCM 2.8/4.3, a window manager for screen N is a client which
# acquires the selection WM_S<N>.  If another client already has this
# selection, we can either abort or steal it.  Once we have it, if someone
# else steals it, then we should exit.

# Standards BUG: ICCCM 2.8 specifies exactly how we are supposed to do the
# detection/stealing stuff, and we totally ignore it, because G[TD]K don't
# make it convenient to 1) ask directly whether a selection is owned, 2) wait
# for a window to be destroyed.  So instead, we detect if the selection is
# owned by trying to convert it, and if it is we either abort or simply steal
# the selection and assume things will work out.

import gobject
import gtk
import gtk.gdk
from struct import pack, unpack
from warnings import warn

import parti.lowlevel

class AlreadyOwned(Exception):
    pass

class ManagerSelection(gobject.GObject):
    __gsignals__ = {
        'selection-lost': (gobject.SIGNAL_RUN_LAST,
                           gobject.TYPE_NONE, ()),
        }

    def __init__(self, display, selection):
        gobject.GObject.__init__(self)
        self.atom = selection
        self.clipboard = gtk.Clipboard(display, selection)

    def owned(self):
        "Returns True if someone owns the given selection."
        return self.clipboard.wait_for_targets() is not None

    def acquire(self, force=False):
        if not force and self.owned():
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
        selection_xatom = parti.lowlevel.get_xatom(self.clipboard, self.atom)
        # Ask X what window we used:
        owner_window = parti.lowlevel.myGetSelectionOwner(self.clipboard, self.atom)
        
        root = self.clipboard.get_display().get_default_screen().get_root_window()
        parti.lowlevel.sendClientMessage(root,
                                         False,
                                         parti.lowlevel.const["StructureNotifyMask"],
                                         "MANAGER",
                                         ts_num,
                                         selection_xatom,
                                         owner_window,
                                         0, 0)

    def _get(self, clipboard, outdata, which, userdata):
        # We are compliant with ICCCM version 2.0 (see section 4.3)
        outdata.set("INTEGER", 32, pack("@ii", 2, 0))

    def _clear(self, clipboard, userdata):
        self.emit("selection-lost")

gobject.type_register(ManagerSelection)
