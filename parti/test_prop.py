from parti.test import *
import struct
import gtk
import parti.prop as p
import parti.lowlevel
import parti.error

class TestProp(TestWithSession):
    def setUp(self):
        super(TestProp, self).setUp()
        f = lambda: gtk.gdk.Window(self.display.get_default_screen().get_root_window(),
                                   width=10, height=10,
                                   window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                   wclass=gtk.gdk.INPUT_OUTPUT,
                                   event_mask=0)
        self.win = f()
        self.win2 = f()

    def enc(self, t, value, exp):
        enc = p._prop_encode(self.display, t, value)
        assert enc[-1] == exp
        assert p._prop_decode(self.display, t, enc[-1]) == value
        p.prop_set(self.win, "__TEST__", t, value)
        assert p.prop_get(self.win, "__TEST__", t) == value

    def test_simple_enc_dec_set_get(self):
        gtk.gdk.flush()
        self.enc("utf8", u"\u1000", "\xe1\x80\x80")
        self.enc(["utf8"], [u"a", u"\u1000"], "a\x00\xe1\x80\x80")
        self.enc("latin1", u"\u00c2", "\xc2")
        self.enc(["latin1"], [u"a", u"\u00c2"], "a\x00\xc2")
        # These are X predefined atoms with fixed numeric values
        self.enc("atom", "PRIMARY", struct.pack("@i", 1))
        self.enc(["atom"], ["PRIMARY", "SECONDARY"], struct.pack("@ii", 1, 2))
        self.enc("u32", 1, struct.pack("@i", 1))
        self.enc(["u32"], [1, 2], struct.pack("@ii", 1, 2))
        self.enc("window", self.win,
                 struct.pack("@i", parti.lowlevel.get_xwindow(self.win)))
        self.enc(["window"], [self.win, self.win2],
                 struct.pack("@ii", *map(parti.lowlevel.get_xwindow,
                                         (self.win, self.win2))))

    def test_prop_get_set_errors(self):
        assert p.prop_get(self.win, "SADFSAFDSADFASDF", "utf8") is None
        self.win2.destroy()
        gtk.gdk.flush()
        assert_raises(parti.error.XError,
                      parti.error.trap.call,
                      p.prop_set, self.win2, "ASDF", "utf8", u"")

        assert p.prop_get(self.win2, "ASDF", "utf8") is None
        p.prop_set(self.win, "ASDF", "utf8", u"")
        assert p.prop_get(self.win, "ASDF", "latin1") is None

    # FIXME: WMSizeHints and WMHints tests.  Stupid baroque formats...
