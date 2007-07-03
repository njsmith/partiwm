import struct
import gtk.gdk
from parti.wrapped import get_xatom, get_xwindow

def unsupported(*args):
    raise UnsupportedException

prop_types = {
    # Python type, X type Atom, format, serializer, deserializer, list
    # terminator
    "utf8": (unicode, "UTF8_STRING", 8,
             lambda u: u.encode("UTF-8"),
             lambda d: d.decode("UTF-8"),
             "\0"),
    "latin1": (unicode, "STRING", 8,
               lambda u: u.encode("latin1"),
               lambda d: d.decode("latin1"),
               "\0"),
    "atom": (str, "ATOM", 32,
             lambda a: struct.pack("@i", get_xatom(a)),
             unsupported,
             ""),
    "u32": (int, "CARDINAL", 32,
            lambda c: struct.pack("@i", c),
            lambda d: struct.unpack("@i", d)[0],
            ""),
    "window": (gtk.gdk.Window, "WINDOW", 32,
               lambda c: struct.pack("@i", get_xwindow(c)),
               #lambda d: struct.unpack("@i", d)[0],
               unsupported,
               ""),
    }

def prop_encode(type, value):
    if isinstance(type, list):
        return prop_encode_list(type[0], value)
    else:
        return prop_encode_scalar(type, value)

def prop_encode_scalar(type, value):
    (pytype, atom, format, serialize, deserialize, terminator) = prop_types[type]
    assert isinstance(value, pytype)
    return (atom, format, serialize(value))

def prop_encode_list(type, value):
    (pytype, atom, format, serialize, deserialize, terminator) = prop_types[type]
    value = list(value)
    serialized = [prop_encode_scalar(type, v)[2] for v in value]
    return (atom, format, terminator.join(serialized) + terminator)
