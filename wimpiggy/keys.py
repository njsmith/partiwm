import gobject
import gtk
from wimpiggy.util import one_arg_signal
from wimpiggy.error import *
from wimpiggy.lowlevel import (get_display_for,
                               get_modifier_map, grab_key, ungrab_all_keys,
                               add_event_receiver, remove_event_receiver)

class HotkeyManager(gobject.GObject):
    __gsignals__ = {
        "hotkey": (gobject.SIGNAL_RUN_LAST | gobject.SIGNAL_DETAILED,
                   gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),

        "wimpiggy-key-press-event": one_arg_signal,
        }

    def __init__(self, window):
        gobject.GObject.__init__(self)
        self.window = window
        self.hotkeys = {}

        disp = get_display_for(self.window)
        self.keymap = gtk.gdk.keymap_get_for_display(disp)
        self.keymap_id = self.keymap.connect("keys-changed",
                                             self._keys_changed)
        self._keys_changed()

        add_event_receiver(self.window, self)

    def destroy(self):
        self.keymap.disconnect(self.keymap_id)
        self.keymap = None
        self.keymap_id = None

        trap.swallow(self.unbind_all)
        remove_event_receiver(self.window, self)
        self.window = None

    def _keys_changed(self, *args):
        self.modifier_map = grok_modifier_map(self.window)
        self.nuisances = set()
        for i in range(256):
            if not(i & ~self.modifier_map["nuisance"]):
                self.nuisances.add(i)
        trap.swallow(self._rebind)

    def _rebind(self, *args):
        try:
            gtk.gdk.x11_grab_server()
            self._unbind_all()
            self._bind_all()
        finally:
            gtk.gdk.x11_ungrab_server()

    def _unbind_all(self):
        ungrab_all_keys(self.window)

    def _bind_all(self):
        self.normalized_hotkeys = {}
        for hotkey, target in self.hotkeys.iteritems():
            modifier_mask, keycodes = parse_key(hotkey, self.keymap,
                                                self.modifier_map)
            for keycode in keycodes:
                # Claim a passive grab on all the different forms of this key
                for nuisance_mask in self.nuisances:
                    grab_key(self.window, keycode,
                             modifier_mask | nuisance_mask)
                # Save off the normalized form to make it easy to lookup later
                # when we see the key appear
                unparsed = unparse_key(modifier_mask, keycode,
                                       self.keymap, self.modifier_map)
                self.normalized_hotkeys[unparsed] = target

    def do_key_press_event(self, event):
        print "got hotkey event, maybe"
        unparsed = unparse_key(event.state, event.hardware_keycode,
                               self.keymap, self.modifier_map)
        print "unparsed = %s" % unparsed
        if unparsed in self.normalized_hotkeys:
            target = self.normalized_hotkeys[unparsed]
            self.emit("hotkey::%s" % (target,), target)

    def add_hotkeys(self, hotkeys):
        self.hotkeys.update(hotkeys)
        self._rebind()

    def del_hotkeys(self, keys):
        for k in keys:
            if k in self.hotkeys:
                del self.hotkeys[k]
        self._rebind()

gobject.type_register(HotkeyManager)


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
