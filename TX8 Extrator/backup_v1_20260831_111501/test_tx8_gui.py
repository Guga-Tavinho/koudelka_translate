"""Teste local da GUI e dos comandos de exportacao, sem modificar o jogo."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
import koudelka_tx8_gui as gui
from test_tx8 import GAME


@unittest.skipUnless((GAME / 'MENU/GAMEOVER/OVER1.TX8').exists(), 'Arquivos ausentes')
class GuiTests(unittest.TestCase):
    def test_preview_navigation_and_export(self):
        with patch.object(gui.sys, 'argv', ['test']), patch.object(gui.messagebox, 'showinfo'), \
                patch.object(gui.messagebox, 'showerror') as errors, \
                patch.object(gui.messagebox, 'showwarning') as warnings:
            app = gui.Tx8App()
            try:
                for callback in app.tk.splitlist(app.tk.call('after', 'info')):
                    app.after_cancel(callback)
                app.geometry('760x500')
                app.update()
                app.load_path(GAME / 'MENU/GAMEOVER/OVER1.TX8')

                def wait_job():
                    deadline = time.monotonic() + 10
                    while app.busy and time.monotonic() < deadline:
                        app.update()
                        time.sleep(0.01)
                    app.update()
                    self.assertFalse(app.busy)

                wait_job()
                self.assertEqual(len(app.lookup), 5)
                self.assertEqual(app.current_image.size, (320, 240))
                for iid in app.lookup:
                    app.tree.selection_set(iid)
                    app.update()
                    self.assertIsNotNone(app.photo)
                    self.assertEqual(app.current_image.size, (320, 240))
                app.tree.focus_set()
                app.tree.focus('f0b4')
                app.tree.event_generate('<Up>')
                app.update()
                self.assertEqual(app.tree.selection(), ('f0b3',))
                for label, size in [('Textura linear completa', (128, 768)),
                                    ('Painéis de 256 linhas', (384, 256)),
                                    ('Tela 320x240 (recorte)', (320, 240))]:
                    app.layout_var.set(label)
                    app.show_current()
                    self.assertEqual(app.current_image.size, size)
                app.transparent_var.set(True)
                app.show_current()
                app.zoom_var.set('4x')
                app.draw_preview()
                self.assertEqual((app.photo.width(), app.photo.height()), (1280, 960))

                # Os botoes de exportacao precisam caber sem maximizar a janela.
                footer = next(child for child in app.winfo_children()
                              if child.grid_info().get('row') == 3)
                for button in footer.winfo_children():
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                         app.winfo_rootx() + app.winfo_width())
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                         app.winfo_rooty() + app.winfo_height())
                with tempfile.TemporaryDirectory(prefix='koudelka_tx8_gui_') as temp:
                    image_path = Path(temp) / 'preview.png'
                    with patch.object(gui.filedialog, 'asksaveasfilename', return_value=str(image_path)):
                        app.save_current()
                    with Image.open(image_path) as img:
                        self.assertEqual(img.size, (320, 240))
                    with patch.object(gui.filedialog, 'askdirectory', return_value=temp):
                        app.extract_file()
                        wait_job()
                    self.assertEqual(len(list(Path(temp).rglob('*_linear.png'))), 5)
                self.assertEqual(errors.call_count, 0)
                self.assertEqual(warnings.call_count, 0)
                app.load_path(GAME / 'MENU/MENUPAD.TX8')
                wait_job()
                # Um recorte incompativel nao deve mostrar pixels adivinhados.
                self.assertIsNone(app.current_image)
                app.layout_var.set('Automático')
                app.show_current()
                self.assertEqual(app.current_image.size, (128, 288))
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
