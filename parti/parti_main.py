import gtk

import parti.lowlevel

from parti.wm import Wm

from parti.world_window import WorldWindow
from parti.world_organizer import WorldOrganizer

from parti.windowset import WindowSet
from parti.tray import TraySet
from parti.trays.simpletab import SimpleTabTray

from parti.addons.ipython_embed import spawn_repl_window

from parti.bus import PartiDBusService

from parti.keys import HotkeyManager

# FIXME: this is only here for testing, definitely not the right place for it!
class RootKeybindings(HotkeyManager):
    def __init__(self, parti):
        HotkeyManager.__init__(self, gtk.gdk.get_default_root_window())
        self.parti = parti
        self.add_hotkeys({"<shift><alt>r": "repl"})

    def do_hotkey(self, target):
        if target == "repl":
            self.parti.spawn_repl_window()
import gobject
gobject.type_register(RootKeybindings)

class Parti(object):
    def __init__(self, replace_other_wm):
        self._wm = Wm("Parti", replace_other_wm)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("quit", self._wm_quit)
        self._wm.connect("focus-got-dropped", self._focus_dropped)

        self._trays = TraySet()
        self._trays.connect("changed", self._desktop_list_changed)
        
        # Create our giant window
        self._world_window = WorldWindow()
        self._world_organizer = WorldOrganizer(self._trays)
        self._world_window.add(self._world_organizer)
        self._world_window.show_all()

        # FIXME: be less stupid
        #self._trays.new(u"default", SimpleTabTray)
        from parti.trays.compositetest import CompositeTest
        self._trays.new(u"default", CompositeTest)

        self._root_keybindings = RootKeybindings(self)

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

    def _focus_dropped(self, *args):
        self._world_window.reset_x_focus()

    def _desktop_list_changed(self, *args):
        self._wm.emit("desktop-list-changed", self._trays.tags())

    def spawn_repl_window(self):
        spawn_repl_window(self._wm,
                          {"parti": self,
                           "wm": self._wm,
                           "windows": self._wm.get_property("windows"),
                           "trays": self._trays,
                           "lowlevel": parti.lowlevel})

