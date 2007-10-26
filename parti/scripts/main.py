# This is the main script that starts up Parti itself.

import os
from parti.scripts import PartiOptionParser
import parti.wm

def main(cmdline):
    parser = PartiOptionParser()
    (options, args) = parser.parse_args(cmdline[1:])

    # This means, if an exception propagates to the gtk mainloop, then pass it
    # on outwards.  Or at least it did at one time; dunno if it actually does
    # anything these days.
    os.environ["PYGTK_FATAL_EXCEPTIONS"] = "1"

    try:
        wm = parti.wm.Wm()
        wm.mainloop()
    except:
        if "_PARTI_PDB" in os.environ:
            import sys, pdb
            pdb.post_morten(sys.exc_traceback)
        raise
