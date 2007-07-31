"""All the goo needed to deal with X properties.

Everyone else should just use prop_set/prop_get with nice clean Python calling
conventions, and if you need more (un)marshalling smarts, add them here."""

import struct
import gtk.gdk
from parti.lowlevel import \
     XGetWindowProperty, XChangeProperty, PropertyError, \
     get_xatom, get_pyatom, get_xwindow, get_pywindow, const
from parti.error import trap, XError

def unsupported(*args):
    raise UnsupportedException

def _force_length(data, length):
    if len(data) != length:
        print ("Odd-lengthed prop, wanted %s bytes, got %s: %r"
               % (length, len(data), data))
    # Zero-pad data
    data += "\0" * length
    return data[:length]

class WMSizeHints(object):
    def __init__(self, data):
        data = _force_length(data, 18 * 4)
        (flags,
         pad1, pad2, pad3, pad4,
         min_width, min_height,
         max_width, max_height,
         width_inc, height_inc,
         min_aspect_num, min_aspect_den,
         max_aspect_num, max_aspect_den,
         base_width, base_height,
         win_gravity) = struct.unpack("@" + "i" * 18, data)
        #print repr(data)
        #print struct.unpack("@" + "i" * 18, data)
        # Only extract the things we care about, i.e., max, min, base,
        # increments.
        if flags & const["PMaxSize"]:
            self.max_size = (max_width, max_height)
        else:
            self.max_size = None
        if flags & const["PMinSize"]:
            self.min_size = (min_width, min_height)
        else:
            self.min_size = None
        if flags & const["PBaseSize"]:
            self.base_size = (base_width, base_height)
        else:
            self.base_size = None
        if flags & const["PResizeInc"]:
            self.resize_inc = (width_inc, height_inc)
        else:
            self.resize_inc = None

class WMHints(object):
    def __init__(self, data):
        data = _force_length(data, 9 * 4)
        (flags, input, initial_state,
         icon_pixmap, icon_window, icon_x, icon_y, icon_mask,
         window_group) = struct.unpack("@" + "i" * 9, data)
        # NB the last field is missing from at least some ICCCM 2.0's (typo).
        # FIXME: extract icon stuff too
        self.urgency = bool(flags & const["XUrgencyHint"])
        if flags & const["WindowGroupHint"]:
            self.group_leader = window_group
        else:
            self.group_leader = None
        if flags & const["StateHint"]:
            self.start_iconic = (initial_state == const["IconicState"])
        else:
            self.start_iconic = None
        if flags & const["InputHint"]:
            self.input = input
        else:
            self.input = None

_prop_types = {
    # Python type, X type Atom, format, serializer, deserializer, list
    # terminator
    "utf8": (unicode, "UTF8_STRING", 8,
             lambda u: u.encode("UTF-8"),
             lambda d: d.decode("UTF-8"),
             "\0"),
    # In theory, there should be something clever about COMPOUND_TEXT here.  I
    # am not sufficiently clever, even knowing that
    # Xutf8TextPropertyToTextList exists.
    "latin1": (unicode, "STRING", 8,
               lambda u: u.encode("latin1"),
               lambda d: d.decode("latin1"),
               "\0"),
    "atom": (str, "ATOM", 32,
             lambda a: struct.pack("@i", get_xatom(a)),
             lambda d: str(get_pyatom(struct.unpack("@i", d)[0])),
             ""),
    "u32": ((int, long), "CARDINAL", 32,
            lambda c: struct.pack("@i", c),
            lambda d: struct.unpack("@i", d)[0],
            ""),
    "window": (gtk.gdk.Window, "WINDOW", 32,
               lambda c: struct.pack("@i", get_xwindow(c)),
               lambda d: get_pywindow(struct.unpack("@i", d)[0]),
               ""),
    "wm-size-hints": (WMSizeHints, "WM_SIZE_HINTS", 32,
                      unsupported,
                      WMSizeHints,
                      None),
    "wm-hints": (WMHints, "WM_HINTS", 32,
                 unsupported,
                 WMHints,
                 None),
    }

def _prop_encode(type, value):
    if isinstance(type, list):
        return _prop_encode_list(type[0], value)
    else:
        return _prop_encode_scalar(type, value)

def _prop_encode_scalar(type, value):
    (pytype, atom, format, serialize, deserialize, terminator) = _prop_types[type]
    assert isinstance(value, pytype)
    return (atom, format, serialize(value))

def _prop_encode_list(type, value):
    (pytype, atom, format, serialize, deserialize, terminator) = _prop_types[type]
    value = list(value)
    serialized = [_prop_encode_scalar(type, v)[2] for v in value]
    # Strings in X really are null-separated, not null-terminated (ICCCM
    # 2.7.1, see also note in 4.1.2.5)
    return (atom, format, terminator.join(serialized))


def prop_set(target, key, type, value):
    trap.call_unsynced(XChangeProperty, target, key,
                       _prop_encode(type, value))


def _prop_decode(type, data):
    if isinstance(type, list):
        return _prop_decode_list(type[0], data)
    else:
        return _prop_decode_scalar(type, data)

def _prop_decode_scalar(type, data):
    (pytype, atom, format, serialize, deserialize, terminator) = _prop_types[type]
    value = deserialize(data)
    assert isinstance(value, pytype)
    return value

def _prop_decode_list(type, data):
    (pytype, atom, format, serialize, deserialize, terminator) = _prop_types[type]
    if terminator:
        datums = data.split(terminator)
    else:
        datums = []
        while data:
            datums.append(data[:(format // 8)])
            data = data[(format // 8):]
    return [_prop_decode_scalar(type, datum) for datum in datums]

# May return None.
def prop_get(target, key, type):
    if isinstance(type, list):
        scalar_type = type[0]
    else:
        scalar_type = type
    (pytype, atom, format, serialize, deserialize, terminator) = _prop_types[scalar_type]
    try:
        data = trap.call_synced(XGetWindowProperty, target, key, atom)
    except (XError, PropertyError):
        return None
    return _prop_decode(type, data)
