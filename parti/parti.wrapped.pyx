# Monolithic file containing simple Pyrex wrappers for otherwise unexposed
# GDK, GTK, and X11 primitives, plus utility functions for writing same.
# (Those utility functions are why this is monolithic; there's no way to write
# a cdef function in one pyrex file and then use it in another, except via
# some complex thing involving an extension type.)

import gobject
import gtk
import gtk.gdk

cdef extern from "Python.h":
    void Py_INCREF(object o)
    void Py_DECREF(object o)

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
        XClientMessageEvent xclient
        
    Status XSendEvent(Display *, Window target, Bool propagate,
                      long event_mask, XEvent * event)

    int XSelectInput(Display * display, Window w, long event_mask)

    int cXChangeProperty "XChangeProperty" \
        (Display *, Window w, Atom property,
         Atom type, int format, int mode, char * data, int nelements)

    int cXAddToSaveSet "XAddToSaveSet" (Display * display, Window w)

    ctypedef struct XWindowAttributes:
        int x, y, width, height, border_width
        Bool override_redirect
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

get_pywindow = gtk.gdk.window_foreign_new

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

def sendConfigureNotify(pywindow):
    Display * display
    display = gdk_x11_get_default_xdisplay()
    Window window
    window = get_xwindow(pywindow)

    # Get basic attributes
    XWindowAttributes attrs
    XGetWindowAttributes(gdk_x11_get_default_xdisplay(),
                         get_xwindow(pywindow),
                         &attrs)

    # Figure out where the window actually is in root coordinate space
    cdef int dest_x, dest_y
    cdef Window child
    if not XTranslateCoordinates(display, window,
                                 get_xwindow(gtk.gdk.get_default_root_window()),
                                 0, 0,
                                 &dest_x, &dest_y, &child):
        raise "can't happen"

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

def configureAndNotify(pywindow, x, y, width, height):
    cdef Display * display
    display = gdk_x11_get_default_xdisplay()
    cdef Window window
    window = get_xwindow(pywindow)

    # Reconfigure the window.  We have to use XConfigureWindow directly
    # instead of GdkWindow.resize, because GDK does not give us any way to
    # squash the border.
    XWindowChanges changes
    changes.x = x
    changes.y = y
    changes.width = width
    changes.height = height
    changes.border_width = border_width
    fields = CWX | CWY | CWWdith | CWHeight | CWBorderWidth
    cXConfigureWindow(display, window, &changes)
    # Tell the client.
    sendConfigureNotify(pywindow)

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

# Catch the events that are generated by selecting for SubstructureRedirect,
# and send them back out to Python.
cdef GdkFilterReturn substructureRedirectFilter(XEvent * e,
                                                void * gdk_event,
                                                void * userdata):
    (map_callback, configure_callback, circulate_callback) = <object>userdata
    if e.type == MapRequest:
        if map_callback is not None:
            pyev = object()
            pyev.parent = get_pywindow(e.xmaprequest.parent)
            pyev.window = get_pywindow(e.xmaprequest.window)
            map_callback(pyev)
        return GDK_FILTER_REMOVE
    elif e.type == ConfigureRequest:
        if configure_callback is not None:
            pyev = object()
            pyev.parent = get_pywindow(e.xconfigurerequest.parent)
            pyev.window = get_pywindow(wrap(e.xconfigurerequest.window))
            pyev.x = e.xconfigurerequest.x
            pyev.y = e.xconfigurerequest.y
            pyev.width = e.xconfigurerequest.width
            pyev.height = e.xconfigurerequest.height
            pyev.border_width = e.xconfigurerequest.border_width
            pyev.above = get_pywindow(e.xconfigurerequest.above)
            pyev.detail = e.xconfigurerequest.detail
            pyev.value_mask = e.xconfigurerequest.value_mask
            configure_callback(pyev)
        return GDK_FILTER_REMOVE
    elif e.type == CirculateRequest:
        if circulate_callback is not None:
            pyev = object()
            pyev.parent = get_pywindow(e.xcirculaterequest.parent)
            pyev.window = get_pywindow(e.xcirculaterequest.window)
            pyev.place = e.xcirculaterequest.place
            circulate_callback(pyev)
        return GDK_FILTER_REMOVE
    else:
        return GDK_FILTER_CONTINUE

def addXSelectInput(pywindow, add_mask):
    XWindowAttributes curr
    XGetWindowAttributes(gdk_x11_get_default_xdisplay(),
                         get_xwindow(pywindow),
                         &curr)
    mask = curr.mask
    mask = mask | add_mask
    XSelectInput(gdk_x11_get_default_xdisplay(),
                 get_xwindow(pywindow),
                 mask)

def substructureRedirect(pywindow,
                         map_callback,
                         configure_callback,
                         circulate_callback):
    """Enable SubstructureRedirect on the given window, and call given
    callbacks when relevant events occur.  Callbacks may be None to ignore
    some event types.  Unfortunately, any exceptions thrown by callbacks will
    be swallowed."""

    addXSelectInput(pywindow, SubstructureRedirectMask)
    callback_tuple = (map_callback, configure_callback, circulate_callback)
    # This tuple will be leaving Python-space.
    # FIXME: LEAK: how can we get notified when the GdkWindow eventually is
    # destructed, so we can DECREF?  (For that matter, are we sure that the
    # GdkWindow actually will be destructed?)
    Py_INCREF(callback_tuple)
    gdk_window_add_filter(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window),
                          substructureRedirectFilter,
                          <void*>callback_tuple)
