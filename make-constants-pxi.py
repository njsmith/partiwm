#!/usr/bin/env python

import sys

def main(progname, args):
    if len(args) != 2:
        sys.stderr.write("Usage: %s CONSTANT-LIST PXI-OUTPUT\n")
        sys.exit(2)
    (constants_path, pxi_path) = args
    constants = []
    for line in open(constants_path):
        data = line.split("#", 1)[0].strip()
        # data can be empty ''...
        if not data:
            continue
        # or a pair like 'cFoo "Foo"'...
        elif len(data.split()) == 2:
            (pyname, cname) = data.split()
            constants.append((pyname, cname))
        # or just a simple token 'Foo'
        else:
            constants.append(data)
    out = open(pxi_path, "w")
    out.write("cdef extern from *:\n")
    out.write("    enum MagicNumbers:\n")
    for const in constants:
        if isinstance(const, tuple):
            out.write('        %s %s\n' % const)
        else:
            out.write('        %s\n' % (const,))
    out.write("const = {\n")
    for const in constants:
        if isinstance(const, tuple):
            pyname = const[0]
        else:
            pyname = const
        out.write('    "%s": %s,\n' % (pyname, pyname))
    out.write("}\n")

if __name__ == "__main__":
    main(sys.argv[0], sys.argv[1:])
