"""Testes locais: MENUHELP completo e regressao de itens. Nao modifica os originais."""
import csv
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
import koudelka_tx4_tradutor_gui as tx4


GAME = Path(os.environ.get('KOUDELKA_GAME', r'E:\KDK\Koudelka (Disc 1)'))
HELP = GAME / 'MENU/MENUHELP.TX4'
ITEMS = GAME / 'MENU/ITEMS/001.TX4'


@unittest.skipUnless(HELP.exists(), 'MENUHELP nao disponivel')
class MenuHelpTests(unittest.TestCase):
    def setUp(self):
        self.project = tx4.TX4Project()
        self.project.load_tx4(HELP)
        self.font = tx4.load_font(tx4.DEFAULT_ARIAL)
        self.temp = tempfile.TemporaryDirectory(prefix='menuhelp_test_')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_real_headers_dimensions_and_colors(self):
        p = self.project
        self.assertEqual(p.block_count, 9)
        self.assertEqual(p.profile, 'menuhelp')
        self.assertEqual(p.view_height, 190)
        for number, info in enumerate(p.blocks, 1):
            self.assertEqual(info.offset, (number-1)*0x8800)
            self.assertEqual((info.width, info.height, info.size), (256, 256, 0x8030))
            self.assertEqual(p.original_image(number).size, (256, 190))
            main, shadow, background = p.help_colors(number)
            self.assertEqual(main, 3 if number in (2, 5) else 0)
            self.assertEqual(p.display_palette(number)[main], (255, 255, 255))
            self.assertEqual(p.display_palette(number)[background], (0, 0, 0))
            self.assertEqual(p.display_palette(number)[shadow], (99, 99, 99))

    def test_no_translation_is_exact_copy(self):
        target = self.folder / 'unchanged.TX4'
        self.assertEqual(self.project.generate(target, self.font), (0, 313344))
        self.assertEqual(target.read_bytes(), HELP.read_bytes())

    def test_menuhelp_renderer_unchanged_from_before_black_update(self):
        snapshot = Path(__file__).parent / 'backup_antes_padrao_sem_sombra_20260831_145114/koudelka_tx4_tradutor_gui.py'
        if not snapshot.exists():
            self.skipTest('Snapshot anterior ausente')
        spec=importlib.util.spec_from_file_location('tx4_before_black',snapshot)
        before=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=before
        spec.loader.exec_module(before)
        old=before.TX4Project(); old.load_tx4(HELP)
        for n in range(1,10):
            for project in (old,self.project):
                project.entry(n).translation='\n'.join(['<Força, ação e proteção>']*14)
            a=old.rendered_indices(old.entry(n),self.font)
            b=self.project.rendered_indices(self.project.entry(n),self.font)
            self.assertEqual(a,b)

    def test_fourteen_lines_visible_and_only_page_pixels_change(self):
        p = self.project
        original = HELP.read_bytes()
        for number in range(1, 10):
            entry = p.entry(number)
            entry.translation = '\n'.join(f'Linha {i:02d}: ação, força e precisão.' for i in range(1, 15))
        target = self.folder / 'translated.TX4'
        self.assertEqual(p.generate(target, self.font), (9, 313344))
        output = target.read_bytes()
        reread = tx4.TX4Project()
        reread.load_tx4(target)
        for number, info in enumerate(p.blocks, 1):
            pixels, lines = p.rendered_indices(p.entry(number), self.font)
            self.assertEqual(len(lines), 14)
            self.assertEqual(reread.block_indices(number), pixels)
            self.assertEqual(output[info.offset:info.pixel_offset], original[info.offset:info.pixel_offset])
            end = info.offset + info.size
            tail = info.pixel_offset + 256*190//2
            self.assertEqual(output[tail:end], original[tail:end])
            next_offset = p.blocks[number].offset if number < 9 else len(output)
            self.assertEqual(output[end:next_offset], original[end:next_offset])
            main, shadow, background = p.help_colors(number)
            self.assertEqual(set(pixels), {main, shadow, background})
            # Ultima linha (y=169) precisa existir: a antiga cortava em y=128.
            self.assertIn(main, pixels[169*256:185*256])
            self.assertEqual(p.preview_image(p.entry(number), self.font).tobytes(), reread.original_image(number).tobytes())
        self.assertEqual(HELP.read_bytes(), original)

    def test_replace_title_from_y_zero_and_preserve_other_pages(self):
        p = self.project
        p.entry(2).translation = '<Força>'
        pixels, _ = p.rendered_indices(p.entry(2), self.font)
        main, shadow, bg = p.help_colors(2)
        self.assertIn(main, pixels[:30*256])
        self.assertEqual(set(pixels[30*256:]), {bg})
        target = self.folder / 'one.TX4'
        p.generate(target, self.font)
        expected = bytearray(p.data)
        start = p.blocks[1].pixel_offset
        encoded = tx4.encode_4bpp(pixels)
        expected[start:start+len(encoded)] = encoded
        self.assertEqual(target.read_bytes(), expected)

    def test_overflow_blocks_output_and_original_is_protected(self):
        p = self.project
        p.entry(1).translation = '\n'.join(['Uma linha']*15)
        self.assertIn('máximo', p.validate(self.font)[0])
        target = self.folder / 'overflow.TX4'
        with self.assertRaises(ValueError):
            p.generate(target, self.font)
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError, 'protegido'):
            p.generate(HELP, self.font)
        p.entry(1).translation = 'Ág'
        enormous = tx4.load_font(tx4.DEFAULT_ARIAL, 300)
        with self.assertRaisesRegex(ValueError, 'área'):
            p.rendered_indices(p.entry(1), enormous)

    def test_ocr_full_page_foreground_not_background(self):
        p = self.project
        for number in (1, 2, 5, 9):
            with patch.object(tx4, 'run_tesseract', return_value='texto') as mocked:
                self.assertEqual(p.ocr_block(number), ('', 'texto'))
                image, psm = mocked.call_args.args
                self.assertEqual(image.size, (1024, 760))
                self.assertEqual(psm, 6)
                main, _, _ = p.help_colors(number)
                indices = p.block_indices(number)
                for value, color in ((main, 0), (2, 255)):
                    pos = indices.index(value)
                    self.assertEqual(image.getpixel(((pos%256)*4, (pos//256)*4)), color)

    def test_csv_roundtrip_profile_and_bad_old_csv(self):
        p = self.project
        p.entry(9).translation = '<Sorte>\nTexto completo da página.'
        csv_path = self.folder / 'translation.csv'
        p.save_csv(csv_path)
        loaded = tx4.TX4Project()
        loaded.load_tx4(HELP)
        self.assertEqual(loaded.import_csv(csv_path), 9)
        self.assertEqual(tx4.normalize_manual_breaks(loaded.entry(9).translation), p.entry(9).translation)
        with csv_path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['block','description_pt'])
            writer.writeheader()
            writer.writerow({'block':1,'description_pt':'Nao deve aplicar parcialmente'})
            writer.writerow({'block':17,'description_pt':'Leitura antiga'})
        with self.assertRaisesRegex(ValueError, '17'):
            loaded.import_csv(csv_path)
        self.assertEqual(loaded.entry(1).translation, '')

    def test_corrupt_and_unsupported_files_rejected(self):
        path = self.folder / 'bad.TX4'
        cases = [b'not TX4', bytes(self.project.data[:200]), bytearray(self.project.data)]
        cases[-1][48 + 190*128] ^= 1
        for data in cases:
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                tx4.TX4Project().load_tx4(path)


@unittest.skipUnless(ITEMS.exists(), 'Itens nao disponiveis')
class ItemRegressionTests(unittest.TestCase):
    def test_all_item_glyphs_preserved_without_shadow_and_titles_protected(self):
        old_path = Path(__file__).parent / 'backup_antes_MENUHELP_20260831_130950/koudelka_tx4_tradutor_gui.py'
        if not old_path.exists():
            self.skipTest('Snapshot de regressao ausente')
        spec = importlib.util.spec_from_file_location('tx4_legacy_snapshot', old_path)
        legacy = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = legacy
        spec.loader.exec_module(legacy)
        old, new = legacy.TX4Project(), tx4.TX4Project()
        old.load_tx4(ITEMS)
        new.load_tx4(ITEMS)
        self.assertEqual(new.block_count, 230)
        self.assertEqual(new.profile, 'items')
        font = tx4.load_font(tx4.DEFAULT_ARIAL)
        for number in range(1, 231):
            self.assertEqual(old.block_indices(number), new.block_indices(number))
            entry = new.entry(number)
            entry.translation = 'Ação e proteção.\nMantém as regras dos itens.'
            raw = old.block_indices(number)
            titled = number <= 114 or number in tx4.EXTRA_TITLED_BLOCKS
            top = (18 if number in tx4.EXTRA_TITLED_BLOCKS and any(raw[18*256:30*256])
                   else 30) if titled else 0
            self.assertEqual(new.text_top(number), top)
            self.assertEqual(entry.is_document, not titled)
            mask = [0] * (256*128)
            old_lines = legacy.draw_ttf_to_indices(mask, entry.translation, y=top,
                                                 font=font, max_lines=8)
            expected = raw[:top*256] + [1 if v == 2 else 0 for v in mask[top*256:]]
            pixels, lines = new.rendered_indices(entry, font)
            self.assertEqual(lines, old_lines)
            self.assertEqual(pixels, expected, f'Bloco {number}')
            self.assertEqual(set(pixels[top*256:]), {0,1})
        with tempfile.TemporaryDirectory(prefix='tx4_regression_') as temp:
            b = Path(temp)/'new.TX4'
            new.generate(b, font)
            reread = tx4.TX4Project(); reread.load_tx4(b)
            result = b.read_bytes()
            self.assertEqual(len(result), len(new.data))
            previous_end = 0
            for number, info in enumerate(new.blocks, 1):
                self.assertEqual(result[previous_end:info.pixel_offset], new.data[previous_end:info.pixel_offset])
                previous_end = info.offset + info.size
                self.assertEqual(reread.block_indices(number), new.rendered_indices(new.entry(number),font)[0])
            self.assertEqual(result[previous_end:], new.data[previous_end:])
        self.assertEqual(ITEMS.read_bytes(), new.data)

    def test_item_preview_uses_real_clut(self):
        project = tx4.TX4Project()
        project.load_tx4(ITEMS)
        word = project.blocks[0].palette[1]
        rgb = tuple((((word >> shift) & 31) << 3) | (((word >> shift) & 31) >> 2)
                    for shift in (0,5,10))
        self.assertEqual(rgb, (0,0,0))
        self.assertEqual(project.display_palette(1)[1], rgb)
        project.preview_background = (232,213,179)
        project.entry(1).translation = 'Texto para conferir a cor.'
        font = tx4.load_font(tx4.DEFAULT_ARIAL)
        indices, _ = project.rendered_indices(project.entry(1), font)
        pos = indices.index(1, 30*256)
        self.assertEqual(project.preview_image(project.entry(1),font).getpixel((pos%256,pos//256)), rgb)

    def test_matches_approved_sa_pistol_glyph_shapes_without_shadow(self):
        approved = ITEMS.parent / 'revisado/001_FONTE_PRETA_SEM_SOMBRA.TX4'
        if not approved.exists():
            self.skipTest('Referencia aprovada ausente')
        p = tx4.TX4Project(); p.load_tx4(approved)
        p.entry(79).translation = ('Lançado em 1874, este revólver de ação simples\n'
                                   'foi muito usado no Velho Oeste americano.')
        actual = p.rendered_indices(p.entry(79),tx4.load_font(tx4.DEFAULT_ARIAL))[0]
        expected = p.block_indices(79)
        self.assertEqual(actual[:7680],expected[:7680])
        self.assertEqual(set(actual[7680:]),{0,1})
        # O arquivo aprovado foi montado com origem vertical um pixel abaixo do
        # renderer antigo da GUI. Mantemos o posicionamento da GUI e comparamos
        # as mascaras recortadas: formato, espaco e preto iguais, sem sombra.
        masks=[]
        for values in (actual,expected):
            mask=Image.new('L',(256,128))
            mask.putdata([255 if v==1 and i>=7680 else 0 for i,v in enumerate(values)])
            masks.append(mask.crop(mask.getbbox()))
        self.assertEqual(masks[0].size,masks[1].size)
        self.assertTrue(masks[0].tobytes()==masks[1].tobytes())

    def test_no_translation_and_sem_texto_are_exact_copies(self):
        p = tx4.TX4Project(); p.load_tx4(ITEMS)
        p.entry(6).translation = 'Não deve ser aplicado.'
        p.entry(6).translation_status = 'SEM_TEXTO'
        with tempfile.TemporaryDirectory(prefix='tx4_unchanged_') as temp:
            output = Path(temp)/'copy.TX4'
            self.assertEqual(p.generate(output,tx4.load_font(tx4.DEFAULT_ARIAL)),(0,len(p.data)))
            self.assertEqual(output.read_bytes(),ITEMS.read_bytes())

    def test_wrong_palette_and_overflow_block_generation(self):
        with tempfile.TemporaryDirectory(prefix='tx4_validation_') as temp:
            raw = bytearray(ITEMS.read_bytes())
            struct.pack_into('<H',raw,18,0)  # Transparencia nao pode ser usada como preto.
            source, output = Path(temp)/'bad.TX4', Path(temp)/'out.TX4'
            source.write_bytes(raw)
            p=tx4.TX4Project(); p.load_tx4(source)
            p.entry(1).translation='Texto'
            font=tx4.load_font(tx4.DEFAULT_ARIAL)
            with self.assertRaisesRegex(ValueError,'preto nativo'):
                p.generate(output,font)
            self.assertFalse(output.exists())
            p.load_tx4(ITEMS)
            for n in (1,115,201,218,223):
                p.entry(n).translation='\n'.join(['Linha']*(p.max_lines(p.entry(n))+1))
                with self.assertRaisesRegex(ValueError,'máximo'):
                    p.rendered_indices(p.entry(n),font)

    def test_ocr_does_not_drop_black_letters_or_top_of_description(self):
        p=tx4.TX4Project(); p.load_tx4(ITEMS)
        for n in (1,115,201,218):
            with patch.object(tx4,'run_tesseract',return_value='texto') as mocked:
                self.assertEqual(p.ocr_block(n),('texto','texto'))
                self.assertEqual(mocked.call_args_list[0].args[0].size,(1024,72))
                self.assertEqual(mocked.call_args_list[1].args[0].size,(1024,440))


@unittest.skipUnless(HELP.exists(), 'MENUHELP nao disponivel')
class GuiTests(unittest.TestCase):
    def test_black_font_light_background_is_display_only(self):
        black = ITEMS.parent / 'revisado' / '001_FONTE_PRETA_SEM_SOMBRA.TX4'
        if not black.exists():
            self.skipTest('Arquivo de fonte preta nao disponivel')
        root = tk.Tk()
        root.withdraw()
        app = tx4.TranslatorGUI(root)
        try:
            app.open_tx4(black)
            self.assertTrue(app.light_background_var.get())
            project = app.project
            indices = project.block_indices(6)
            image = project.original_image(6)
            for index, color in ((0, (232, 213, 179)), (1, (0, 0, 0)),
                                 (2, project.display_palette(6)[2])):
                pos = indices.index(index)
                self.assertEqual(image.getpixel((pos % 256, pos // 256)), color)
            with tempfile.TemporaryDirectory(prefix='tx4_black_preview_') as temp:
                output = Path(temp) / 'unchanged.TX4'
                project.generate(output, tx4.load_font(tx4.DEFAULT_ARIAL))
                self.assertEqual(output.read_bytes(), black.read_bytes())
                app.select_block(79)
                app._set_text(app.translation_text,'Ação e proteção. Sem sombra.')
                app.apply_current()
                self.assertIn('preto nativo dos títulos',app.color_label.cget('text'))
                current,_=project.rendered_indices(project.entry(79),app.font)
                self.assertEqual(set(current[7680:]),{0,1})
                self.assertTrue(app.preview_pil.tobytes()==project.present_indices(current,79).tobytes())
                result=Path(temp)/'translated.TX4'
                project.generate(result,app.font)
                loaded=tx4.TX4Project(); loaded.load_tx4(result)
                self.assertEqual(loaded.block_indices(79),current)
            app.light_background_var.set(False)
            app.change_preview_background()
            self.assertIsNone(project.preview_background)
        finally:
            root.destroy()

    def test_help_preview_zoom_and_switch_to_items(self):
        root = tk.Tk()
        app = tx4.TranslatorGUI(root)
        try:
            root.geometry('1100x740+20+20')
            with patch.object(tx4.messagebox, 'showwarning') as warnings, \
                    patch.object(tx4.messagebox, 'showerror') as errors:
                app.open_tx4(HELP)
                root.update()
                self.assertEqual(len(app.tree.get_children()), 9)
                self.assertEqual(app.original_pil.size, (256, 190))
                self.assertEqual(warnings.call_count, 0)
                self.assertIn('AJUDA', app.type_label.cget('text'))
                app._set_text(app.translation_text, '\n'.join(f'Linha {i:02d}: força e ação.' for i in range(1, 15)))
                app.apply_current()
                root.update()
                self.assertEqual(app.preview_pil.size, (256, 190))
                self.assertIn('14/14', app.validation_label.cget('text'))
                self.assertLessEqual(app.preview_photo.height(), app.preview_canvas.winfo_height())
                root.geometry('1000x660+20+20')
                root.update()
                for widget in (app.validation_label, app.rule_note):
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                         root.winfo_rooty()+root.winfo_height())
                root.geometry('1100x740+20+20')
                root.update()
                screenshot = os.environ.get('MENUHELP_UI_SCREENSHOT')
                if screenshot:
                    from PIL import ImageGrab
                    ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),
                        root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(screenshot)
                app.image_zoom_var.set('2x')
                app.redraw_previews()
                self.assertEqual((app.preview_photo.width(),app.preview_photo.height()), (512,380))
                self.assertGreaterEqual(float(app.preview_canvas.cget('scrollregion').split()[3]), 380)
                self.assertEqual(errors.call_count, 0)
                app.dirty = False
                if ITEMS.exists():
                    app.open_tx4(ITEMS)
                    root.update()
                    self.assertEqual(len(app.tree.get_children()), 230)
                    self.assertEqual(app.original_pil.size, (256,128))
                    self.assertIn('TÍTULO PRESERVADO', app.type_label.cget('text'))
                    self.assertTrue(app.light_background_var.get())
                    self.assertIn('preto sem sombra', app.rules_label.cget('text'))
                    app.select_block(218)
                    self.assertIn('TÍTULO PRESERVADO', app.type_label.cget('text'))
                    app.select_block(223)
                    self.assertIn('CONTINUAÇÃO', app.type_label.cget('text'))
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
