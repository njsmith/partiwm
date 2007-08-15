# Monolithic file containing simple Pyrex wrappers for otherwise unexposed
# GDK, GTK, and X11 primitives, plus utility functions for writing same.
# (Those utility functions are why this is monolithic; there's no way to write
# a cdef function in one pyrex file and then use it in another, except via
# some complex thing involving an extension type.)

import struct

import gobject
import gtk
import gtk.gdk

from parti.util import dump_exc
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
    void Py_INCREF(object o)
    void Py_DECREF(object o)
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

# cdef object wrap(cGObject * contents):
#     # Put a raw GObject* into a PyGObject wrapper.
#     return pygobject_new(contents)

###################################
# Raw Xlib and GDK
###################################

######
# Xlib primitives and constants
######

include "parti._lowlevel.const.pxi"

cdef extern from *:
    ctypedef struct Display:
        pass
    ctypedef int Bool
    ctypedef int Status
    ctypedef int Atom
    ctypedef int Window
    ctypedef int Time

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
    elif isinstance(obj, (gtk.gdk.Window,
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
    buffer_size = 64 * 1024
    cdef Atom actual_type
    cdef int actual_format
    cdef unsigned long nitems, bytes_after
    cdef unsigned char * prop
    cdef Status status
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
                                 get_xatom(pywindow, req_type), &actual_type,
                                 &actual_format, &nitems, &bytes_after, &prop)
    if status != Success:
        raise PropertyError, "no such window"
    if actual_type == XNone:
        raise NoSuchProperty, property
    if bytes_after and not nitems:
        raise BadPropertyType, actual_type
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
    
###################################
# Smarter convenience wrappers
###################################

def myGetSelectionOwner(display_source, pyatom):
    return XGetSelectionOwner(get_xdisplay_for(display_source),
                              get_xatom(display_source, pyatom))

def sendClientMessage(target, propagate, event_mask,
                      message_type, data0, data1, data2, data3, data4):
    # data0 etc. are passed through get_xatom, so they can be integers, which
    # are passed through directly, or else they can be any form of atom (in
    # particular, strings), which are converted appropriately.
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

def configureAndNotify(pywindow, x, y, width, height):
    cdef Display * display
    display = get_xdisplay_for(pywindow)
    cdef Window window
    window = get_xwindow(pywindow)

    # Reconfigure the window.  We have to use XConfigureWindow directly
    # instead of GdkWindow.resize, because GDK does not give us any way to
    # squash the border.
    cdef XWindowChanges changes
    changes.x = x
    changes.y = y
    changes.width = width
    changes.height = height
    changes.border_width = 0
    fields = CWX | CWY | CWWidth | CWHeight | CWBorderWidth
    cXConfigureWindow(display, window, fields, &changes)
    # Tell the client.
    sendConfigureNotify(pywindow)

###################################
# Raw event handling
###################################

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

# Catch the events that are generated by selecting for SubstructureRedirect,
# and send them back out to Python.
class LameStruct(object):
    # Can't set random attrs on an object() instance directly.
    pass
cdef GdkFilterReturn substructureRedirectFilter(GdkXEvent * e_gdk,
                                                GdkEvent * gdk_event,
                                                void * userdata):
    cdef XEvent * e
    e = <XEvent*>e_gdk
    cu = trap.call_unsynced
    try:
        (disp, map_callback, configure_callback, circulate_callback) = <object>userdata
        if e.type == MapRequest:
            print "MapRequest"
            if map_callback is not None:
                pyev = LameStruct()
                try:
                    pyev.parent = cu(get_pywindow,
                                     disp, e.xmaprequest.parent)
                    pyev.window = cu(get_pywindow,
                                     disp, e.xmaprequest.window)
                except XError:
                    print "Window disappeared before MapRequest handled, ignoring"
                else:
                    map_callback(pyev)
            return GDK_FILTER_REMOVE
        elif e.type == ConfigureRequest:
            print "ConfigureRequest"
            if configure_callback is not None:
                pyev = LameStruct()
                try:
                    pyev.parent = cu(get_pywindow,
                                     disp, e.xconfigurerequest.parent)
                    pyev.window = cu(get_pywindow,
                                     disp, e.xconfigurerequest.window)
                    pyev.x = e.xconfigurerequest.x
                    pyev.y = e.xconfigurerequest.y
                    pyev.width = e.xconfigurerequest.width
                    pyev.height = e.xconfigurerequest.height
                    pyev.border_width = e.xconfigurerequest.border_width
                    pyev.above = cu(get_pywindow,
                                    disp, e.xconfigurerequest.above)
                    pyev.detail = e.xconfigurerequest.detail
                    pyev.value_mask = e.xconfigurerequest.value_mask
                except XError:
                    print "Window disappeared before ConfigureRequest handled, ignoring"
                else:
                    configure_callback(pyev)
            return GDK_FILTER_REMOVE
        elif e.type == CirculateRequest:
            print "CirculateRequest"
            if circulate_callback is not None:
                pyev = LameStruct()
                try:
                    pyev.parent = cu(get_pywindow,
                                     disp, e.xcirculaterequest.parent)
                    pyev.window = cu(get_pywindow,
                                     disp, e.xcirculaterequest.window)
                    pyev.place = e.xcirculaterequest.place
                except XError:
                    print "Window disappeared before CirculateRequest handled, ignoring"
                else:
                    circulate_callback(pyev)
            return GDK_FILTER_REMOVE
        return GDK_FILTER_CONTINUE
    except:
        print "Exception in pyrex callback:"
        dump_exc()
        raise

def substructureRedirect(pywindow,
                         map_callback,
                         configure_callback,
                         circulate_callback):
    """Enable SubstructureRedirect on the given window, and call given
    callbacks when relevant events occur.  Callbacks may be None to ignore
    some event types.  Unfortunately, any exceptions thrown by callbacks will
    be swallowed."""

    addXSelectInput(pywindow, SubstructureRedirectMask)
    disp = get_display_for(pywindow)
    callback_tuple = (disp, map_callback, configure_callback, circulate_callback)
    # This tuple will be leaving Python-space.
    # FIXME: LEAK: how can we get notified when the GdkWindow eventually is
    # destructed, so we can DECREF?  (For that matter, are we sure that the
    # GdkWindow actually will be destructed?)
    Py_INCREF(callback_tuple)
    gdk_window_add_filter(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window),
                          substructureRedirectFilter,
                          <void*>callback_tuple)

cdef GdkFilterReturn focusFilter(GdkXEvent * e_gdk,
                                 GdkEvent * gdk_event,
                                 void * userdata):
    cdef XEvent * e
    e = <XEvent*>e_gdk
    try:
        (disp, focus_in_callback, focus_out_callback) = <object>userdata
        pyev = LameStruct()
        try:
            pyev.window = trap.call_unsynced(get_pywindow,
                                             disp, e.xfocus.window)
        except XError:
            print "focus event on disappeared window, ignoring"
            return GDK_FILTER_CONTINUE
        pyev.mode = e.xfocus.mode
        pyev.detail = e.xfocus.detail
        if e.type == FocusIn:
            print "FocusIn"
            if focus_in_callback is not None:
                focus_in_callback(pyev)
        elif e.type == FocusOut:
            print "FocusOut"
            if focus_out_callback is not None:
                focus_out_callback(pyev)
        # GDK also selects for Focus events for its own purposes
        return GDK_FILTER_CONTINUE
    except:
        print "Exception in pyrex callback:"
        dump_exc()
        raise

def selectFocusChange(pywindow, in_callback, out_callback):
    addXSelectInput(pywindow, FocusChangeMask)
    disp = get_display_for(pywindow)
    callback_tuple = (disp, in_callback, out_callback)
    # This tuple will be leaving Python-space.
    # FIXME: LEAK: how can we get notified when the GdkWindow eventually is
    # destructed, so we can DECREF?  (For that matter, are we sure that the
    # GdkWindow actually will be destructed?)
    Py_INCREF(callback_tuple)
    gdk_window_add_filter(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window),
                          focusFilter,
                          <void*>callback_tuple)
