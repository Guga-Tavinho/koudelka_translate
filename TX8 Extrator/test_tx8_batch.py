"""Lotes de PNG: associação, erro sem aplicação parcial e gravação real do OVER1."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from PIL import Image
from koudelka_tx8_core import image_for, read_tx8
from koudelka_tx8_import import match_png_batch, prepare_import_batch, save_modified
from koudelka_tx8_import_gui import ImportWindow
from test_tx8 import GAME

SOURCE = GAME / 'MENU/GAMEOVER/OVER1.TX8'


@unittest.skipUnless(SOURCE.exists(), 'OVER1 não disponível')
class BatchTests(unittest.TestCase):
    def setUp(self):
        self.source = read_tx8(SOURCE)
        self.original = SOURCE.read_bytes()
        self.temp = tempfile.TemporaryDirectory(prefix='tx8_batch_')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.paths = []
        self.expected = bytearray(self.original)
        for number, texture in enumerate(self.source.textures):
            image = image_for(texture, 'screen')
            # Limites entre painéis, última coluna/linha e um ponto comum.
            for x, y in ((127, 12), (128, 12), (255, 12), (256, 12), (319, 239), (10, 20)):
                value = (image.getpixel((x, y)) + 1) % 256
                image.putpixel((x, y), value)
                at = texture.pixel_offset + (x // 128 * 256 + y) * 128 + x % 128
                self.expected[at] = value
            png = self.folder / f'{number+1:03d}_tela_320x240_PTBR.png'
            image.save(png)
            self.paths.append(png)

    def test_shuffled_five_pngs_match_and_preserve_every_other_byte(self):
        paths = self.paths[::-1]
        matched = match_png_batch(self.source, paths)
        self.assertEqual(list(matched), list(range(5)))
        prepared = prepare_import_batch(self.source, paths)
        target = self.folder / 'all.TX8'
        save_modified(self.source, {n: edit.texture for n, edit in prepared.items()}, target)
        self.assertTrue(target.read_bytes() == self.expected)
        self.assertEqual(SOURCE.read_bytes(), self.original)

    def test_reject_duplicate_number_unknown_name_and_out_of_range(self):
        duplicate = self.folder / '001_linear.png'
        image_for(self.source.textures[0], 'linear').save(duplicate)
        cases = [([self.paths[0], duplicate], 'Dois PNGs'),
                 ([self.folder / 'sem_numero.png'], 'número da imagem'),
                 ([self.folder / '2026edicao.png'], 'número da imagem'),
                 ([self.folder / '000_tela.png'], 'fora do intervalo'),
                 ([self.folder / '006_tela.png'], 'fora do intervalo')]
        for paths, message in cases:
            with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, message):
                match_png_batch(self.source, paths)

    def make_window(self):
        root = tk.Tk()
        root.geometry('760x500')
        root.update()
        window = ImportWindow(root, self.source)
        window.geometry('760x500')
        root.update()
        self.addCleanup(root.destroy)
        return root, window

    def wait(self, root, window):
        deadline = time.monotonic() + 20
        while window.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        root.update()
        self.assertFalse(window.busy)

    def test_gui_file_picker_confirmation_preview_and_save_five(self):
        root, window = self.make_window()
        self.assertTrue(any(b.cget('text') == 'Importar vários PNGs…' for b in window.buttons))
        for button in window.buttons:
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), window.winfo_rootx()+760)
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), window.winfo_rooty()+500)
        observed = []

        def widgets(widget):
            for child in widget.winfo_children():
                yield child
                yield from widgets(child)

        def accept_review():
            dialog = next(w for w in window.winfo_children() if isinstance(w, tk.Toplevel))
            dialog.geometry('560x280')
            dialog.update()
            children = list(widgets(dialog))
            tree = next(w for w in children if isinstance(w, ttk.Treeview))
            observed.extend(tree.item(i, 'values') for i in tree.get_children())
            button = next(w for w in children if isinstance(w, ttk.Button) and w.cget('text') == 'Importar')
            # Encerre a janela mesmo se houver falha de layout para não travar o teste.
            fits = button.winfo_rooty()+button.winfo_height() <= dialog.winfo_rooty()+280
            if not fits:
                print('Layout do diálogo:', 'janela', dialog.winfo_geometry(),
                      'botão relativo', button.winfo_rooty()-dialog.winfo_rooty(),
                      'altura botão', button.winfo_height())
            button.invoke()
            observed.append(fits)

        target = self.folder / 'gui.TX8'
        with patch('koudelka_tx8_import_gui.messagebox.showerror') as errors, \
                patch('koudelka_tx8_import_gui.messagebox.showinfo'), \
                patch('koudelka_tx8_import_gui.filedialog.askopenfilenames',
                      return_value=tuple(str(p) for p in self.paths[::-1])):
            window.after(80, accept_review)
            window.choose_pngs()
            self.wait(root, window)
            self.assertEqual(observed[-1], True)
            self.assertEqual([r[0] for r in observed[:-1]], ['001','002','003','004','005'])
            self.assertEqual(set(window.changes), set(range(5)))
            self.assertIn('5 imagem(ns)', window.info_var.get())
            for n in range(5):
                window.selector.current(n)
                window.on_select()
                expected = image_for(window.changes[n].texture, 'screen')
                self.assertEqual(window.preview_images[1].tobytes(), expected.tobytes())
            with patch('koudelka_tx8_import_gui.filedialog.asksaveasfilename', return_value=str(target)):
                window.save_tx8()
                self.wait(root, window)
            self.assertFalse(window.dirty)
            self.assertEqual(errors.call_count, 0)
            self.assertTrue(target.read_bytes() == self.expected)
            self.assertEqual(SOURCE.read_bytes(), self.original)

    def test_gui_failed_or_cancelled_batch_keeps_previous_imports(self):
        root, window = self.make_window()
        window.load_png(self.paths[0])
        self.wait(root, window)
        previous = dict(window.changes)
        with patch.object(window, 'confirm_batch_import', return_value=False):
            window.load_pngs(self.paths)
        self.assertEqual(window.changes, previous)
        Image.new('RGB', (10,10)).save(self.paths[-1])
        with patch.object(window, 'confirm_batch_import', return_value=True), \
                patch('koudelka_tx8_import_gui.messagebox.showerror') as errors:
            window.load_pngs(self.paths)
            self.wait(root, window)
            self.assertEqual(errors.call_count, 1)
            self.assertIn('005', errors.call_args.args[1])
            self.assertIn('Nenhuma imagem', errors.call_args.args[1])
        self.assertEqual(window.changes, previous)
        self.assertTrue(window.dirty)
        self.assertEqual(SOURCE.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
