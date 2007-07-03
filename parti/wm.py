import sys

import pygtk
pygtk.require('2.0')
import gtk
import gtk.gdk

# gdk_window_set_composited()

import parti.selection
import parti.wrapped
import parti.prop

_NET_SUPPORTED = [
    "_NET_SUPPORTING_WM_CHECK",
    "_NET_WM_FULL_PLACEMENT",
    "_NET_WM_HANDLED_ICONS",
    # We don't actually use _NET_WM_USER_TIME at all (yet), but it is
    # important to say we support the _NET_WM_USER_TIME_WINDOW property,
    # because this tells applications that they do not need to constantly ping
    # any pagers etc. that might be running -- see EWMH for details.
    "_NET_WM_USER_TIME",
    "_NET_WM_USER_TIME_WINDOW",
    #"_NET_WM_NAME",
    # ...
    ]

class Wm(object):
    def __init__(self):
        # Become the Official Window Manager of the games:
        self._wm_selection = parti.selection.ManagerSelection("WM_S0")
        self._wm_selection.connect("selection-lost", self._lost_wm_selection)
        if self._wm_selection.owned():
            print "A window manager is already running; exiting"
            sys.exit()
        self._wm_selection.acquire()
        # (If we become a compositing manager, then we will want to do the
        # same thing with the _NET_WM_CM_S0 selection (says EWMH).)

        self._real_root = gtk.gdk.get_default_root_window()
        self._ewmh_window = self._utility_window()

        # Basic EWMH setup:
        parti.wrapped.XChangeProperty(self._ewmh_window,
                                      "_NET_SUPPORTING_WM_CHECK",
                                      parti.prop.prop_encode("window",
                                                             self.ewmh_window))
        parti.wrapped.XChangeProperty(self._real_root,
                                      "_NET_SUPPORTING_WM_CHECK",
                                      parti.prop.prop_encode("window",
                                                             self.ewmh_window))
        parti.wrapped.XChangeProperty(self._real_root,
                                      "_NET_SUPPORTED",
                                      parti.prop.prop_encode(["atom"],
                                                             _NET_SUPPORTED))
        
        # Okay, ready to select for SubstructureRedirect and 

    def _lost_wm_selection(self, data):
        print "Lost WM selection, exiting"
        self.quit()

    def quit(self):
        gtk.main_quit()

    def mainloop(self):
        gtk.main()

    def _utility_window(self):
        # Returns a 1x1, unmapped, top-level override-redirect window with all
        # events masked on
        return gtk.gdk.Window(gtk.gdk.get_default_root_window(),
                              1, 1, gtk.gdk.WINDOW_TOPLEVEL,
                              gtk.gdk.ALL_EVENTS_MASK,
                              gtk.gdk.INPUT_ONLY,
                              "Parti",
                              0, 0,
                              gtk.gdk.visual_get_system(),
                              gtk.gdk.colormap_get_system(),
                              gtk.gdk.Cursor(gtk.gdk.X_CURSOR),
                              # FIXME: the docs for these next two args say
                              # "don't use".  How?
                              "", "",
                              True)

