from parti.test import *
import subprocess
import parti.keys

class TestKeys(TestWithSession):
    def xmodmap(self, code):
        xmodmap = subprocess.Popen(["xmodmap",
                                    "-display", self.display_name,
                                    "-"],
                                   stdin=subprocess.PIPE)
        xmodmap.communicate(code)
        subprocess.call(["xmodmap", "-display", self.display_name, "-pm"])

    def clear_xmodmap(self):
        # No assigned modifiers, but all modifier keys *have* keycodes for
        # later.
        self.xmodmap("""clear Lock
                        clear Shift
                        clear Control
                        clear Mod1
                        clear Mod2
                        clear Mod3
                        clear Mod4
                        clear Mod5
                        keycode any = Num_Lock
                        keycode any = Scroll_Lock
                        keycode any = Hyper_L
                        keycode any = Hyper_R
                        keycode any = Super_L
                        keycode any = Super_R
                        keycode any = Alt_L
                        keycode any = Alt_R
                        keycode any = Meta_L
                        keycode any = Meta_R
                        """)

    def test_grok_modifier_map(self):
        self.clear_xmodmap()
        mm = parti.keys.grok_modifier_map(self.display)
        print mm
        assert mm == {"shift": 1, "lock": 2, "control": 4,
                      "mod1": 8, "mod2": 16, "mod3": 32, "mod4": 64,
                      "mod5": 128,
                      "scroll": 0, "num": 0, "meta": 0, "super": 0,
                      "hyper": 0, "alt": 0, "nuisance": 2}
        
        self.xmodmap("""add Mod1 = Num_Lock Hyper_L
                        add Mod2 = Hyper_R Meta_L Alt_L
                        add Mod3 = Super_R
                        add Mod4 = Alt_R Meta_R Super_L
                        add Mod5 = Scroll_Lock Super_R
                        """)
        mm = parti.keys.grok_modifier_map(self.display)
        print mm
        assert mm["scroll"] == 128
        assert mm["num"] == 8
        assert mm["meta"] == 16 | 64
        assert mm["super"] == 32 | 64 | 128
        assert mm["hyper"] == 8 | 16
        assert mm["alt"] == 16 | 64
        assert mm["nuisance"] == 2 | 8 | 128

    def test_parse_unparse_keys(self):
        self.clear_xmodmap()
        self.xmodmap("""add Mod1 = Meta_L Meta_R Alt_L
                        !add Mod2 = 
                        add Mod3 = Super_L Super_R
                        !add Mod4 = 
                        add Mod5 = Scroll_Lock
                        keycode 240 = p P
                        """)
        gtk.gdk.flush()
        mm = parti.keys.grok_modifier_map(self.display)
        keymap = gtk.gdk.keymap_get_for_display(self.display)

        o_keyval = gtk.gdk.keyval_from_name("o")
        o_keycode = keymap.get_entries_for_keyval(o_keyval)[0][0]

        assert parti.keys.parse_key("o", keymap, mm) == (0, [o_keycode])
        assert parti.keys.parse_key("O", keymap, mm) == (0, [o_keycode])
        assert parti.keys.parse_key("<alt>O", keymap, mm) == (8, [o_keycode])
        assert parti.keys.parse_key("<ALT>O", keymap, mm) == (8, [o_keycode])
        assert parti.keys.parse_key("<meTa>O", keymap, mm) == (8, [o_keycode])
        assert parti.keys.parse_key("<meTa><mod5>O", keymap, mm) == (8, [o_keycode])
        assert parti.keys.parse_key("<mod2>O", keymap, mm) == (16, [o_keycode])
        assert (parti.keys.parse_key("<mod4><mod3><MOD1><mod3>O", keymap, mm)
                == (8 | 32 | 64, [o_keycode]))

        p_keyval = gtk.gdk.keyval_from_name("p")
        p_keycodes = [entry[0]
                      for entry in keymap.get_entries_for_keyval(p_keyval)]
        assert len(p_keycodes) > 1
        assert parti.keys.parse_key("P", keymap, mm) == (0, p_keycodes)
        assert parti.keys.parse_key("<alt>p", keymap, mm) == (8, p_keycodes)

        assert parti.keys.unparse_key(0, o_keycode, keymap, mm) == "o"
        assert parti.keys.unparse_key(8, o_keycode, keymap, mm) == "<alt>o"
        assert parti.keys.unparse_key(16, o_keycode, keymap, mm) == "<mod2>o"
        assert parti.keys.unparse_key(32, o_keycode, keymap, mm) == "<super>o"
        assert (parti.keys.unparse_key(16 | 32, o_keycode, keymap, mm)
                == "<mod2><super>o")
        assert (parti.keys.unparse_key(8 | 32, o_keycode, keymap, mm)
                == "<super><alt>o")
        assert (parti.keys.unparse_key(1 | 2 | 4, o_keycode, keymap, mm)
                == "<shift><control>o")
        
