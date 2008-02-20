#!/usr/bin/env python

# NOTE (FIXME): This setup.py file will not work on its own; you have to run
#   $ python make-constants-pxi.py wimpiggy/lowlevel/constants.txt wimpiggy/lowlevel/constants.pxi
# before using this setup.py, and again if you change
# wimpiggy/lowlevel/constants.txt.

# FIXME: Pyrex.Distutils.build_ext leaves crud in the source directory.  (So
# does the make-constants-pxi.py hack.)

from distutils.core import setup
from distutils.extension import Extension
from Pyrex.Distutils import build_ext
import commands

# Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
def pkgconfig(*packages, **kw):
    flag_map = {'-I': 'include_dirs',
                '-L': 'library_dirs',
                '-l': 'libraries'}
    for token in commands.getoutput("pkg-config --libs --cflags %s"
                                    % ' '.join(packages)).split():
        if flag_map.has_key(token[:2]):
            kw.setdefault(flag_map.get(token[:2]), []).append(token[2:])
        else: # throw others to extra_link_args
            kw.setdefault('extra_link_args', []).append(token)
        for k, v in kw.iteritems(): # remove duplicates
            kw[k] = list(set(v))
    return kw

import wimpiggy
import parti
import xpra
assert wimpiggy.__version__ == parti.__version__ == xpra.__version__

wimpiggy_desc = "A library for writing window managers, using GTK+"
parti_desc = "A tabbing/tiling window manager using GTK+"
xpra_desc = "'screen for X' -- a tool to detach/reattach running X programs"

full_desc = """This package contains several sub-projects:
  wimpiggy:
    %s
  parti:
    %s
  xpra:
    %s""" % (wimpiggy_desc, parti_desc, xpra_desc)

setup(
    name="parti-all",
    author="Nathaniel Smith",
    author_email="parti-discuss@partiwm.org",
    version=parti.__version__,
    url="http://partiwm.org",
    description=full_desc,
    download_url="http://partiwm.org/static/downloads/",
    packages=["wimpiggy", "wimpiggy.lowlevel",
              "parti", "parti.trays", "parti.addons", "parti.scripts",
              "xpra", "xpra.scripts",
              ],
    scripts=["scripts/parti", "scripts/parti-repl",
             "scripts/xpra",
             ],
    ext_modules=[ 
      Extension("wimpiggy.lowlevel.bindings",
                ["wimpiggy/lowlevel/wimpiggy.lowlevel.bindings.pyx"],
                **pkgconfig("pygobject-2.0", "gdk-x11-2.0", "gtk+-x11-2.0",
                            "xtst")
                ),
      ],
    # Turn on Pyrex-sensitivity:
    cmdclass = {'build_ext': build_ext}
    )
