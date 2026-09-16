"""Testes de leitura/exportacao. Originais nunca sao modificados."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from PIL import Image
from koudelka_tx8_core import read_tx8, image_for, palette_rgb, export_tx8


GAME = Path(os.environ.get('KOUDELKA_GAME', r'E:\KDK\Koudelka (Disc 1)'))


def block(width=4, height=4, pixels=None):
    palette = struct.pack('<256H', *range(256))
    pixels = bytes(range(width * height)) if pixels is None else pixels
    return b'TX8 ' + struct.pack('<IHHB', 528 + len(pixels), width, height, 8) + b'\xab' * 3 + palette + pixels


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='koudelka_tx8_test_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def read(self, data):
        path = self.root / 'test.TX8'
        path.write_bytes(data)
        return read_tx8(path)

    def test_padding_and_embedded_magic(self):
        source = self.read(block(pixels=b'TX8 ' + bytes(12)) + bytes(37) + block())
        self.assertEqual(len(source.textures), 2)
        self.assertEqual(source.textures[1].offset, 544 + 37)
        self.assertEqual(source.textures[0].pixels[:4], b'TX8 ')

    def test_reject_invalid(self):
        for data in (b'WRONG', b'TX8 ', block()[:-1], block()[:12] + b'\x04' + block()[13:]):
            with self.subTest(data=data[:16]), self.assertRaises(ValueError):
                self.read(data)
        unknown = bytearray(block() + bytes(10))
        struct.pack_into('<I', unknown, 4, len(unknown))
        with self.assertRaisesRegex(ValueError, 'Variante'):
            self.read(unknown)

    def test_palette_and_alpha(self):
        self.assertEqual(palette_rgb((0x001f, 0x03e0, 0x7c00, 0x8000)),
                         [255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0])
        texture = self.read(block()).textures[0]
        self.assertEqual(image_for(texture).convert('RGBA').getpixel((0, 0))[3], 255)
        self.assertEqual(image_for(texture, transparent=True).convert('RGBA').getpixel((0, 0))[3], 0)
        self.assertEqual(image_for(texture, transparent=True).convert('RGBA').getpixel((1, 0))[3], 255)

    def test_export_roundtrip_and_no_overwrite(self):
        source = self.read(block())
        folder = export_tx8(source, self.root / 'out')
        with Image.open(folder / '001_linear.png') as img:
            self.assertEqual(img.mode, 'P')
            self.assertEqual(img.tobytes(), source.textures[0].pixels)
            self.assertEqual(img.getpalette(), palette_rgb(source.textures[0].palette_words))
        with self.assertRaises(FileExistsError):
            export_tx8(source, folder)
        report = json.loads((folder / 'dados_extracao.json').read_text(encoding='utf-8'))
        self.assertEqual(report['source_sha256'], hashlib.sha256(source.path.read_bytes()).hexdigest())


@unittest.skipUnless((GAME / 'MENU/GAMEOVER/OVER1.TX8').exists(), 'Arquivos do jogo nao disponiveis')
class RealFileTests(unittest.TestCase):
    def test_gameover_layout(self):
        source = read_tx8(GAME / 'MENU/GAMEOVER/OVER1.TX8')
        self.assertEqual(len(source.textures), 5)
        self.assertEqual([t.offset for t in source.textures], [0, 100352, 200704, 301056, 401408])
        for texture in source.textures:
            raw = image_for(texture, 'linear')
            panels = image_for(texture, 'panels')
            screen = image_for(texture)
            self.assertEqual(raw.size, (128, 768))
            self.assertEqual(panels.size, (384, 256))
            self.assertEqual(screen.size, (320, 240))
            for panel in range(3):
                self.assertEqual(raw.crop((0, 256*panel, 128, 256*(panel+1))).tobytes(),
                                 panels.crop((128*panel, 0, 128*(panel+1), 256)).tobytes())
            self.assertEqual(screen.tobytes(), panels.crop((0, 0, 320, 240)).tobytes())

    def test_special_variants(self):
        maps = read_tx8(GAME / 'MENU/MENUMAPS/NEWF0.TX8')
        self.assertEqual(len(maps.textures), 12)
        for texture in maps.textures:
            self.assertEqual(texture.palette_offset - texture.offset, 208)
            self.assertEqual(texture.pixel_offset - texture.offset, 720)
        controller = read_tx8(GAME / 'MENU/MENUPAD.TX8').textures[0]
        self.assertEqual((controller.height, controller.stored_height), (256, 288))
        self.assertEqual(controller.pixel_offset, 528)
        self.assertEqual(image_for(controller).size, (128, 288))

    def test_all_real_files_png_roundtrip(self):
        paths = sorted(path for path in GAME.rglob('*') if path.suffix.lower() == '.tx8')
        count = 0
        with tempfile.TemporaryDirectory(prefix='koudelka_tx8_real_') as temp:
            for number, path in enumerate(paths):
                with self.subTest(path=path):
                    source = read_tx8(path)
                    folder = export_tx8(source, Path(temp) / str(number))
                    for index, texture in enumerate(source.textures, 1):
                        with Image.open(folder / f'{index:03d}_linear.png') as img:
                            self.assertEqual(img.mode, 'P')
                            self.assertEqual(img.tobytes(), texture.pixels)
                    self.assertEqual(source.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
                    count += len(source.textures)
        print(f'Verificados: {len(paths)} TX8, {count} imagens; originais intactos.')


if __name__ == '__main__':
    unittest.main(verbosity=2)
