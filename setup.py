#!/usr/bin/env python

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
  author_email="njs@pobox.com",
  scripts=["partiwm"],
  packages=["parti", "parti.trays"],
  ext_modules=[ 
    Extension("parti.wrapped",
              ["parti/parti.wrapped.pyx"],
              **pkgconfig("pygobject-2.0", "gdk-x11-2.0", "gtk+-x11-2.0")
              ),
    ],
  cmdclass = {'build_ext': build_ext}
)
