# A utility system for cooperation among stuff that needs nested main-loops.
# 
# So here's the problem: in the clipboard code, and eventually maybe in other
# places too, we have to define a function that
#   1) gets called
#   2) makes a request over the wire
#   3) gets the response to that request
#   4) and *then* returns to its caller
# And of course, we don't want to block the whole application between (2) and
# (3). So we have to make the request, and then enter the main-loop
# recursively. Eventually, once the response is received, we need to exit that
# main loop.
#
# That's easy enough. The trouble comes when we need to handle multiple such
# requests at the same time. (E.g., suppose the user attempts to paste twice
# in quick succession.) Some responses might come out of order; some might
# never come. But, because of how Python works, it doesn't matter -- we have
# to return from these functions in strict LIFO order.
#
# So, for instance, if we send out request 1, then request 2, and then get
# response 1... we can't just call gtk.main_quit(), because that will actually
# drop us back into request *2*'s handler function. The correct thing to do is
# to stash the response somewhere and wait. Then, when we get response 2, we
# should call gtk.main_quit() *twice*, since both responses are now available.
# (However, as an additional complication, you can't just call gtk.main_quit()
# twice, because that just makes you quit the current main loop. Two times,
# which is the same as doing it once. So we have to return to the main loop
# between each call to gtk.main_quit().)
#
# Also, suppose it happens that response 2 never arrives. Then not only will
# we never exit the inner main-loop... we will never exit the outer main-loop
# either! Response 1 will just sit there and never get processed, even though
# it has arrived.
#
# Solution: indirection!
#
# Specifically, we keep track of the 'state' of each such nested call. Each
# call can be in one of 3 states:
#   -- done
#   -- soft timed out
#   -- hard timed out
# The soft-timeout is the maximum amount of time that this nested call can
# block other nested calls from completion. The hard-timeout is the maximum
# amount of time that we'll wait for this nested call, period. (However, this
# might be extended if this nested call ends up blocked on other calls. If the
# nested call finishes after the hard time out expires, but before we actually
# get around to processing it, then it'll still be processed as normal -- not
# as timed out.)
#
# There actually is no guarantee on how long a nested call ends up blocked,
# even in the face of soft timeouts, because new nested calls might keep
# coming in, each extending the total blocking period by their soft
# timeout. If the user ever stops pasting madly for a few seconds, though,
# then everything should have a chance to return to equilibrium...

import gobject
import gtk

from wimpiggy.log import Logger
log = Logger()

# For debugging:
def _dump_recursion_info():
    # This is how deeply nested in recursive main-loops we are:
    print "gtk depth: %s" % (gtk.main_level())
    import ctypes
    class ThreadState(ctypes.Structure):
        _fields_ = [("next", ctypes.c_voidp),
                    ("interp", ctypes.c_voidp),
                    ("frame", ctypes.c_voidp),
                    ("recursion_depth", ctypes.c_int)]
    ts = ctypes.cast(ctypes.pythonapi.PyThreadState_Get(),
                     ctypes.POINTER(ThreadState))
    # This is Python's count of the recursion depth -- i.e., the thing that
    # will eventually trigger the 'Maximum recursion depth exceeded' message.
    print "python internal depth: %s" % ts[0].recursion_depth
    import inspect
    count = 0
    frame = inspect.currentframe()
    while frame:
        frame = frame.f_back
        count += 1
    # This is the number of frames in the current stack. It probably only
    # counts up to the last call to gtk.main().
    print "stack frames: %s" % count
    # The number of NestedMainLoops in progress:
    print "NestedMainLoops: %s" % len(NestedMainLoop._stack)

class NestedMainLoop(object):
    _stack = []

    @classmethod
    def _quit_while_top_done(cls):
        if (cls._stack
            and (cls._stack[-1]._done
                 or cls._stack[-1]._hard_timed_out
                 or (cls._stack[-1]._soft_timed_out
                     and bool([o for o in cls._stack if o._done])))):
            gtk.main_quit()
            return True
        else:
            return False

    def _wakeup(self):
        gobject.timeout_add(0, self._quit_while_top_done)

    def _soft_timeout_cb(self):
        log("%s: soft timeout", hex(id(self)))
        self._soft_timed_out = True
        self._wakeup()

    def _hard_timeout_cb(self):
        log("%s: hard timeout", hex(id(self)))
        self._hard_timed_out = True
        self._wakeup()

    def done(self, result):
        log("%s: done: %s", hex(id(self)), result)
        self._result = result
        self._done = True
        self._wakeup()

    # Returns whatever was passed to done(), or None in the case of a
    # timeout.
    def main(self, soft_timeout, hard_timeout):
        self._result = None
        self._done = False
        self._soft_timed_out = False
        self._hard_timed_out = False
        self._stack.append(self)
        soft = gobject.timeout_add(soft_timeout, self._soft_timeout_cb)
        hard = gobject.timeout_add(hard_timeout, self._hard_timeout_cb)
        log("Entering nested loop %s (level %s)",
            hex(id(self)), gtk.main_level())
        try:
            gtk.main()
        finally:
            assert self._stack.pop() is self
            gobject.source_remove(soft)
            gobject.source_remove(hard)
        log("%s: returned from nested main loop (done=%s, soft=%s, hard=%s, result=%s)",
            hex(id(self)), self._done,
            self._soft_timed_out, self._hard_timed_out,
            self._result)
        return self._result
