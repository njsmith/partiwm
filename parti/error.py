# Goal: make it as easy and efficient as possible to manage the X errors that
# a WM is inevitably susceptible to.  (E.g., if a window goes away while we
# are working on it.)  On the one hand, we want to parcel operations into as
# broad chunks as possible that at treated as succeeding or failing as a whole
# (e.g., "setting up a new window", we don't really care how much was
# accomplished before the failure occurred).  On the other, we do want to
# check for X errors often, for use in debugging (esp., this makes it more
# useful to run with -sync).
#
# The solution is to keep a stack of how deep we are in "transaction-like"
# operations -- a transaction is a series of operations where we don't care if
# we don't find about the failures until the end.  We only sync when exiting a
# top-level transaction.
#
# The _synced and _unsynced variants differ in whether they assume the X
# connection was left in a synchronized state by the code they called (e.g.,
# if the last operation was an XGetProperty, then there is no need for us to
# do another XSync).
#
# (In this modern world, with WM's either on the same machine or over
# super-fast connections to the X server, everything running on fast
# computers... does being this careful to avoid sync's actually matter?)

import gtk.gdk as _gdk
import parti.wrapped as _wrapped

class XError(Exception):
    pass

### Exceptions cannot be new-style classes.  Who came up with _that_ one?
# # Define its more precise subclasses, XBadRequest, XBadValue, etc.
# _all_errors = ["BadRequest", "BadValue", "BadWindow", "BadPixmap", "BadAtom",
#                "BadCursor", "BadFont", "BadMatch", "BadDrawable", "BadAccess",
#                "BadAlloc", "BadColor", "BadGC", "BadIDChoice", "BadName",
#                "BadLength", "BadImplementation"]
_exc_for_error = {}
# for error in _all_errors:
#     exc_name = "X%s" % error
#     exc_class = type(exc_name, (XError,), {})
#     locals()[exc_name] = exc_class
#     _exc_for_error[_wrapped.const[error]] = exc_class

# gdk has its own depth tracking stuff, but we have to duplicate it here to
# minimize calls to XSync.
class _ErrorManager(object):
    def __init__(self):
        self.depth = 0

    def enter(self):
        assert self.depth >= 0
        _gdk.error_trap_push()
        self.depth += 1

    def _exit(self, need_sync):
        assert self.depth >= 0
        self.depth -= 1
        if self.depth == 0 and need_sync:
            _gdk.flush()
        # This is a Xlib error constant (Success == 0)
        error = _gdk.error_trap_pop()
        if error != _wrapped.const["Success"]:
            if error in _exc_for_error:
                raise _exc_for_error[error](error)
            else:
                raise XError, error

    def exit_unsynced(self):
        self._exit(True)

    def exit_synced(self):
        self._exit(False)

    exit = exit_unsynced

    def _call(self, need_sync, fun, args, kwargs):
        # Goal: call the function.  In all conditions, call _exit exactly once
        # on the way out.  However, if we are exiting because of an exception,
        # then probably that exception is more informative than any XError
        # that might also be raised, so suppress the XError in that case.
        value = None
        try:
            self.enter()
            value = fun(*args, **kwargs)
        except:
            try:
                self._exit(need_sync)
            except XError:
                print "XError detected while already in unwind; discarding"
            raise
        self._exit(need_sync)
        return value

    def call_unsynced(self, fun, *args, **kwargs):
        return self._call(True, fun, args, kwargs)

    def call_synced(self, fun, *args, **kwargs):
        return self._call(False, fun, args, kwargs)

    call = call_unsynced

    def swallow_unsynced(self, fun, *args, **kwargs):
        try:
            return self.call_unsynced(fun, *args, **kwargs)
        except XError:
            pass

    def swallow_synced(self, fun, *args, **kwargs):
        try:
            return self.call_synced(fun, *args, **kwargs)
        except XError:
            pass

    swallow = swallow_unsynced

    def assert_out(self):
        assert self.depth == 0

trap = _ErrorManager()
