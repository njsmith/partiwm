cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    int PyObject_AsWriteBuffer(object obj,
                               void ** buffer,
                               Py_ssize_t * buffer_len) except -1

def premultiply_argb_in_place(buf):
    # b is a Python buffer object, containing non-premultiplied ARGB32 data in
    # native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef int * cbuf
    cdef Py_ssize_t cbuf_len
    assert sizeof(int) == 4
    PyObject_AsWriteBuffer(buf, &cbuf, &cbuf_len)
    cdef i
    for 0 <= i < cbuf_len / 4:
        cdef int a, r, g, b
        a = cbuf[i] & 0xff
        r = (cbuf[i] >> 8) & 0xff
        r = r * a / 255
        g = (cbuf[i] >> 16) & 0xff
        g = g * a / 255
        b = (cbuf[i] >> 24) & 0xff
        b = b * a / 255
        cbuf[i] = a | (r << 8) | (g << 16) | (b << 24)
