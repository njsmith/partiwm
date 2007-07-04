import gtk
import gtk.gdk
import parti.tray

class SimpleTabTray(parti.tray.Tray):
    def __init__(self, trayset, tag):
        super(SimpleTabTray, self).__init__(trayset, tag)
        self.windows = []
        self.main = gtk.Window()
        self.main.set_size_request(gtk.gdk.screen_width(),
                                   gtk.gdk.screen_height())
        self.hpane = gtk.HPaned()
        self.hpane.set_position(gtk.gdk.screen_width() / 2)
        self.left_notebook = gtk.Notebook()
        self.hpane.add1(self.left_notebook)
        self.right_notebook = gtk.Notebook()
        self.hpane.add2(self.right_notebook)

        for notebook in (self.left_notebook, self.right_notebook):
            notebook.set_group_id(5)

        self.main.add(self.hpane)
        self.main.show_all()

    def add(self, window):
        window.connect("unmanaged", self._handle_window_departure)
        self.windows.append(window)
        if self.left_notebook.get_n_pages() > self.right_notebook.get_n_pages():
            notebook = self.right_notebook
        else:
            notebook = self.left_notebook
        notebook.append_page(window)
        notebook.set_tab_label_text(window,
                                    window.get_property("title"))
        notebook.set_tab_reorderable(window, True)
        notebook.set_tab_detachable(window, True)
        window.connect("notify::title", self._handle_title_change)
        window.show()

    def _handle_title_change(self, window, title):
        left_children = self.left_notebook.get_children()
        right_children = self.right_notebook.get_children()
        if window in left_children:
            notebook = self.left_notebook
        elif window in right_children:
            notebook = self.right_notebook
        else:
            print "Mrr?"
            return
        notebook.set_tab_label_text(window,
                                    window.get_property("title"))

    def _handle_window_departure(self, window):
        self.windows.remove(window)
        left_children = self.left_notebook.get_children()
        right_children = self.right_notebook.get_children()
        if window in left_children:
            notebook = self.left_notebook
        elif window in right_children:
            notebook = self.right_notebook
        notebook.remove_page(notebook.get_children().index(window))
        
    def windows(self):
        return set(self.windows)
