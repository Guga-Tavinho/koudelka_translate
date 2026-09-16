"""Importacao PNG -> copia TX8, com paleta fixa e estrutura preservada."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import tempfile
from struct import iter_unpack
from typing import Mapping

from PIL import Image
from koudelka_tx8_core import Texture, Tx8File, image_for, palette_rgb, read_tx8


@dataclass(frozen=True)
class PreparedImport:
    png_path: Path
    layout: str
    texture: Texture
    changed_pixels: int
    approximated_pixels: int
    stp_changes: int
    indexed: bool


def import_layouts(texture: Texture) -> dict[str, tuple[int, int]]:
    layouts = {'linear': (texture.width, texture.stored_height)}
    if texture.panel_layout:
        layouts['panels'] = (texture.width * (texture.stored_height // 256), 256)
    if texture.screen_layout:
        layouts['screen'] = (320, 240)
    return layouts


def prepare_import(texture: Texture, png_path: Path | str) -> PreparedImport:
    """Detecta dimensoes sem redimensionar. Paleta e pixels fora do recorte nao mudam."""
    png_path = Path(png_path).resolve()
    with Image.open(png_path) as opened:
        if opened.format != 'PNG' or getattr(opened, 'n_frames', 1) != 1:
            raise ValueError('Selecione um PNG estatico, nao uma animacao ou outro formato.')
        layouts = import_layouts(texture)
        layout = next((key for key, size in layouts.items() if size == opened.size), None)
        if layout is None:
            expected = ', '.join(f'{w}x{h}' for w, h in layouts.values())
            raise ValueError(f'PNG com tamanho {opened.width}x{opened.height}. Esperado: {expected}. '
                             'Nao redimensionamos automaticamente para evitar distorcoes.')
        opened.load()
        png = opened.copy()

    before = image_for(texture, layout)
    old_indices = before.tobytes()
    rgba = png.convert('RGBA')
    alphas = set(rgba.getchannel('A').tobytes())
    if alphas - {0, 255}:
        raise ValueError('O PNG tem transparencia parcial (alpha entre 1 e 254). '
                         'Mescle as camadas com o fundo original antes de importar. '
                         'O efeito de semitransparencia do PS1 nao equivale ao alpha de PNG.')
    words = texture.palette_words
    zero_indices = [i for i, word in enumerate(words) if word == 0]
    if 0 in alphas and not zero_indices:
        raise ValueError('Este TX8 nao possui cor transparente na paleta original. '
                         'Salve o PNG opaco, mesclado com o fundo original.')
    palette = palette_rgb(words)
    colors = tuple(tuple(palette[i:i+3]) for i in range(0, 768, 3))
    indexed = png.mode == 'P' and png.getpalette('RGB') == palette
    if indexed:
        # PNGs exportados preservam indices duplicados e o bit STP de cada entrada.
        # Se o alpha de uma entrada tiver sido editado, convertemos explicitamente.
        candidate = png.tobytes()
        indexed = all(alpha != 0 or words[index] == 0
                      for index, alpha in zip(candidate, rgba.getchannel('A').tobytes()))
    approximated = 0
    if indexed:
        indices = candidate
    else:
        # Nao usar palavra 0000 para cores opacas novas: ela pode criar buracos no jogo.
        opaque = [i for i, word in enumerate(words) if word != 0]
        groups = {bit: [i for i in opaque if words[i] >> 15 == bit] for bit in (0, 1)}
        cache = {}
        result = bytearray(len(old_indices))
        for pos, (old, color) in enumerate(zip(old_indices, iter_unpack('4B', rgba.tobytes()))):
            rgb, alpha = color[:3], color[3]
            if alpha == 0:
                new = old if words[old] == 0 else zero_indices[0]
            elif rgb == colors[old]:
                # Crucial: RGB/RGBA exportado sem edicao deve voltar byte a byte igual,
                # inclusive onde entradas CLUT duplicadas possuem bits diferentes.
                new = old
            else:
                bit = words[old] >> 15
                key = (rgb, bit)
                if key not in cache:
                    choices = groups[bit] or opaque
                    if not choices:
                        raise ValueError('A paleta original nao tem nenhuma cor opaca disponivel.')
                    cache[key] = min(choices, key=lambda i: sum((a-b)**2 for a, b in zip(rgb, colors[i])))
                new = cache[key]
            result[pos] = new
            if alpha and colors[new] != rgb:
                approximated += 1
        indices = bytes(result)

    view = Image.frombytes('P', before.size, indices)
    view.putpalette(palette)
    if layout == 'linear':
        pixels = indices
    else:
        panels = image_for(texture, 'panels')
        panels.paste(view, (0, 0))
        pixels = b''.join(panels.crop((x, 0, x + texture.width, 256)).tobytes()
                          for x in range(0, panels.width, texture.width))
    changed = sum(a != b for a, b in zip(texture.pixels, pixels))
    stp_changes = sum((words[a] >> 15) != (words[b] >> 15) for a, b in zip(texture.pixels, pixels))
    return PreparedImport(png_path, layout, replace(texture, pixels=pixels), changed,
                          approximated, stp_changes, indexed)


def save_modified(source: Tx8File, changes: Mapping[int, Texture], target: Path | str) -> Path:
    """Salva exclusivamente em arquivo NOVO e confere a copia antes de entregar."""
    target = Path(target).resolve()
    if target == source.path.resolve():
        raise ValueError('O original nao pode ser sobrescrito. Escolha outro nome ou pasta.')
    if target.suffix.lower() != '.tx8':
        raise ValueError('O arquivo de saida deve ter extensao .TX8.')
    if target.exists():
        raise FileExistsError('Ja existe um arquivo neste destino. Escolha um novo nome.')
    if not changes:
        raise ValueError('Importe pelo menos um PNG antes de salvar o TX8.')
    original = source.path.read_bytes()
    if hashlib.sha256(original).hexdigest() != source.sha256:
        raise ValueError('O TX8 de origem mudou desde que foi aberto. Reabra-o antes de importar.')
    output = bytearray(original)
    for number, texture in changes.items():
        if not isinstance(number, int) or not 0 <= number < len(source.textures):
            raise ValueError('Numero de imagem invalido.')
        base = source.textures[number]
        if replace(texture, pixels=base.pixels) != base or len(texture.pixels) != len(base.pixels):
            raise ValueError('A importacao tentou alterar estrutura ou paleta. Gravacao cancelada.')
        output[base.pixel_offset:base.pixel_offset + len(base.pixels)] = texture.pixels
    if len(output) != source.size:
        raise ValueError('O tamanho do TX8 nao pode mudar.')

    # Valida em arquivo temporario antes de criar o resultado definitivo.
    with tempfile.TemporaryDirectory(prefix='tx8_validacao_', dir=target.parent) as temp:
        trial = Path(temp) / 'validacao.TX8'
        trial.write_bytes(output)
        decoded = read_tx8(trial)
        expected = tuple(changes.get(i, t) for i, t in enumerate(source.textures))
        if decoded.textures != expected or decoded.size != source.size:
            raise ValueError('A releitura do TX8 modificado nao passou na verificacao.')
    # xb protege contra nomes existentes, links e concorrencia no destino.
    with target.open('xb') as handle:
        try:
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            handle.close()
            target.unlink()  # Somente o arquivo incompleto criado por esta chamada.
            raise
    if target.read_bytes() != output:
        raise OSError('O arquivo gravado nao passou na verificacao de leitura. Nao o injete no jogo.')
    return target
