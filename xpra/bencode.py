# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further. The incremental bdecode code is entirely new.

# Original version written by Petru Paler

import re

class IncrBDecode(object):
    num_re = re.compile("-?([0-9]+)")

    def __init__(self, initial_buf=""):
        self._buf = initial_buf
        self._offset = 0
        self._result = None
        self._nesteds = []
        self._states = {
            "l": self._list_start,
            "d": self._dict_start,
            "i": self._int,
            "e": self._nested_end,
            }
        for c in "0123456789":
            self._states[c] = self._string_start
        self._state = self._sniff

        self._string_length = None

    def add(self, bytes):
        assert self._result is None
        self._buf += bytes

    def process(self):
        self._state()
        if self._result is not None:
            return self._result, self._buf[self._offset:]

    def _transition(self, state):
        self._state = state
        self._state()

    def _finish(self, value):
        if not self._nesteds:
            self._result = value
            self._transition(self._done)
        else:
            self._nesteds[-1].append(value)
            self._transition(self._sniff)

    def _str2int(self, str):
        m = self.num_re.match(str)
        if m is None or m.end() != len(str):
            raise ValueError, str
        if len(m.group(1)) > 1 and m.group(1)[0] == "0":
            raise ValueError, str
        try:
            value = int(str)
        except OverflowError:
            value = long(str)
        return value

    def _done(self):
        pass

    def _sniff(self):
        if len(self._buf) <= self._offset:
            return
        new_state = self._states.get(self._buf[self._offset])
        if new_state is None:
            raise ValueError
        self._transition(new_state)

    def _int(self):
        assert self._buf[self._offset] == "i"
        e_offset = self._buf.find("e", self._offset)
        if e_offset != -1:
            self._offset += 1
            value = self._str2int(self._buf[self._offset:e_offset])
            self._offset = e_offset + 1
            self._finish(value)

    def _string_start(self):
        colon_offset = self._buf.find(":", self._offset)
        if colon_offset != -1:
            length = self._str2int(self._buf[self._offset:colon_offset])
            if length < 0:
                raise ValueError, length
            self._string_length = length
            self._offset = colon_offset + 1
            self._transition(self._string_end)

    def _string_end(self):
        if len(self._buf) - self._offset >= self._string_length:
            value = self._buf[self._offset:self._offset + self._string_length]
            assert len(value) == self._string_length
            self._offset += self._string_length
            self._string_length = None
            self._finish(value)

    def _nested_end(self):
        assert self._buf[self._offset] == "e"
        self._offset += 1
        nested = self._nesteds.pop()
        nested[0](nested[1:])

    def _list_start(self):
        assert self._buf[self._offset] == "l"
        self._offset += 1
        self._nesteds.append([self._list_end])
        self._transition(self._sniff)

    def _list_end(self, values):
        self._finish(values)

    def _dict_start(self):
        assert self._buf[self._offset] == "d"
        self._offset += 1
        self._nesteds.append([self._dict_end])
        self._transition(self._sniff)

    def _dict_end(self, values):
        last_key = None
        if not len(values) % 2 == 0:
            raise ValueError
        d = {}
        for i, entry in enumerate(values):
            if i % 2 == 0:
                if not isinstance(entry, str):
                    raise ValueError
                if last_key is not None and last_key >= entry:
                    raise ValueError
                last_key = entry
            else:
                d[last_key] = entry
        self._finish(d)

def test_IncrBDecode():
    def t(str, value, remainder):
        print str
        # Test "one-shot":
        assert IncrBDecode().process(str) == (value, remainder)
        # With gibberish added:
        assert IncrBDecode().process(str + "asdf") == (value,
                                                       remainder + "asdf")
        # Byte at a time:
        decoder = IncrBDecode()
        for i, c in enumerate(str):
            retval = decoder.process(c)
            if retval is not None:
                print retval
                assert retval == (value, "")
                assert str[i + 1:] == remainder
                break
        
    t("i12345e", 12345, "")
    t("i-12345e", -12345, "")
    t("i12345eQQQ", 12345, "QQQ")
    t("3:foo", "foo", "")
    t("3:fooQQQ", "foo", "QQQ")
    t("li12e4:asdfi34ee", [12, "asdf", 34], "")
    t("d4:asdf3:foo4:bsdfi1234ee", {"asdf": "foo", "bsdf": 1234}, "")

    t("d4:asdfli1ei2ei3ei4ee5:otheri-55e2:qqd2:qql2:hieee",
      {"asdf": [1, 2, 3, 4], "qq": {"qq": ["hi"]}, "other": -55},
      "")

    t("l0:e", [""], "")

    print "------"
    def te(str, exc):
        print str
        try:
            IncrBDecode().process(str)
        except exc:
            pass
        else:
            assert False, "didn't raise exception"
        try:
            decoder = IncrBDecode()
            for c in str:
                decoder.process(c)
        except exc:
            pass
        else:
            assert False, "didn't raise exception"

    te("iie", ValueError)
    te("i0x0e", ValueError)
    t("i0e", 0, "")
    te("i00e", ValueError)

    te("0x2:aa", ValueError)
    te("-1:aa", ValueError)
    te("02:aa", ValueError)

    # Keys must be strings:
    te("di0ei0ee", ValueError)
    te("dli0eei0ee", ValueError)
    te("dd1:a1:aei0ee", ValueError)
    # Keys must be in ascending order:
    te("d1:bi0e1:ai0e1:ci0ee", ValueError)
    te("d1:ai0e1:ci0e1:bi0ee", ValueError)

def decode_int(x, f):
    f += 1
    newf = x.index('e', f)
    try:
        n = int(x[f:newf])
    except (OverflowError, ValueError):
        n = long(x[f:newf])
    if x[f] == '-':
        if x[f + 1] == '0':
            raise ValueError
    elif x[f] == '0' and newf != f+1:
        raise ValueError
    return (n, newf+1)

def decode_string(x, f):
    colon = x.index(':', f)
    try:
        n = int(x[f:colon])
    except (OverflowError, ValueError):
        n = long(x[f:colon])
    if x[f] == '0' and colon != f+1:
        raise ValueError
    colon += 1
    return (x[colon:colon+n], colon+n)

def decode_list(x, f):
    r, f = [], f+1
    while x[f] != 'e':
        v, f = decode_func[x[f]](x, f)
        r.append(v)
    return (r, f + 1)

def decode_dict(x, f):
    r, f = {}, f+1
    lastkey = None
    while x[f] != 'e':
        k, f = decode_string(x, f)
        if lastkey >= k:
            raise ValueError
        lastkey = k
        r[k], f = decode_func[x[f]](x, f)
    return (r, f + 1)

decode_func = {}
decode_func['l'] = decode_list
decode_func['d'] = decode_dict
decode_func['i'] = decode_int
for c in '0123456789':
    decode_func[c] = decode_string

def bdecode(x):
    try:
        r, l = decode_func[x[0]](x, 0)
    except (IndexError, KeyError):
        raise ValueError
    return r, l

from types import (StringType, IntType, LongType, DictType, ListType,
                   TupleType, BooleanType)

def encode_int(x, r):
    # Explicit cast, because bool.__str__ is annoying.
    r.extend(('i', str(long(x)), 'e'))

def encode_string(x, r):
    r.extend((str(len(x)), ':', x))

def encode_list(x, r):
    r.append('l')
    for i in x:
        encode_func[type(i)](i, r)
    r.append('e')

def encode_dict(x,r):
    r.append('d')
    ilist = x.items()
    ilist.sort()
    for k, v in ilist:
        r.extend((str(len(k)), ':', k))
        encode_func[type(v)](v, r)
    r.append('e')

encode_func = {}
encode_func[IntType] = encode_int
encode_func[LongType] = encode_int
encode_func[StringType] = encode_string
encode_func[ListType] = encode_list
encode_func[TupleType] = encode_list
encode_func[DictType] = encode_dict
encode_func[BooleanType] = encode_int

def bencode(x):
    r = []
    encode_func[type(x)](x, r)
    return ''.join(r)
