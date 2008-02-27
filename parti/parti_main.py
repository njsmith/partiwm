import gtk

import wimpiggy.lowlevel

from wimpiggy.wm import Wm
from wimpiggy.keys import HotkeyManager

from parti.world_organizer import WorldOrganizer

from parti.tray import TraySet
from parti.trays.simpletab import SimpleTabTray

from parti.addons.ipython_embed import spawn_repl_window

from parti.bus import PartiDBusService

class Parti(object):
    def __init__(self, replace_other_wm):
        self._wm = Wm("Parti", replace_other_wm)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("quit", self._wm_quit)

        self._trays = TraySet()
        self._trays.connect("changed", self._desktop_list_changed)
        
        # Create our display stage
        self._world_organizer = WorldOrganizer(self._trays)
        self._wm.get_property("toplevel").add(self._world_organizer)
        self._world_organizer.show_all()

        # FIXME: be less stupid
        #self._trays.new(u"default", SimpleTabTray)
        from parti.trays.compositetest import CompositeTest
        self._trays.new(u"default", CompositeTest)

        self._root_hotkeys = HotkeyManager(gtk.gdk.get_default_root_window())
        self._root_hotkeys.add_hotkeys({"<shift><alt>r": "repl"})
        self._root_hotkeys.connect("hotkey::repl",
                                   lambda *args: self.spawn_repl_window())

        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        # Start providing D-Bus api
        self._dbus = PartiDBusService(self)

    def main(self):
        gtk.main()

    def _wm_quit(self, *args):
        gtk.main_quit()

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def _add_new_window(self, window):
        # FIXME: be less stupid
        self._trays.trays[0].add(window)

    def _desktop_list_changed(self, *args):
        self._wm.emit("desktop-list-changed", self._trays.tags())

    def spawn_repl_window(self):
        spawn_repl_window(self._wm,
                          {"parti": self,
                           "wm": self._wm,
                           "windows": self._wm.get_property("windows"),
                           "trays": self._trays,
                           "lowlevel": wimpiggy.lowlevel})

