import gtk
from parti.pseudoclient import PseudoclientWindow
from parti.addons.ipython_view import IPythonView

def spawn_repl_window(namespace):
    window = PseudoclientWindow()
    window.set_resizable(True)
    window.set_title("Parti REPL")
    scroll = gtk.ScrolledWindow()
    scroll.set_policy(gtk.POLICY_AUTOMATIC,gtk.POLICY_AUTOMATIC)
    view = IPythonView()
    view.set_wrap_mode(gtk.WRAP_CHAR)
    view.updateNamespace(namespace)
    scroll.add(view)
    window.add(scroll)
    window.show_all()
    window.connect('delete-event', lambda x, y: window.destroy())
