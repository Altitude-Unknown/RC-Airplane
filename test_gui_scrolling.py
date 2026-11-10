"""Real Tk layout checks; run with a desktop session (or Xvfb on Linux)."""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest

from fram_gui_models import App


class ScrollableTabsTests(unittest.TestCase):
    def test_small_windows_scaled_content_wheel_and_focus(self):
        app = App()
        original_scale = app.tk.call('tk', 'scaling')
        try:
            for scale in (1.0, 2.0):
                app.tk.call('tk', 'scaling', scale)
                # Changing the named default font forces existing ttk widgets
                # to remeasure too, simulating larger desktop text settings.
                app.tk.call('font', 'configure', 'TkDefaultFont', '-size', 12 if scale == 2 else 10)
                for size in ('640x480', '1024x600', '480x320'):
                    app.geometry(size)
                    app.update()
                    for tab in (app.tab_models, app.tab_roles, app.tab_firmware):
                        app.nb.select(tab)
                        app.update()
                        with self.subTest(scale=scale, size=size, tab=str(tab)):
                            self.assertTrue(tab.vertical.winfo_ismapped())
                            self.assertTrue(tab.horizontal.winfo_ismapped())
                            self.assertGreater(tab.canvas.winfo_height(), 1)
                            self.assertGreaterEqual(tab.content.winfo_width(), tab.content.winfo_reqwidth())
                            self.assertGreaterEqual(tab.content.winfo_height(), tab.content.winfo_reqheight())
                            # Both scrollbars remain inside the visible window.
                            for bar in (tab.vertical, tab.horizontal):
                                self.assertLessEqual(bar.winfo_rooty() + bar.winfo_height(),
                                                     app.winfo_rooty() + app.winfo_height())
                            def descendants(widget):
                                for child in widget.winfo_children():
                                    yield child
                                    yield from descendants(child)
                            buttons = [w for w in descendants(tab.content) if isinstance(w, ttk.Button)]
                            self.assertTrue(buttons)
                            for button in buttons:
                                tab._focus(SimpleNamespace(widget=button))
                                app.update_idletasks()
                                x = button.winfo_rootx() - tab.canvas.winfo_rootx()
                                y = button.winfo_rooty() - tab.canvas.winfo_rooty()
                                self.assertGreaterEqual(x, 0)
                                self.assertGreaterEqual(y, 0)
                                if button.winfo_width() <= tab.canvas.winfo_width():
                                    self.assertLessEqual(x + button.winfo_width(), tab.canvas.winfo_width())
                                if button.winfo_height() <= tab.canvas.winfo_height():
                                    self.assertLessEqual(y + button.winfo_height(), tab.canvas.winfo_height())
                            tab.canvas.yview_moveto(0)
                            before = tab.canvas.yview()
                            buttons[-1].event_generate('<MouseWheel>', delta=-120)
                            app.update()
                            self.assertGreater(tab.canvas.yview()[0], before[0])
                            tab.canvas.xview_moveto(0)
                            if tab.content.winfo_width() > tab.canvas.winfo_width():
                                buttons[-1].event_generate('<Shift-MouseWheel>', delta=-120)
                                app.update()
                                self.assertGreater(tab.canvas.xview()[0], 0)
            # A wheel over a selection scrolls the form, never its stored value.
            app.nb.select(app.tab_roles)
            app.update()
            app.esp_port_cmb.configure(values=('first', 'second'))
            app.esp_port_cmb.set('first')
            app.esp_port_cmb.event_generate('<MouseWheel>', delta=-120)
            app.update()
            self.assertEqual(app.esp_port_cmb.get(), 'first')
        finally:
            app.tk.call('tk', 'scaling', original_scale)
            app.on_close()


if __name__ == '__main__':
    unittest.main()
