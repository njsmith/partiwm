import os as _os
if _os.name == "nt":
    from xpra.platform.win32 import *
elif _os.name == "posix":
    from xpra.platform.posix import *
else:
    raise OSError, "Unknown OS %s" % (_os.name)

