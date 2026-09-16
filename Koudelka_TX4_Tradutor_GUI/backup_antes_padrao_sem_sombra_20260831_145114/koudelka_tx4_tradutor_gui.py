#!/usr/bin/env python3
"""
Koudelka TX4 Tradutor GUI
=========================

Editor gráfico para MENU/ITEMS/001.TX4 e MENU/MENUHELP.TX4 de Koudelka.

Regras preservadas do fluxo de itens (MENUHELP usa um perfil separado):
- 230 blocos de 0x4800 bytes;
- imagem visível de 256x128, 4bpp linear reverse-order;
- pixels começam em +0x30 e o cabeçalho/CLUT nunca é alterado;
- blocos 1-114: mantém o título original e redesenha apenas a descrição;
- blocos 115-230: limpa toda a área textual e escreve até 8 linhas;
- Arial 11 px, line-height 15, sem antialias e com sombra de 1 px;
- arquivo gerado mantém exatamente o tamanho do TX4 original.

MENUHELP: 9 paginas 256x256, area textual 256x190, paleta branca nativa,
Arial 11 px com passo 13 px, 14 linhas. As 66 linhas finais sao preservadas.

Dependência: Pillow
    python -m pip install pillow
"""

from __future__ import annotations

import csv
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - depende da instalação do Python
    raise SystemExit("Esta instalação do Python não possui Tkinter.") from exc

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError as exc:
    raise SystemExit("Instale Pillow com: python -m pip install pillow") from exc


APP_TITLE = "Koudelka TX4 Tradutor — Arial / MENUHELP"
WIDTH = 256
STORED_HEIGHT = 144
VIEW_HEIGHT = 128
BLOCK_SIZE = WIDTH * STORED_HEIGHT // 2  # 0x4800
IMAGE_DATA_OFFSET = 0x30
PROTECTED_BYTES = 0x30
TEXT_X = 10
TEXT_MAX_X = 252
ITEM_BODY_Y = 30
COLOR_MAIN = 2
COLOR_SHADOW = 1
ITEM_LAST_BLOCK = 114
EXPECTED_BLOCKS = 230
DEFAULT_FONT_SIZE = 11
DEFAULT_LINE_HEIGHT = 15
ITEM_MAX_LINES = 6
DOCUMENT_MAX_LINES = 8
DEFAULT_ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")
HELP_VIEW_HEIGHT = 190  # As linhas 190..255 sao preenchimento uniforme nas 9 paginas.
HELP_LINE_HEIGHT = 13
HELP_MAX_LINES = 14
HELP_MAX_WIDTH = 248
HELP_NAMES = ('AP', 'STR', 'VIT', 'DEX', 'INT', 'PIE', 'MND', 'AGL', 'LUC')


@dataclass(frozen=True)
class TX4Block:
    offset: int
    size: int
    width: int
    height: int
    palette: tuple[int, ...]

    @property
    def pixel_offset(self) -> int:
        return self.offset + IMAGE_DATA_OFFSET


DISPLAY_PALETTE = [
    (0, 0, 0),       # 0: fundo
    (160, 64, 32),   # 1: sombra marrom-avermelhada
    (208, 160, 80),  # 2: texto laranja claro
    (96, 96, 96),
    (128, 128, 128),
    (160, 160, 160),
    (192, 192, 192),
    (224, 224, 224),
    (72, 72, 72),
    (96, 48, 32),
    (128, 80, 48),
    (160, 112, 64),
    (192, 144, 80),
    (224, 176, 96),
    (240, 208, 144),
    (255, 255, 255),
]


@dataclass
class Entry:
    block: int
    original_name: str
    title_ocr: str = ""
    original_text: str = ""
    translation: str = ""
    translation_status: str = "PENDENTE"

    @property
    def is_document(self) -> bool:
        return self.block > ITEM_LAST_BLOCK


def decode_4bpp(data: bytes, width: int = WIDTH) -> tuple[list[int], int]:
    indices: list[int] = []
    for value in data:
        indices.append(value & 0x0F)
        indices.append((value >> 4) & 0x0F)
    height = len(indices) // width
    return indices[: width * height], height


def encode_4bpp(indices: list[int]) -> bytes:
    if len(indices) % 2:
        raise ValueError("Quantidade ímpar de pixels 4bpp.")
    output = bytearray(len(indices) // 2)
    for pos in range(0, len(indices), 2):
        output[pos // 2] = (indices[pos] & 0x0F) | ((indices[pos + 1] & 0x0F) << 4)
    return bytes(output)


def load_font(path: Path, size: int = DEFAULT_FONT_SIZE) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(
            f"Fonte Arial não encontrada em {path}. Selecione arial.ttf na interface."
        )
    return ImageFont.truetype(str(path), size=size)


def text_width(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, text: str) -> int:
    if not text:
        return 0
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def normalize_manual_breaks(text: str) -> str:
    return (text or "").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def wrap_text(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
    text: str,
    max_width: int,
) -> list[str]:
    """Quebra por largura real. Uma nova linha ou ``\\n`` força a quebra."""
    text = normalize_manual_breaks(text)
    result: list[str] = []

    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            result.append("")
            continue

        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if text_width(draw, font, candidate) <= max_width:
                current = candidate
                continue

            if current:
                result.append(current)

            if text_width(draw, font, word) > max_width:
                part = ""
                for char in word:
                    candidate_part = part + char
                    if part and text_width(draw, font, candidate_part) > max_width:
                        result.append(part)
                        part = char
                    else:
                        part = candidate_part
                current = part
            else:
                current = word

        if current:
            result.append(current)

    return result


def measure_translation(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int = TEXT_MAX_X - TEXT_X,
) -> tuple[list[str], int]:
    measure_image = Image.new("L", (WIDTH, VIEW_HEIGHT), 0)
    draw = ImageDraw.Draw(measure_image)
    lines = wrap_text(draw, font, text, max_width)
    widest = max((text_width(draw, font, line) for line in lines), default=0)
    return lines, widest


def draw_ttf_to_indices(
    indices: list[int],
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    max_lines: int,
    line_height: int = DEFAULT_LINE_HEIGHT,
    height: int = VIEW_HEIGHT,
    max_width: int = TEXT_MAX_X - TEXT_X,
    centered: bool = False,
    color_main: int = COLOR_MAIN,
    color_shadow: int = COLOR_SHADOW,
) -> list[str]:
    lines, _widest = measure_translation(text, font, max_width)
    if len(lines) > max_lines:
        raise ValueError(
            f"usa {len(lines)} linhas; o máximo para este bloco é {max_lines}"
        )

    mask = Image.new("1", (WIDTH, height), 0)
    draw = ImageDraw.Draw(mask)
    for number, line in enumerate(lines):
        line_y = y + number * line_height
        x = (WIDTH - text_width(draw, font, line)) // 2 if centered else TEXT_X
        if line:
            left, top, right, bottom = draw.textbbox((x, line_y), line, font=font)
            if left < 0 or top < 0 or right + 1 > WIDTH or bottom + 1 > height:
                raise ValueError(f"linha {number + 1} ultrapassa a área de {WIDTH}x{height} pixels (incluindo sombra)")
        if line_y >= height:
            raise ValueError(f"ultrapassa a altura de {height} pixels")
        draw.text((x, line_y), line, font=font, fill=1)

    pixels = mask.load()

    shadow_points: list[tuple[int, int]] = []
    for py in range(height):
        for px in range(WIDTH):
            if pixels[px, py]:
                sx, sy = px + 1, py + 1
                if sx < WIDTH and sy < height:
                    shadow_points.append((sx, sy))
    for px, py in shadow_points:
        indices[py * WIDTH + px] = color_shadow

    for py in range(height):
        for px in range(WIDTH):
            if pixels[px, py]:
                indices[py * WIDTH + px] = color_main

    return lines


def indices_to_rgb(indices: list[int], height: int = VIEW_HEIGHT, palette=None) -> Image.Image:
    image = Image.new("RGB", (WIDTH, height), (0, 0, 0))
    palette = DISPLAY_PALETTE if palette is None else palette
    image.putdata([palette[value & 0x0F] for value in indices])
    return image


def indices_to_ocr_image(indices: list[int], crop_top: int, crop_bottom: int,
                         foreground: set[int] | None = None) -> Image.Image:
    """Cria imagem binária (preto no branco) adequada ao Tesseract."""
    height = max(1, crop_bottom - crop_top)
    image = Image.new("L", (WIDTH, height), 255)
    pixels = image.load()
    for py in range(crop_top, crop_bottom):
        for px in range(WIDTH):
            value = indices[py * WIDTH + px]
            if (value != 0 if foreground is None else value in foreground):
                pixels[px, py - crop_top] = 0
    return image.resize((WIDTH * 4, height * 4), Image.Resampling.NEAREST)


def clean_ocr_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\x0c", "").splitlines()]
    return " ".join(line for line in lines if line).strip()


def find_tesseract() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    from_path = shutil.which("tesseract")
    if from_path:
        candidates.insert(0, Path(from_path))
    return next((candidate for candidate in candidates if candidate.exists()), None)


def run_tesseract(image: Image.Image, page_mode: int) -> str:
    executable = find_tesseract()
    if executable is None:
        raise FileNotFoundError(
            "Tesseract não encontrado. Instale-o em C:\\Program Files\\Tesseract-OCR."
        )
    with tempfile.TemporaryDirectory(prefix="koudelka_tx4_ocr_") as temp_dir:
        image_path = Path(temp_dir) / "ocr.png"
        image.save(image_path)
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        completed = subprocess.run(
            [str(executable), str(image_path), "stdout", "-l", "eng", "--psm", str(page_mode)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Falha desconhecida no Tesseract.")
        return clean_ocr_text(completed.stdout)


class TX4Project:
    def __init__(self) -> None:
        self.tx4_path: Path | None = None
        self.data = bytearray()
        self.entries: list[Entry] = []
        self.blocks: list[TX4Block] = []
        self.profile = "items"
        self.preview_background = None

    @property
    def is_menuhelp(self) -> bool:
        return self.profile == "menuhelp"

    @property
    def view_height(self) -> int:
        return HELP_VIEW_HEIGHT if self.is_menuhelp else VIEW_HEIGHT

    def max_lines(self, entry: Entry) -> int:
        return HELP_MAX_LINES if self.is_menuhelp else (DOCUMENT_MAX_LINES if entry.is_document else ITEM_MAX_LINES)

    def measure(self, text: str, font: ImageFont.FreeTypeFont) -> tuple[list[str], int]:
        return measure_translation(text, font, HELP_MAX_WIDTH if self.is_menuhelp else TEXT_MAX_X - TEXT_X)

    def help_colors(self, block: int) -> tuple[int, int, int]:
        palette = self.blocks[block - 1].palette
        main = 0 if palette[0] == 0xFFFF else 3
        return main, 1, 2

    def display_palette(self, block: int):
        # A previa deve decodificar a CLUT real, inclusive para os itens.
        # DISPLAY_PALETTE era apenas uma paleta ilustrativa: nao era gravada no TX4.
        palette = []
        for word in self.blocks[block - 1].palette:
            rgb = []
            for shift in (0, 5, 10):
                value = (word >> shift) & 31
                rgb.append((value << 3) | (value >> 2))
            palette.append(tuple(rgb))
        return palette

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    def load_tx4(self, path: Path) -> None:
        data = bytearray(path.read_bytes())
        if not data.startswith(b'TX41'):
            raise ValueError('Cabeçalho TX41 de Koudelka não encontrado. Use o TX4 original.')
        blocks = []
        cursor = 0
        while cursor < len(data):
            offset = data.find(b'TX41', cursor)
            if offset < 0:
                break
            if offset + IMAGE_DATA_OFFSET > len(data):
                raise ValueError(f'Cabeçalho incompleto em 0x{offset:X}.')
            size, width, height, depth = struct.unpack_from('<IHHB', data, offset + 4)
            if depth != 4 or (width, height) not in {(256, 128), (256, 256)}:
                raise ValueError(f'Layout TX4 não suportado em 0x{offset:X}: {width}x{height}, {depth}bpp.')
            if size != IMAGE_DATA_OFFSET + width * height // 2 or offset + size > len(data):
                raise ValueError(f'Bloco TX4 truncado ou tamanho inconsistente em 0x{offset:X}.')
            palette = struct.unpack_from('<16H', data, offset + 16)
            blocks.append(TX4Block(offset, size, width, height, palette))
            cursor = offset + size
        if len({block.height for block in blocks}) != 1:
            raise ValueError('O arquivo mistura layouts de textura; edição cancelada por segurança.')
        profile = 'menuhelp' if blocks[0].height == 256 else 'items'
        if profile == 'menuhelp':
            for block in blocks:
                main = 0 if block.palette[0] == 0xFFFF else 3
                if block.palette[main] != 0xFFFF or block.palette[1] != 0xB18C or block.palette[2] != 0:
                    raise ValueError('Paleta de ajuda não reconhecida. Use um MENUHELP.TX4 original.')
                tail = data[block.pixel_offset + WIDTH * HELP_VIEW_HEIGHT // 2:block.offset + block.size]
                if any(value != main * 17 for value in tail):
                    raise ValueError('O preenchimento das páginas de ajuda não corresponde ao layout conhecido. '
                                     'Reabra o MENUHELP.TX4 original, não uma saída da versão antiga.')
        self.tx4_path = path.resolve()
        self.data = data
        self.blocks = blocks
        self.profile = profile
        names = ({i+1: f'AJUDA_{name}' for i, name in enumerate(HELP_NAMES)} if self.is_menuhelp
                 else self._load_names_from_neighbor(path.parent / "ITMTBL.ITM"))
        self.entries = [
            Entry(number, names.get(number, f"BLOCK_{number}"))
            for number in range(1, self.block_count + 1)
        ]

    def _load_names_from_neighbor(self, path: Path) -> dict[int, str]:
        if not path.exists():
            return {}
        raw = path.read_bytes()
        names: dict[int, str] = {}
        for index in range(min(140, len(raw) // 160)):
            start = 0x2A + index * 160
            value = raw[start : start + 16].split(b"\0", 1)[0]
            name = value.decode("ascii", errors="replace").strip()
            if name:
                names[index + 1] = name
        return names

    def entry(self, block: int) -> Entry:
        return self.entries[block - 1]

    def block_indices(self, block: int) -> list[int]:
        if block < 1 or block > self.block_count:
            raise IndexError(block)
        info = self.blocks[block - 1]
        raw = bytes(self.data[info.pixel_offset : info.offset + info.size])
        indices, _height = decode_4bpp(raw)
        visible = indices[: WIDTH * self.view_height]
        if len(visible) != WIDTH * self.view_height:
            raise ValueError(f"Bloco {block} não contém a área visível esperada.")
        return visible

    def original_image(self, block: int) -> Image.Image:
        return self.present_indices(self.block_indices(block), block)

    def present_indices(self, indices, block):
        palette = list(self.display_palette(block))
        if self.preview_background is not None:
            for index, word in enumerate(self.blocks[block-1].palette):
                if word == 0:
                    palette[index] = self.preview_background
        return indices_to_rgb(indices, self.view_height, palette)

    def rendered_indices(
        self,
        entry: Entry,
        font: ImageFont.FreeTypeFont,
    ) -> tuple[list[int], list[str]]:
        indices = self.block_indices(entry.block)
        translation = entry.translation.strip()
        if not translation or entry.translation_status == "SEM_TEXTO":
            return indices, []

        if self.is_menuhelp:
            main, shadow, background = self.help_colors(entry.block)
            indices = [background] * (WIDTH * self.view_height)
            lines = draw_ttf_to_indices(indices, translation, y=0, font=font,
                        max_lines=HELP_MAX_LINES, line_height=HELP_LINE_HEIGHT,
                        height=self.view_height, max_width=HELP_MAX_WIDTH,
                        centered=True, color_main=main, color_shadow=shadow)
        elif entry.is_document:
            for pos in range(WIDTH * VIEW_HEIGHT):
                indices[pos] = 0
            lines = draw_ttf_to_indices(
                indices,
                translation,
                y=0,
                font=font,
                max_lines=DOCUMENT_MAX_LINES,
            )
        else:
            for py in range(ITEM_BODY_Y, VIEW_HEIGHT):
                base = py * WIDTH
                for px in range(WIDTH):
                    indices[base + px] = 0
            lines = draw_ttf_to_indices(
                indices,
                translation,
                y=ITEM_BODY_Y,
                font=font,
                max_lines=ITEM_MAX_LINES,
            )
        return indices, lines

    def preview_image(self, entry: Entry, font: ImageFont.FreeTypeFont) -> Image.Image:
        indices, _lines = self.rendered_indices(entry, font)
        return self.present_indices(indices, entry.block)

    def validate(self, font: ImageFont.FreeTypeFont) -> list[str]:
        errors: list[str] = []
        for entry in self.entries:
            if not entry.translation.strip() or entry.translation_status == "SEM_TEXTO":
                continue
            try:
                self.rendered_indices(entry, font)
            except ValueError as exc:
                errors.append(f"Bloco {entry.block} ({entry.original_name}): {exc}")
        return errors

    def generate(self, output: Path, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
        if self.tx4_path is None:
            raise ValueError('Abra primeiro um TX4.')
        if output.resolve() == self.tx4_path.resolve() or (output.exists() and output.samefile(self.tx4_path)):
            raise ValueError('O TX4 original está protegido. Escolha outro arquivo de saída.')
        if self.tx4_path.read_bytes() != self.data:
            raise ValueError('O TX4 de origem mudou após a abertura. Reabra-o antes de gerar.')
        errors = self.validate(font)
        if errors:
            preview = "\n".join(errors[:15])
            if len(errors) > 15:
                preview += f"\n... e mais {len(errors) - 15} erro(s)."
            raise ValueError(preview)

        rebuilt = bytearray(self.data)
        changed = 0
        for entry in self.entries:
            if not entry.translation.strip() or entry.translation_status == "SEM_TEXTO":
                continue
            indices, _lines = self.rendered_indices(entry, font)
            encoded = encode_4bpp(indices)
            info = self.blocks[entry.block - 1]
            rebuilt[info.pixel_offset : info.pixel_offset + len(encoded)] = encoded
            changed += 1

        if len(rebuilt) != len(self.data):
            raise RuntimeError("O tamanho do TX4 mudou durante a geração.")
        output.write_bytes(rebuilt)
        return changed, len(rebuilt)

    def import_csv(self, path: Path) -> int:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        # Valide o CSV completo antes de aplicar qualquer linha. A versao antiga
        # interpretava MENUHELP como 17 blocos falsos; nao reassociar silenciosamente.
        for row in rows:
            profile = (row.get('tx4_profile') or '').strip()
            if profile and profile != self.profile:
                raise ValueError(f'CSV do perfil {profile}, mas o TX4 aberto é {self.profile}.')
            try:
                number = int((row.get('block') or row.get('id') or '').strip())
            except (TypeError, ValueError):
                continue
            if self.is_menuhelp and not 1 <= number <= self.block_count:
                raise ValueError(f'O CSV contém o bloco {number}, mas MENUHELP tem {self.block_count} páginas. '
                                 'CSV da leitura antiga incorreta não pode ser reassociado automaticamente.')
            position = (row.get('block_offset') or '').strip()
            if position and 1 <= number <= self.block_count:
                if int(position, 0) != self.blocks[number - 1].offset:
                    raise ValueError(f'O endereço do bloco {number} no CSV não corresponde ao TX4 aberto.')
        imported = 0
        for row in rows:
            try:
                block = int((row.get("block") or row.get("id") or "").strip())
            except (TypeError, ValueError):
                continue
            if block < 1 or block > self.block_count:
                continue
            entry = self.entry(block)
            entry.original_name = (
                row.get("original_name")
                or row.get("name")
                or row.get("filename")
                or entry.original_name
            ).strip()
            entry.title_ocr = (row.get("title_ocr") or row.get("title_original") or "").strip()
            entry.original_text = (
                row.get("description_original_ocr")
                or row.get("original_text")
                or row.get("description_original")
                or ""
            ).strip()
            entry.translation = (
                row.get("description_pt")
                or row.get("translation_pt")
                or row.get("translation")
                or ""
            ).strip()
            imported_status = (row.get("translation_status") or "").strip().upper()
            if imported_status in {"TRADUZIDO", "PENDENTE", "SEM_TEXTO"}:
                entry.translation_status = imported_status
            elif entry.translation:
                entry.translation_status = "TRADUZIDO"
            elif (row.get("status") or "").strip().upper() == "SEM_TEXTO":
                entry.translation_status = "SEM_TEXTO"
            else:
                entry.translation_status = "PENDENTE"
            imported += 1
        return imported

    def save_csv(self, path: Path) -> None:
        fieldnames = [
            "block",
            "original_name",
            "title_ocr",
            "description_original_ocr",
            "description_pt",
            "status",
            "translation_status",
            "tx4_profile",
            "block_offset",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for entry in self.entries:
                writer.writerow(
                    {
                        "block": entry.block,
                        "original_name": entry.original_name,
                        "title_ocr": entry.title_ocr.replace("\n", "\\n"),
                        "description_original_ocr": entry.original_text.replace("\n", "\\n"),
                        "description_pt": entry.translation.replace("\n", "\\n"),
                        "status": "OK" if entry.translation_status != "PENDENTE" else "REVISAR",
                        "translation_status": entry.translation_status,
                        "tx4_profile": self.profile,
                        "block_offset": hex(self.blocks[entry.block - 1].offset),
                    }
                )

    def ocr_block(self, block: int) -> tuple[str, str]:
        entry = self.entry(block)
        indices = self.block_indices(block)
        if self.is_menuhelp:
            main, _shadow, _background = self.help_colors(block)
            full = indices_to_ocr_image(indices, 0, self.view_height, foreground={main})
            return "", run_tesseract(full, 6)
        if entry.is_document:
            full = indices_to_ocr_image(indices, 0, VIEW_HEIGHT)
            return "", run_tesseract(full, 6)
        title = indices_to_ocr_image(indices, 0, ITEM_BODY_Y)
        description = indices_to_ocr_image(indices, ITEM_BODY_Y, VIEW_HEIGHT)
        return run_tesseract(title, 7), run_tesseract(description, 6)


class TranslatorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1280x820")
        self.root.minsize(1000, 660)

        self.project = TX4Project()
        self.current_block: int | None = None
        self.csv_path: Path | None = None
        self.font_path = DEFAULT_ARIAL
        self.font = load_font(self.font_path)
        self.dirty = False
        self.preview_job: str | None = None
        self.original_photo: ImageTk.PhotoImage | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.original_pil: Image.Image | None = None
        self.preview_pil: Image.Image | None = None
        self.image_zoom_var = tk.StringVar(value='Ajustar')
        self.light_background_var = tk.BooleanVar(value=False)
        self.ocr_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.ocr_running = False

        self._build_ui()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Abrir TX4", command=self.open_tx4).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Importar CSV", command=self.import_csv).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Salvar CSV", command=self.save_csv).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Gerar TX4", command=self.generate_tx4).pack(side=tk.LEFT, padx=(12, 2))
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(toolbar, text="OCR selecionado", command=self.ocr_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="OCR de todos", command=self.ocr_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Escolher Arial", command=self.choose_font).pack(side=tk.LEFT, padx=(12, 2))

        self.progress = ttk.Progressbar(toolbar, mode="determinate", length=170)
        self.progress.pack(side=tk.RIGHT, padx=4)

        info = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        info.pack(fill=tk.X)
        self.file_label = ttk.Label(info, text="Nenhum TX4 aberto")
        self.file_label.pack(anchor=tk.W)
        self.rules_label = ttk.Label(
            info,
            text="Arial 11 px • altura 15 • itens: 6 linhas • documentos: 8 linhas",
        )
        self.rules_label.pack(anchor=tk.W)

        panes = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(panes, padding=4)
        center = ttk.Frame(panes, padding=4)
        right = ttk.Frame(panes, padding=4)
        panes.add(left, weight=1)
        panes.add(center, weight=2)
        panes.add(right, weight=2)

        ttk.Label(left, text="Pesquisar bloco ou nome:").pack(anchor=tk.W)
        self.search_var = tk.StringVar()
        search = ttk.Entry(left, textvariable=self.search_var)
        search.pack(fill=tk.X, pady=(2, 6))
        self.search_var.trace_add("write", lambda *_args: self.refresh_tree())

        self.tree = ttk.Treeview(
            left,
            columns=("block", "name", "status"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("block", text="#")
        self.tree.heading("name", text="Nome")
        self.tree.heading("status", text="Estado")
        self.tree.column("block", width=45, anchor=tk.CENTER, stretch=False)
        self.tree.column("name", width=170)
        self.tree.column("status", width=85, anchor=tk.CENTER, stretch=False)
        tree_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.tag_configure("translated", foreground="#187a32")
        self.tree.tag_configure("pending", foreground="#a05a00")
        self.tree.tag_configure("empty", foreground="#777777")

        zoom_row = ttk.Frame(center)
        zoom_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(zoom_row, text='Zoom das páginas:').pack(side=tk.LEFT)
        zoom = ttk.Combobox(zoom_row, textvariable=self.image_zoom_var,
                           values=('Ajustar', '1x', '2x', '3x'), state='readonly', width=8)
        zoom.pack(side=tk.LEFT, padx=5)
        zoom.bind('<<ComboboxSelected>>', lambda event: self.redraw_previews())
        ttk.Checkbutton(center, text='Fundo claro (somente na prévia)', variable=self.light_background_var,
                        command=self.change_preview_background).pack(anchor=tk.W, pady=(0, 4))
        original_frame = ttk.LabelFrame(center, text="Original no TX4", padding=8)
        original_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.original_canvas = self.make_image_view(original_frame)

        preview_frame = ttk.LabelFrame(center, text="Prévia Arial no TX4", padding=8)
        preview_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas = self.make_image_view(preview_frame)

        meta = ttk.LabelFrame(right, text="Bloco selecionado", padding=8)
        meta.pack(fill=tk.X)
        self.block_label = ttk.Label(meta, text="Bloco: —", font=("Segoe UI", 11, "bold"))
        self.block_label.grid(row=0, column=0, sticky=tk.W)
        self.type_label = ttk.Label(meta, text="")
        self.type_label.grid(row=0, column=1, sticky=tk.E)
        self.color_label = ttk.Label(meta, text='', wraplength=390, foreground='#555555')
        self.color_label.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
        meta.columnconfigure(0, weight=1)
        meta.columnconfigure(1, weight=1)

        ttk.Label(right, text="Título reconhecido (somente referência):").pack(anchor=tk.W, pady=(10, 2))
        self.title_var = tk.StringVar()
        title_entry = ttk.Entry(right, textvariable=self.title_var)
        title_entry.pack(fill=tk.X)
        title_entry.bind("<KeyRelease>", self.on_editor_change)

        ttk.Label(right, text="Texto original/OCR:").pack(anchor=tk.W, pady=(10, 2))
        self.original_text = tk.Text(right, height=7, width=38, wrap=tk.WORD, undo=True)
        self.original_text.pack(fill=tk.X)
        self.original_text.bind("<<Modified>>", self.on_text_modified)

        ttk.Label(right, text="Tradução PT-BR:").pack(anchor=tk.W, pady=(10, 2))
        self.translation_text = tk.Text(right, height=10, width=38, wrap=tk.WORD, undo=True)
        self.translation_text.pack(fill=tk.BOTH, expand=True)
        self.translation_text.bind("<<Modified>>", self.on_text_modified)

        controls = ttk.Frame(right)
        controls.pack(fill=tk.X, pady=(8, 2))
        ttk.Label(controls, text="Estado:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="PENDENTE")
        status_combo = ttk.Combobox(
            controls,
            textvariable=self.status_var,
            values=("PENDENTE", "TRADUZIDO", "SEM_TEXTO"),
            state="readonly",
            width=14,
        )
        status_combo.pack(side=tk.LEFT, padx=6)
        status_combo.bind("<<ComboboxSelected>>", self.on_editor_change)
        ttk.Button(controls, text="Aplicar", command=self.apply_current).pack(side=tk.RIGHT)

        self.validation_label = ttk.Label(right, text="", wraplength=440)
        self.validation_label.pack(fill=tk.X, pady=(5, 2))
        self.rule_note = ttk.Label(
            right,
            text=(
                "Blocos 1–114 preservam o título original e substituem apenas a descrição. "
                "Blocos 115–230 são limpos por inteiro antes da tradução."
            ),
            wraplength=440,
            foreground="#555555",
        )
        self.rule_note.pack(fill=tk.X, pady=(4, 0))
        # Reserve a validacao e os controles antes de distribuir espaco ao editor.
        # O campo de texto pode rolar; o aviso de excesso nao deve ficar escondido.
        self.rule_note.pack_configure(side=tk.BOTTOM, before=self.translation_text)
        self.validation_label.pack_configure(side=tk.BOTTOM, before=self.translation_text)
        controls.pack_configure(side=tk.BOTTOM, before=self.translation_text)
        right.bind('<Configure>', lambda event: self.resize_editor_notes(event.width))

        self.status_bar = ttk.Label(self.root, text="Pronto.", relief=tk.SUNKEN, anchor=tk.W, padding=5)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def resize_editor_notes(self, width):
        self.validation_label.configure(wraplength=max(120, width-12))
        self.rule_note.configure(wraplength=max(120, width-12))
        self.color_label.configure(wraplength=max(120, width-28))

    def change_preview_background(self):
        self.project.preview_background = (232, 213, 179) if self.light_background_var.get() else None
        self.update_images()

    def make_image_view(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        canvas = tk.Canvas(parent, width=280, height=190, background='#222222', highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        sx = ttk.Scrollbar(parent, orient='horizontal', command=canvas.xview)
        sy = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        sx.grid(row=1, column=0, sticky='ew')
        sy.grid(row=0, column=1, sticky='ns')
        canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        canvas.bind('<Configure>', lambda event: self.redraw_previews())
        return canvas

    def redraw_previews(self):
        for attr, canvas, image in (
                ('original_photo', self.original_canvas, self.original_pil),
                ('preview_photo', self.preview_canvas, self.preview_pil)):
            canvas.delete('all')
            if image is None:
                continue
            cw, ch = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
            zoom = self.image_zoom_var.get()
            scale = min(cw/image.width, ch/image.height, 4) if zoom == 'Ajustar' else int(zoom[0])
            size = (max(1, round(image.width*scale)), max(1, round(image.height*scale)))
            photo = ImageTk.PhotoImage(image.resize(size, Image.Resampling.NEAREST))
            setattr(self, attr, photo)
            canvas.create_image(max(0, (cw-size[0])//2), max(0, (ch-size[1])//2), image=photo, anchor='nw')
            canvas.configure(scrollregion=(0, 0, max(cw,size[0]), max(ch,size[1])))

    def update_rules(self):
        if self.project.is_menuhelp:
            self.rules_label.configure(text=f'{self.font_path.name} 11 px • ajuda: 14 linhas, passo 13 px • área útil 256×190 (textura 256×256)')
            self.rule_note.configure(text='AJUDA: traduza a página completa, incluindo títulos. '
                                     'A página útil é substituída desde Y=0; as 66 linhas finais de preenchimento são preservadas. '
                                     'Texto centralizado, com as cores nativas. Quebras manuais são respeitadas.')
        else:
            self.rules_label.configure(text=f'{self.font_path.name} 11 px • altura 15 • itens: 6 linhas • documentos: 8 linhas')
            self.rule_note.configure(text='Blocos 1–114 preservam o título original e substituem apenas a descrição. '
                                     'Blocos 115–230 são limpos por inteiro antes da tradução. '
                                     'A prévia usa a paleta real; a mistura de cores e a iluminação do jogo não são simuladas.')

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.open_tx4())
        self.root.bind("<Control-s>", lambda _event: self.save_csv())
        self.root.bind("<Control-g>", lambda _event: self.generate_tx4())
        self.root.bind("<Control-Down>", lambda _event: self.move_selection(1))
        self.root.bind("<Control-Up>", lambda _event: self.move_selection(-1))

    def set_status(self, text: str) -> None:
        self.status_bar.configure(text=text)
        self.root.update_idletasks()

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno(
            "Alterações não salvas",
            "Há alterações ainda não salvas no CSV. Deseja continuar mesmo assim?",
        )

    def open_tx4(self, path: Path | None = None) -> None:
        if not self.confirm_discard():
            return
        if path is None:
            selected = filedialog.askopenfilename(
                title="Abrir TX4 de itens ou MENUHELP.TX4",
                filetypes=(("Koudelka TX4", "*.TX4"), ("Todos os arquivos", "*.*")),
            )
            if not selected:
                return
            path = Path(selected)
        try:
            self.project.load_tx4(path)
        except Exception as exc:
            messagebox.showerror("TX4 inválido", str(exc))
            return

        self.csv_path = None
        self.current_block = None
        self.dirty = False
        black_font = not self.project.is_menuhelp and self.project.display_palette(1)[COLOR_MAIN] == (0, 0, 0)
        self.light_background_var.set(black_font)
        self.project.preview_background = (232, 213, 179) if black_font else None
        self.file_label.configure(
            text=f"{path} • {len(self.project.data):,} bytes • {self.project.block_count} blocos"
        )
        self.update_rules()
        self.refresh_tree()
        if not self.project.is_menuhelp and self.project.block_count != EXPECTED_BLOCKS:
            messagebox.showwarning(
                "Quantidade diferente",
                f"Foram encontrados {self.project.block_count} blocos; o 001.TX4 conhecido possui 230.",
            )
        self.select_block(1)
        self.set_status(f"TX4 aberto: {path.name}")

    def choose_font(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar Arial TTF",
            initialdir=str(DEFAULT_ARIAL.parent),
            filetypes=(("Fonte TrueType", "*.ttf"), ("Todos os arquivos", "*.*")),
        )
        if not selected:
            return
        try:
            new_font = load_font(Path(selected))
        except Exception as exc:
            messagebox.showerror("Fonte inválida", str(exc))
            return
        self.font_path = Path(selected)
        self.font = new_font
        self.update_rules()
        self.update_preview()

    def import_csv(self, path: Path | None = None) -> None:
        if not self.project.data:
            messagebox.showinfo("Abra o TX4", "Abra primeiro o TX4 original de itens ou de ajuda.")
            return
        self.apply_current()
        if path is None:
            selected = filedialog.askopenfilename(
                title="Importar CSV de tradução",
                initialdir=str(self.project.tx4_path.parent if self.project.tx4_path else Path.cwd()),
                filetypes=(("CSV", "*.csv"), ("Todos os arquivos", "*.*")),
            )
            if not selected:
                return
            path = Path(selected)
        try:
            imported = self.project.import_csv(path)
        except Exception as exc:
            messagebox.showerror("Falha ao importar CSV", str(exc))
            return
        self.csv_path = path
        self.dirty = False
        self.refresh_tree()
        self.select_block(self.current_block or 1)
        self.set_status(f"CSV importado: {path.name} ({imported} registros)")

    def save_csv(self, save_as: bool = False) -> None:
        if not self.project.data:
            messagebox.showinfo("Nada para salvar", "Abra primeiro o TX4 original de itens ou de ajuda.")
            return
        self.apply_current()
        path = None if save_as else self.csv_path
        if path is None:
            default_name = ('MENUHELP_TRADUCAO_GUI.csv' if self.project.is_menuhelp else 'koudelka_230_TRADUCAO_GUI.csv')
            selected = filedialog.asksaveasfilename(
                title="Salvar projeto de tradução",
                initialdir=str(self.project.tx4_path.parent if self.project.tx4_path else Path.cwd()),
                initialfile=default_name,
                defaultextension=".csv",
                filetypes=(("CSV", "*.csv"),),
            )
            if not selected:
                return
            path = Path(selected)
        try:
            self.project.save_csv(path)
        except Exception as exc:
            messagebox.showerror("Falha ao salvar CSV", str(exc))
            return
        self.csv_path = path
        self.dirty = False
        self.set_status(f"Projeto salvo: {path}")

    def generate_tx4(self) -> None:
        if not self.project.data:
            messagebox.showinfo("Abra o TX4", "Abra primeiro o TX4 original de itens ou de ajuda.")
            return
        self.apply_current()
        try:
            errors = self.project.validate(self.font)
        except Exception as exc:
            messagebox.showerror("Erro de validação", str(exc))
            return
        if errors:
            preview = "\n".join(errors[:15])
            if len(errors) > 15:
                preview += f"\n... e mais {len(errors) - 15} erro(s)."
            messagebox.showerror(
                "Traduções não cabem",
                "O TX4 não foi gerado. Corrija estas entradas:\n\n" + preview,
            )
            return

        original = self.project.tx4_path
        assert original is not None
        selected = filedialog.asksaveasfilename(
            title="Gerar TX4 traduzido",
            initialdir=str(original.parent),
            initialfile=f"{original.stem}_TRADUZIDO_ARIAL.TX4",
            defaultextension=".TX4",
            filetypes=(("Koudelka TX4", "*.TX4"),),
        )
        if not selected:
            return
        output = Path(selected)
        if output.resolve() == original.resolve():
            messagebox.showerror(
                "Arquivo original protegido",
                "Escolha outro nome. A interface não sobrescreve o TX4 original.",
            )
            return
        try:
            changed, size = self.project.generate(output, self.font)
        except Exception as exc:
            messagebox.showerror("Falha ao gerar TX4", str(exc))
            return
        messagebox.showinfo(
            "TX4 gerado",
            f"Arquivo: {output}\nBlocos renderizados: {changed}\nTamanho: {size:,} bytes\n\n"
            "O cabeçalho/CLUT dos blocos foi preservado.",
        )
        self.set_status(f"TX4 gerado: {output.name} • {changed} blocos • {size:,} bytes")

    def refresh_tree(self) -> None:
        selected = self.current_block
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().strip().lower()
        for entry in self.project.entries:
            haystack = f"{entry.block} {entry.original_name}".lower()
            if query and query not in haystack:
                continue
            status = entry.translation_status
            tag = "translated" if status == "TRADUZIDO" else "empty" if status == "SEM_TEXTO" else "pending"
            self.tree.insert(
                "",
                tk.END,
                iid=str(entry.block),
                values=(entry.block, entry.original_name, status),
                tags=(tag,),
            )
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))

    def on_tree_select(self, _event: object = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        block = int(selection[0])
        if block == self.current_block:
            return
        self.apply_current(refresh=False)
        self.load_entry(block)

    def select_block(self, block: int) -> None:
        iid = str(block)
        if not self.tree.exists(iid):
            self.search_var.set("")
            self.refresh_tree()
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self.load_entry(block)

    def move_selection(self, delta: int) -> None:
        if not self.project.entries:
            return
        self.apply_current(refresh=False)
        current = self.current_block or 1
        self.select_block(max(1, min(self.project.block_count, current + delta)))

    def load_entry(self, block: int) -> None:
        self.current_block = block
        entry = self.project.entry(block)
        self.block_label.configure(text=f"Bloco {entry.block:03d} — {entry.original_name}")
        self.type_label.configure(text='AJUDA (14 linhas)' if self.project.is_menuhelp
                                   else ("DOCUMENTO (8 linhas)" if entry.is_document else "ITEM (6 linhas)"))
        color_index = self.project.help_colors(block)[0] if self.project.is_menuhelp else COLOR_MAIN
        rgb = self.project.display_palette(block)[color_index]
        word = self.project.blocks[block-1].palette[color_index]
        native = '#{:02X}{:02X}{:02X}'.format(*rgb)
        flag = 'semitransparência habilitada no pixel' if word & 0x8000 else 'cor opaca'
        if word == 0:
            flag = 'cor totalmente transparente'
        self.color_label.configure(text=f'Fonte no TX4: {native} • {flag}')
        self.title_var.set(entry.title_ocr)
        self._set_text(self.original_text, normalize_manual_breaks(entry.original_text))
        self._set_text(self.translation_text, normalize_manual_breaks(entry.translation))
        self.status_var.set(entry.translation_status)
        self.update_images()

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.edit_modified(False)

    def apply_current(self, refresh: bool = True) -> None:
        if self.current_block is None or not self.project.entries:
            return
        entry = self.project.entry(self.current_block)
        new_title = self.title_var.get().strip()
        new_original = self.original_text.get("1.0", "end-1c").strip()
        new_translation = self.translation_text.get("1.0", "end-1c").strip()
        new_status = self.status_var.get().strip().upper() or "PENDENTE"
        if new_translation and new_status == "PENDENTE":
            new_status = "TRADUZIDO"
            self.status_var.set(new_status)
        changed = (
            entry.title_ocr != new_title
            or entry.original_text != new_original
            or entry.translation != new_translation
            or entry.translation_status != new_status
        )
        entry.title_ocr = new_title
        entry.original_text = new_original
        entry.translation = new_translation
        entry.translation_status = new_status
        if changed:
            self.dirty = True
            if refresh:
                self.refresh_tree()
        self.update_preview()

    def on_editor_change(self, _event: object = None) -> None:
        self.schedule_preview()

    def on_text_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if widget.edit_modified():
            widget.edit_modified(False)
            self.schedule_preview()

    def schedule_preview(self) -> None:
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(250, self.apply_current)

    def update_images(self) -> None:
        if self.current_block is None:
            return
        self.original_pil = self.project.original_image(self.current_block)
        self.update_preview()

    def update_preview(self) -> None:
        self.preview_job = None
        if self.current_block is None:
            return
        entry = self.project.entry(self.current_block)
        translation = self.translation_text.get("1.0", "end-1c").strip()
        status = self.status_var.get().strip().upper() or "PENDENTE"
        temporary = Entry(
            block=entry.block,
            original_name=entry.original_name,
            title_ocr=entry.title_ocr,
            original_text=entry.original_text,
            translation=translation,
            translation_status=status,
        )
        try:
            preview = self.project.preview_image(temporary, self.font)
            lines, widest = self.project.measure(translation, self.font) if translation else ([], 0)
            max_lines = self.project.max_lines(temporary)
            if status == 'SEM_TEXTO':
                self.validation_label.configure(text='Estado SEM_TEXTO: o bloco original será mantido.', foreground='#555555')
            elif translation:
                self.validation_label.configure(
                    text=f"Prévia válida: {len(lines)}/{max_lines} linhas • maior linha: {widest}px",
                    foreground="#187a32" if len(lines) <= max_lines else "#b00020",
                )
            else:
                self.validation_label.configure(text="Sem tradução: o bloco original será mantido.", foreground="#555555")
        except ValueError as exc:
            preview = self.project.original_image(temporary.block)
            self.validation_label.configure(text=f"ERRO: {exc}", foreground="#b00020")
        self.preview_pil = preview
        self.redraw_previews()

    def ocr_selected(self) -> None:
        if self.current_block is None:
            messagebox.showinfo("Abra o TX4", "Selecione primeiro um bloco.")
            return
        if self.ocr_running:
            return
        block = self.current_block
        self.ocr_running = True
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self.set_status(f"Executando OCR no bloco {block}...")

        def worker() -> None:
            try:
                result = self.project.ocr_block(block)
                self.ocr_queue.put(("selected_ok", (block, result)))
            except Exception as exc:
                self.ocr_queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self.poll_ocr_queue)

    def ocr_all(self) -> None:
        if not self.project.entries:
            messagebox.showinfo("Abra o TX4", "Abra primeiro o TX4 original de itens ou de ajuda.")
            return
        if self.ocr_running:
            return
        if find_tesseract() is None:
            messagebox.showerror(
                "Tesseract não encontrado",
                r"Instale o Tesseract em C:\Program Files\Tesseract-OCR antes de usar OCR.",
            )
            return
        if not messagebox.askyesno(
            "OCR de todos os blocos",
            f"O OCR dos {self.project.block_count} blocos pode demorar vários minutos. Deseja continuar?",
        ):
            return
        self.apply_current()
        self.ocr_running = True
        self.progress.configure(mode="determinate", maximum=self.project.block_count, value=0)
        self.set_status("Iniciando OCR em massa...")

        def worker() -> None:
            try:
                for number in range(1, self.project.block_count + 1):
                    title, description = self.project.ocr_block(number)
                    self.ocr_queue.put(("all_item", (number, title, description)))
                self.ocr_queue.put(("all_done", None))
            except Exception as exc:
                self.ocr_queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self.poll_ocr_queue)

    def poll_ocr_queue(self) -> None:
        keep_polling = self.ocr_running
        try:
            while True:
                event, payload = self.ocr_queue.get_nowait()
                if event == "selected_ok":
                    block, result = payload  # type: ignore[misc]
                    title, description = result
                    entry = self.project.entry(block)
                    entry.title_ocr = title
                    entry.original_text = description
                    self.dirty = True
                    if self.current_block == block:
                        self.load_entry(block)
                    self.set_status(f"OCR concluído no bloco {block}.")
                    self._finish_ocr()
                    keep_polling = False
                elif event == "all_item":
                    block, title, description = payload  # type: ignore[misc]
                    entry = self.project.entry(block)
                    entry.title_ocr = title
                    entry.original_text = description
                    self.progress.configure(value=block)
                    self.set_status(f"OCR em massa: {block}/{self.project.block_count}")
                elif event == "all_done":
                    self.dirty = True
                    self.refresh_tree()
                    if self.current_block:
                        self.load_entry(self.current_block)
                    self.set_status("OCR em massa concluído. Revise o texto reconhecido antes de traduzir.")
                    self._finish_ocr()
                    keep_polling = False
                elif event == "error":
                    self._finish_ocr()
                    keep_polling = False
                    messagebox.showerror("Falha no OCR", str(payload))
                    self.set_status("OCR interrompido por erro.")
        except queue.Empty:
            pass
        if keep_polling:
            self.root.after(100, self.poll_ocr_queue)

    def _finish_ocr(self) -> None:
        self.ocr_running = False
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)

    def on_close(self) -> None:
        if self.confirm_discard():
            self.root.destroy()


def render_csv_headless(tx4: Path, csv_path: Path, output: Path, font_path: Path) -> None:
    project = TX4Project()
    project.load_tx4(tx4)
    imported = project.import_csv(csv_path)
    font = load_font(font_path)
    changed, size = project.generate(output, font)
    print(f"CSV importado: {imported} registros")
    print(f"Blocos renderizados: {changed}")
    print(f"Tamanho: {size} bytes")
    print(f"OK: {output}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--render-csv":
        if len(args) not in {4, 6}:
            print(
                "Uso: koudelka_tx4_tradutor_gui.py --render-csv 001.TX4 traducao.csv saida.TX4 "
                "[--font arial.ttf]",
                file=sys.stderr,
            )
            return 2
        tx4, csv_path, output = map(Path, args[1:4])
        font_path = DEFAULT_ARIAL
        if len(args) == 6:
            if args[4] != "--font":
                print("Opção desconhecida. Use --font.", file=sys.stderr)
                return 2
            font_path = Path(args[5])
        render_csv_headless(tx4, csv_path, output, font_path)
        return 0

    initial_tx4: Path | None = None
    initial_csv: Path | None = None
    if args:
        initial_tx4 = Path(args[0])
    if len(args) > 1:
        initial_csv = Path(args[1])

    root = tk.Tk()
    app = TranslatorGUI(root)
    if initial_tx4:
        root.after(100, lambda: app.open_tx4(initial_tx4))
        if initial_csv:
            root.after(250, lambda: app.import_csv(initial_csv))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
