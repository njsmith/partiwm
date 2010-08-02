# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os as _os
if _os.name == "nt":
    from xpra.platform.win32 import *
elif _os.name == "posix":
    from xpra.platform.xposix import *
else:
    raise OSError, "Unknown OS %s" % (_os.name)

