# This is the main script that starts up Parti itself.

import os
from parti.scripts import PartiOptionParser
import parti.parti

def main(cmdline):
    parser = PartiOptionParser()
    parser.add_option("--replace", action="store_true",
                      dest="replace", default=False,
                      help="Replace any running window manager with Parti")
    (options, args) = parser.parse_args(cmdline[1:])

    # This means, if an exception propagates to the gtk mainloop, then pass it
    # on outwards.  Or at least it did at one time; dunno if it actually does
    # anything these days.
    os.environ["PYGTK_FATAL_EXCEPTIONS"] = "1"

    try:
        p = parti.parti.Parti(options["replace"])
        p.main()
    except:
        if "_PARTI_PDB" in os.environ:
            import sys, pdb
            pdb.post_morten(sys.exc_traceback)
        raise
