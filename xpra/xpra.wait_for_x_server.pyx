# Special guard to work around Fedora/RH's pygtk2 silliness
# see http://partiwm.org/ticket/34 for details

import time

cdef extern from "Python.h":
    char * PyString_AsString(object string) except NULL

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    Display * XOpenDisplay(char * name)
    int XCloseDisplay(Display * xdisplay)

# timeout is in seconds
def wait_for_x_server(display_name, timeout):
    cdef Display * d
    start = time.time()
    first_time = True
    while first_time or (time.time() - start) < timeout:
        if not first_time:
            time.sleep(0.2)
        first_time = False
        d = XOpenDisplay(PyString_AsString(display_name))
        if d is not NULL:
            XCloseDisplay(d)
            return
    raise RuntimeError, ("could not connect to server after %s seconds"
                         % timeout)
