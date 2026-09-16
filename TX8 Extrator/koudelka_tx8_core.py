"""Leitor TX8 de Koudelka. Somente leitura: nunca altera os arquivos do jogo."""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class Texture:
    offset: int
    size: int
    width: int
    height: int
    stored_height: int
    palette_offset: int
    pixel_offset: int
    extra_header: int
    header_hex: str
    palette_words: tuple[int, ...]
    pixels: bytes

    @property
    def screen_layout(self) -> bool:
        return (self.width, self.height, self.stored_height) == (128, 768, 768)

    @property
    def panel_layout(self) -> bool:
        return self.stored_height >= 512 and self.stored_height % 256 == 0


@dataclass(frozen=True)
class Tx8File:
    path: Path
    size: int
    sha256: str
    textures: tuple[Texture, ...]


def read_tx8(path: Path | str) -> Tx8File:
    path = Path(path).resolve()
    data = path.read_bytes()
    if not data.startswith(b'TX8 '):
        raise ValueError('Assinatura TX8 de Koudelka não encontrada no início do arquivo.')
    textures = []
    cursor = 0
    while cursor < len(data):
        offset = data.find(b'TX8 ', cursor)
        if offset < 0:
            break
        if offset + 16 > len(data):
            raise ValueError(f'Cabeçalho incompleto em 0x{offset:X}.')
        size, width, height, depth = struct.unpack_from('<IHHB', data, offset + 4)
        if depth != 8:
            raise ValueError(f'Bloco 0x{offset:X}: profundidade {depth} não suportada.')
        if not (0 < width <= 8192 and 0 < height <= 8192) or width * height > 16_777_216:
            raise ValueError(f'Dimensões inválidas em 0x{offset:X}: {width}x{height}.')
        if size < 528 + width * height or offset + size > len(data):
            raise ValueError(f'Bloco truncado ou tamanho inválido em 0x{offset:X}.')

        extra = size - 528 - width * height
        extra_header = 0
        stored_height = height
        if extra:
            if (width, height, extra) == (128, 512, 192) and data[offset+14:offset+16] != b'\xab\xab':
                # NEWF0: 192 bytes de coordenadas antes da paleta, verificado visualmente.
                extra_header = 192
            elif (width, height, extra) == (128, 256, 4096) and data[offset+14:offset+16] == b'\xab\xab':
                # MENUPAD: 32 linhas adicionais (ícones de botões) após a área declarada.
                stored_height = 288
            else:
                raise ValueError(
                    f'Variante TX8 ainda não reconhecida em 0x{offset:X}: '
                    f'{width}x{height}, {extra} bytes adicionais. Nenhuma extração foi presumida.'
                )
        palette_offset = offset + 16 + extra_header
        pixel_offset = palette_offset + 512
        pixel_end = pixel_offset + width * stored_height
        if pixel_end != offset + size:
            raise ValueError(f'Inconsistência no fim dos pixels em 0x{offset:X}.')
        textures.append(Texture(
            offset, size, width, height, stored_height, palette_offset, pixel_offset,
            extra_header, data[offset:offset+16].hex(),
            struct.unpack_from('<256H', data, palette_offset), data[pixel_offset:pixel_end],
        ))
        cursor = offset + size
    return Tx8File(path, len(data), hashlib.sha256(data).hexdigest(), tuple(textures))


def palette_rgb(words: tuple[int, ...]) -> list[int]:
    rgb = []
    for word in words:
        for shift in (0, 5, 10):
            value = (word >> shift) & 31
            rgb.append((value << 3) | (value >> 2))
    return rgb


def image_for(texture: Texture, layout: str = 'auto', transparent: bool = False) -> Image.Image:
    """PNG indexado preserva índices; transparência opcional apenas para palavra CLUT 0."""
    if layout == 'auto':
        layout = 'screen' if texture.screen_layout else 'linear'
    if layout not in ('linear', 'panels', 'screen'):
        raise ValueError('Modo de imagem desconhecido.')
    image = Image.frombytes('P', (texture.width, texture.stored_height), texture.pixels)
    image.putpalette(palette_rgb(texture.palette_words))
    if transparent:
        image.info['transparency'] = bytes(0 if word == 0 else 255 for word in texture.palette_words)
    if layout == 'linear':
        return image
    if not texture.panel_layout:
        raise ValueError('Esta textura não tem painéis completos de 256 linhas.')
    count = texture.stored_height // 256
    result = Image.new('P', (texture.width * count, 256))
    result.putpalette(image.getpalette())
    result.info.update(image.info)
    for panel in range(count):
        result.paste(image.crop((0, panel * 256, texture.width, (panel + 1) * 256)), (panel * texture.width, 0))
    if layout == 'screen':
        if not texture.screen_layout:
            raise ValueError('Recorte 320x240 disponível somente para as texturas 128x768.')
        return result.crop((0, 0, 320, 240))
    return result


def export_tx8(source: Tx8File, folder: Path | str, transparent: bool = False) -> Path:
    """Cria uma pasta nova, nunca substituindo extrações anteriores."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    report = {
        'source': str(source.path), 'source_size': source.size, 'source_sha256': source.sha256,
        'format': 'Koudelka TX8 8bpp / CLUT PS1 16-bit',
        'palette_zero_transparent': transparent,
        'note': 'PNG linear preserva todos os índices. Tela 320x240 é um recorte para prévia; não usar como substituto direto do binário.',
        'textures': [],
    }
    for number, texture in enumerate(source.textures, 1):
        name = f'{number:03d}'
        outputs = {'linear': f'{name}_linear.png'}
        image_for(texture, 'linear', transparent).save(folder / outputs['linear'])
        if texture.panel_layout:
            outputs['panels'] = f'{name}_paineis.png'
            image_for(texture, 'panels', transparent).save(folder / outputs['panels'])
        if texture.screen_layout:
            outputs['screen'] = f'{name}_tela_320x240.png'
            image_for(texture, 'screen', transparent).save(folder / outputs['screen'])
        report['textures'].append({
            'number': number, 'offset': texture.offset, 'size': texture.size,
            'width': texture.width, 'height_declared': texture.height,
            'height_stored': texture.stored_height, 'palette_offset': texture.palette_offset,
            'pixel_offset': texture.pixel_offset, 'extra_header_bytes': texture.extra_header,
            'header_hex': texture.header_hex, 'palette_words': list(texture.palette_words),
            'files': outputs,
        })
    (folder / 'dados_extracao.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder


def checkerboard(size: tuple[int, int]) -> Image.Image:
    result = Image.new('RGBA', size, '#353535')
    draw = ImageDraw.Draw(result)
    for y in range(0, size[1], 16):
        for x in range(0, size[0], 16):
            if (x//16 + y//16) % 2:
                draw.rectangle((x, y, x+15, y+15), fill='#555555')
    return result
