import sys
import logging

# A wrapper around 'logging' with some convenience stuff.  In particular:
#   -- You initialize it with a prefix (like "wimpiggy.window"), but can pass
#      a type= kwarg to any of the loggin methods to further specialize the
#      logging target (like "damage" to get "wimpiggy.window.damage").
#   -- You can pass exc_info=True to any method, and sys.exc_info() will be
#      substituted.
#   -- __call__ is an alias for debug

class Logger(object):
    def __init__(self, base):
        self._base = base

    def getLogger(self, type=None):
        name = self._base
        if type:
            name += ". " + type
        return logging.getLogger(name)

    def log(self, level, msg, *args, **kwargs):
        if kwargs.get("exc_info") is True:
            kwargs["exc_info"] = sys.exc_info()
        self.getLogger(kwargs.get("type")).log(level, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        self.log(logging.WARNING, msg, *args, **kwargs)

    def __call__(self, msg, *args, **kwargs):
        self.debug(msg, *args, **kwargs)
