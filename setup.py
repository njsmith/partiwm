#!/usr/bin/env python

# NOTE (FIXME): This setup.py file will not work on its own; you have to run
#   $ python make-constants-pxi.py parti/parti._lowlevel.const.txt parti/parti._lowlevel.const.pxi
# before using this setup.py, and again if you change
# parti/parti._lowlevel.const.txt.

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


setup(
  name = 'parti',
  author="Nathaniel Smith",
  author_email="parti-discuss@partiwm.org",
  version="0.0.2",
  url="http://partiwm.org",
  description="A tabbing/tiling window manager using GTK+",
  download_url="http://partiwm.org/static/downloads/",
  
  scripts=["scripts/parti", "scripts/parti-repl"],
  packages=["parti", "parti.trays", "parti.addons", "parti.scripts"],
  ext_modules=[ 
    Extension("parti.lowlevel.bindings",
              ["parti/lowlevel/parti.lowlevel.bindings.pyx"],
              **pkgconfig("pygobject-2.0", "gdk-x11-2.0", "gtk+-x11-2.0",
                          "xtst")
              ),
    ],
  # Turn on Pyrex-sensitivity:
  cmdclass = {'build_ext': build_ext}
)
