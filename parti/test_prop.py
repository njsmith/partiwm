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

    def test_strut_decode(self):
        partial = p.NetWMStrut(self.display,
                               struct.pack("@" + "i" * 12, *range(12)))
        assert partial.left == 0
        assert partial.right == 1
        assert partial.top == 2
        assert partial.bottom == 3
        assert partial.left_start_y == 4
        assert partial.left_end_y == 5
        assert partial.right_start_y == 6
        assert partial.right_end_y == 7
        assert partial.top_start_x == 8
        assert partial.top_end_x == 9
        assert partial.bottom_start_x == 10
        assert partial.bottom_stop_x == 11

        full = p.NetWMStrut(self.display,
                            struct.pack("@" + "i" * 4, *range(4)))
        assert full.left == 0
        assert full.right == 1
        assert full.top == 2
        assert full.bottom == 3
        assert full.left_start_y == 0
        assert full.left_end_y == 0
        assert full.right_start_y == 0
        assert full.right_end_y == 0
        assert full.top_start_x == 0
        assert full.top_end_x == 0
        assert full.bottom_start_x == 0
        assert full.bottom_stop_x == 0

        # FIXME: use ["utf8"] trick to round-trip this (or add a way to push
        # CARDINAL bytes directly to the server for testing)

    def test_icon(self):
        import cairo
        LARGE_W = 49
        LARGE_H = 47
        SMALL_W = 25
        SMALL_H = 23

        large = cairo.ImageSurface(cairo.FORMAT_ARGB32, LARGE_W, LARGE_H)
        # Scribble something on our "icon"
        large_cr = cairo.Context(large)
        pat = cairo.LinearGradient(0, 0, LARGE_W, LARGE_H)
        pat.add_color_stop_rgb(0, 1, 0, 0)
        pat.add_color_stop_rgb(1, 0, 1, 0)
        large_cr.set_source(pat)
        large_cr.paint()

        # Make a "small version"
        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, SMALL_W, SMALL_H)
        small_cr = cairo.Context(small)
        small_cr.set_source(pat)
        small_cr.paint()

        small_dat = struct.pack("@ii", SMALL_W, SMALL_H) + str(small.get_data())
        large_dat = struct.pack("@ii", LARGE_W, LARGE_H) + str(large.get_data())

        icon_bytes = small_dat + large_dat + small_dat

        p.prop_set(self.win, "_NET_WM_ICON", "debug-CARDINAL", icon_bytes)
        pixmap = p.prop_get(self.win, "_NET_WM_ICON", "icon")

        assert pixmap.get_size() == (LARGE_W, LARGE_H)

        round_tripped = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                           *pixmap.get_size())
        round_tripped_cr = gtk.gdk.CairoContext(cairo.Context(round_tripped))
        round_tripped_cr.set_source_pixmap(pixmap, 0, 0)
        round_tripped_cr.set_operator(cairo.OPERATOR_SOURCE)
        round_tripped_cr.paint()

        assert str(round_tripped.get_data()) == str(large.get_data())

    # FIXME: WMSizeHints and WMHints tests.  Stupid baroque formats...
