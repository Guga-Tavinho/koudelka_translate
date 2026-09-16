"""Regressao da reinsercao: indices, paletas, recortes e arquivos intocados."""
from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import unittest

from PIL import Image
from koudelka_tx8_core import image_for, palette_rgb, read_tx8
from koudelka_tx8_import import import_layouts, prepare_import, save_modified
from test_tx8 import GAME, block


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='koudelka_import_test_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'original.TX8'
        self.path.write_bytes(block())
        self.source = read_tx8(self.path)
        self.texture = self.source.textures[0]
        self.png = self.root / 'edit.png'

    def test_same_png_indexed_and_rgb(self):
        for mode in ('P', 'RGB', 'RGBA'):
            image_for(self.texture).convert(mode).save(self.png)
            edit = prepare_import(self.texture, self.png)
            self.assertEqual(edit.texture, self.texture)
            self.assertEqual(edit.changed_pixels, 0)
            self.assertEqual(edit.approximated_pixels, 0)
            self.assertEqual(edit.indexed, mode == 'P')

    def test_duplicate_palette_entries_preserve_indices(self):
        data = bytearray(block())
        struct.pack_into('<4H', data, 16, 0, 0x8000, 0x801f, 0x801f)
        self.path.write_bytes(data)
        texture = read_tx8(self.path).textures[0]
        for mode in ('P', 'RGB', 'RGBA'):
            image_for(texture).convert(mode).save(self.png)
            edit = prepare_import(texture, self.png)
            self.assertEqual(edit.texture.pixels, texture.pixels)

    def test_invalid_dimensions_alpha_format(self):
        Image.new('RGB', (8, 8)).save(self.png)
        with self.assertRaisesRegex(ValueError, 'tamanho'):
            prepare_import(self.texture, self.png)
        Image.new('RGBA', (4, 4), (255, 0, 0, 128)).save(self.png)
        with self.assertRaisesRegex(ValueError, 'parcial'):
            prepare_import(self.texture, self.png)
        Image.new('RGB', (4, 4)).save(self.png, format='BMP')
        with self.assertRaisesRegex(ValueError, 'PNG estatico'):
            prepare_import(self.texture, self.png)

    def test_explicit_transparency_maps_native_zero(self):
        img = image_for(self.texture).convert('RGBA')
        img.putpixel((1, 1), (255, 0, 0, 0))
        img.save(self.png)
        edit = prepare_import(self.texture, self.png)
        self.assertEqual(edit.texture.pixels[5], 0)
        self.assertEqual(edit.changed_pixels, 1)
        no_zero = replace(self.texture, palette_words=tuple(word | 0x8000 for word in self.texture.palette_words))
        with self.assertRaisesRegex(ValueError, 'nao possui cor transparente'):
            prepare_import(no_zero, self.png)

    def test_nearest_color_and_original_palette(self):
        img = image_for(self.texture).convert('RGB')
        desired = (127, 207, 15)
        img.putpixel((1, 1), desired)
        img.save(self.png)
        edit = prepare_import(self.texture, self.png)
        palette = palette_rgb(self.texture.palette_words)
        colors = [tuple(palette[i:i+3]) for i in range(0, 768, 3)]
        expected = min(range(1, 256), key=lambda i: sum((a-b)**2 for a, b in zip(desired, colors[i])))
        self.assertEqual(edit.texture.pixels[5], expected)
        self.assertEqual(edit.approximated_pixels, 1)
        self.assertEqual(edit.texture.palette_words, self.texture.palette_words)

    def test_protect_original_existing_destination_and_structure(self):
        changes = {0: self.texture}
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'original'):
            save_modified(self.source, changes, self.path)
        target = self.root / 'new.TX8'
        save_modified(self.source, changes, target)
        self.assertEqual(target.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            save_modified(self.source, changes, target)
        for changes in ({}, {2: self.texture}, {0: replace(self.texture, size=1)},
                        {0: replace(self.texture, pixels=b'')},
                        {0: replace(self.texture, palette_words=(0,)*256)}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                save_modified(self.source, changes, self.root / 'bad.TX8')
        self.assertFalse((self.root / 'bad.TX8').exists())
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'extensao'):
            save_modified(self.source, {0: self.texture}, self.root / 'wrong.png')

    def test_stale_source_rejected(self):
        self.path.write_bytes(self.path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'mudou'):
            save_modified(self.source, {0: self.texture}, self.root / 'new.TX8')
        self.assertFalse((self.root / 'new.TX8').exists())


@unittest.skipUnless((GAME / 'MENU/GAMEOVER/OVER1.TX8').exists(), 'Jogo nao disponivel')
class RealImportTests(unittest.TestCase):
    def test_roundtrip_every_real_texture_and_layout(self):
        files = sorted(p for p in GAME.rglob('*') if p.suffix.lower() == '.tx8')
        count, pngs = 0, 0
        with tempfile.TemporaryDirectory(prefix='tx8_roundtrip_') as temp:
            root = Path(temp)
            png = root / 'test.png'
            for file_number, path in enumerate(files):
                source = read_tx8(path)
                original = path.read_bytes()
                changes = {}
                for number, texture in enumerate(source.textures):
                    for layout in import_layouts(texture):
                        with self.subTest(path=path, image=number, layout=layout):
                            image_for(texture, layout).save(png)
                            edit = prepare_import(texture, png)
                            self.assertEqual(edit.texture, texture)
                            self.assertEqual(edit.changed_pixels, 0)
                            changes[number] = edit.texture
                            pngs += 1
                    count += 1
                target = save_modified(source, changes, root / f'{file_number}.TX8')
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(path.read_bytes(), original)
        print(f'Round-trip exato: {len(files)} TX8, {count} texturas, {pngs} PNGs/layouts.')

    def test_gameover_rgb_screen_is_lossless(self):
        source = read_tx8(GAME / 'MENU/GAMEOVER/OVER1.TX8')
        with tempfile.TemporaryDirectory(prefix='tx8_rgb_') as temp:
            png = Path(temp) / 'screen.png'
            for texture in source.textures:
                image_for(texture, 'screen').convert('RGB').save(png)
                edit = prepare_import(texture, png)
                self.assertEqual(edit.texture.pixels, texture.pixels)

    def test_edited_screens_preserve_every_other_byte(self):
        source = read_tx8(GAME / 'MENU/GAMEOVER/OVER1.TX8')
        original = source.path.read_bytes()
        expected = bytearray(original)
        changes = {}
        with tempfile.TemporaryDirectory(prefix='tx8_modified_') as temp:
            root = Path(temp)
            for number in (1, 4):
                texture = source.textures[number]
                png = root / f'{number}.png'
                image = image_for(texture, 'screen')
                # Testa os limites entre os paineis 1/2 e 2/3, e a ultima linha/coluna.
                for x, y in ((0, 0), (127, 12), (128, 12), (255, 12), (256, 12), (319, 239)):
                    index = (image.getpixel((x, y)) + 1) % 256
                    image.putpixel((x, y), index)
                    raw_pos = (x//128 * 256 + y)*128 + x%128
                    expected[texture.pixel_offset + raw_pos] = index
                image.save(png)
                edit = prepare_import(texture, png)
                self.assertEqual(edit.changed_pixels, 6)
                self.assertEqual(image_for(edit.texture, 'screen').tobytes(), image.tobytes())
                changes[number] = edit.texture
            target = save_modified(source, changes, root / 'modified.TX8')
            self.assertEqual(target.read_bytes(), expected)
            self.assertEqual(source.path.read_bytes(), original)
            reloaded = read_tx8(target)
            for number in (0, 2, 3):
                self.assertEqual(reloaded.textures[number], source.textures[number])

    def test_modified_map_metadata_and_extra_controller_rows(self):
        with tempfile.TemporaryDirectory(prefix='tx8_variants_') as temp:
            root = Path(temp)
            for variant in ('MENUPAD.TX8', 'MENUMAPS/NEWF0.TX8'):
                source = read_tx8(GAME / 'MENU' / variant)
                texture = source.textures[0]
                original = source.path.read_bytes()
                png = root / 'edit.png'
                image = image_for(texture, 'linear')
                last = (texture.pixels[-1]+1)%256
                image.putpixel((image.width-1, image.height-1), last)
                image.save(png)
                edit = prepare_import(texture, png)
                expected = bytearray(original)
                expected[texture.pixel_offset+len(texture.pixels)-1] = last
                result = save_modified(source, {0: edit.texture}, root / source.path.name)
                self.assertEqual(result.read_bytes(), expected)
                self.assertEqual(source.path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
