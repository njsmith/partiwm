# Monolithic file containing simple Pyrex wrappers for otherwise unexposed
# GDK, GTK, and X11 primitives, plus utility functions for writing same.
# (Those utility functions are why this is monolithic; there's no way to write
# a cdef function in one pyrex file and then use it in another, except via
# some complex thing involving an extension type.)

import gobject
import gtk
import gtk.gdk

###################################
# GObject
###################################

cdef extern from "pygobject.h":
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

def print_unwrapped(box):
    "For debugging the above."
    cdef cGObject * unwrapped
    unwrapped = unwrap(box, gobject.GObject)
    if unwrapped == NULL:
        print "contents is NULL!"
    else:
        print "contents is %s" % (<long long>unwrapped)

cdef object wrap(cGObject * contents):
    # Put a raw GObject* into a PyGObject wrapper.
    return pygobject_new(contents)

###################################
# Raw Xlib and GDK
###################################

######
# Xlib primitives and constants
######

cdef extern from "X11/Xlib.h":
    pass

include "parti.wrapped.const.pxi"

cdef extern from *:
    ctypedef struct Display:
        pass
    ctypedef int Bool
    ctypedef int Status
    ctypedef int Atom
    ctypedef int Window

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
    ctypedef union XEvent:
        int type
        XAnyEvent xany
        XClientMessageEvent xclient
        
    Status XSendEvent(Display *, Window target, Bool propagate,
                      long event_mask, XEvent * event)

    int cXChangeProperty "XChangeProperty" \
        (Display *, Window w, Atom property,
         Atom type, int format, int mode, char * data, int nelements)

    int cXAddToSaveSet "XAddToSaveSet" (Display * display, Window w)

    # Needed to find the secret window Gtk creates to own the selection, so we
    # can broadcast it:
    Window XGetSelectionOwner(Display * display, Atom selection)

######
# GDK primitives, and wrappers for Xlib
######

cdef extern from "gdk/gdk.h":
    pass
cdef extern from "gdk/gdkx.h":
    pass
cdef extern from "pygtk/pygtk.h":
    pass

# Basic utilities:
cdef extern from *:
    ctypedef struct cGdkWindow "GdkWindow":
        pass
    Window GDK_WINDOW_XID(cGdkWindow *)
    cGdkWindow * gdk_window_foreign_new(Window w)

    Display * gdk_x11_get_default_xdisplay()

def get_xwindow(pywindow):
    return GDK_WINDOW_XID(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window))

# Atom stuff:
cdef extern from *:
    ctypedef struct PyGdkAtom_Object:
        pass
    ctypedef void * GdkAtom
    # FIXME: this should have stricter type checking
    GdkAtom PyGdkAtom_Get(object)
    Atom gdk_x11_atom_to_xatom(GdkAtom)

def get_xatom(gdkatom_or_str):
    """Returns the X atom corresponding to the given PyGdkAtom or Python
    string."""
    if isinstance(gdkatom_or_str, str):
        gdkatom_or_str = gtk.gdk.atom_intern(gdkatom_or_str)
    # Assume it is a PyGdkAtom (since there's no easy way to check, sigh)
    return gdk_x11_atom_to_xatom(PyGdkAtom_Get(gdkatom_or_str))

# Property handling:
def XChangeProperty(pywindow, property, value):
    "Set a property on a window.  Returns a true value on failure."
    (type, format, data) = value
    assert format in (8, 16, 32)
    assert (len(data) % (format / 8)) == 0
    result = cXChangeProperty(gdk_x11_get_default_xdisplay(),
                              get_xwindow(pywindow),
                              get_xatom(property),
                              get_xatom(type),
                              format,
                              PropModeReplace,
                              data,
                              len(data) / (format / 8))

# Save set handling
def XAddToSaveSet(pywindow):
    cXAddToSaveSet(gdk_x11_get_default_xdisplay(),
                   get_xwindow(pywindow))

###################################
# Smarter convenience wrappers
###################################

def myGetSelectionOwner(pyatom):
    return XGetSelectionOwner(gdk_x11_get_default_xdisplay(),
                              get_xatom(pyatom))

def sendClientMessage(target, propagate, event_mask,
                      message_type, data0, data1, data2, data3, data4):
    cdef Display * display
    display = gdk_x11_get_default_xdisplay()
    cdef Window w
    w = get_xwindow(target)
    cdef XEvent e
    e.type = ClientMessage
    e.xany.display = display
    e.xany.window = w
    e.xclient.message_type = get_xatom(message_type)
    e.xclient.format = 32
    e.xclient.data.l[0] = data0
    e.xclient.data.l[1] = data1
    e.xclient.data.l[2] = data2
    e.xclient.data.l[3] = data3
    e.xclient.data.l[4] = data4
    cdef Status s
    s = XSendEvent(display, w, propagate, event_mask, &e)
    if s == 0:
        raise ValueError, "failed to serialize ClientMessage"


###################################
# Raw event handling
###################################

cdef extern from *:
    enum GdkFilterReturn:
        GDK_FILTER_CONTINUE   # If we ignore the event
        GDK_FILTER_TRANSLATE  # If we converted the event to a GdkEvent
        GDK_FILTER_REMOVE     # If we handled the event and GDK should ignore it

    ctypedef GdkFilterReturn (*GdkFilterFunc)(XEvent *, void *, void *)
    void gdk_window_add_filter(cGdkWindow * w,
                               GdkFilterFunc filter,
                               void * userdata)

cdef GdkFilterReturn rootRawEventFilter(XEvent * e,
                                        void * gdk_event,
                                        void * userdata):
    return GDK_FILTER_CONTINUE

def registerRawFilter(pywindow):
    gdk_window_add_filter(get_xwindow(pywindow),
                          rootRawEventFilter,
                          NULL)
