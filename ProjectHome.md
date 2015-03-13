# PLEASE NOTE #

This project is in deep hibernation; I haven't had time to devote for several years now.

If you are looking for xpra, there is a fork which receives more support at: http://xpra.org/

# Welcome to the Parti project #

Parti is a tabbing/tiling (one might say "partitioning") window manager.  Its goal is to bring this superior window management interface to modern, mainstream desktop environments.  It is written in Python, uses GTK+, has an automated test suite, and is released under the GPL.

For more details, see [the FAQ](http://code.google.com/p/partiwm/source/browse/README.parti).

To see it in action (with a very prototype-y interface), check out our [screencasts](Screenshots.md).

# xpra #

Also, I got a little distracted and wrote a useful utility called [xpra](xpra.md).  It gives you "persistent remote applications" -- basically, [screen](http://www.gnu.org/software/screen/) for X.  See [xpra](xpra.md) for details.

# Status #

Summary: At the moment, Parti is fun to hack, but not usable as an actual day-to-day window manager.  If you are looking for a tiling window manager now, you may want to try some [other WM](OtherWMs.md).

In particular, most of the X11 interaction window management guts are done, with a few exceptions.  This means that we basically can just get a gtk.Widget for each client window and then do whatever we want with it at the GTK level.  What still needs to be written is the actual GTK UI that displays those Widgets in some sensible way.

xpra is ahead in the game here, because while it's essentially a window manager under the covers, it doesn't have to implement any policy -- it just acts as a proxy to the real window manager you're running on your real desktop.  So it's more like beta-quality, and usable in the real world.