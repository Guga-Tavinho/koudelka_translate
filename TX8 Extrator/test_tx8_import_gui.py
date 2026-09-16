"""Smoke test do importador: previa, multiplos PNGs, salvar e protecoes."""
from pathlib import Path
import os
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from koudelka_tx8_core import image_for, read_tx8
from koudelka_tx8_import_gui import ImportWindow
from test_tx8 import GAME


@unittest.skipUnless((GAME / 'MENU/GAMEOVER/OVER1.TX8').exists(), 'Jogo nao disponivel')
class ImportGuiTests(unittest.TestCase):
    def test_preview_multiple_edits_and_save(self):
        source = read_tx8(GAME / 'MENU/GAMEOVER/OVER1.TX8')
        original = source.path.read_bytes()
        root = tk.Tk()
        root.geometry('760x500')
        root.update()
        window = ImportWindow(root, source, selected=1)
        try:
            window.geometry('760x500')
            window.update()
            self.assertEqual(window.preview_images[0].size, (320, 240))
            for button in window.buttons:
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     window.winfo_rootx() + window.winfo_width())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                     window.winfo_rooty() + window.winfo_height())

            def wait():
                deadline = time.monotonic() + 15
                while window.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                root.update()
                self.assertFalse(window.busy)

            with tempfile.TemporaryDirectory(prefix='tx8_import_ui_') as temp, \
                    patch('koudelka_tx8_import_gui.messagebox.showerror') as errors, \
                    patch('koudelka_tx8_import_gui.messagebox.showinfo'):
                folder = Path(temp)
                for number in (1, 4):
                    window.selector.current(number)
                    window.on_select()
                    png = folder / f'{number}.png'
                    img = image_for(source.textures[number], 'screen')
                    img.putpixel((10, 20), (img.getpixel((10, 20))+1)%256)
                    img.save(png)
                    with patch('koudelka_tx8_import_gui.filedialog.askopenfilename', return_value=str(png)):
                        window.choose_png()
                        wait()
                    self.assertNotEqual(window.preview_images[0].tobytes(), window.preview_images[1].tobytes())
                    self.assertEqual(window.changes[number].changed_pixels, 1)
                self.assertEqual(set(window.changes), {1, 4})
                screenshot = os.environ.get('KOUDELKA_UI_SCREENSHOT')
                if screenshot:
                    from PIL import ImageGrab
                    window.geometry('960x650+50+50')
                    window.update()
                    window.lift()
                    window.update()
                    ImageGrab.grab(bbox=(window.winfo_rootx(), window.winfo_rooty(),
                        window.winfo_rootx()+window.winfo_width(),
                        window.winfo_rooty()+window.winfo_height())).save(screenshot)
                with patch('koudelka_tx8_import_gui.messagebox.askyesno', return_value=False):
                    window.close()
                    self.assertTrue(window.winfo_exists())
                window.reload_png()
                wait()
                window.zoom_var.set('2x')
                window.draw_preview()
                self.assertEqual(window.photos[0].width(), 640)
                target = folder / 'imported.TX8'
                with patch('koudelka_tx8_import_gui.filedialog.asksaveasfilename', return_value=str(target)):
                    window.save_tx8()
                    wait()
                self.assertFalse(window.dirty)
                reloaded = read_tx8(target)
                for number in (1, 4):
                    self.assertEqual(reloaded.textures[number], window.changes[number].texture)
                self.assertEqual(errors.call_count, 0)
                window.reset_current()
                self.assertEqual(set(window.changes), {1})
                self.assertEqual(window.preview_images[0].tobytes(), window.preview_images[1].tobytes())
                # Tentar salvar no original deve falhar sem modificar um byte.
                with patch('koudelka_tx8_import_gui.filedialog.asksaveasfilename', return_value=str(source.path)):
                    window.save_tx8()
                    wait()
                self.assertEqual(errors.call_count, 1)
                self.assertEqual(source.path.read_bytes(), original)
        finally:
            window.destroy()
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
