import gobject
import gtk
from parti.util import base, two_arg_signal
from parti.error import *
from parti.lowlevel import (get_display_for,
                            get_modifier_map, grab_key, ungrab_all_keys)

class HotkeyWidget(gtk.Widget):
    __gsignals__ = {
        "hotkey-press-event": two_arg_signal,
        "hotkey-release-event": two_arg_signal,
        }

    def __init__(self):
        gtk.Widget.__init__(self)
        self._hotkeys = {}
        self._modifier_map = None
        self._nuisances = None
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
        self._modifier_map = grok_modifier_map(self.window)
        self._nuisances = set()
        self._nuisances.add(0)
        for i in range(256):
            if i & ~self._modifier_map["nuisance"]:
                self._nuisances.add(i)
        self._rebind()

    def _unrealizing(self):
        self._unbind_all()
        self._modifier_map = None
        self._nuisances = None
        self._keymap.disconnect(self.keymap_id)
        self._keymap = None
        self._keymap_id = None

    def do_destroy(self):
        if self._keymap is not None:
            self._keymap.disconnect(self._keymap_id)
        gtk.Widget.do_destroy(self)

    def _rebind(self, *args):
        if not self.flags() & gtk.REALIZED:
            return
        try:
            gtk.gdk.x11_grab_server()
            self._unbind_all()
            self._bind_all()
        finally:
            gtk.gdk.x11_ungrab_server()

    def _unbind_all(self):
        ungrab_all_keys(self.window)

    def _bind_all(self):
        assert self.flags() & gtk.REALIZED
        self._normalized_hotkeys = {}
        for hotkey, target in self._hotkeys.iteritems():
            modifier_mask, keycodes = parse_key(hotkey, self._keymap,
                                                self._modifier_map)
            for keycode in keycodes:
                # Claim a passive grab on all the different forms of this key
                for nuisance_mask in self._nuisances:
                    trap.swallow(grab_key,
                                 self.window, keycode,
                                 modifier_mask | nuisance_mask)
                # Save off the normalized form to make it easy to lookup later
                # when we see the key appear
                unparsed = unparse_key(modifier_mask, keycode,
                                       self._keymap, self._modifier_map)
                self._normalized_hotkeys[unparsed] = target

    def _key_press(self, event):
        self._key_event(event, "key-press-event", "hotkey-press-event")

    def _key_release(self, event):
        self._key_event(event, "key-release-event", "hotkey-release-event")
        
    def _key_event(self, event, orig_event, forward_event):
        unparsed = unparse_key(event.state, event.hardware_keycode,
                               self._keymap, self._modifier_map)
        if unparsed in self._normalized_hotkeys:
            self.stop_emission(orig_event)
            self.emit(forward_event, self._normalized_hotkeys[unparsed])

    def add_hotkeys(self, hotkeys):
        self._hotkeys.update(hotkeys)
        self._rebind()

    def del_hotkeys(self, keys):
        for k in keys:
            if k in self._hotkeys:
                del self._hotkeys[k]
        self._rebind()

gobject.type_register(HotkeyWidget)


def grok_modifier_map(display_source):
    """Return an dict mapping modifier names to corresponding X modifier
    bitmasks."""
    modifier_map = {
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

    disp = get_display_for(display_source)
    (max_keypermod, keycodes) = get_modifier_map(disp)
    assert len(keycodes) == 8 * max_keypermod
    keymap = gtk.gdk.keymap_get_for_display(disp)
    for i in range(8):
        for j in range(max_keypermod):
            keycode = keycodes[i * max_keypermod + j]
            if keycode:
                entries = keymap.get_entries_for_keycode(keycode)
                for (keyval, _, _, _) in entries:
                    keyval_name = gtk.gdk.keyval_name(keyval)
                    if keyval_name in meanings:
                        modifier_map[meanings[keyval_name]] |= (1 << i)
    modifier_map["nuisance"] = (modifier_map["lock"]
                                | modifier_map["scroll"]
                                | modifier_map["num"])
    return modifier_map

def parse_key(name, keymap, modifier_map):
    modifier_mask = 0
    name = name.strip().lower()
    while name.startswith("<"):
        ket = name.index(">")
        modifier_name = name[1:ket]
        extra_mask = modifier_map[modifier_name]
        assert extra_mask
        modifier_mask |= extra_mask
        name = name[ket+1:]
    keycodes = []
    try:
        keycodes.append(int(name))
    except ValueError:
        keyval = gtk.gdk.keyval_from_name(name)
        entries = keymap.get_entries_for_keyval(keyval)
        for entry in entries:
            keycodes.append(entry[0])
    modifier_mask &= ~modifier_map["nuisance"]
    return (modifier_mask, keycodes)

def unparse_key(modifier_mask, keycode, keymap, modifier_map):
    name = None
    modifier_mask &= ~modifier_map["nuisance"]

    keyval_entries = keymap.get_entries_for_keycode(keycode)
    if keyval_entries is not None:
        for keyval_entry in keyval_entries:
            if keyval_entry[0]:
                name = gtk.gdk.keyval_name(keyval_entry[0])
                break
    if name is None:
        name = str(keycode)

    mods = modifier_map.keys()
    def sort_modn_to_end(a, b):
        a = (a.startswith("mod"), a)
        b = (b.startswith("mod"), b)
        return cmp(a, b)
    mods.sort(sort_modn_to_end)
    for mod in mods:
        mask = modifier_map[mod]
        if mask & modifier_mask:
            name = "<%s>%s" % (mod, name)
            modifier_mask &= ~mask
    return name
