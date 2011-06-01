# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
from wimpiggy.util import one_arg_signal, AutoPropGObjectMixin
from wimpiggy.error import *
from wimpiggy.lowlevel import (xcomposite_redirect_window,
                               xcomposite_unredirect_window,
                               xcomposite_name_window_pixmap,
                               xdamage_start, xdamage_stop,
                               xdamage_acknowledge,
                               add_event_receiver, remove_event_receiver,
                               get_parent, addXSelectInput, const,
                               geometry_with_border)

from wimpiggy.log import Logger
log = Logger()

class CompositeHelper(AutoPropGObjectMixin, gobject.GObject):
    __gsignals__ = {
        "contents-changed": one_arg_signal,

        "wimpiggy-damage-event": one_arg_signal,
        "wimpiggy-unmap-event": one_arg_signal,
        "wimpiggy-configure-event": one_arg_signal,
        "wimpiggy-reparent-event": one_arg_signal,
        }

    __gproperties__ = {
        "contents": (gobject.TYPE_PYOBJECT,
                     "", "", gobject.PARAM_READABLE),
        "contents-handle": (gobject.TYPE_PYOBJECT,
                            "", "", gobject.PARAM_READABLE),
        }        

    # This may raise XError.
    def __init__(self, window, already_composited):
        super(CompositeHelper, self).__init__()
        self._window = window
        self._already_composited = already_composited
        def setup():
            if not self._already_composited:
                xcomposite_redirect_window(window)
            (_, _, _, _, self._border_width) = geometry_with_border(window)
        trap.call(setup)
        self._listening_to = None
        self.invalidate_pixmap()
        self._damage_handle = xdamage_start(window)

        add_event_receiver(self._window, self)

    def destroy(self):
        if not self._already_composited:
            trap.swallow(xcomposite_unredirect_window, self._window)
        trap.swallow(xdamage_stop, self._window, self._damage_handle)
        self._damage_handle = None
        self._contents_handle = None
        self.invalidate_pixmap()
        remove_event_receiver(self._window, self)
        self._window = None

    def acknowledge_changes(self, x, y, w, h):
        if self._damage_handle is not None:
            trap.swallow(xdamage_acknowledge,
                         self._window, self._damage_handle,
                         x - self._border_width,
                         y - self._border_width,
                         w, h)

    def invalidate_pixmap(self):
        log("invalidating named pixmap", type="pixmap")
        if self._listening_to is not None:
            self._cleanup_listening(self._listening_to)
            self._listening_to = None
        self._contents_handle = None

    def _cleanup_listening(self, listening):
        # Don't want to stop listening to self._window!:
        assert self._window not in self._listening_to
        for w in self._listening_to:
            remove_event_receiver(w, self)

    def do_get_property_contents_handle(self, name):
        if self._contents_handle is None:
            log("refreshing named pixmap", type="pixmap")
            assert self._listening_to is None
            def set_pixmap():
                # The tricky part here is that the pixmap returned by
                # NameWindowPixmap gets invalidated every time the window's
                # viewable state changes.  ("viewable" here is the X term that
                # means "mapped, and all ancestors are also mapped".)  But
                # there is no X event that will tell you when a window's
                # viewability changes!  Instead we have to find all ancestors,
                # and watch all of them for unmap and reparent events.  But
                # what about races?  I hear you cry.  By doing things in the
                # exact order:
                #   1) select for StructureNotify
                #   2) QueryTree to get parent
                #   3) repeat 1 & 2 up to the root
                #   4) call NameWindowPixmap
                # we are safe.  (I think.)
                listening = []
                try:
                    win = get_parent(self._window)
                    while win is not None and win.get_parent() is not None:
                        # We have to use a lowlevel function to manipulate the
                        # event selection here, because
                        # SubstructureRedirectMask does not roundtrip through
                        # the GDK event mask functions.  So if we used them,
                        # here, we would clobber corral window selection
                        # masks, and those don't deserve clobbering.  They are
                        # our friends!  X is driving me slowly mad.
                        addXSelectInput(win, const["StructureNotifyMask"])
                        add_event_receiver(win, self)
                        listening.append(win)
                        win = get_parent(win)
                    handle = xcomposite_name_window_pixmap(self._window)
                except:
                    try:
                        self._cleanup_listening(listening)
                    except:
                        pass
                    raise
                if handle is None:
                    log("failed to name a window pixmap (expect an X error soon)",
                        type="pixmap")
                    self._cleanup_listening(listening)
                else:
                    self._contents_handle = handle
                    # Don't save the listening set until after
                    # NameWindowPixmap has succeeded, to maintain our
                    # invariant:
                    self._listening_to = listening
            trap.swallow(set_pixmap)
        return self._contents_handle

    def do_get_property_contents(self, name):
        handle = self.get_property("contents-handle")
        if handle is None:
            return None
        else:
            return handle.pixmap

    def do_wimpiggy_unmap_event(self, *args):
        self.invalidate_pixmap()

    def do_wimpiggy_configure_event(self, event):
        self._border_width = event.border_width
        self.invalidate_pixmap()

    def do_wimpiggy_reparent_event(self, *args):
        self.invalidate_pixmap()

    def do_wimpiggy_damage_event(self, event):
        event.x += self._border_width
        event.y += self._border_width
        self.emit("contents-changed", event)

gobject.type_register(CompositeHelper)
