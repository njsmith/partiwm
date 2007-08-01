"""This is the container widget that has all trays as children and manages
their display."""

import gtk
import gobject

from parti.util import base

# FIXME: there should be multiple logical viewports, one for each xinerama
# screen, somehow... not clear what the best way to get that is, since GTK has
# a widget tree, not a widget DAG.

class Viewport(gtk.Container):
    def __init__(self, trayset):
        super(Viewport, self).__init__()
        self._trayset = trayset
        self._children = []
        self._current = None

        self.set_flags(gtk.NO_WINDOW)

        # FIXME: This would better be a default handler, but there is a bug in
        # the superclass's default handler that means we can't call it
        # properly[0], so as a workaround we let the real default handler run,
        # and then come in afterward to do what we need to.
        #   [0] http://bugzilla.gnome.org/show_bug.cgi?id=462368
        self.connect_after("set-focus-child", self._after_set_focus_child)

        self._trayset.connect_after("removed", self._tray_removed)
        self._trayset.connect_after("added", self._tray_added)
        # Don't care about "moved" or "renamed" signals in initial lame
        # implementation.

        for tray in self._trayset.trays:
            self._tray_added(self._trayset, tray.tag, tray)

    def do_add(self, child):
        if child not in self._children:
            self._children.append(child)
            child.set_parent(self)
            if self._current is None:
                self._switch_to(self._children[0])

    def do_remove(self, child):
        assert child in self._children
        self._children.remove(child)
        child.unparent()
        if self._current is child:
            self._current = None
            if self._children:
                self._switch_to(self._children[0])

    def do_forall(self, internal, callback, data):
        # We have no internal widgets, so ignore 'internal' flag
        for child in self._children:
            callback(child, data)

    def _tray_removed(self, trayset, tag, tray):
        self.remove(tray)

    def _tray_added(self, trayset, tag, tray):
        self.add(tray)

    def _switch_to(self, child):
        assert child in self._children
        if self._current is child:
            return
        if self._current is not None:
            self._current.set_child_visible(False)
        self._current = child
        self._current.set_child_visible(True)

    def _after_set_focus_child(self, self_again, child):
        self._switch_to(child)

    def do_size_request(self, requisition):
        if self._current:
            (requisition.width, requisition.height) \
                                = self._current.size_request()
        else:
            (requisition.width, requisition.height) = (0, 0)

    def do_size_allocate(self, allocation):
        self.allocation = allocation
        def apply_allocation(child, data):
            child.size_allocate(allocation)
        self.forall(apply_allocation, None)

gobject.type_register(Viewport)
