# Monolithic file containing simple Pyrex wrappers for otherwise unexposed
# GDK, GTK, and X11 primitives, plus utility functions for writing same.
# Really this should be split up, but I haven't figured out how Pyrex's
# cimport stuff works yet.

import struct

import gobject
import gtk
import gtk.gdk

from parti.util import dump_exc, LameStruct
from parti.error import trap, XError

###################################
# Headers, python magic
###################################

cdef extern from "X11/Xlib.h":
    pass
cdef extern from "X11/Xutil.h":
    pass

cdef extern from "gdk/gdk.h":
    pass
cdef extern from "gdk/gdkx.h":
    pass

cdef extern from "Python.h":
    object PyString_FromStringAndSize(char * s, int len)

# Serious black magic happens here (I owe these guys beers):
cdef extern from "pygobject.h":
    void init_pygobject()
init_pygobject()
    
cdef extern from "pygtk/pygtk.h":
    void init_pygtk()
init_pygtk()
# Now all the macros in those header files will work.

###################################
# GObject
###################################

cdef extern from *:
    ctypedef struct cGObject "GObject":
        pass
    cGObject * pygobject_get(object box)
    object pygobject_new(cGObject * contents)

cdef cGObject * unwrap(box, pyclass) except? NULL:
    # Extract a raw GObject* from a PyGObject wrapper.
    assert issubclass(pyclass, gobject.GObject)
    if not isinstance(box, pyclass):
        raise TypeError, ("object %r is not a %r" % (box, pyclass))
    return pygobject_get(box)

# def print_unwrapped(box):
#     "For debugging the above."
#     cdef cGObject * unwrapped
#     unwrapped = unwrap(box, gobject.GObject)
#     if unwrapped == NULL:
#         print "contents is NULL!"
#     else:
#         print "contents is %s" % (<long long>unwrapped)

cdef object wrap(cGObject * contents):
    # Put a raw GObject* into a PyGObject wrapper.
    return pygobject_new(contents)

###################################
# Raw Xlib and GDK
###################################

######
# Xlib primitives and constants
######

include "constants.pxi"

cdef extern from *:
    ctypedef struct Display:
        pass
    # To make it easier to translate stuff in the X header files into
    # appropriate pyrex declarations, without having to untangle the typedefs
    # over and over again, here are some convenience typedefs.  (Yes, CARD32
    # really is 64 bits on 64-bit systems.  Why?  I have no idea.)
    ctypedef unsigned long CARD32
    ctypedef CARD32 XID

    ctypedef int Bool
    ctypedef int Status
    ctypedef CARD32 Atom
    ctypedef XID Drawable
    ctypedef XID Window
    ctypedef XID Pixmap
    ctypedef CARD32 Time

    int XFree(void * data)

    # Needed to find the secret window Gtk creates to own the selection, so we
    # can broadcast it:
    Window XGetSelectionOwner(Display * display, Atom selection)

    # There are way more event types than this; add them as needed.
    ctypedef struct XAnyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display * display
        Window window
    # Needed to broadcast that we are a window manager, among other things:
    union payload_for_XClientMessageEvent:
        char b[20]
        short s[10]
        long l[5]
    ctypedef struct XClientMessageEvent:
        Atom message_type
        int format
        payload_for_XClientMessageEvent data
    # SubstructureRedirect-related events:
    ctypedef struct XMapRequestEvent:
        Window parent  # Same as xany.window, confusingly.
        Window window  
    ctypedef struct XConfigureRequestEvent:
        Window parent  # Same as xany.window, confusingly.
        Window window  
        int x, y, width, height, border_width
        Window above
        int detail
        unsigned long value_mask
    ctypedef struct XCirculateRequestEvent:
        Window parent  # Same as xany.window, confusingly.
        Window window  
        int place
    # Focus handling
    ctypedef struct XFocusChangeEvent:
        Window window
        int mode, detail
    # We have to generate synthetic ConfigureNotify's:
    ctypedef struct XConfigureEvent:
        Window event   # Same as xany.window, confusingly.  The selected-on
                       # window.
        Window window  # The effected window.
        int x, y, width, height, border_width
        Window above
        Bool override_redirect
    ctypedef union XEvent:
        int type
        XAnyEvent xany
        XMapRequestEvent xmaprequest
        XConfigureRequestEvent xconfigurerequest
        XCirculateRequestEvent xcirculaterequest
        XConfigureEvent xconfigure
        XFocusChangeEvent xfocus
        XClientMessageEvent xclient
        
    Status XSendEvent(Display *, Window target, Bool propagate,
                      long event_mask, XEvent * event)

    int XSelectInput(Display * display, Window w, long event_mask)

    int cXChangeProperty "XChangeProperty" \
        (Display *, Window w, Atom property,
         Atom type, int format, int mode, unsigned char * data, int nelements)
    int cXGetWindowProperty "XGetWindowProperty" \
        (Display * display, Window w, Atom property,
         long offset, long length, Bool delete,
         Atom req_type, Atom * actual_type,
         int * actual_format,
         unsigned long * nitems, unsigned long * bytes_after,
         unsigned char ** prop)
    int cXDeleteProperty "XDeleteProperty" \
        (Display * display, Window w, Atom property)


    int cXAddToSaveSet "XAddToSaveSet" (Display * display, Window w)

    ctypedef struct XWindowAttributes:
        int x, y, width, height, border_width
        Bool override_redirect
        int map_state
        long your_event_mask
    Status XGetWindowAttributes(Display * display, Window w,
                                XWindowAttributes * attributes)
    
    ctypedef struct XWindowChanges:
        int x, y, width, height, border_width
        Window sibling
        int stack_mode
    int cXConfigureWindow "XConfigureWindow" \
        (Display * display, Window w,
         unsigned int value_mask, XWindowChanges * changes)

    Bool XTranslateCoordinates(Display * display,
                               Window src_w, Window dest_w,
                               int src_x, int src_y,
                               int * dest_x, int * dest_y,
                               Window * child)

    Status XQueryTree(Display * display, Window w,
                      Window * root, Window * parent,
                      Window ** children, unsigned int * nchildren)

    int cXSetInputFocus "XSetInputFocus" (Display * display, Window focus,
                                          int revert_to, Time time)
    # Debugging:
    int cXGetInputFocus "XGetInputFocus" (Display * display, Window * focus,
                                          int * revert_to)

    # Keyboard bindings
    ctypedef unsigned char KeyCode
    ctypedef struct XModifierKeymap:
        int max_keypermod
        KeyCode * modifiermap # an array with 8*max_keypermod elements
    XModifierKeymap * XGetModifierMapping(Display * display)
    int XFreeModifiermap(XModifierKeymap *)
    int XGrabKey(Display * display, int keycode, unsigned int modifiers,
                 Window grab_window, Bool owner_events,
                 int pointer_mode, int keyboard_mode)
    int XUngrabKey(Display * display, int keycode, unsigned int modifiers,
                   Window grab_window)

    # XKillClient
    int cXKillClient "XKillClient" (Display *, XID)
    
######
# GDK primitives, and wrappers for Xlib
######

# Basic utilities:

cdef extern from *:
    ctypedef struct cGdkWindow "GdkWindow":
        pass
    Window GDK_WINDOW_XID(cGdkWindow *)

    ctypedef struct cGdkDisplay "GdkDisplay":
        pass
    Display * GDK_DISPLAY_XDISPLAY(cGdkDisplay *)

    cGdkDisplay * gdk_x11_lookup_xdisplay(Display *)

def get_xwindow(pywindow):
    return GDK_WINDOW_XID(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window))

def get_pywindow(display_source, xwindow):
    disp = get_display_for(display_source)
    win = gtk.gdk.window_foreign_new_for_display(disp, xwindow)
    if win is None:
        raise XError, BadWindow
    return win

def get_display_for(obj):
    if isinstance(obj, gtk.gdk.Display):
        return obj
    elif isinstance(obj, (gtk.gdk.Drawable,
                          gtk.Widget,
                          gtk.Clipboard)):
        return obj.get_display()
    else:
        raise TypeError, "Don't know how to get a display from %r" % (obj,)

cdef cGdkDisplay * get_raw_display_for(obj) except? NULL:
    return <cGdkDisplay*> unwrap(get_display_for(obj), gtk.gdk.Display)

cdef Display * get_xdisplay_for(obj) except? NULL:
    return GDK_DISPLAY_XDISPLAY(get_raw_display_for(obj))

# Atom stuff:
cdef extern from *:
    ctypedef void * GdkAtom
    # FIXME: this should have stricter type checking
    GdkAtom PyGdkAtom_Get(object)
    object PyGdkAtom_New(GdkAtom)
    Atom gdk_x11_atom_to_xatom_for_display(cGdkDisplay *, GdkAtom)
    GdkAtom gdk_x11_xatom_to_atom_for_display(cGdkDisplay *, Atom)

def get_xatom(display_source, str_or_xatom):
    """Returns the X atom corresponding to the given Python string or Python
    integer (assumed to already be an X atom)."""
    if isinstance(str_or_xatom, (int, long)):
        return str_or_xatom
    assert isinstance(str_or_xatom, str)
    gdkatom = gtk.gdk.atom_intern(str_or_xatom)
    return gdk_x11_atom_to_xatom_for_display(
        get_raw_display_for(display_source),
        PyGdkAtom_Get(gdkatom),
        )

def get_pyatom(display_source, xatom):
    if xatom > 2 ** 32:
        raise Exception, "weirdly huge purported xatom: %s" % xatom
    cdef cGdkDisplay * disp
    disp = get_raw_display_for(display_source)
    return str(PyGdkAtom_New(gdk_x11_xatom_to_atom_for_display(disp, xatom)))

# Property handling:

# (Note: GDK actually has a wrapper for the Xlib property API,
# gdk_property_{get,change,delete}.  However, the documentation for
# gtk_property_get says "gtk_property_get() makes the situation worse...the
# semantics should be considered undefined...You are advised to use
# XGetWindowProperty() directly".  In light of this, we just ignore the GDK
# property API and use the Xlib functions directly.)

def _munge_packed_ints_to_longs(data):
    assert len(data) % sizeof(int) == 0
    n = len(data) / sizeof(int)
    format_from = "@" + "i" * n
    format_to = "@" + "l" * n
    return struct.pack(format_to, *struct.unpack(format_from, data))

def XChangeProperty(pywindow, property, value):
    "Set a property on a window."
    (type, format, data) = value
    assert format in (8, 16, 32)
    assert (len(data) % (format / 8)) == 0
    nitems = len(data) / (format / 8)
    if format == 32:
        data = _munge_packed_ints_to_longs(data)
    cdef char * data_str
    data_str = data
    cXChangeProperty(get_xdisplay_for(pywindow),
                     get_xwindow(pywindow),
                     get_xatom(pywindow, property),
                     get_xatom(pywindow, type),
                     format,
                     PropModeReplace,
                     <unsigned char *>data_str,
                     nitems)

def _munge_packed_longs_to_ints(data):
    assert len(data) % sizeof(long) == 0
    n = len(data) / sizeof(long)
    format_from = "@" + "l" * n
    format_to = "@" + "i" * n
    return struct.pack(format_to, *struct.unpack(format_from, data))

class PropertyError(Exception):
    pass
class BadPropertyType(PropertyError):
    pass
class PropertyOverflow(PropertyError):
    pass
class NoSuchProperty(PropertyError):
    pass
def XGetWindowProperty(pywindow, property, req_type):
    # "64k is enough for anybody"
    # (Except, I've found window icons that are strictly larger...)
    buffer_size = 64 * 1024 * 5
    cdef Atom xactual_type
    cdef int actual_format
    cdef unsigned long nitems, bytes_after
    cdef unsigned char * prop
    cdef Status status
    xreq_type = get_xatom(pywindow, req_type)
    # This is the most bloody awful API I have ever seen.  You will probably
    # not be able to understand this code fully without reading
    # XGetWindowProperty's man page at least 3 times, slowly.
    status = cXGetWindowProperty(get_xdisplay_for(pywindow),
                                 get_xwindow(pywindow),
                                 get_xatom(pywindow, property),
                                 0,
                                 # This argument has to be divided by 4.  Thus
                                 # speaks the spec.
                                 buffer_size / 4,
                                 False,
                                 xreq_type, &xactual_type,
                                 &actual_format, &nitems, &bytes_after, &prop)
    if status != Success:
        raise PropertyError, "no such window"
    if xactual_type == XNone:
        raise NoSuchProperty, property
    if xreq_type != xactual_type:
        raise BadPropertyType, xactual_type
    # This should only occur for bad property types:
    assert not (bytes_after and not nitems)
    # actual_format is in (8, 16, 32), and is the number of bits in a logical
    # element.  However, this doesn't mean that each element is stored in that
    # many bits, oh no.  On a 32-bit machine it is, but on a 64-bit machine,
    # iff the output array contains 32-bit integers, than each one is given
    # 64-bits of space.
    assert actual_format > 0
    if actual_format == 8:
        bytes_per_item = 1
    elif actual_format == 16:
        bytes_per_item = sizeof(short)
    elif actual_format == 32:
        bytes_per_item = sizeof(long)
    else:
        assert False
    nbytes = bytes_per_item * nitems
    if bytes_after:
        raise PropertyOverflow, nbytes + bytes_after
    data = PyString_FromStringAndSize(<char *>prop, nbytes)
    XFree(prop)
    if actual_format == 32:
        return _munge_packed_longs_to_ints(data)
    else:
        return data

def XDeleteProperty(pywindow, property):
    cXDeleteProperty(get_xdisplay_for(pywindow),
                     get_xwindow(pywindow),
                     get_xatom(pywindow, property))

# Save set handling
def XAddToSaveSet(pywindow):
    cXAddToSaveSet(get_xdisplay_for(pywindow),
                   get_xwindow(pywindow))

# Children listing
def get_children(pywindow):
    cdef Window root, parent
    cdef Window * children
    cdef unsigned int nchildren
    XQueryTree(get_xdisplay_for(pywindow),
               get_xwindow(pywindow),
               &root, &parent, &children, &nchildren)
    pychildren = []
    for i from 0 <= i < nchildren:
        pychildren.append(get_pywindow(pywindow, children[i]))
    if children != NULL:
        XFree(children)
    return pychildren

# Mapped status
def is_mapped(pywindow):
    cdef XWindowAttributes attrs
    XGetWindowAttributes(get_xdisplay_for(pywindow),
                         get_xwindow(pywindow),
                         &attrs)
    return attrs.map_state != IsUnmapped

# Focus management
def XSetInputFocus(pywindow, time=None):
    # Always does RevertToParent
    if time is None:
        time = CurrentTime
    cXSetInputFocus(get_xdisplay_for(pywindow),
                    get_xwindow(pywindow),
                    RevertToParent,
                    time)
    printFocus(pywindow)

def printFocus(display_source):
    # Debugging
    cdef Window w
    cdef int revert_to
    cXGetInputFocus(get_xdisplay_for(display_source), &w, &revert_to)
    print "Current focus: %s, %s" % (hex(w), revert_to)
    
# Geometry hints

cdef extern from *:
    ctypedef struct cGdkGeometry "GdkGeometry":
        int min_width, min_height, max_width, max_height, 
        int base_width, base_height, width_inc, height_inc
        double min_aspect, max_aspect
    void gdk_window_constrain_size(cGdkGeometry *geometry,
                                   unsigned int flags, int width, int height,
                                   int * new_width, int * new_height)

def calc_constrained_size(width, height, hints):
    if hints is None:
        return (width, height, width, height)

    cdef cGdkGeometry geom
    cdef int new_width, new_height
    flags = 0
    
    if hints.max_size is not None:
        flags = flags | gtk.gdk.HINT_MAX_SIZE
        geom.max_width, geom.max_height = hints.max_size
    if hints.min_size is not None:
        flags = flags | gtk.gdk.HINT_MIN_SIZE
        geom.min_width, geom.min_height = hints.min_size
    if hints.base_size is not None:
        flags = flags | gtk.gdk.HINT_BASE_SIZE
        geom.base_width, geom.base_height = hints.base_size
    if hints.resize_inc is not None:
        flags = flags | gtk.gdk.HINT_RESIZE_INC
        geom.width_inc, geom.height_inc = hints.resize_inc
    if hints.min_aspect is not None:
        assert hints.max_aspect is not None
        flags = flags | gtk.gdk.HINT_ASPECT
        geom.min_aspect = hints.min_aspect
        geom.max_aspect = hints.max_aspect
    gdk_window_constrain_size(&geom, flags, width, height,
                              &new_width, &new_height)

    vis_width, vis_height = (new_width, new_height)
    if hints.resize_inc is not None:
        if hints.base_size is not None:
            vis_width = vis_width - hints.base_size[0]
            vis_height = vis_height - hints.base_size[1]
        vis_width = vis_width / hints.resize_inc[0]
        vis_height = vis_height / hints.resize_inc[1]

    return (new_width, new_height, vis_width, vis_height)
        

###################################
# Keyboard binding
###################################

def get_modifier_map(display_source):
    cdef XModifierKeymap * xmodmap
    xmodmap = XGetModifierMapping(get_xdisplay_for(display_source))
    try:
        keycode_array = []
        for i in range(8 * xmodmap.max_keypermod):
            keycode_array.append(xmodmap.modifiermap[i])
        return (xmodmap.max_keypermod, keycode_array)
    finally:
        XFreeModifiermap(xmodmap)

def grab_key(pywindow, keycode, modifiers):
    print "grabbing %s (%s) on %s" % (keycode, hex(modifiers), pywindow)
    XGrabKey(get_xdisplay_for(pywindow), keycode, modifiers,
             get_xwindow(pywindow),
             # Really, grab the key even if it's also in another window we own
             False,
             # Don't stall the pointer upon this key being pressed:
             GrabModeAsync,
             # Don't stall the keyboard upon this key being pressed (need to
             # change this if we ever want to allow for multi-key bindings
             # a la emacs):
             GrabModeAsync)
    print "XGrabKey finished"
    
def ungrab_all_keys(pywindow):
    XUngrabKey(get_xdisplay_for(pywindow), AnyKey, AnyModifier,
               get_xwindow(pywindow))

###################################
# XKillClient
###################################

def XKillClient(pywindow):
    cXKillClient(get_xdisplay_for(pywindow), get_xwindow(pywindow))

###################################
# XTest
###################################

cdef extern from "X11/extensions/XTest.h":
    Bool XTestQueryExtension(Display *, int *, int *,
                             int * major, int * minor)
    int XTestFakeKeyEvent(Display *, unsigned int keycode,
                          Bool is_press, unsigned long delay)
    int XTestFakeButtonEvent(Display *, unsigned int button,
                             Bool is_press, unsigned long delay)

def _ensure_XTest_support(display_source):
    display = get_display_for(display_source)
    cdef int ignored
    if display.get_data("XTest-support") is None:
        display.set_data("XTest-support",
                         XTestQueryExtension(get_xdisplay_for(display),
                                             &ignored, &ignored,
                                             &ignored, &ignored))
    if not display.get_data("XTest-support"):
        raise ValueError, "XTest not supported"

def xtest_fake_key(display_source, keycode, is_press):
    _ensure_XTest_support(display_source)
    XTestFakeKeyEvent(get_xdisplay_for(display_source), keycode, is_press, 0)

def xtest_fake_button(display_source, button, is_press):
    _ensure_XTest_support(display_source)
    XTestFakeButtonEvent(get_xdisplay_for(display_source), button, is_press, 0)

###################################
# Composite
###################################

cdef extern from "X11/extensions/Xcomposite.h":
    Bool XCompositeQueryExtension(Display *, int *, int *)
    Status XCompositeQueryVersion(Display *, int * major, int * minor)
    unsigned int CompositeRedirectManual
    unsigned int CompositeRedirectAutomatic
    void XCompositeRedirectWindow(Display *, Window, int mode)
    void XCompositeRedirectSubwindows(Display *, Window, int mode)
    void XCompositeUnredirectWindow(Display *, Window, int mode)
    void XCompositeUnredirectSubwindows(Display *, Window, int mode)
    Pixmap XCompositeNameWindowPixmap(Display *, Window)

    int XFreePixmap(Display *, Pixmap)

def _ensure_XComposite_support(display_source):
    cdef int ignored
    cdef int major
    cdef int minor
    display = get_display_for(display_source)
    if display.get("XComposite-support") is None:
        display.set_data("XComposite-support", False)
        if XCompositeQueryExtension(get_xdisplay_for(display),
                                    &ignored, &ignored):
            required_version = (0, 4)
            (major, minor) = required_version
            if XCompositeQueryVersion(get_xdisplay_for(display),
                                      &major, &minor):
                if (major, minor) == required_version:
                    display.set_data("XComposite-support", True)
    if not display.get_data("XComposite-support"):
        raise ValueError, "Composite not supported, or insufficiently supported"

def _manual_mode(manual_redraw):
    if manual_redraw:
        return CompositeRedirectManual
    else:
        return CompositeRedirectAutomatic

def xcomposite_redirect_window(window, manual_redraw):
    _ensure_XComposite_support(window)
    XCompositeRedirectWindow(get_xdisplay_for(window), get_xwindow(window),
                             _manual_mode(mode))

def xcomposite_redirect_subwindows(window, manual_redraw):
    _ensure_XComposite_support(window)
    XCompositeRedirectSubwindows(get_xdisplay_for(window), get_xwindow(window),
                                 _manual_mode(mode))

def xcomposite_unredirect_window(window, manual_redraw):
    _ensure_XComposite_support(window)
    XCompositeUnredirectWindow(get_xdisplay_for(window), get_xwindow(window),
                               _manual_mode(mode))

def xcomposite_unredirect_subwindows(window, manual_redraw):
    _ensure_XComposite_support(window)
    XCompositeUnredirectSubwindows(get_xdisplay_for(window), get_xwindow(window),
                                   _manual_mode(mode))

class _PixmapCleanupHandler(object):
    def __init__(self, pixmap):
        self.pixmap = pixmap

    def cleanup(self):
        if self.pixmap is not None:
            XFreePixmap(get_xdisplay_for(self.pixmap), self.pixmap.xid)
            self.pixmap = None

    def __del__(self):
        self.cleanup()

def xcomposite_name_window_pixmap(window):
    _ensure_XComposite_support(window)
    xpixmap = XCompositeNameWindowPixmap(get_xdisplay_for(window),
                                         get_xwindow(window))
    gpixmap = gtk.gdk.pixmap_foreign_new_for_display(get_display_for(window),
                                                     xpixmap)
    return _PixmapCleanupHandler(gpixmap)

###################################
# Xdamage
###################################

cdef extern from "X11/extensions/Xfixes.h":
    ctypedef XID XserverRegion
    XserverRegion XFixesCreateRegion(Display *, XRectangle *, int nrectangles)
    void XFixesDestroyRegion(Display *, XserverRegion)

cdef extern from "X11/extensions/Xdamage.h":
    ctypedef XID Damage
    unsigned int XDamageReportDeltaRectangles
    unsigned int XDamageNotify
    ctypedef struct XRectangle:
        short x, y
        unsigned short width, height
    ctypedef struct XDamageNotifyEvent:
        Damage damage
        int level
        Bool more
        XRectangle area
    Bool XDamageQueryExtension(Display *, int * event_base, int *)
    Status XDamageQueryVersion(Display *, int * major, int * minor)
    Damage XDamageCreate(Display *, Drawable, int level)
    void XDamageDestroy(Display *, Damage)
    void XDamageSubtract(Display *, Damage,
                         XserverRegion repair, XserverRegion parts)

def _ensure_XDamage_support(display_source):
    cdef int event_base
    cdef int ignored
    cdef int major
    cdef int minor
    display = get_display_for(display_source)
    if display.get("XDamage-support") is None:
        display.set_data("XDamage-support", False)
        if XDamageQueryExtension(get_xdisplay_for(display),
                                 &event_base, &ignored):
            display.set_data("XDamage-event-base", event_base)
            required_version = (1, 0)
            (major, minor) = required_version
            if XDamageQueryVersion(get_xdisplay_for(display),
                                   &major, &minor):
                if (major, minor) == required_version:
                    display.set_data("XDamage-support", True)
    if not display.get_data("XDamage-support"):
        raise ValueError, "Xdamage not supported, or insufficiently supported"

def xdamage_start(window):
    _ensure_XDamage_support(window)
    return XDamageCreate(get_xdisplay_for(window), get_xwindow(window),
                         XDamageReportDeltaRectangles)

def xdamage_stop(display_source, handle):
    _ensure_XDamage_support(display_source)
    XDamageDestroy(get_xdisplay_for(display_source), handle)

def xdamage_acknowledge(display_source, handle, x, y, width, height):
    cdef XRectangle rect
    rect.x = x
    rect.y = y
    rect.width = width
    rect.height = height
    repair = XFixesCreateRegion(get_xdisplay_for(display_source), &rect, 1)
    XDamageSubtract(get_xdisplay_for(display_source), handle, repair, XNone)
    XFixesDestroyRegion(get_xdisplay_for(display_source), repair)

###################################
# Smarter convenience wrappers
###################################

def myGetSelectionOwner(display_source, pyatom):
    return XGetSelectionOwner(get_xdisplay_for(display_source),
                              get_xatom(display_source, pyatom))

def sendClientMessage(target, propagate, event_mask,
                      message_type, data0, data1, data2, data3, data4):
    # data0 etc. are passed through get_xatom, so they can be integers, which
    # are passed through directly, or else they can be strings, which are
    # converted appropriately.
    cdef Display * display
    display = get_xdisplay_for(target)
    cdef Window w
    w = get_xwindow(target)
    print "sending message to %s" % hex(w)
    cdef XEvent e
    e.type = ClientMessage
    e.xany.display = display
    e.xany.window = w
    e.xclient.message_type = get_xatom(target, message_type)
    e.xclient.format = 32
    e.xclient.data.l[0] = get_xatom(target, data0)
    e.xclient.data.l[1] = get_xatom(target, data1)
    e.xclient.data.l[2] = get_xatom(target, data2)
    e.xclient.data.l[3] = get_xatom(target, data3)
    e.xclient.data.l[4] = get_xatom(target, data4)
    cdef Status s
    s = XSendEvent(display, w, propagate, event_mask, &e)
    if s == 0:
        raise ValueError, "failed to serialize ClientMessage"

def sendConfigureNotify(pywindow):
    cdef Display * display
    display = get_xdisplay_for(pywindow)
    cdef Window window
    window = get_xwindow(pywindow)

    # Get basic attributes
    cdef XWindowAttributes attrs
    XGetWindowAttributes(display, window, &attrs)

    # Figure out where the window actually is in root coordinate space
    cdef int dest_x, dest_y
    cdef Window child
    if not XTranslateCoordinates(display, window,
                                 get_xwindow(gtk.gdk.get_default_root_window()),
                                 0, 0,
                                 &dest_x, &dest_y, &child):
        # Window seems to have disappeared, so never mind.
        print "couldn't TranslateCoordinates (maybe window is gone)"
        return

    # Send synthetic ConfigureNotify (ICCCM 4.2.3, for example)
    cdef XEvent e
    e.type = ConfigureNotify
    e.xconfigure.event = window
    e.xconfigure.window = window
    e.xconfigure.x = dest_x
    e.xconfigure.y = dest_y
    e.xconfigure.width = attrs.width
    e.xconfigure.height = attrs.height
    e.xconfigure.border_width = attrs.border_width
    e.xconfigure.above = XNone
    e.xconfigure.override_redirect = attrs.override_redirect
    
    cdef Status s
    s = XSendEvent(display, window, False, StructureNotifyMask, &e)
    if s == 0:
        raise ValueError, "failed to serialize ConfigureNotify"

def configureAndNotify(pywindow, x, y, width, height, fields=None):
    cdef Display * display
    display = get_xdisplay_for(pywindow)
    cdef Window window
    window = get_xwindow(pywindow)

    # Reconfigure the window.  We have to use XConfigureWindow directly
    # instead of GdkWindow.resize, because GDK does not give us any way to
    # squash the border.

    # The caller can pass an XConfigureWindow-style fields mask to turn off
    # some of these bits; this is useful if they are pulling such a field out
    # of a ConfigureRequest (along with the other arguments they are passing
    # to us).  This also means we need to be careful to zero out any bits
    # besides these, because they could be set to anything.
    all_optional_fields_we_know = CWX | CWY | CWWidth | CWHeight
    if fields is None:
        fields = all_optional_fields_we_know
    else:
        fields = fields & all_optional_fields_we_know
    # But we always unconditionally squash the border to zero.
    fields = fields | CWBorderWidth

    cdef XWindowChanges changes
    changes.x = x
    changes.y = y
    changes.width = width
    changes.height = height
    changes.border_width = 0
    cXConfigureWindow(display, window, fields, &changes)
    # Tell the client.
    sendConfigureNotify(pywindow)

###################################
# Event handling
###################################

# We need custom event handling in a few ways:
#   -- We need to listen to various events on client windows, even though they
#      have no GtkWidget associated.
#   -- We need to listen to various events that are not otherwise wrapped by
#      GDK at all.  (In particular, the SubstructureRedirect events.)
# To do this, we use two different hooks in GDK:
#   gdk_window_add_filter: This allows us to snoop on all events before they
#     are converted into GDK events.  We use this to capture:
#       MapRequest
#       ConfigureRequest
#       FocusIn
#       FocusOut
#       ClientMessage
#     (We could get ClientMessage from PyGTK using the API below, but
#     PyGTK's ClientMessage handling is annoying -- see bug #466990.)
#   gdk_event_handler_set: This allows us to snoop on all events after they
#     have gone through the GDK event handling machinery, just before they
#     enter GTK.  Everything that we catch in this manner could just as well
#     be caught by the gdk_window_add_filter technique, but waiting until here
#     lets us write less binding gunk.  We use this to catch:
#       PropertyNotify
#       Unmap
#       Destroy
# Our hooks in any case use the "parti-route-events-to" GObject user data
# field of the gtk.gdk.Window's involved.  For the SubstructureRedirect
# events, we use this field of either the window that is making the request,
# or, if its field is unset, to the window that actually has
# SubstructureRedirect selected on it; for other events, we send it to the
# event window directly.
#
# So basically, to use this code:
#   -- Import this module to install the global event filters
#   -- Call win.set_data("parti-route-events-to", obj) on random windows.
#   -- Call addXSelectInput or its convenience wrappers, substructureRedirect
#      and selectFocusChange.
#   -- Receive interesting signals on 'obj'.

cdef extern from *:
    ctypedef enum GdkFilterReturn:
        GDK_FILTER_CONTINUE   # If we ignore the event
        GDK_FILTER_TRANSLATE  # If we converted the event to a GdkEvent
        GDK_FILTER_REMOVE     # If we handled the event and GDK should ignore it

    ctypedef struct GdkXEvent:
        pass
    ctypedef struct GdkEvent:
        pass

    ctypedef GdkFilterReturn (*GdkFilterFunc)(GdkXEvent *, GdkEvent *, void *)
    void gdk_window_add_filter(cGdkWindow * w,
                               GdkFilterFunc filter,
                               void * userdata)

def addXSelectInput(pywindow, add_mask):
    cdef XWindowAttributes curr
    XGetWindowAttributes(get_xdisplay_for(pywindow),
                         get_xwindow(pywindow),
                         &curr)
    mask = curr.your_event_mask
    mask = mask | add_mask
    XSelectInput(get_xdisplay_for(pywindow),
                 get_xwindow(pywindow),
                 mask)

def substructureRedirect(pywindow):
    """Enable SubstructureRedirect on the given window.

    This enables reception of MapRequest and ConfigureRequest events.  At the
    X level, it also enables the reception of CirculateRequest events, but
    those are pretty useless, so we just ignore such events unconditionally
    rather than routing them anywhere.  (The circulate request appears to be
    in the protocol just so simple window managers have an easy way to
    implement the equivalent of alt-tab; I can't imagine how it'd be useful
    these days.  Metacity and KWin do not support it; GTK+/GDK and Qt4 provide
    no way to actually send it.)"""
    addXSelectInput(pywindow, SubstructureRedirectMask)

def selectFocusChange(pywindow):
    addXSelectInput(pywindow, FocusChangeMask)

# No need to select for ClientMessage; in fact, one cannot select for
# ClientMessages.  If they are sent with an empty mask, then they go to the
# client that owns the window they are sent to, otherwise they go to any
# clients that are selecting for that mask they are sent with.

def _maybe_send_event(handler, signal, event):
    if signal in gobject.signal_list_names(handler):
        handler.emit(signal, event)
    else:
        print ("Handler %r has no '%s' signal; ignoring event"
               % (handler, signal))

def _route_event(event, signal, parent_signal):
    # Sometimes we get GDK events with event.window == None, because they are
    # for windows we have never created a GdkWindow object for, and GDK
    # doesn't do so just for this event.  As far as I can tell this only
    # matters for override redirect windows when they disappear, and we don't
    # care about those anyway.
    if event.window is None:
        assert event.type in (gtk.gdk.UNMAP, gtk.gdk.DESTROY)
        return
    handler = event.window.get_data("parti-route-events-to")
    if handler is not None:
        print "  sending event to event.window's handler"
        _maybe_send_event(handler, signal, event)
    elif parent_signal is not None:
        handler = event.parent.get_data("parti-route-events-to")
        if handler is not None:
            print "  sending event to event.parent's handler"
            print handler, parent_signal, event
            _maybe_send_event(handler, parent_signal, event)

_x_event_signals = {
    MapRequest: ("map-request-event", "child-map-request-event"),
    ConfigureRequest: ("configure-request-event",
                       "child-configure-request-event"),
    FocusIn: ("parti-focus-in-event", None),
    FocusOut: ("parti-focus-out-event", None),
    ClientMessage: ("parti-client-message-event", None),
    "XDamageNotify": ("parti-damage-event", None),
    }

def _gw(display, xwin):
    return trap.call_synced(get_pywindow, display, xwin)

cdef GdkFilterReturn x_event_filter(GdkXEvent * e_gdk,
                                    GdkEvent * gdk_event,
                                    void * userdata):
    cdef XEvent * e
    e = <XEvent*>e_gdk
    try:
        d = wrap(<cGObject*>gdk_x11_lookup_xdisplay(e.xany.display))
        my_events = dict(_x_event_signals)
        if d.get_data("XDamage-event-base") is not None:
            damage_type = d.get_data("XDamage-event-base") + XDamageNotify
            my_events[damage_type] = my_events["XDamageNotify"]
        else:
            damage_type = -1
        if e.type in my_events:
            pyev = LameStruct()
            pyev.type = e.type
            pyev.display = d
            # Unmarshal:
            try:
                if e.type == MapRequest:
                    print "MapRequest received"
                    pyev.parent = _gw(d, e.xmaprequest.parent)
                    pyev.window = _gw(d, e.xmaprequest.window)
                elif e.type == ConfigureRequest:
                    print "ConfigureRequest received"
                    pyev.parent = _gw(d, e.xconfigurerequest.parent)
                    pyev.window = _gw(d, e.xconfigurerequest.window)
                    pyev.x = e.xconfigurerequest.x
                    pyev.y = e.xconfigurerequest.y
                    pyev.width = e.xconfigurerequest.width
                    pyev.height = e.xconfigurerequest.height
                    pyev.border_width = e.xconfigurerequest.border_width
                    try:
                        # In principle there are two cases here: .above is
                        # XNone (i.e. not specified in the original request),
                        # or .above is an invalid window (i.e. it was
                        # specified by the client, but it specified something
                        # weird).  I don't see any reason to handle these
                        # differently, though.
                        pyev.above = _gw(d, e.xconfigurerequest.above)
                    except XError:
                        pyev.above = None
                    pyev.detail = e.xconfigurerequest.detail
                    pyev.value_mask = e.xconfigurerequest.value_mask
                elif e.type in (FocusIn, FocusOut):
                    print "FocusIn/FocusOut received"
                    pyev.window = _gw(d, e.xfocus.window)
                    pyev.mode = e.xfocus.mode
                    pyev.detail = e.xfocus.detail
                elif e.type == ClientMessage:
                    print "ClientMessage received"
                    pyev.window = _gw(d, e.xany.window)
                    if e.xclient.message_type > (2 ** 32):
                        print ("Xlib claims that this ClientEvent's 32-bit "
                               + "message_type is %s.  "
                               + "Note that this is >2^32.  "
                               + "This makes no sense, so I'm ignoring it."
                               ) % e.xclient.message_type
                        return GDK_FILTER_CONTINUE
                    pyev.message_type = get_pyatom(pyev.display,
                                                   e.xclient.message_type)
                    pyev.format = e.xclient.format
                    # I am lazy.  Add this later if needed for some reason.
                    if pyev.format != 32:
                        print "Ignoring ClientMessage with format != 32"
                        return GDK_FILTER_CONTINUE
                    pieces = []
                    for i in xrange(5):
                        pieces.append(int(e.xclient.data.l[i]))
                    pyev.data = tuple(pieces)
                elif e.type == damage_type:
                    print "DamageNotify received"
                    cdef XDamageNotifyEvent* damage_e
                    damage_e = <XDamageNotifyEvent*>e
                    pyev.window = _gw(d, e.xany.window)
                    pyev.x = damage_e.area.x
                    pyev.y = damage_e.area.y
                    pyev.width = damage_e.area.width
                    pyev.height = damage_e.area.height
            except XError, e:
                print ("Some window in our event disappeared before we could "
                       + "handle the event; so I'm just ignoring it instead.")

            # Dispatch:
            _route_event(pyev, *_x_event_signals[e.type])
    except:
        print "Unhandled exception in pyrex callback:"
        dump_exc()
    return GDK_FILTER_CONTINUE

_gdk_event_signals = {
    # These other events are on client windows, mostly
    gtk.gdk.PROPERTY_NOTIFY: "parti-property-notify-event",
    gtk.gdk.UNMAP: "parti-unmap-event",
    gtk.gdk.DESTROY: "parti-destroy-event",
    # I can get CONFIGURE and MAP for client windows too,
    # but actually I don't care ATM:
    #gtk.gdk.GDK_MAP: "client-map-event",
    #gtk.gdk.GDK_CONFIGURE: "client-configure-event",
    }

def _dispatch_gdk_event(event):
    # This function is called for every event GDK sees.  Most of them we
    # want to just pass on to GTK, but some we are especially interested
    # in...
    if event.type in _gdk_event_signals:
        _route_event(event, _gdk_event_signals[event.type], None)
    if (event.window is not None
        and event.type == gtk.gdk.KEY_PRESS):
        hotkey_manager = event.window.get_data("parti-hotkey-manager")
        if hotkey_manager is not None:
            hotkey_manager.emit("key-press-event", event)
    gtk.main_do_event(event)

def _install_global_event_filters():
    gdk_window_add_filter(<cGdkWindow*>0, x_event_filter, <void*>0)
    gtk.gdk.event_handler_set(_dispatch_gdk_event)

_install_global_event_filters()
