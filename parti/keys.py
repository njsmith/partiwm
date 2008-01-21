import gobject
import gtk
from parti.util import base, two_arg_signal
from parti.lowlevel import get_display_for, get_modifier_map, ungrab_all_keys

class HotkeyWidget(gtk.Widget):
    __gsignals__ = {
        "hotkey-press-event": two_arg_signal,
        "hotkey-release-event": two_arg_signal,
        }

    def __init__(self):
        base(self).__init__(self)
        self._hotkeys = {}
        self._modifiers = None
        self._keymap = None
        self._keymap_id = None

        # The games with type() here avoid creating circular references:

        # Runs AFTER do_realize:
        self.connect("realize", type(self)._realized)
        # Runs BEFORE do_unrealize:
        self.connect("unrealize", type(self)._unrealizing)
        # Run BEFORE do_key_{press,release}_event:
        self.connect("key-press-event", type(self)._key_press)
        self.connect("key-release-event", type(self)._key_release)

    def _realized(self):
        disp = get_display_for(self.window)
        self._keymap = gtk.gdk.keymap_get_for_display(disp)
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

    def _keys_changed(self, *args):
        assert self.flags() & gtk.REALIZED
        self._modifiers = get_modifiers(get_display_for(self.window))
        self._rebind()

    def _unrealizing(self):
        self._unbind_all()
        self._modifiers = None
        self._keymap.disconnect(self.keymap_id)
        self._keymap = None
        self._keymap_id = None

    def do_destroy(self):
        if keymap is not None:
            self.keymap.disconnect(self.keymap_id)
        base(self).do_destroy(self)

    def _rebind(self, *args):
        try:
            gtk.gdk.x11_grab_server()
            self._unbind_all()
            self._bind_all()
        finally:
            gtk.gdk.x11_ungrab_server()

    def _unbind_all(self):
        ungrab_all_keys(win)

    def _bind_all(self):
        pass

    def add_hotkeys(self, hotkeys):
        self.hotkeys.update(hotkeys)
        self._rebind()

    def del_hotkeys(self, keys):
        for k in keys:
            if k in self.hotkeys:
                del self.hotkeys[k]
        self._rebind()

gobject.type_register(HotkeyWidget)


def grok_modifier_map(display_source):
    """Return an dict mapping modifier names to corresponding X modifier
    bitmasks."""
    disp = get_display_for(display_source)
    (max_keypermod, keycodes) = get_modifier_map(disp)
    assert len(keycodes) == 8 * max_keypermod
    modifiers = {
        "shift": 1 << 0,
        "lock": 1 << 1,
        "control": 1 << 2,
        "mod1": 1 << 3,
        "mod2": 1 << 4,
        "mod3": 1 << 5,
        "mod4": 1 << 6,
        "mod5": 1 << 7,
        "scroll": 0,
        "num": 0,
        "meta": 0,
        "super": 0,
        "hyper": 0,
        "alt": 0,
        }
    meanings = {
        "Scroll_Lock": "scroll",
        "Num_Lock": "num",
        "Meta_L": "meta",
        "Meta_R": "meta",
        "Super_L": "super",
        "Super_R": "super",
        "Hyper_L": "hyper",
        "Hyper_R": "hyper",
        "Alt_L": "alt",
        "Alt_R": "alt",
        }
    keymap = gtk.gdk.keymap_get_for_display(disp)
    for i in range(8):
        for j in range(max_keypermod):
            keycode = keycodes[i * max_keypermod + j]
            if keycode:
                entries = keymap.get_entries_for_keycode(keycode)
                for (keyval, _, _, _) in entries:
                    keyval_name = gtk.gdk.keyval_name(keyval)
                    if keyval_name in meanings:
                        modifiers[meanings[keyval_name]] |= (1 << i)
    return modifiers

