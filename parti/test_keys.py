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

    def test_grok_modifier_map(self):
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
        subprocess.call(["xmodmap", "-display", self.display_name, "-pm"])
        mm = parti.keys.grok_modifier_map(self.display)
        print mm
        assert mm == {"shift": 1, "lock": 2, "control": 4,
                      "mod1": 8, "mod2": 16, "mod3": 32, "mod4": 64,
                      "mod5": 128,
                      "scroll": 0, "num": 0, "meta": 0, "super": 0,
                      "hyper": 0, "alt": 0}
        
        self.xmodmap("""add Mod1 = Num_Lock Hyper_L
                        add Mod2 = Hyper_R Meta_L Alt_L
                        add Mod3 = Super_R
                        add Mod4 = Alt_R Meta_R Super_L
                        add Mod5 = Scroll_Lock Super_R
                        """)
        subprocess.call(["xmodmap", "-display", self.display_name, "-pm"])
        mm = parti.keys.grok_modifier_map(self.display)
        print mm
        assert mm["scroll"] == 128
        assert mm["num"] == 8
        assert mm["meta"] == 16 | 64
        assert mm["super"] == 32 | 64 | 128
        assert mm["hyper"] == 8 | 16
        assert mm["alt"] == 16 | 64
