# -*- coding: utf-8 -*-
"""
Koudelka MCF Subtitle Tool v6 - GUI FT4/TTF
================================

Ferramenta gráfica para inserir legendas PT-BR nos arquivos .MCF de Koudelka
usando a fonte nativa FONTS.FT4 ou uma fonte TTF/OTF rasterizada.

Requisitos:
    pip install pillow numpy

A v2 também extrai MCF -> CSV automaticamente.

CSV mínimo:
    id;triplet_inicio;triplet_fim;portugues

Você também pode carregar CSVs com outras colunas. Elas serão preservadas.

Quebra manual de linha:
    use o caractere | dentro do campo "portugues"

Exemplo:
    Você perdeu a cabeça?|De jeito nenhum vou rezar por você.

Configuração padrão confirmada para SC01:
    bloco MCF       = 0x2800
    região gráfica  = 0x1040
    3 segmentos     = 100 px cada
    canvas lógico   = 300 x 39
    wrap            = 68 px
    largura segura  = 286 px
    atlas FT4       = offset 0x100 (256), 256x256, 4bpp
"""

from __future__ import annotations

import csv
import os
import sys
import unicodedata
import shutil
import re
import threading
import queue
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import numpy as np
    from PIL import Image, ImageTk, ImageOps, ImageDraw, ImageFont
except ImportError:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Dependências ausentes",
        "Instale as dependências com:\n\n"
        "python -m pip install pillow numpy"
    )
    raise

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import pytesseract
except ImportError:
    pytesseract = None


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

@dataclass
class EngineConfig:
    block_size: int = 0x2800
    region_start: int = 0x1040
    segment_width: int = 100
    segment_height: int = 39
    phases: int = 3
    wrap_x: int = 68
    max_line_width: int = 286

    ft4_offset: int = 0x100
    ft4_atlas_width: int = 256
    ft4_atlas_height: int = 256

    cell_size: int = 16
    glyph_height: int = 15

    # "normalized" = método usado no teste aprovado.
    # "native_y" = preserva a coordenada Y original da célula FT4.
    baseline_mode: str = "normalized"
    normalized_baseline: int = 11

    # Renderizador visual usado ao gerar/visualizar as legendas.
    # No modo TTF limpo, somente o índice 1 (branco opaco) é gravado.
    render_mode: str = "ttf"
    ttf_font_size: int = 11
    ttf_supersample: int = 4

    @property
    def canvas_width(self) -> int:
        return self.segment_width * self.phases

    @property
    def canvas_height(self) -> int:
        return self.segment_height

    @property
    def region_len(self) -> int:
        # 4bpp = 2 pixels por byte
        return (self.segment_width * self.segment_height) // 2

    @property
    def inverse_wrap(self) -> int:
        return self.segment_width - self.wrap_x


@dataclass
class SubtitleRow:
    values: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.values.get("id", "")

    @property
    def triplet_start(self) -> int:
        return int(self.values.get("triplet_inicio", "0"))

    @triplet_start.setter
    def triplet_start(self, value: int) -> None:
        self.values["triplet_inicio"] = str(value)

    @property
    def triplet_end(self) -> int:
        return int(self.values.get("triplet_fim", "0"))

    @triplet_end.setter
    def triplet_end(self, value: int) -> None:
        self.values["triplet_fim"] = str(value)

    @property
    def original_jp(self) -> str:
        return self.values.get("original_jp", "")

    @original_jp.setter
    def original_jp(self, value: str) -> None:
        self.values["original_jp"] = value

    @property
    def text(self) -> str:
        return self.values.get("portugues", "")

    @text.setter
    def text(self, value: str) -> None:
        self.values["portugues"] = value


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class KoudelkaSubtitleEngine:
    def __init__(self, config: Optional[EngineConfig] = None):
        self.cfg = config or EngineConfig()
        self.atlas: Optional[np.ndarray] = None
        self._glyph_cache: dict[tuple[str, str], np.ndarray] = {}
        self.ttf_path: Optional[Path] = None
        self._ttf_line_cache: dict[tuple[str, str, int], np.ndarray] = {}

    @property
    def font_ready(self) -> bool:
        if self.cfg.render_mode == "ttf":
            return self.ttf_path is not None and self.ttf_path.is_file()
        return self.atlas is not None

    def load_ttf(self, path: str | Path) -> None:
        """Carrega uma fonte TrueType/OpenType para o renderizador TTF."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Fonte TTF/OTF não encontrada: {path}")

        try:
            ImageFont.truetype(str(path), self.cfg.ttf_font_size)
        except Exception as exc:
            raise ValueError(f"Fonte TTF/OTF inválida: {path}\n{exc}") from exc

        self.ttf_path = path
        self._ttf_line_cache.clear()

    # ---------------------------- FT4 -------------------------------------

    def load_ft4(self, path: str | Path) -> None:
        """
        Decodifica diretamente o FONTS.FT4.

        Formato confirmado:
          - header / início do atlas em 0x100
          - 4bpp
          - nibble baixo primeiro, depois nibble alto
          - atlas latino em 256x256
        """
        path = Path(path)
        data = path.read_bytes()

        required_pixels = (
            self.cfg.ft4_atlas_width * self.cfg.ft4_atlas_height
        )
        required_bytes = required_pixels // 2

        start = self.cfg.ft4_offset
        end = start + required_bytes

        if len(data) < end:
            raise ValueError(
                f"FONTS.FT4 pequeno demais. "
                f"Preciso de pelo menos {end} bytes."
            )

        raw = np.frombuffer(data[start:end], dtype=np.uint8)

        pixels = np.empty(raw.size * 2, dtype=np.uint8)
        pixels[0::2] = raw & 0x0F
        pixels[1::2] = raw >> 4

        self.atlas = (
            pixels.reshape(
                self.cfg.ft4_atlas_height,
                self.cfg.ft4_atlas_width,
            ) * 17
        ).astype(np.uint8)

        self._glyph_cache.clear()

    def _native_cell(self, code: int) -> np.ndarray:
        if self.atlas is None:
            raise RuntimeError("Carregue o FONTS.FT4 primeiro.")

        cell = self.cfg.cell_size
        row = (code >> 4) & 0x0F
        low = code & 0x0F

        # Ordem real das colunas descoberta no FONTS.FT4:
        # 6 7 8 9 A B C D E F 0 1 2 3 4 5
        col = (low - 6) % 16

        x = col * cell
        y = row * cell

        raw = self.atlas[
            y:y + cell,
            x:x + cell,
        ][:self.cfg.glyph_height]

        out = np.zeros(
            (self.cfg.glyph_height, cell),
            dtype=np.uint8,
        )

        # Mapeamento confirmado comparando com o teste aprovado:
        # 136 = contorno
        # 17/34 = branco
        out[raw == 136] = 1
        out[(raw == 17) | (raw == 34)] = 2

        return out

    def _ascii_glyph(self, ch: str) -> np.ndarray:
        key = (ch, self.cfg.baseline_mode)
        cached = self._glyph_cache.get(key)
        if cached is not None:
            return cached.copy()

        if ch == " ":
            glyph = np.zeros(
                (self.cfg.glyph_height, 4),
                dtype=np.uint8,
            )
            self._glyph_cache[key] = glyph
            return glyph.copy()

        cell = self._native_cell(ord(ch))

        ys, xs = np.where(cell > 0)

        if len(xs) == 0:
            glyph = np.zeros(
                (self.cfg.glyph_height, 4),
                dtype=np.uint8,
            )
            self._glyph_cache[key] = glyph
            return glyph.copy()

        # Corta apenas margens horizontais.
        cell = cell[:, xs.min():xs.max() + 1]

        if self.cfg.baseline_mode == "normalized":
            ys, _ = np.where(cell > 0)
            bottom = int(ys.max())
            shift = self.cfg.normalized_baseline - bottom

            aligned = np.zeros_like(cell)

            if shift > 0:
                aligned[shift:, :] = cell[
                    :self.cfg.glyph_height - shift,
                    :
                ]
            elif shift < 0:
                d = -shift
                aligned[
                    :self.cfg.glyph_height - d,
                    :
                ] = cell[d:, :]
            else:
                aligned[:] = cell

            cell = aligned

        # native_y: não altera a posição vertical.

        self._glyph_cache[key] = cell.copy()
        return cell.copy()

    # -------------------------- acentos -----------------------------------

    ACCENTS = {
        "á": ("a", "acute"), "é": ("e", "acute"),
        "í": ("i", "acute"), "ó": ("o", "acute"),
        "ú": ("u", "acute"),
        "Á": ("A", "acute"), "É": ("E", "acute"),
        "Í": ("I", "acute"), "Ó": ("O", "acute"),
        "Ú": ("U", "acute"),

        "ã": ("a", "tilde"), "õ": ("o", "tilde"),
        "Ã": ("A", "tilde"), "Õ": ("O", "tilde"),

        "â": ("a", "circ"), "ê": ("e", "circ"),
        "ô": ("o", "circ"),
        "Â": ("A", "circ"), "Ê": ("E", "circ"),
        "Ô": ("O", "circ"),

        "ç": ("c", "cedilla"),
        "Ç": ("C", "cedilla"),
    }

    @staticmethod
    def _add_mark(
        glyph: np.ndarray,
        points: list[tuple[int, int]],
    ) -> np.ndarray:
        g = glyph.copy()

        for x, y in points:
            if 0 <= x < g.shape[1] and 0 <= y < g.shape[0]:
                for dx, dy in [
                    (-1, 0), (1, 0),
                    (0, -1), (0, 1),
                ]:
                    nx, ny = x + dx, y + dy

                    if (
                        0 <= nx < g.shape[1]
                        and 0 <= ny < g.shape[0]
                        and g[ny, nx] == 0
                    ):
                        g[ny, nx] = 1

                g[y, x] = 2

        return g

    def _accented_glyph(self, ch: str) -> np.ndarray:
        base_ch, accent = self.ACCENTS[ch]
        base = self._ascii_glyph(base_ch)

        padded = np.zeros(
            (
                self.cfg.glyph_height,
                base.shape[1] + 2,
            ),
            dtype=np.uint8,
        )
        padded[:, 1:1 + base.shape[1]] = base
        base = padded

        ys, xs = np.where(base > 0)

        if len(xs) == 0:
            return base

        center = int((xs.min() + xs.max()) // 2)
        top = int(ys.min())
        bottom = int(ys.max())

        if accent == "acute":
            y = max(0, top - 3)
            points = [
                (center + 1, y),
                (center,     y + 1),
                (center - 1, y + 2),
            ]

        elif accent == "tilde":
            y = max(0, top - 3)
            points = [
                (center - 2, y + 1),
                (center - 1, y),
                (center,     y + 1),
                (center + 1, y),
                (center + 2, y + 1),
            ]

        elif accent == "circ":
            y = max(0, top - 3)
            points = [
                (center - 2, y + 2),
                (center - 1, y + 1),
                (center,     y),
                (center + 1, y + 1),
                (center + 2, y + 2),
            ]

        elif accent == "cedilla":
            y = min(
                self.cfg.glyph_height - 3,
                bottom + 1,
            )
            points = [
                (center,     y),
                (center + 1, y + 1),
                (center,     y + 2),
            ]

        else:
            points = []

        return self._add_mark(base, points)

    def glyph_for_char(self, ch: str) -> np.ndarray:
        if ch in self.ACCENTS:
            return self._accented_glyph(ch)

        if ch == " ":
            return self._ascii_glyph(ch)

        if ord(ch) < 128:
            return self._ascii_glyph(ch)

        decomp = unicodedata.normalize("NFD", ch)
        base = "".join(
            c for c in decomp
            if unicodedata.category(c) != "Mn"
        )

        if base:
            return self._ascii_glyph(base[0])

        return np.zeros(
            (self.cfg.glyph_height, 4),
            dtype=np.uint8,
        )

    # -------------------------- texto -------------------------------------

    def _compose_line_ttf(self, text: str) -> np.ndarray:
        """
        Renderiza a frase inteira com kerning e superamostragem.

        O modo TTF limpo não cria contorno, halo nem sombra: os pixels
        sólidos da fonte viram índice 1 (branco opaco no jogo) e todo o
        restante fica transparente. O índice 2 isolado é semitransparente
        e deixa a legenda cinza.
        """
        if self.ttf_path is None:
            raise RuntimeError("Carregue uma fonte TTF/OTF primeiro.")

        key = (text, str(self.ttf_path), self.cfg.ttf_font_size)
        cached = self._ttf_line_cache.get(key)
        if cached is not None:
            return cached.copy()

        if not text:
            return np.zeros((self.cfg.glyph_height, 1), dtype=np.uint8)

        scale = max(2, int(self.cfg.ttf_supersample))
        font = ImageFont.truetype(
            str(self.ttf_path),
            self.cfg.ttf_font_size * scale,
        )

        # Margem de segurança. O baseline fixo impede que linhas com
        # acentos ou descendentes pulem verticalmente entre legendas.
        margin = scale
        logical_width = max(
            1,
            int(np.ceil(float(font.getlength(text)) / scale)) + 2,
        )
        high_width = logical_width * scale
        high_height = self.cfg.glyph_height * scale
        baseline = min(high_height - scale, 11 * scale)

        mask_image = Image.new("L", (high_width, high_height), 0)
        draw = ImageDraw.Draw(mask_image)
        draw.text(
            (margin, baseline),
            text,
            font=font,
            fill=255,
            anchor="ls",
        )

        mask_image = mask_image.resize(
            (logical_width, self.cfg.glyph_height),
            Image.Resampling.LANCZOS,
        )
        coverage = np.asarray(mask_image, dtype=np.uint8)

        # Meio-tom ou mais vira letra sólida. Não há expansão de contorno.
        fill = coverage >= 128

        result = np.zeros_like(coverage, dtype=np.uint8)
        result[fill] = 1

        # Retira colunas vazias, preservando um pixel de margem.
        ys, xs = np.where(result > 0)
        if len(xs):
            x0 = max(0, int(xs.min()) - 1)
            x1 = min(result.shape[1], int(xs.max()) + 2)
            result = result[:, x0:x1]

        self._ttf_line_cache[key] = result.copy()
        return result

    def compose_line(self, text: str) -> np.ndarray:
        if self.cfg.render_mode == "ttf":
            return self._compose_line_ttf(text)

        glyphs = [
            self.glyph_for_char(ch)
            for ch in text
        ]

        width = sum(
            glyph.shape[1]
            for glyph in glyphs
        )

        canvas = np.zeros(
            (
                self.cfg.glyph_height,
                max(width, 1),
            ),
            dtype=np.uint8,
        )

        x = 0

        for glyph in glyphs:
            w = glyph.shape[1]

            canvas[:, x:x + w] = np.maximum(
                canvas[:, x:x + w],
                glyph,
            )

            x += w

        return canvas

    def line_width(self, text: str) -> int:
        return self.compose_line(text).shape[1]

    def split_text(self, text: str) -> Optional[list[str]]:
        """
        | força quebra manual.
        Caso contrário, tenta 1 linha e depois encontra a melhor quebra
        automática em no máximo 2 linhas.
        """
        text = text.strip()

        if "|" in text:
            parts = [
                part.strip()
                for part in text.split("|")
            ]

            if len(parts) > 2 or any(not p for p in parts):
                return None

            if any(
                self.line_width(p)
                > self.cfg.max_line_width
                for p in parts
            ):
                return None

            return parts

        if self.line_width(text) <= self.cfg.max_line_width:
            return [text]

        words = text.split()
        candidates = []

        for i in range(1, len(words)):
            line1 = " ".join(words[:i])
            line2 = " ".join(words[i:])

            w1 = self.line_width(line1)
            w2 = self.line_width(line2)

            if (
                w1 <= self.cfg.max_line_width
                and w2 <= self.cfg.max_line_width
            ):
                score = (
                    max(w1, w2)
                    + abs(w1 - w2) * 0.05
                )

                candidates.append(
                    (score, [line1, line2])
                )

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])

        return candidates[0][1]

    def validate_text(
        self,
        text: str,
    ) -> tuple[bool, str, Optional[list[str]]]:
        try:
            lines = self.split_text(text)
        except Exception as exc:
            return False, str(exc), None

        if lines is None:
            return (
                False,
                "Não cabe em até 2 linhas. "
                "Edite o texto ou use | para escolher a quebra.",
                None,
            )

        widths = [
            self.line_width(line)
            for line in lines
        ]

        description = (
            " / ".join(lines)
            + "   ["
            + ", ".join(str(w) for w in widths)
            + " px]"
        )

        return True, description, lines

    # -------------------------- render ------------------------------------

    def render_global(
        self,
        text: str,
    ) -> tuple[np.ndarray, list[str]]:
        lines = self.split_text(text)

        if lines is None:
            raise ValueError(
                "A legenda não cabe em até duas linhas "
                f"de {self.cfg.max_line_width}px."
            )

        screen = np.zeros(
            (
                self.cfg.canvas_height,
                self.cfg.canvas_width,
            ),
            dtype=np.uint8,
        )

        if len(lines) == 1:
            bitmap = self.compose_line(lines[0])

            x = (
                self.cfg.canvas_width
                - bitmap.shape[1]
            ) // 2

            y = 12

            screen[
                y:y + self.cfg.glyph_height,
                x:x + bitmap.shape[1],
            ] = np.maximum(
                screen[
                    y:y + self.cfg.glyph_height,
                    x:x + bitmap.shape[1],
                ],
                bitmap,
            )

        else:
            bitmap1 = self.compose_line(lines[0])
            bitmap2 = self.compose_line(lines[1])

            x1 = (
                self.cfg.canvas_width
                - bitmap1.shape[1]
            ) // 2

            x2 = (
                self.cfg.canvas_width
                - bitmap2.shape[1]
            ) // 2

            # Valores medidos nas legendas japonesas.
            y1 = 1
            y2 = 18

            screen[
                y1:y1 + self.cfg.glyph_height,
                x1:x1 + bitmap1.shape[1],
            ] = bitmap1

            screen[
                y2:y2 + self.cfg.glyph_height,
                x2:x2 + bitmap2.shape[1],
            ] = bitmap2

        return screen, lines

    def preview_image(
        self,
        text: str,
        scale: int = 3,
    ) -> Image.Image:
        screen, _ = self.render_global(text)

        # Índice 1 = branco opaco; índice 2 = branco semitransparente/cinza.
        rgb = np.zeros(
            (
                self.cfg.canvas_height,
                self.cfg.canvas_width,
                3,
            ),
            dtype=np.uint8,
        )

        rgb[screen == 0] = (35, 35, 35)
        rgb[screen == 1] = (255, 255, 255)
        rgb[screen == 2] = (160, 160, 160)

        img = Image.fromarray(rgb, mode="RGB")

        return img.resize(
            (
                self.cfg.canvas_width * scale,
                self.cfg.canvas_height * scale,
            ),
            Image.Resampling.NEAREST,
        )

    # ----------------------------- MCF ------------------------------------

    def _encode_segment(
        self,
        visual: np.ndarray,
    ) -> bytes:
        """
        Cada faixa de 100 px sofre rotação circular interna.
        visual = raw[wrap:] + raw[:wrap]
        portanto:
        raw = visual[inverse_wrap:] + visual[:inverse_wrap]
        """
        inv = self.cfg.inverse_wrap

        raw = np.concatenate(
            [
                visual[:, inv:],
                visual[:, :inv],
            ],
            axis=1,
        )

        flat = raw.reshape(-1)

        packed = (
            flat[0::2]
            | (flat[1::2] << 4)
        ).astype(np.uint8)

        return packed.tobytes()


    def _decode_segment(
        self,
        packed: bytes,
    ) -> np.ndarray:
        """
        Faz o caminho inverso de _encode_segment().

        Retorna o segmento visual 100x39.
        """
        raw_bytes = np.frombuffer(
            packed,
            dtype=np.uint8,
        )

        pixels = np.empty(
            raw_bytes.size * 2,
            dtype=np.uint8,
        )

        pixels[0::2] = raw_bytes & 0x0F
        pixels[1::2] = raw_bytes >> 4

        raw = pixels.reshape(
            self.cfg.segment_height,
            self.cfg.segment_width,
        )

        # encode:
        # raw = visual[32:] + visual[:32]
        #
        # decode:
        # visual = raw[68:] + raw[:68]
        visual = np.concatenate(
            [
                raw[:, self.cfg.wrap_x:],
                raw[:, :self.cfg.wrap_x],
            ],
            axis=1,
        )

        return visual

    def decode_triplet_canvas(
        self,
        data: bytes | bytearray,
        triplet: int,
    ) -> np.ndarray:
        """
        Reconstrói os 3 blocos do triplet em um canvas lógico 300x39.
        """
        segments = []

        for phase in range(self.cfg.phases):
            block = (
                triplet * self.cfg.phases
                + phase
            )

            pos = (
                block * self.cfg.block_size
                + self.cfg.region_start
            )

            end_pos = (
                pos
                + self.cfg.region_len
            )

            if end_pos > len(data):
                raise IndexError(
                    f"Triplet {triplet} ultrapassa o arquivo."
                )

            segments.append(
                self._decode_segment(
                    bytes(data[pos:end_pos])
                )
            )

        return np.concatenate(
            segments,
            axis=1,
        )

    @staticmethod
    def _subtitle_layer(
        canvas: np.ndarray,
    ) -> np.ndarray:
        """
        Isola somente os pixels da legenda.

        Nos MCF japoneses originais existe uma camada estática com
        valor 8 dentro da mesma região gráfica. A legenda em si usa
        os índices 1 (contorno) e 2 (preenchimento).

        Portanto, para detectar/comparar/exportar legendas:
          1 e 2 -> preservados
          qualquer outro valor -> transparente (0)
        """
        layer = np.zeros_like(canvas)

        mask = (
            (canvas == 1)
            | (canvas == 2)
        )

        layer[mask] = canvas[mask]

        return layer

    @classmethod
    def _looks_like_subtitle_canvas(
        cls,
        canvas: np.ndarray,
    ) -> bool:
        """
        Detecta conteúdo real de legenda.

        A v2 rejeitava o MCF japonês porque encontrava o valor 8.
        A v3 ignora essa camada e procura apenas pixels 1/2.
        """
        if canvas.size == 0:
            return False

        layer = cls._subtitle_layer(
            canvas
        )

        return (
            int(np.count_nonzero(layer))
            > 5
        )

    def _recognition_candidates(self):
        """
        Conjunto usado para reconstruir texto latino/PT-BR a partir
        de um MCF que tenha sido gerado por esta ferramenta.
        """
        preferred = (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz"
            "0123456789"
            " .,!?;:'\"()-"
        )

        chars = list(preferred)
        chars.extend(self.ACCENTS.keys())

        # Completa com ASCII imprimível para aumentar compatibilidade.
        chars.extend(chr(i) for i in range(32, 127))

        seen = set()
        candidates = []

        for ch in chars:
            if ch in seen:
                continue

            seen.add(ch)

            candidates.append(
                (
                    ch,
                    self.glyph_for_char(ch),
                )
            )

        return candidates

    @staticmethod
    def _edge_glyph_variants(
        glyph: np.ndarray,
        allow_left_trim: bool,
        allow_right_trim: bool,
    ) -> list[np.ndarray]:
        """
        Ao extrair uma linha, removemos as colunas vazias externas.
        Alguns caracteres acentuados possuem uma margem vazia criada
        pelo sintetizador. Esta rotina aceita a versão aparada somente
        quando o glifo está na borda da linha.
        """
        variants = [glyph]

        occupied = np.any(
            glyph > 0,
            axis=0,
        )

        if occupied.any():
            left = int(np.argmax(occupied))
            right = int(
                len(occupied)
                - np.argmax(occupied[::-1])
            )

            if allow_left_trim and left > 0:
                variants.append(
                    glyph[:, left:]
                )

            if (
                allow_right_trim
                and right < glyph.shape[1]
            ):
                variants.append(
                    glyph[:, :right]
                )

            if (
                allow_left_trim
                and allow_right_trim
                and (
                    left > 0
                    or right < glyph.shape[1]
                )
            ):
                variants.append(
                    glyph[:, left:right]
                )

        unique = []
        keys = set()

        for variant in variants:
            key = (
                variant.shape,
                variant.tobytes(),
            )

            if key not in keys:
                keys.add(key)
                unique.append(variant)

        return unique

    def _recognize_line_bitmap(
        self,
        band: np.ndarray,
    ) -> Optional[str]:
        """
        Reconhecimento por comparação exata de glifos.

        Não é OCR tradicional: como o MCF traduzido usa os mesmos
        bitmaps criados a partir do FONTS.FT4, podemos desmontar a
        linha glifo por glifo.
        """
        occupied_x = np.where(
            np.any(
                band > 0,
                axis=0,
            )
        )[0]

        if len(occupied_x) == 0:
            return ""

        line = band[
            :,
            occupied_x.min():occupied_x.max() + 1,
        ]

        width = line.shape[1]
        candidates = self._recognition_candidates()

        cache: dict[int, Optional[str]] = {}

        def solve(x: int) -> Optional[str]:
            if x == width:
                return ""

            if x in cache:
                return cache[x]

            for ch, glyph in candidates:
                # Forma normal / margem esquerda removida no começo.
                first_variants = self._edge_glyph_variants(
                    glyph,
                    allow_left_trim=(x == 0),
                    allow_right_trim=False,
                )

                for variant in first_variants:
                    w = variant.shape[1]

                    if (
                        x + w <= width
                        and np.array_equal(
                            line[:, x:x + w],
                            variant,
                        )
                    ):
                        rest = solve(x + w)

                        if rest is not None:
                            cache[x] = ch + rest
                            return cache[x]

                # Se este glifo encerrar a linha, permite aparar
                # a margem vazia direita.
                final_variants = self._edge_glyph_variants(
                    glyph,
                    allow_left_trim=(x == 0),
                    allow_right_trim=True,
                )

                for variant in final_variants:
                    w = variant.shape[1]

                    if (
                        x + w == width
                        and np.array_equal(
                            line[:, x:x + w],
                            variant,
                        )
                    ):
                        cache[x] = ch
                        return ch

            cache[x] = None
            return None

        return solve(0)

    def recognize_canvas_text(
        self,
        canvas: np.ndarray,
    ) -> Optional[str]:
        """
        Reconhece o layout produzido pela própria ferramenta.

        1 linha:
          y = 12 .. 26

        2 linhas:
          y = 1  .. 15
          y = 18 .. 32

        Retorna | como marcador de quebra manual.
        """
        glyph_h = self.cfg.glyph_height

        # Tenta primeiro layout de uma linha.
        outside = canvas > 0
        outside = outside.copy()

        outside[
            12:12 + glyph_h,
            :
        ] = False

        if not outside.any():
            text = self._recognize_line_bitmap(
                canvas[
                    12:12 + glyph_h,
                    :
                ]
            )

            if text is not None:
                return text

        # Layout de duas linhas.
        outside = canvas > 0
        outside = outside.copy()

        outside[
            1:1 + glyph_h,
            :
        ] = False

        outside[
            18:18 + glyph_h,
            :
        ] = False

        if not outside.any():
            line1 = self._recognize_line_bitmap(
                canvas[
                    1:1 + glyph_h,
                    :
                ]
            )

            line2 = self._recognize_line_bitmap(
                canvas[
                    18:18 + glyph_h,
                    :
                ]
            )

            if (
                line1 is not None
                and line2 is not None
            ):
                return (
                    line1
                    + "|"
                    + line2
                )

        return None

    @staticmethod
    def _canvas_png(
        canvas: np.ndarray,
        scale: int = 4,
    ) -> Image.Image:
        rgb = np.zeros(
            (
                canvas.shape[0],
                canvas.shape[1],
                3,
            ),
            dtype=np.uint8,
        )

        rgb[canvas == 0] = (
            35, 35, 35
        )

        rgb[canvas == 1] = (
            255, 255, 255
        )

        rgb[canvas == 2] = (
            160, 160, 160
        )

        # Valores desconhecidos, úteis ao inspecionar MCFs originais.
        unknown = canvas > 2
        rgb[unknown] = (
            150, 150, 150
        )

        image = Image.fromarray(
            rgb,
            mode="RGB",
        )

        if scale != 1:
            image = image.resize(
                (
                    canvas.shape[1] * scale,
                    canvas.shape[0] * scale,
                ),
                Image.Resampling.NEAREST,
            )

        return image


    @staticmethod
    def find_tesseract() -> Optional[str]:
        """
        Procura Tesseract no PATH e em caminhos comuns do Windows.
        """
        found = shutil.which("tesseract")
        if found:
            return found

        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(
                r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"
            ),
        ]

        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate

        return None

    @staticmethod
    def _clean_japanese_ocr(text: str) -> str:
        """
        Limpa saída do Tesseract sem tentar 'inventar' caracteres.
        Mantém as linhas separadas por | para edição na interface.
        """
        text = text.replace("\r", "\n")
        lines = []

        for raw_line in text.split("\n"):
            line = raw_line.strip()

            if not line:
                continue

            # remove espaços ASCII inseridos entre caracteres japoneses
            line = re.sub(
                r"(?<=[\u3000-\u9fff\uff00-\uffef])\s+"
                r"(?=[\u3000-\u9fff\uff00-\uffef])",
                "",
                line,
            )

            line = re.sub(r"[ \t]+", " ", line).strip()

            if line:
                lines.append(line)

        return "|".join(lines)

    @staticmethod
    def _japanese_char_ratio(text: str) -> float:
        compact = text.replace("|", "").replace(" ", "")
        if not compact:
            return 0.0

        jp = sum(
            1
            for ch in compact
            if (
                "\u3040" <= ch <= "\u30ff"
                or "\u3400" <= ch <= "\u9fff"
                or "\uff00" <= ch <= "\uffef"
            )
        )

        return jp / len(compact)

    def _prepare_japanese_ocr_image(
        self,
        canvas: np.ndarray,
        scale: int = 4,
    ) -> Image.Image:
        """
        Para OCR usamos contorno + preenchimento como uma única massa.
        Isso funciona muito melhor que mandar a imagem 1/2 original ao OCR.
        """
        binary = (
            canvas > 0
        ).astype(np.uint8) * 255

        ys, xs = np.where(binary > 0)

        if len(xs) == 0:
            return Image.new("L", (32, 32), 255)

        margin = 2

        y0 = max(0, int(ys.min()) - margin)
        y1 = min(binary.shape[0], int(ys.max()) + margin + 1)
        x0 = max(0, int(xs.min()) - margin)
        x1 = min(binary.shape[1], int(xs.max()) + margin + 1)

        crop = binary[
            y0:y1,
            x0:x1,
        ]

        image = Image.fromarray(
            crop,
            mode="L",
        )

        image = image.resize(
            (
                image.width * scale,
                image.height * scale,
            ),
            Image.Resampling.NEAREST,
        )

        # Tesseract normalmente se sai melhor com texto preto em fundo branco.
        image = ImageOps.invert(image)

        # Borda branca extra evita caracteres encostados na margem.
        bordered = Image.new(
            "L",
            (
                image.width + 32,
                image.height + 32,
            ),
            255,
        )

        bordered.paste(
            image,
            (16, 16),
        )

        return bordered

    def ocr_japanese_canvas(
        self,
        canvas: np.ndarray,
        tesseract_cmd: Optional[str] = None,
        progress_callback=None,
    ) -> tuple[str, float]:
        """
        OCR japonês local via Tesseract.

        Retorna:
            (texto, score_estimado)

        O resultado é propositalmente editável: pixel fonts de PS1 podem
        confundir alguns kanjis e nomes próprios.
        """
        if pytesseract is None:
            raise RuntimeError(
                "O módulo pytesseract não está instalado.\n\n"
                "Execute:\n"
                "python -m pip install pytesseract"
            )

        cmd = (
            tesseract_cmd
            or self.find_tesseract()
        )

        if not cmd:
            raise RuntimeError(
                "Tesseract OCR não foi encontrado.\n\n"
                "Instale Tesseract OCR com o idioma japonês (jpn) "
                "e reinicie a ferramenta."
            )

        pytesseract.pytesseract.tesseract_cmd = cmd

        # Algumas escalas funcionam melhor para diferentes kanjis.
        # Mantemos poucos testes para não deixar a extração lenta demais.
        variants = [
            (3, 6),
            (3, 11),
            (4, 6),
            (5, 11),
            (8, 6),
        ]

        candidates = []

        for variant_index, (scale, psm) in enumerate(
            variants,
            start=1,
        ):
            if progress_callback:
                progress_callback(
                    variant_index,
                    len(variants),
                    f"Tesseract {variant_index}/{len(variants)}",
                )

            image = self._prepare_japanese_ocr_image(
                canvas,
                scale=scale,
            )

            config = f"--psm {psm}"

            try:
                raw = pytesseract.image_to_string(
                    image,
                    lang="jpn",
                    config=config,
                )
            except pytesseract.TesseractError as exc:
                msg = str(exc)

                if "jpn" in msg.lower():
                    raise RuntimeError(
                        "O pacote de idioma japonês do Tesseract "
                        "não está instalado (jpn.traineddata)."
                    ) from exc

                raise

            cleaned = self._clean_japanese_ocr(
                raw
            )

            if not cleaned:
                continue

            ratio = self._japanese_char_ratio(
                cleaned
            )

            # Preferência por texto essencialmente japonês e com menos
            # espaços espúrios. O score não significa 'certeza absoluta'.
            compact_len = len(
                cleaned.replace("|", "").replace(" ", "")
            )

            score = (
                ratio * 100.0
                + min(compact_len, 40) * 0.10
                - cleaned.count(" ") * 1.5
            )

            candidates.append(
                (
                    score,
                    cleaned,
                    scale,
                    psm,
                )
            )

        if not candidates:
            return "", 0.0

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        best = candidates[0]

        return (
            best[1],
            float(best[0]),
        )


    def extract_subtitles_from_mcf(
        self,
        source_mcf: str | Path,
        image_dir: str | Path | None = None,
        progress_callback=None,
        use_japanese_ocr: bool = False,
        tesseract_cmd: Optional[str] = None,
    ) -> list[SubtitleRow]:
        """
        Extrai automaticamente os trechos de legenda do MCF.

        Para MCFs criados por esta ferramenta:
          - detecta os triplets
          - recupera o texto PT-BR
          - recupera as quebras de linha

        Para um MCF original cujo alfabeto não exista no FONTS.FT4
        selecionado:
          - os timings ainda são detectados
          - o bitmap é salvo como PNG
          - o texto fica vazio para edição manual
        """
        if self.atlas is None:
            raise RuntimeError(
                "Carregue o FONTS.FT4 antes de extrair."
            )

        source_mcf = Path(source_mcf)
        data = source_mcf.read_bytes()

        total_blocks = (
            len(data)
            // self.cfg.block_size
        )

        total_triplets = (
            total_blocks
            // self.cfg.phases
        )

        groups = []

        active_start = None
        active_end = None
        active_canvas = None

        for triplet in range(total_triplets):
            canvas = self.decode_triplet_canvas(
                data,
                triplet,
            )

            # Remove a camada estática (valor 8) presente nos MCFs
            # japoneses e trabalha somente com o bitmap da legenda.
            subtitle_canvas = (
                self._subtitle_layer(
                    canvas
                )
            )

            is_subtitle = (
                self._looks_like_subtitle_canvas(
                    subtitle_canvas
                )
            )

            if is_subtitle:
                if active_start is None:
                    active_start = triplet
                    active_end = triplet
                    active_canvas = subtitle_canvas.copy()

                elif (
                    triplet == active_end + 1
                    and np.array_equal(
                        subtitle_canvas,
                        active_canvas,
                    )
                ):
                    active_end = triplet

                else:
                    groups.append(
                        (
                            active_start,
                            active_end,
                            active_canvas,
                        )
                    )

                    active_start = triplet
                    active_end = triplet
                    active_canvas = subtitle_canvas.copy()

            else:
                if active_start is not None:
                    groups.append(
                        (
                            active_start,
                            active_end,
                            active_canvas,
                        )
                    )

                    active_start = None
                    active_end = None
                    active_canvas = None

            if progress_callback:
                progress_callback(
                    triplet + 1,
                    total_triplets,
                    "scan",
                )

        if active_start is not None:
            groups.append(
                (
                    active_start,
                    active_end,
                    active_canvas,
                )
            )

        output_dir = None

        if image_dir is not None:
            output_dir = Path(image_dir)
            output_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

        rows = []

        for index, (
            start,
            end,
            canvas,
        ) in enumerate(
            groups,
            start=1,
        ):
            text = self.recognize_canvas_text(
                canvas
            )

            recognized = (
                text is not None
            )

            image_name = ""

            if output_dir is not None:
                image_name = (
                    f"{index:03d}_"
                    f"{start}-{end}.png"
                )

                self._canvas_png(
                    canvas,
                    scale=4,
                ).save(
                    output_dir / image_name
                )

            original_jp = ""
            ocr_score = ""

            if (
                not recognized
                and use_japanese_ocr
            ):
                try:
                    original_jp, score = (
                        self.ocr_japanese_canvas(
                            canvas,
                            tesseract_cmd=tesseract_cmd,
                            progress_callback=(
                                lambda cur, total, stage,
                                       idx=index,
                                       grp_total=len(groups):
                                    progress_callback(
                                        idx,
                                        grp_total,
                                        "ocr",
                                    )
                                if progress_callback
                                else None
                            ),
                        )
                    )

                    if original_jp:
                        ocr_score = f"{score:.1f}"

                except Exception:
                    # A extração dos timings/PNGs nunca deve falhar só
                    # porque OCR não está disponível.
                    original_jp = ""
                    ocr_score = ""

            if recognized:
                status = "RECONHECIDO_PT"
            elif original_jp:
                status = "OCR_JP_REVISAR"
            else:
                status = "BITMAP_EXTRAIDO"

            if progress_callback:
                progress_callback(
                    index,
                    len(groups),
                    "ocr" if use_japanese_ocr else "extract",
                )

            rows.append(
                SubtitleRow(
                    {
                        "id": str(index),
                        "triplet_inicio": str(start),
                        "triplet_fim": str(end),
                        "original_jp": original_jp,
                        "portugues": (
                            text
                            if recognized
                            else ""
                        ),
                        "status": status,
                        "ocr_score": ocr_score,
                        "imagem": image_name,
                    }
                )
            )

        return rows


    def generate_mcf(
        self,
        source_mcf: str | Path,
        rows: list[SubtitleRow],
        output_mcf: str | Path,
        progress_callback=None,
    ) -> None:
        if not self.font_ready:
            raise RuntimeError(
                "Carregue a fonte selecionada antes de gerar."
            )

        source_mcf = Path(source_mcf)
        output_mcf = Path(output_mcf)

        data = bytearray(source_mcf.read_bytes())

        # Validação total antes de alterar qualquer coisa.
        prepared = []

        for row in rows:
            text = row.text.strip()

            if not text:
                raise ValueError(
                    f"ID {row.id}: tradução vazia."
                )

            lines = self.split_text(text)

            if lines is None:
                raise ValueError(
                    f"ID {row.id}: não cabe em até duas linhas.\n"
                    f"{text}"
                )

            prepared.append((row, text, lines))

        total = len(prepared)

        for index, (row, text, lines) in enumerate(
            prepared,
            start=1,
        ):
            global_bitmap, _ = self.render_global(text)

            encoded_phases = []

            for phase in range(self.cfg.phases):
                x0 = phase * self.cfg.segment_width
                x1 = x0 + self.cfg.segment_width

                segment = global_bitmap[:, x0:x1]

                encoded_phases.append(
                    self._encode_segment(segment)
                )

            start = row.triplet_start
            end = row.triplet_end

            if start > end:
                raise ValueError(
                    f"ID {row.id}: triplet inicial maior que final."
                )

            for triplet in range(start, end + 1):
                for phase in range(self.cfg.phases):
                    block = triplet * self.cfg.phases + phase

                    pos = (
                        block * self.cfg.block_size
                        + self.cfg.region_start
                    )

                    end_pos = pos + self.cfg.region_len

                    if end_pos > len(data):
                        raise ValueError(
                            f"ID {row.id}: bloco {block} "
                            "ultrapassa o tamanho do MCF."
                        )

                    data[pos:end_pos] = encoded_phases[phase]

            if progress_callback:
                progress_callback(
                    index,
                    total,
                    row.id,
                )

        output_mcf.write_bytes(data)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    "id",
    "triplet_inicio",
    "triplet_fim",
    "portugues",
}


def load_csv_file(
    path: str | Path,
) -> tuple[list[str], list[SubtitleRow], str]:
    path = Path(path)

    # tenta ; primeiro, depois ,
    raw_text = path.read_text(
        encoding="utf-8-sig",
    )

    first_line = raw_text.splitlines()[0] if raw_text else ""

    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(
            file,
            delimiter=delimiter,
        )

        fieldnames = list(
            reader.fieldnames or []
        )

        missing = (
            REQUIRED_COLUMNS
            - set(fieldnames)
        )

        if missing:
            raise ValueError(
                "CSV sem as colunas obrigatórias: "
                + ", ".join(sorted(missing))
            )

        rows = [
            SubtitleRow(
                dict(row)
            )
            for row in reader
        ]

    return fieldnames, rows, delimiter


def save_csv_file(
    path: str | Path,
    fieldnames: list[str],
    rows: list[SubtitleRow],
    delimiter: str = ";",
) -> None:
    path = Path(path)

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            delimiter=delimiter,
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(row.values)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class KoudelkaGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(
            "Koudelka MCF Subtitle Tool v6 - FT4 / TTF"
        )
        self.geometry("1180x760")
        self.minsize(1000, 650)

        self.engine = KoudelkaSubtitleEngine()

        self.rows: list[SubtitleRow] = []
        self.fieldnames: list[str] = []
        self.csv_delimiter = ";"

        self.current_index: Optional[int] = None
        self.preview_tk = None
        self.preview_after_id = None

        # Modo pasta: mantém todas as legendas em uma lista única, mas
        # registra a qual MCF cada linha pertence para agrupar e gerar com
        # segurança somente o arquivo selecionado.
        self.folder_mode = False
        self.mcf_folder_path: Optional[Path] = None
        self.mcf_groups: dict[str, list[int]] = {}
        self.row_mcf_paths: dict[int, str] = {}
        self.group_iid_to_path: dict[str, str] = {}
        self.active_mcf_path: Optional[str] = None

        self.mcf_var = tk.StringVar()
        self.ft4_var = tk.StringVar()
        self.ttf_var = tk.StringVar()
        self.csv_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.render_mode_var = tk.StringVar(value="Tahoma Bold (TTF)")
        self.ttf_size_var = tk.StringVar(
            value=str(self.engine.cfg.ttf_font_size)
        )
        self.search_var = tk.StringVar()
        self.replace_var = tk.StringVar()
        self.whole_word_var = tk.BooleanVar(value=True)
        self.case_sensitive_var = tk.BooleanVar(value=False)
        self.ocr_found_only_var = tk.BooleanVar(value=False)
        self.ocr_jp_var = tk.BooleanVar(value=True)
        self.tesseract_var = tk.StringVar()

        bundled_ttf = Path(__file__).with_name("tahomabd.ttf")
        if bundled_ttf.is_file():
            self.ttf_var.set(str(bundled_ttf))
            self.engine.load_ttf(bundled_ttf)

        auto_tesseract = self.engine.find_tesseract()
        if auto_tesseract:
            self.tesseract_var.set(auto_tesseract)

        self.status_var = tk.StringVar(
            value="Tahoma Bold pronta. Selecione o MCF e o CSV."
        )

        self.extract_queue = queue.Queue()
        self.extract_thread = None
        self.extract_started_at = None
        self.folder_queue = queue.Queue()
        self.folder_thread = None

        self._build_ui()

    # ----------------------------- UI -------------------------------------

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        files_frame = ttk.LabelFrame(
            self,
            text="Arquivos",
            padding=8,
        )
        files_frame.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=8,
            pady=8,
        )
        files_frame.columnconfigure(1, weight=1)

        self._file_row(
            files_frame,
            0,
            "MCF de origem:",
            self.mcf_var,
            self._browse_mcf,
        )

        ttk.Button(
            files_frame,
            text="Abrir pasta MCF...",
            command=self._browse_mcf_folder,
        ).grid(
            row=0,
            column=3,
            padx=(6, 0),
            pady=2,
        )

        self._file_row(
            files_frame,
            1,
            "FONTS.FT4:",
            self.ft4_var,
            self._browse_ft4,
        )

        self._file_row(
            files_frame,
            2,
            "Fonte TTF/OTF:",
            self.ttf_var,
            self._browse_ttf,
        )

        self._file_row(
            files_frame,
            3,
            "CSV:",
            self.csv_var,
            self._browse_csv,
        )

        self._file_row(
            files_frame,
            4,
            "Saída MCF:",
            self.output_var,
            self._browse_output,
        )

        extract_line = ttk.Frame(
            files_frame,
        )
        extract_line.grid(
            row=5,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Button(
            extract_line,
            text="Extrair MCF → CSV",
            command=self._extract_mcf_to_csv,
        ).pack(
            side=tk.LEFT,
        )

        ttk.Label(
            extract_line,
            text=(
                "  Recupera triplets, imagens e texto quando possível."
            ),
        ).pack(
            side=tk.LEFT,
            padx=(6, 0),
        )

        ocr_line = ttk.Frame(
            files_frame,
        )
        ocr_line.grid(
            row=6,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(4, 0),
        )

        ttk.Checkbutton(
            ocr_line,
            text="OCR japonês ao extrair",
            variable=self.ocr_jp_var,
        ).pack(
            side=tk.LEFT,
        )

        ttk.Label(
            ocr_line,
            text="Tesseract:",
        ).pack(
            side=tk.LEFT,
            padx=(12, 4),
        )

        ttk.Entry(
            ocr_line,
            textvariable=self.tesseract_var,
            width=45,
        ).pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )

        ttk.Button(
            ocr_line,
            text="Selecionar...",
            command=self._browse_tesseract,
        ).pack(
            side=tk.LEFT,
            padx=(6, 0),
        )

        main = ttk.Panedwindow(
            self,
            orient=tk.HORIZONTAL,
        )
        main.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=8,
            pady=(0, 8),
        )

        # tabela
        left = ttk.Frame(main)
        main.add(left, weight=3)

        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        search_frame = ttk.LabelFrame(
            left,
            text="Pesquisar / substituir em massa",
            padding=6,
        )
        search_frame.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 6),
        )
        search_frame.columnconfigure(1, weight=1)

        ttk.Label(
            search_frame,
            text="Pesquisar:",
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 5),
        )

        search_entry = ttk.Entry(
            search_frame,
            textvariable=self.search_var,
        )
        search_entry.grid(
            row=0,
            column=1,
            sticky="ew",
        )
        search_entry.bind(
            "<KeyRelease>",
            self._on_search_changed,
        )
        search_entry.bind(
            "<Return>",
            self._select_next_search_match,
        )

        ttk.Button(
            search_frame,
            text="Próximo",
            command=self._select_next_search_match,
        ).grid(
            row=0,
            column=2,
            padx=(6, 0),
        )

        ttk.Button(
            search_frame,
            text="Limpar",
            command=self._clear_search,
        ).grid(
            row=0,
            column=3,
            padx=(6, 0),
        )

        ttk.Label(
            search_frame,
            text="Substituir por:",
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 5),
            pady=(5, 0),
        )

        replace_entry = ttk.Entry(
            search_frame,
            textvariable=self.replace_var,
        )
        replace_entry.grid(
            row=1,
            column=1,
            sticky="ew",
            pady=(5, 0),
        )
        replace_entry.bind(
            "<Return>",
            lambda _event: self._replace_all(),
        )

        options = ttk.Frame(search_frame)
        options.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(5, 0),
        )

        ttk.Checkbutton(
            options,
            text="Palavra inteira",
            variable=self.whole_word_var,
        ).pack(side=tk.LEFT)

        ttk.Checkbutton(
            options,
            text="Diferenciar maiúsculas",
            variable=self.case_sensitive_var,
            command=self._on_search_changed,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Checkbutton(
            options,
            text="OCR encontrados",
            variable=self.ocr_found_only_var,
            command=self._on_search_changed,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(
            options,
            text="Substituir todos no português",
            command=self._replace_all,
        ).pack(side=tk.RIGHT)

        columns = (
            "alterado",
            "ocr",
            "id",
            "start",
            "end",
            "jp",
            "texto",
            "status",
        )

        self.tree = ttk.Treeview(
            left,
            columns=columns,
            show="tree headings",
            selectmode="browse",
        )

        self.tree.heading(
            "#0",
            text="",
        )
        self.tree.column(
            "#0",
            width=0,
            minwidth=0,
            stretch=False,
        )

        self.tree.heading(
            "alterado",
            text="✓",
        )
        self.tree.heading(
            "ocr",
            text="OCR",
        )

        self.tree.heading(
            "id",
            text="ID",
        )
        self.tree.heading(
            "start",
            text="Início",
        )
        self.tree.heading(
            "end",
            text="Fim",
        )
        self.tree.heading(
            "jp",
            text="Original JP",
        )
        self.tree.heading(
            "texto",
            text="Português",
        )
        self.tree.heading(
            "status",
            text="Status",
        )

        self.tree.column(
            "alterado",
            width=38,
            anchor="center",
            stretch=False,
        )
        self.tree.column(
            "ocr",
            width=45,
            anchor="center",
            stretch=False,
        )
        self.tree.column(
            "id",
            width=45,
            stretch=False,
        )
        self.tree.column(
            "start",
            width=65,
            stretch=False,
        )
        self.tree.column(
            "end",
            width=65,
            stretch=False,
        )
        self.tree.column(
            "jp",
            width=260,
        )
        self.tree.column(
            "texto",
            width=320,
        )
        self.tree.column(
            "status",
            width=125,
            stretch=False,
        )

        scroll_y = ttk.Scrollbar(
            left,
            orient=tk.VERTICAL,
            command=self.tree.yview,
        )

        self.tree.configure(
            yscrollcommand=scroll_y.set
        )

        self.tree.tag_configure(
            "mass_replaced",
            background="#fff2a8",
        )
        self.tree.tag_configure(
            "mcf_group",
            background="#dbeafe",
            font=("", 9, "bold"),
        )
        self.tree.tag_configure(
            "mcf_group_ocr",
            background="#fde68a",
            font=("", 9, "bold"),
        )
        self.tree.tag_configure(
            "ocr_found",
            foreground="#9a3412",
        )

        self.tree.grid(
            row=1,
            column=0,
            sticky="nsew",
        )
        scroll_y.grid(
            row=1,
            column=1,
            sticky="ns",
        )

        self.tree.bind(
            "<<TreeviewSelect>>",
            self._on_tree_select,
        )
        self.tree.bind(
            "<Button-1>",
            self._on_tree_click,
        )
        self.tree.bind(
            "<<TreeviewOpen>>",
            self._on_group_opened,
        )
        self.tree.bind(
            "<<TreeviewClose>>",
            self._on_group_closed,
        )

        # editor
        right = ttk.Frame(main, padding=(10, 0, 0, 0))
        main.add(right, weight=2)

        right.columnconfigure(1, weight=1)
        right.rowconfigure(5, weight=1)

        ttk.Label(
            right,
            text="Editar legenda",
            font=("", 11, "bold"),
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 8),
        )

        ttk.Label(
            right,
            text="ID:",
        ).grid(
            row=1,
            column=0,
            sticky="w",
        )

        self.id_label = ttk.Label(
            right,
            text="-",
        )
        self.id_label.grid(
            row=1,
            column=1,
            sticky="w",
        )

        ttk.Label(
            right,
            text="Triplet início:",
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=3,
        )

        self.start_var = tk.StringVar()

        ttk.Entry(
            right,
            textvariable=self.start_var,
            width=12,
        ).grid(
            row=2,
            column=1,
            sticky="w",
            pady=3,
        )

        ttk.Label(
            right,
            text="Triplet fim:",
        ).grid(
            row=3,
            column=0,
            sticky="w",
            pady=3,
        )

        self.end_var = tk.StringVar()

        ttk.Entry(
            right,
            textvariable=self.end_var,
            width=12,
        ).grid(
            row=3,
            column=1,
            sticky="w",
            pady=3,
        )

        ttk.Label(
            right,
            text="Original japonês (OCR — revise se necessário):",
        ).grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 2),
        )

        self.jp_edit = tk.Text(
            right,
            height=3,
            wrap="word",
        )
        self.jp_edit.grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="nsew",
        )

        ttk.Label(
            right,
            text="Português (use | para quebra manual):",
        ).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 2),
        )

        self.text_edit = tk.Text(
            right,
            height=4,
            wrap="word",
        )
        self.text_edit.grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="nsew",
        )
        self.text_edit.bind(
            "<KeyRelease>",
            self._schedule_preview,
        )

        button_line = ttk.Frame(right)
        button_line.grid(
            row=8,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=6,
        )

        ttk.Button(
            button_line,
            text="Aplicar edição",
            command=self._apply_current_edit,
        ).pack(
            side=tk.LEFT,
        )

        ttk.Button(
            button_line,
            text="Visualizar",
            command=self._preview_current,
        ).pack(
            side=tk.LEFT,
            padx=6,
        )

        self.validation_label = ttk.Label(
            right,
            text="",
            wraplength=390,
        )
        self.validation_label.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(2, 6),
        )

        preview_frame = ttk.LabelFrame(
            right,
            text="Preview lógico 300×39",
            padding=5,
        )
        preview_frame.grid(
            row=10,
            column=0,
            columnspan=2,
            sticky="ew",
        )

        self.preview_label = ttk.Label(
            preview_frame,
        )
        self.preview_label.pack()

        # avançado
        advanced = ttk.LabelFrame(
            right,
            text="Configuração avançada",
            padding=6,
        )
        advanced.grid(
            row=11,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        advanced.columnconfigure(1, weight=1)

        self.max_width_var = tk.StringVar(
            value=str(self.engine.cfg.max_line_width)
        )

        ttk.Label(
            advanced,
            text="Largura máxima:",
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Entry(
            advanced,
            textvariable=self.max_width_var,
            width=8,
        ).grid(
            row=0,
            column=1,
            sticky="w",
        )

        self.baseline_var = tk.StringVar(
            value="Normalizada"
        )

        ttk.Label(
            advanced,
            text="Renderização:",
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=3,
        )

        render_combo = ttk.Combobox(
            advanced,
            textvariable=self.render_mode_var,
            state="readonly",
            values=(
                "Tahoma Bold (TTF)",
                "Fonte nativa FT4",
            ),
            width=20,
        )
        render_combo.grid(
            row=1,
            column=1,
            sticky="w",
            pady=3,
        )
        render_combo.bind(
            "<<ComboboxSelected>>",
            self._on_render_mode_changed,
        )

        ttk.Label(
            advanced,
            text="Tamanho TTF:",
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=3,
        )

        ttf_size_entry = ttk.Entry(
            advanced,
            textvariable=self.ttf_size_var,
            width=8,
        )
        ttf_size_entry.grid(
            row=2,
            column=1,
            sticky="w",
            pady=3,
        )
        ttf_size_entry.bind("<KeyRelease>", self._schedule_preview)

        ttk.Label(
            advanced,
            text="Baseline:",
        ).grid(
            row=3,
            column=0,
            sticky="w",
            pady=3,
        )

        ttk.Combobox(
            advanced,
            textvariable=self.baseline_var,
            state="readonly",
            values=(
                "Normalizada",
                "Y nativo do FT4",
            ),
            width=20,
        ).grid(
            row=3,
            column=1,
            sticky="w",
            pady=3,
        )

        # rodapé / ações
        actions = ttk.Frame(
            self,
            padding=(8, 0, 8, 8),
        )
        actions.grid(
            row=2,
            column=0,
            sticky="ew",
        )
        actions.columnconfigure(1, weight=1)

        ttk.Button(
            actions,
            text="Salvar CSV",
            command=self._save_csv,
        ).grid(
            row=0,
            column=0,
            padx=(0, 6),
        )

        ttk.Button(
            actions,
            text="Exportar para tradução",
            command=self._export_translation_csv,
        ).grid(
            row=0,
            column=1,
            padx=(0, 6),
        )

        ttk.Button(
            actions,
            text="Importar traduções",
            command=self._import_translation_csv,
        ).grid(
            row=0,
            column=2,
            padx=(0, 6),
        )

        ttk.Button(
            actions,
            text="Validar todas",
            command=self._validate_all,
        ).grid(
            row=0,
            column=3,
            padx=(0, 6),
        )

        ttk.Button(
            actions,
            text="Exportar previews PNG",
            command=self._export_preview_images,
        ).grid(
            row=0,
            column=4,
            padx=(0, 6),
        )

        self.generate_button = ttk.Button(
            actions,
            text="GERAR MCF",
            command=self._generate,
        )
        self.generate_button.grid(
            row=0,
            column=5,
            padx=(6, 0),
        )

        self.progress = ttk.Progressbar(
            actions,
            mode="determinate",
            length=220,
        )
        self.progress.grid(
            row=0,
            column=6,
            padx=(10, 0),
        )

        status = ttk.Label(
            self,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor="w",
        )
        status.grid(
            row=3,
            column=0,
            sticky="ew",
        )

    def _file_row(
        self,
        parent,
        row,
        label,
        variable,
        command,
    ):
        ttk.Label(
            parent,
            text=label,
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 6),
            pady=2,
        )

        ttk.Entry(
            parent,
            textvariable=variable,
        ).grid(
            row=row,
            column=1,
            sticky="ew",
            pady=2,
        )

        ttk.Button(
            parent,
            text="Selecionar...",
            command=command,
        ).grid(
            row=row,
            column=2,
            padx=(6, 0),
            pady=2,
        )

    # ------------------------- arquivos -----------------------------------

    def _browse_mcf(self):
        path = filedialog.askopenfilename(
            title="Selecionar MCF de origem",
            filetypes=[
                ("Koudelka MCF", "*.MCF *.mcf"),
                ("Todos", "*.*"),
            ],
        )

        if path:
            self.folder_mode = False
            self.mcf_folder_path = None
            self.mcf_groups.clear()
            self.row_mcf_paths.clear()
            self.group_iid_to_path.clear()
            self.active_mcf_path = None
            self.generate_button.config(text="GERAR MCF")
            self.mcf_var.set(path)

            if not self.output_var.get():
                p = Path(path)
                self.output_var.set(
                    str(
                        p.with_name(
                            p.stem + "_PTBR.MCF"
                        )
                    )
                )

    @staticmethod
    def _path_is_within(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (ValueError, OSError):
            return False

    @staticmethod
    def _find_companion_csv(
        mcf_path: Path,
        csv_files: list[Path],
    ) -> Optional[Path]:
        """Encontra o CSV mais provável para um MCF dentro da pasta."""
        stem = mcf_path.stem.casefold()
        preferred_names = {
            stem: 0,
            f"{stem}_extraido": 1,
            f"{stem}_ptbr": 2,
            f"{stem}_traducao": 3,
            f"{stem}_tradução": 3,
        }

        candidates = []

        for csv_path in csv_files:
            csv_stem = csv_path.stem.casefold()

            if csv_stem in preferred_names:
                name_score = preferred_names[csv_stem]
            elif csv_stem.startswith(stem + "_"):
                name_score = 10
            else:
                continue

            same_folder = (
                0
                if csv_path.parent == mcf_path.parent
                else 1
            )

            candidates.append(
                (
                    same_folder,
                    name_score,
                    len(str(csv_path)),
                    str(csv_path).casefold(),
                    csv_path,
                )
            )

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[:-1])
        return candidates[0][-1]

    def _browse_mcf_folder(self):
        if (
            self.folder_thread is not None
            and self.folder_thread.is_alive()
        ):
            messagebox.showinfo(
                "Pasta MCF",
                "Uma pasta já está sendo carregada.",
            )
            return

        selected = filedialog.askdirectory(
            title="Selecionar pasta com arquivos MCF",
        )

        if not selected:
            return

        folder = Path(selected)
        generated_root = folder / "MCF_TRADUZIDOS"
        mcf_files = sorted(
            (
                path
                for path in folder.rglob("*")
                if path.is_file()
                and path.suffix.casefold() == ".mcf"
                and not self._path_is_within(path, generated_root)
            ),
            key=lambda path: str(path).casefold(),
        )

        if not mcf_files:
            messagebox.showwarning(
                "Pasta MCF",
                "Nenhum arquivo .MCF foi encontrado nessa pasta.",
            )
            return

        csv_files = [
            path
            for path in folder.rglob("*")
            if path.is_file()
            and path.suffix.casefold() == ".csv"
            and not self._path_is_within(path, generated_root)
        ]

        companion_csvs = {
            str(mcf): self._find_companion_csv(mcf, csv_files)
            for mcf in mcf_files
        }

        missing_csv = [
            mcf
            for mcf in mcf_files
            if companion_csvs[str(mcf)] is None
        ]

        if missing_csv and self.engine.atlas is None:
            ft4 = self.ft4_var.get().strip()

            if not ft4:
                ft4_candidates = sorted(
                    (
                        path
                        for path in folder.rglob("*")
                        if path.is_file()
                        and path.name.casefold() == "fonts.ft4"
                    ),
                    key=lambda path: (
                        0 if path.parent == folder else 1,
                        len(str(path)),
                        str(path).casefold(),
                    ),
                )

                if ft4_candidates:
                    ft4 = str(ft4_candidates[0])
                    self.ft4_var.set(ft4)

            if ft4:
                try:
                    self.engine.load_ft4(ft4)
                except Exception as exc:
                    messagebox.showerror("FONTS.FT4", str(exc))
                    return
            else:
                messagebox.showwarning(
                    "Pasta MCF",
                    f"Foram encontrados {len(missing_csv)} MCF(s) sem CSV "
                    "correspondente.\n\nSelecione o FONTS.FT4 antes de "
                    "abrir a pasta, para que esses arquivos possam ser "
                    "analisados e seus textos extraídos.",
                )
                return

        self.folder_mode = True
        self.mcf_folder_path = folder
        self.generate_button.config(text="GERAR TODOS OS MCFs")
        self.mcf_var.set(str(folder))
        self.csv_var.set("")
        self.output_var.set("")
        self.progress["value"] = 0
        self.progress["maximum"] = max(len(mcf_files), 1)
        self.status_var.set(
            f"Carregando pasta — 0/{len(mcf_files)} MCFs..."
        )

        try:
            while True:
                self.folder_queue.get_nowait()
        except queue.Empty:
            pass

        use_ocr = bool(self.ocr_jp_var.get())
        tesseract_cmd = self.tesseract_var.get().strip() or None

        def worker():
            groups = []
            errors = []

            for file_index, mcf_path in enumerate(mcf_files, start=1):
                csv_path = companion_csvs[str(mcf_path)]

                self.folder_queue.put(
                    (
                        "folder_progress",
                        file_index - 1,
                        len(mcf_files),
                        mcf_path.name,
                        "CSV" if csv_path else "MCF",
                    )
                )

                try:
                    if csv_path is not None:
                        fields, rows, delimiter = load_csv_file(csv_path)
                    else:
                        fields = [
                            "id",
                            "triplet_inicio",
                            "triplet_fim",
                            "original_jp",
                            "portugues",
                            "status",
                            "ocr_score",
                            "imagem",
                        ]
                        delimiter = ";"

                        def file_progress(current, total, stage):
                            self.folder_queue.put(
                                (
                                    "folder_scan",
                                    file_index,
                                    len(mcf_files),
                                    mcf_path.name,
                                    current,
                                    total,
                                    stage,
                                )
                            )

                        rows = self.engine.extract_subtitles_from_mcf(
                            mcf_path,
                            image_dir=None,
                            progress_callback=file_progress,
                            use_japanese_ocr=use_ocr,
                            tesseract_cmd=tesseract_cmd,
                        )

                    groups.append(
                        (
                            mcf_path,
                            csv_path,
                            fields,
                            rows,
                            delimiter,
                        )
                    )

                except Exception as exc:
                    errors.append(f"{mcf_path.name}: {exc}")

                self.folder_queue.put(
                    (
                        "folder_progress",
                        file_index,
                        len(mcf_files),
                        mcf_path.name,
                        "concluído",
                    )
                )

            self.folder_queue.put(
                (
                    "folder_done",
                    folder,
                    groups,
                    errors,
                    len(mcf_files),
                )
            )

        self.folder_thread = threading.Thread(
            target=worker,
            daemon=True,
        )
        self.folder_thread.start()
        self.after(100, self._poll_folder_queue)

    def _poll_folder_queue(self):
        keep_polling = False

        try:
            while True:
                message = self.folder_queue.get_nowait()
                kind = message[0]

                if kind == "folder_progress":
                    _, current, total, name, source_kind = message
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = current
                    self.status_var.set(
                        f"Carregando pasta — {current}/{total}: "
                        f"{name} ({source_kind})"
                    )
                    keep_polling = True

                elif kind == "folder_scan":
                    (
                        _, file_index, file_total, name,
                        current, total, stage,
                    ) = message
                    self.status_var.set(
                        f"Analisando {name} — arquivo {file_index}/{file_total}; "
                        f"{stage} {current}/{max(total, 1)}"
                    )
                    keep_polling = True

                elif kind == "folder_done":
                    _, folder, groups, errors, found_total = message

                    self.rows = []
                    self.fieldnames = []
                    self.csv_delimiter = ";"
                    self.mcf_groups.clear()
                    self.row_mcf_paths.clear()
                    self.group_iid_to_path.clear()
                    self.active_mcf_path = None

                    standard_fields = [
                        "id",
                        "triplet_inicio",
                        "triplet_fim",
                        "original_jp",
                        "portugues",
                        "status",
                        "ocr_score",
                        "imagem",
                        "arquivo_mcf",
                        "caminho_mcf",
                        "csv_origem",
                    ]

                    for field_name in standard_fields:
                        if field_name not in self.fieldnames:
                            self.fieldnames.append(field_name)

                    for mcf_path, csv_path, fields, rows, _delimiter in groups:
                        path_key = str(mcf_path)
                        indices = []

                        for field_name in fields:
                            if field_name not in self.fieldnames:
                                self.fieldnames.append(field_name)

                        for row in rows:
                            row.values["arquivo_mcf"] = mcf_path.name
                            row.values["caminho_mcf"] = path_key
                            row.values["csv_origem"] = (
                                str(csv_path) if csv_path else ""
                            )

                            index = len(self.rows)
                            self.rows.append(row)
                            indices.append(index)
                            self.row_mcf_paths[index] = path_key

                        self.mcf_groups[path_key] = indices

                    self.folder_mode = True
                    self.mcf_folder_path = Path(folder)
                    self.search_var.set("")
                    self._populate_tree()
                    self.progress["maximum"] = max(found_total, 1)
                    self.progress["value"] = found_total
                    self.folder_thread = None

                    loaded_files = len(groups)
                    ocr_rows = sum(
                        1
                        for row in self.rows
                        if self._row_has_ocr(row)
                    )
                    ocr_files = sum(
                        1
                        for indices in self.mcf_groups.values()
                        if any(
                            self._row_has_ocr(self.rows[index])
                            for index in indices
                        )
                    )
                    self.status_var.set(
                        f"Pasta carregada: {loaded_files} MCF(s), "
                        f"{len(self.rows)} legenda(s), "
                        f"{ocr_rows} OCR em {ocr_files} MCF(s)."
                    )

                    detail = (
                        f"MCFs encontrados: {found_total}\n"
                        f"MCFs carregados: {loaded_files}\n"
                        f"Legendas: {len(self.rows)}\n"
                        f"OCR encontrados: {ocr_rows}\n"
                        f"MCFs com OCR: {ocr_files}"
                    )

                    if errors:
                        detail += (
                            f"\n\nFalhas: {len(errors)}\n"
                            + "\n".join(errors[:8])
                            + ("\n..." if len(errors) > 8 else "")
                        )

                    messagebox.showinfo("Pasta MCF carregada", detail)
                    return

        except queue.Empty:
            pass

        if (
            self.folder_thread is not None
            and self.folder_thread.is_alive()
        ):
            keep_polling = True

        if keep_polling:
            self.after(100, self._poll_folder_queue)

    def _browse_ft4(self):
        path = filedialog.askopenfilename(
            title="Selecionar FONTS.FT4",
            filetypes=[
                ("FT4", "*.FT4 *.ft4"),
                ("Todos", "*.*"),
            ],
        )

        if not path:
            return

        try:
            self.engine.load_ft4(path)
        except Exception as exc:
            messagebox.showerror(
                "Erro no FT4",
                str(exc),
            )
            return

        self.ft4_var.set(path)
        self.status_var.set(
            "FONTS.FT4 carregado."
        )

        self._refresh_tree_statuses()

    def _browse_ttf(self):
        path = filedialog.askopenfilename(
            title="Selecionar fonte TTF/OTF",
            filetypes=[
                ("Fontes TrueType/OpenType", "*.ttf *.otf *.TTF *.OTF"),
                ("Todos", "*.*"),
            ],
        )

        if not path:
            return

        try:
            self.engine.load_ttf(path)
        except Exception as exc:
            messagebox.showerror(
                "Erro na fonte TTF/OTF",
                str(exc),
            )
            return

        self.ttf_var.set(path)
        self.render_mode_var.set("Tahoma Bold (TTF)")
        self.engine.cfg.render_mode = "ttf"
        self.status_var.set("Fonte TTF/OTF carregada.")
        self._refresh_tree_statuses()
        self._preview_current(show_errors=False)

    def _on_render_mode_changed(self, _event=None):
        try:
            self._engine_settings_from_ui()
        except Exception as exc:
            self.status_var.set(str(exc))
            return

        self._refresh_tree_statuses()
        self._preview_current(show_errors=False)

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="Selecionar CSV",
            filetypes=[
                ("CSV", "*.csv"),
                ("Todos", "*.*"),
            ],
        )

        if not path:
            return

        try:
            (
                self.fieldnames,
                self.rows,
                self.csv_delimiter,
            ) = load_csv_file(path)
        except Exception as exc:
            messagebox.showerror(
                "Erro no CSV",
                str(exc),
            )
            return

        self.csv_var.set(path)
        self.search_var.set("")
        self._restore_folder_groups_from_csv()
        self._populate_tree()

        self.status_var.set(
            f"{len(self.rows)} legendas carregadas."
        )

    def _restore_folder_groups_from_csv(self):
        """Reconstrói os grupos ao reabrir um CSV combinado do modo pasta."""
        paths = []

        for row in self.rows:
            path_value = str(
                row.values.get("caminho_mcf", "")
                or ""
            ).strip()

            if path_value and path_value not in paths:
                paths.append(path_value)

        self.mcf_groups.clear()
        self.row_mcf_paths.clear()
        self.group_iid_to_path.clear()
        self.active_mcf_path = None

        if not paths:
            self.folder_mode = False
            self.mcf_folder_path = None
            self.generate_button.config(text="GERAR MCF")
            return

        self.folder_mode = True
        self.generate_button.config(text="GERAR TODOS OS MCFs")

        for path_key in paths:
            self.mcf_groups[path_key] = []

        for index, row in enumerate(self.rows):
            path_key = str(
                row.values.get("caminho_mcf", "")
                or ""
            ).strip()

            if not path_key:
                continue

            self.row_mcf_paths[index] = path_key
            self.mcf_groups.setdefault(path_key, []).append(index)

        try:
            parents = [str(Path(path).parent) for path in paths]
            self.mcf_folder_path = Path(os.path.commonpath(parents))
        except Exception:
            self.mcf_folder_path = Path(paths[0]).parent


    def _extract_mcf_to_csv(self):
        """
        v5: extração/OCR em thread separada.

        Assim o Tkinter continua respondendo enquanto o Tesseract trabalha.
        A thread de trabalho nunca toca diretamente nos widgets; ela envia
        mensagens para self.extract_queue, processadas pelo loop do Tkinter.
        """
        if (
            self.extract_thread is not None
            and self.extract_thread.is_alive()
        ):
            messagebox.showinfo(
                "Extração em andamento",
                "Já existe uma extração/OCR em andamento.",
            )
            return

        try:
            self._engine_settings_from_ui()
        except Exception as exc:
            messagebox.showerror(
                "Configuração",
                str(exc),
            )
            return

        mcf = self.mcf_var.get().strip()
        ft4 = self.ft4_var.get().strip()

        if not mcf:
            messagebox.showwarning(
                "MCF",
                "Selecione o MCF de origem.",
            )
            return

        if not ft4:
            messagebox.showwarning(
                "Fonte",
                "Selecione o FONTS.FT4.",
            )
            return

        try:
            if self.engine.atlas is None:
                self.engine.load_ft4(ft4)
        except Exception as exc:
            messagebox.showerror(
                "FONTS.FT4",
                str(exc),
            )
            return

        source = Path(mcf)

        suggested_name = (
            source.stem
            + "_extraido.csv"
        )

        csv_path = filedialog.asksaveasfilename(
            title="Salvar CSV extraído",
            initialfile=suggested_name,
            defaultextension=".csv",
            filetypes=[
                ("CSV", "*.csv"),
                ("Todos", "*.*"),
            ],
        )

        if not csv_path:
            return

        csv_path = Path(csv_path)

        image_dir = (
            csv_path.parent
            / (
                csv_path.stem
                + "_imagens"
            )
        )

        use_ocr = bool(
            self.ocr_jp_var.get()
        )

        tesseract_cmd = (
            self.tesseract_var.get().strip()
            or None
        )

        self.progress["value"] = 0
        self.progress["maximum"] = 100

        self.status_var.set(
            "Iniciando extração..."
        )

        self.extract_started_at = time.time()

        # limpa mensagens antigas
        try:
            while True:
                self.extract_queue.get_nowait()
        except queue.Empty:
            pass

        def worker():
            try:
                def progress(
                    current,
                    total,
                    stage,
                ):
                    self.extract_queue.put(
                        (
                            "progress",
                            current,
                            total,
                            stage,
                        )
                    )

                extracted = (
                    self.engine.extract_subtitles_from_mcf(
                        source,
                        image_dir=image_dir,
                        progress_callback=progress,
                        use_japanese_ocr=use_ocr,
                        tesseract_cmd=tesseract_cmd,
                    )
                )

                fieldnames = [
                    "id",
                    "triplet_inicio",
                    "triplet_fim",
                    "original_jp",
                    "portugues",
                    "status",
                    "ocr_score",
                    "imagem",
                ]

                save_csv_file(
                    csv_path,
                    fieldnames,
                    extracted,
                    ";",
                )

                self.extract_queue.put(
                    (
                        "done",
                        extracted,
                        fieldnames,
                        csv_path,
                        image_dir,
                    )
                )

            except Exception as exc:
                self.extract_queue.put(
                    (
                        "error",
                        str(exc),
                    )
                )

        self.extract_thread = threading.Thread(
            target=worker,
            daemon=True,
        )

        self.extract_thread.start()

        self.after(
            100,
            self._poll_extract_queue,
        )

    def _poll_extract_queue(self):
        """
        Processa mensagens da thread de OCR sem bloquear a interface.
        """
        keep_polling = False

        try:
            while True:
                message = (
                    self.extract_queue.get_nowait()
                )

                kind = message[0]

                if kind == "progress":
                    _, current, total, stage = message

                    total = max(
                        int(total),
                        1,
                    )

                    self.progress["maximum"] = total
                    self.progress["value"] = current

                    elapsed = 0
                    if self.extract_started_at is not None:
                        elapsed = int(
                            time.time()
                            - self.extract_started_at
                        )

                    if stage == "scan":
                        self.status_var.set(
                            "Procurando legendas no MCF — "
                            f"triplet {current}/{total} "
                            f"({elapsed}s)"
                        )

                    elif stage == "ocr":
                        self.status_var.set(
                            "OCR japonês — "
                            f"legenda {current}/{total} "
                            f"({elapsed}s)"
                        )

                    else:
                        self.status_var.set(
                            "Extraindo — "
                            f"{current}/{total} "
                            f"({elapsed}s)"
                        )

                    keep_polling = True

                elif kind == "done":
                    (
                        _,
                        extracted,
                        fieldnames,
                        csv_path,
                        image_dir,
                    ) = message

                    self.rows = extracted
                    self.fieldnames = fieldnames
                    self.csv_delimiter = ";"
                    self.folder_mode = False
                    self.mcf_folder_path = None
                    self.mcf_groups.clear()
                    self.row_mcf_paths.clear()
                    self.group_iid_to_path.clear()
                    self.active_mcf_path = None
                    self.generate_button.config(text="GERAR MCF")

                    self.csv_var.set(
                        str(csv_path)
                    )

                    self.search_var.set("")
                    self._populate_tree()

                    recognized_pt = sum(
                        1
                        for row in extracted
                        if row.values.get("status")
                        == "RECONHECIDO_PT"
                    )

                    recognized_jp = sum(
                        1
                        for row in extracted
                        if row.values.get("status")
                        == "OCR_JP_REVISAR"
                    )

                    total = len(extracted)

                    self.progress["maximum"] = max(
                        total,
                        1,
                    )
                    self.progress["value"] = total

                    elapsed = 0
                    if self.extract_started_at is not None:
                        elapsed = int(
                            time.time()
                            - self.extract_started_at
                        )

                    self.status_var.set(
                        f"Concluído — {total} legendas "
                        f"em {elapsed}s; "
                        f"{recognized_jp} com OCR japonês."
                    )

                    self.extract_thread = None

                    messagebox.showinfo(
                        "Extração concluída",
                        f"Legendas encontradas: {total}\n"
                        f"Texto PT reconhecido: {recognized_pt}\n"
                        f"OCR japonês: {recognized_jp}\n"
                        f"Somente bitmap: "
                        f"{total - recognized_pt - recognized_jp}\n"
                        f"Tempo: {elapsed}s\n\n"
                        f"CSV:\n{csv_path}\n\n"
                        f"Imagens:\n{image_dir}\n\n"
                        "Revise o campo Original JP antes de traduzir."
                    )

                    return

                elif kind == "error":
                    _, error_text = message

                    self.extract_thread = None

                    self.status_var.set(
                        "Erro durante extração/OCR."
                    )

                    messagebox.showerror(
                        "Extração",
                        error_text,
                    )

                    return

        except queue.Empty:
            pass

        if (
            self.extract_thread is not None
            and self.extract_thread.is_alive()
        ):
            keep_polling = True

        if keep_polling:
            self.after(
                100,
                self._poll_extract_queue,
            )

    def _browse_tesseract(self):
        path = filedialog.askopenfilename(
            title="Selecionar tesseract.exe",
            filetypes=[
                ("Tesseract", "tesseract.exe"),
                ("Executáveis", "*.exe"),
                ("Todos", "*.*"),
            ],
        )

        if path:
            self.tesseract_var.set(path)


    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Salvar MCF traduzido",
            defaultextension=".MCF",
            filetypes=[
                ("Koudelka MCF", "*.MCF"),
                ("Todos", "*.*"),
            ],
        )

        if path:
            self.output_var.set(path)

    # --------------------------- tabela -----------------------------------

    @staticmethod
    def _row_was_mass_replaced(row: SubtitleRow) -> bool:
        value = str(
            row.values.get("alterado_em_massa", "")
            or ""
        ).strip().casefold()

        return value in {
            "sim",
            "yes",
            "true",
            "1",
            "x",
            "✓",
        }

    @staticmethod
    def _row_has_ocr(row: SubtitleRow) -> bool:
        status = str(
            row.values.get("status", "")
            or ""
        ).strip().casefold()
        score = str(
            row.values.get("ocr_score", "")
            or ""
        ).strip()

        return "ocr" in status or bool(score)

    def _tree_tags_for_row(self, row: SubtitleRow) -> tuple[str, ...]:
        tags = []

        if self._row_was_mass_replaced(row):
            tags.append("mass_replaced")

        if self._row_has_ocr(row):
            tags.append("ocr_found")

        return tuple(tags)

    def _matching_row_indices(self) -> list[int]:
        query = self.search_var.get().strip()
        ocr_only = bool(self.ocr_found_only_var.get())

        case_sensitive = bool(
            self.case_sensitive_var.get()
        )

        needle = (
            query
            if case_sensitive
            else query.casefold()
        )

        matches = []

        for index, row in enumerate(self.rows):
            if ocr_only and not self._row_has_ocr(row):
                continue

            if not query:
                matches.append(index)
                continue

            searchable = "\n".join(
                [
                    str(row.id),
                    str(row.triplet_start),
                    str(row.triplet_end),
                    str(row.values.get("arquivo_mcf", "")),
                    str(row.values.get("caminho_mcf", "")),
                    row.original_jp,
                    row.text,
                ]
            )

            haystack = (
                searchable
                if case_sensitive
                else searchable.casefold()
            )

            if needle in haystack:
                matches.append(index)

        return matches

    def _tree_values_for_row(
        self,
        row: SubtitleRow,
    ) -> tuple:
        status, _ = self._status_for_row(row)
        changed = self._row_was_mass_replaced(row)
        has_ocr = self._row_has_ocr(row)

        return (
            "✓" if changed else "",
            "✓" if has_ocr else "",
            row.id,
            row.triplet_start,
            row.triplet_end,
            row.original_jp,
            row.text,
            status,
        )

    def _on_search_changed(self, _event=None):
        if not hasattr(self, "tree"):
            return

        matches = self._matching_row_indices()
        self._populate_tree(preserve_selection=True)

        query = self.search_var.get().strip()
        if query or self.ocr_found_only_var.get():
            filter_name = (
                "OCR encontrados"
                if self.ocr_found_only_var.get()
                else "pesquisa"
            )
            self.status_var.set(
                f"Filtro {filter_name}: {len(matches)} de "
                f"{len(self.rows)} legenda(s)."
            )

    def _clear_search(self):
        self.search_var.set("")
        self.ocr_found_only_var.set(False)
        self._populate_tree(preserve_selection=True)
        self.status_var.set(
            f"Pesquisa limpa — {len(self.rows)} legenda(s)."
        )

    def _select_next_search_match(self, _event=None):
        visible = []

        for root_iid in self.tree.get_children():
            if root_iid in self.group_iid_to_path:
                visible.extend(self.tree.get_children(root_iid))
            else:
                visible.append(root_iid)

        if not visible:
            self.status_var.set("Nenhuma legenda encontrada na pesquisa.")
            return "break"

        selected = self.tree.selection()

        if selected and selected[0] in visible:
            position = visible.index(selected[0])
            target = visible[(position + 1) % len(visible)]
        else:
            target = visible[0]

        self.tree.selection_set(target)
        self.tree.focus(target)
        self.tree.see(target)

        parent = self.tree.parent(target)
        if parent:
            self.tree.item(parent, open=True)
            self._set_group_checkbox(parent, True)

        self._on_tree_select()
        return "break"

    def _replace_all(self):
        if not self.rows:
            messagebox.showwarning(
                "Substituição em massa",
                "Carregue ou extraia um CSV primeiro.",
            )
            return

        search_text = self.search_var.get().strip()
        replacement = self.replace_var.get()

        if not search_text:
            messagebox.showwarning(
                "Substituição em massa",
                "Digite a palavra ou expressão que deseja substituir.",
            )
            return

        if self.current_index is not None:
            self._apply_current_edit()

        escaped = re.escape(search_text)

        if self.whole_word_var.get():
            escaped = rf"(?<!\w){escaped}(?!\w)"

        flags = (
            0
            if self.case_sensitive_var.get()
            else re.IGNORECASE
        )

        try:
            pattern = re.compile(escaped, flags)
        except re.error as exc:
            messagebox.showerror(
                "Substituição em massa",
                f"Pesquisa inválida:\n\n{exc}",
            )
            return

        changes = []
        occurrence_count = 0

        for index, row in enumerate(self.rows):
            new_text, count = pattern.subn(
                lambda _match: replacement,
                row.text,
            )

            if count and new_text != row.text:
                changes.append((index, new_text, count))
                occurrence_count += count

        if not changes:
            messagebox.showinfo(
                "Substituição em massa",
                "Nenhuma ocorrência diferente foi encontrada "
                "no texto em português.",
            )
            return

        confirmed = messagebox.askyesno(
            "Confirmar substituição em massa",
            f"Substituir '{search_text}' por '{replacement}'?\n\n"
            f"Ocorrências: {occurrence_count}\n"
            f"Legendas afetadas: {len(changes)}\n\n"
            "As linhas modificadas receberão ✓ e destaque amarelo.",
        )

        if not confirmed:
            return

        for index, new_text, _count in changes:
            row = self.rows[index]
            row.text = new_text
            row.values["alterado_em_massa"] = "SIM"

        if "alterado_em_massa" not in self.fieldnames:
            self.fieldnames.append("alterado_em_massa")

        # Exibe todas as linhas para que os ✓ recém-criados fiquem visíveis.
        self.search_var.set("")
        self._populate_tree()

        first_index = changes[0][0]
        first_iid = str(first_index)

        if self.tree.exists(first_iid):
            self.tree.selection_set(first_iid)
            self.tree.focus(first_iid)
            self.tree.see(first_iid)
            self._on_tree_select()

        self.status_var.set(
            f"Substituição concluída: {occurrence_count} ocorrência(s) "
            f"em {len(changes)} legenda(s)."
        )

        messagebox.showinfo(
            "Substituição concluída",
            f"Ocorrências substituídas: {occurrence_count}\n"
            f"Legendas modificadas: {len(changes)}\n\n"
            "As linhas estão marcadas com ✓ e fundo amarelo.\n"
            "Use 'Salvar CSV' para gravar as alterações.",
        )

    def _engine_settings_from_ui(self):
        try:
            max_width = int(
                self.max_width_var.get().strip()
            )
        except ValueError:
            raise ValueError(
                "Largura máxima inválida."
            )

        if not 1 <= max_width <= self.engine.cfg.canvas_width:
            raise ValueError(
                "Largura máxima deve ficar entre 1 e 300."
            )

        self.engine.cfg.max_line_width = max_width

        try:
            ttf_size = int(self.ttf_size_var.get().strip())
        except ValueError:
            raise ValueError("Tamanho TTF inválido.")

        if not 8 <= ttf_size <= 16:
            raise ValueError("Tamanho TTF deve ficar entre 8 e 16.")

        if self.engine.cfg.ttf_font_size != ttf_size:
            self.engine.cfg.ttf_font_size = ttf_size
            self.engine._ttf_line_cache.clear()

        self.engine.cfg.render_mode = (
            "ttf"
            if self.render_mode_var.get() == "Tahoma Bold (TTF)"
            else "ft4"
        )

        if self.engine.cfg.render_mode == "ttf":
            ttf_path = self.ttf_var.get().strip()
            if not ttf_path:
                raise ValueError("Selecione uma fonte TTF/OTF.")
            if (
                self.engine.ttf_path is None
                or str(self.engine.ttf_path) != ttf_path
            ):
                self.engine.load_ttf(ttf_path)

        self.engine.cfg.baseline_mode = (
            "native_y"
            if self.baseline_var.get() == "Y nativo do FT4"
            else "normalized"
        )

        self.engine._glyph_cache.clear()

    def _status_for_row(
        self,
        row: SubtitleRow,
    ) -> tuple[str, str]:
        if not self.engine.font_ready:
            return "SEM FONTE", ""

        try:
            ok, description, _ = (
                self.engine.validate_text(
                    row.text
                )
            )

            return (
                "OK" if ok else "NÃO CABE",
                description,
            )

        except Exception as exc:
            return "ERRO", str(exc)

    def _populate_tree(self, preserve_selection=False):
        if self.folder_mode:
            self.tree.heading("#0", text="Arquivo MCF")
            self.tree.column(
                "#0",
                width=190,
                minwidth=120,
                stretch=True,
            )
        else:
            self.tree.heading("#0", text="")
            self.tree.column(
                "#0",
                width=0,
                minwidth=0,
                stretch=False,
            )

        selected_index = (
            self.current_index
            if preserve_selection
            else None
        )

        open_group_paths = {
            self.group_iid_to_path[iid]
            for iid in self.tree.get_children()
            if iid in self.group_iid_to_path
            and bool(self.tree.item(iid, "open"))
        }

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.group_iid_to_path.clear()

        if not preserve_selection:
            self.current_index = None

        matching_indices = self._matching_row_indices()
        matching_set = set(matching_indices)
        filter_active = (
            bool(self.search_var.get().strip())
            or bool(self.ocr_found_only_var.get())
        )

        if self.folder_mode and self.mcf_groups:
            for group_number, (path_key, all_indices) in enumerate(
                self.mcf_groups.items()
            ):
                visible_indices = [
                    index
                    for index in all_indices
                    if index in matching_set
                ]

                if filter_active and not visible_indices:
                    continue

                group_iid = f"group::{group_number}"
                self.group_iid_to_path[group_iid] = path_key

                path = Path(path_key)
                try:
                    display_name = str(
                        path.relative_to(self.mcf_folder_path)
                    )
                except Exception:
                    display_name = path.name

                is_open = filter_active or path_key in open_group_paths
                count_text = (
                    f"{len(visible_indices)}/{len(all_indices)}"
                    if filter_active
                    else str(len(all_indices))
                )
                ocr_count = sum(
                    1
                    for index in all_indices
                    if self._row_has_ocr(self.rows[index])
                )
                ocr_label = (
                    f"  ⚠ OCR: {ocr_count}"
                    if ocr_count
                    else ""
                )

                self.tree.insert(
                    "",
                    tk.END,
                    iid=group_iid,
                    text=(
                        f"{'☑' if is_open else '☐'} "
                        f"{display_name} ({count_text}){ocr_label}"
                    ),
                    open=is_open,
                    values=("", "", "", "", "", "", "", ""),
                    tags=(
                        "mcf_group_ocr" if ocr_count else "mcf_group",
                    ),
                )

                for index in visible_indices:
                    row = self.rows[index]
                    self.tree.insert(
                        group_iid,
                        tk.END,
                        iid=str(index),
                        text="",
                        values=self._tree_values_for_row(row),
                        tags=self._tree_tags_for_row(row),
                    )

        else:
            for index in matching_indices:
                row = self.rows[index]
                self.tree.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=self._tree_values_for_row(row),
                    tags=self._tree_tags_for_row(row),
                )

        if selected_index is not None:
            iid = str(selected_index)
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self.tree.see(iid)

    def _set_group_checkbox(self, iid: str, is_open: bool):
        if iid not in self.group_iid_to_path or not self.tree.exists(iid):
            return

        current_text = str(self.tree.item(iid, "text"))
        label = current_text[2:] if current_text[:2] in {"☐ ", "☑ "} else current_text
        self.tree.item(
            iid,
            text=f"{'☑' if is_open else '☐'} {label}",
        )

    def _on_tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)

        if iid in self.group_iid_to_path and column == "#0":
            new_state = not bool(self.tree.item(iid, "open"))
            self.tree.item(iid, open=new_state)
            self._set_group_checkbox(iid, new_state)
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self._on_tree_select()
            return "break"

        return None

    def _on_group_opened(self, _event=None):
        iid = self.tree.focus()
        self.after_idle(
            lambda target=iid: self._set_group_checkbox(target, True)
        )

    def _on_group_closed(self, _event=None):
        iid = self.tree.focus()
        self.after_idle(
            lambda target=iid: self._set_group_checkbox(target, False)
        )

    def _refresh_tree_statuses(self):
        if not self.rows:
            return

        try:
            self._engine_settings_from_ui()
        except Exception:
            pass

        for index, row in enumerate(self.rows):
            iid = str(index)

            if not self.tree.exists(iid):
                continue

            self.tree.item(
                iid,
                values=self._tree_values_for_row(row),
                tags=self._tree_tags_for_row(row),
            )

    def _on_tree_select(self, _event=None):
        selection = self.tree.selection()

        if not selection:
            return

        iid = selection[0]

        if iid in self.group_iid_to_path:
            path_key = self.group_iid_to_path[iid]
            self.active_mcf_path = path_key
            self.current_index = None
            self.mcf_var.set(path_key)
            source = Path(path_key)
            self.output_var.set(
                str(source.with_name(source.stem + "_PTBR.MCF"))
            )
            self.id_label.config(text=f"Arquivo: {source.name}")
            self.start_var.set("")
            self.end_var.set("")
            self.jp_edit.delete("1.0", tk.END)
            self.text_edit.delete("1.0", tk.END)
            self.preview_tk = None
            self.preview_label.config(image="")
            group_indices = self.mcf_groups.get(path_key, [])
            ocr_count = sum(
                1
                for index in group_indices
                if self._row_has_ocr(self.rows[index])
            )
            self.validation_label.config(
                text=(
                    f"{len(group_indices)} legenda(s); "
                    f"OCR encontrados: {ocr_count}. "
                    "Use ☐/☑ para recolher ou ampliar o grupo."
                )
            )
            return

        try:
            index = int(iid)
        except ValueError:
            return

        if not (
            0 <= index < len(self.rows)
        ):
            return

        self.current_index = index
        row = self.rows[index]

        if self.folder_mode:
            path_key = self.row_mcf_paths.get(index)
            if path_key:
                self.active_mcf_path = path_key
                self.mcf_var.set(path_key)
                source = Path(path_key)
                self.output_var.set(
                    str(source.with_name(source.stem + "_PTBR.MCF"))
                )

        self.id_label.config(
            text=row.id
        )

        self.start_var.set(
            str(row.triplet_start)
        )
        self.end_var.set(
            str(row.triplet_end)
        )

        self.jp_edit.delete(
            "1.0",
            tk.END,
        )
        self.jp_edit.insert(
            "1.0",
            row.original_jp,
        )

        self.text_edit.delete(
            "1.0",
            tk.END,
        )
        self.text_edit.insert(
            "1.0",
            row.text,
        )

        self._update_current_validation()
        self._preview_current(show_errors=False)

    def _apply_current_edit(self):
        if self.current_index is None:
            return

        try:
            start = int(
                self.start_var.get().strip()
            )
            end = int(
                self.end_var.get().strip()
            )
        except ValueError:
            messagebox.showerror(
                "Valor inválido",
                "Triplets devem ser números inteiros.",
            )
            return

        text = self.text_edit.get(
            "1.0",
            "end-1c",
        ).strip()

        row = self.rows[
            self.current_index
        ]

        row.triplet_start = start
        row.triplet_end = end
        row.original_jp = self.jp_edit.get(
            "1.0",
            "end-1c",
        ).strip()
        row.text = text

        self._refresh_tree_statuses()

        self.tree.selection_set(
            str(self.current_index)
        )

        self._update_current_validation()

    def _update_current_validation(self):
        if self.current_index is None:
            self.validation_label.config(
                text=""
            )
            return

        try:
            self._engine_settings_from_ui()
        except Exception as exc:
            self.validation_label.config(
                text=str(exc),
            )
            return

        text = self.text_edit.get(
            "1.0",
            "end-1c",
        ).strip()

        if not self.engine.font_ready:
            self.validation_label.config(
                text="Carregue a fonte selecionada para calcular a largura."
            )
            return

        ok, description, _ = (
            self.engine.validate_text(text)
        )

        self.validation_label.config(
            text=(
                ("OK — " if ok else "NÃO CABE — ")
                + description
            )
        )

    # --------------------------- preview ----------------------------------

    def _schedule_preview(self, _event=None):
        """Atualiza a imagem pouco depois da última tecla digitada."""
        if self.preview_after_id is not None:
            try:
                self.after_cancel(self.preview_after_id)
            except Exception:
                pass

        self.preview_after_id = self.after(
            180,
            lambda: self._preview_current(show_errors=False),
        )

    def _preview_current(self, show_errors=True):
        self.preview_after_id = None

        try:
            self._engine_settings_from_ui()
        except Exception as exc:
            if show_errors:
                messagebox.showerror(
                    "Configuração",
                    str(exc),
                )
            return

        if not self.engine.font_ready:
            if show_errors:
                messagebox.showwarning(
                    "Fonte",
                    "Selecione a fonte configurada primeiro.",
                )
            return

        text = self.text_edit.get(
            "1.0",
            "end-1c",
        ).strip()

        if not text:
            self.preview_tk = None
            self.preview_label.config(image="")
            self._update_current_validation()
            return

        try:
            img = self.engine.preview_image(
                text,
                scale=2,
            )
        except Exception as exc:
            self.preview_tk = None
            self.preview_label.config(image="")
            if show_errors:
                messagebox.showerror(
                    "Preview",
                    str(exc),
                )
            else:
                self._update_current_validation()
            return

        self.preview_tk = ImageTk.PhotoImage(
            img
        )

        self.preview_label.config(
            image=self.preview_tk
        )

        self._update_current_validation()

    def _export_preview_images(self):
        """Exporta uma imagem PNG de cada tradução carregada."""
        if not self.rows:
            messagebox.showwarning(
                "Previews PNG",
                "Carregue ou extraia um CSV primeiro.",
            )
            return

        if self.current_index is not None:
            self._apply_current_edit()

        try:
            self._engine_settings_from_ui()
        except Exception as exc:
            messagebox.showerror(
                "Configuração",
                str(exc),
            )
            return

        if not self.engine.font_ready:
            messagebox.showwarning(
                "Fonte",
                "Selecione a fonte configurada primeiro.",
            )
            return

        errors = []

        for row in self.rows:
            if not row.text.strip():
                errors.append(
                    f"ID {row.id}: tradução vazia."
                )
                continue

            ok, description, _ = self.engine.validate_text(
                row.text
            )

            if not ok:
                errors.append(
                    f"ID {row.id}: {description}"
                )

        if errors:
            messagebox.showerror(
                "Previews PNG",
                "Corrija as legendas antes de exportar:\n\n"
                + "\n".join(errors[:12])
                + ("\n..." if len(errors) > 12 else ""),
            )
            return

        current_csv = self.csv_var.get().strip()
        initial_dir = (
            str(Path(current_csv).parent)
            if current_csv
            else str(Path.cwd())
        )

        selected_dir = filedialog.askdirectory(
            title="Escolher onde criar a pasta de previews",
            initialdir=initial_dir,
        )

        if not selected_dir:
            return

        output_dir = Path(selected_dir) / "PREVIEWS_PTBR"
        output_dir.mkdir(parents=True, exist_ok=True)

        self.progress["maximum"] = max(len(self.rows), 1)
        self.progress["value"] = 0

        try:
            for index, row in enumerate(self.rows, start=1):
                image = self.engine.preview_image(
                    row.text,
                    scale=4,
                )

                safe_id = re.sub(
                    r"[^A-Za-z0-9_-]+",
                    "_",
                    str(row.id).strip(),
                ).strip("_") or str(index)

                filename = (
                    f"{index:03d}_ID_{safe_id}_"
                    f"{row.triplet_start}-{row.triplet_end}.png"
                )

                image.save(output_dir / filename)
                self.progress["value"] = index
                self.update_idletasks()

        except Exception as exc:
            messagebox.showerror(
                "Previews PNG",
                f"Não foi possível exportar as imagens:\n\n{exc}",
            )
            return

        self.status_var.set(
            f"{len(self.rows)} previews PNG exportados."
        )

        open_folder = messagebox.askyesno(
            "Previews PNG",
            f"Imagens exportadas: {len(self.rows)}\n\n"
            f"Pasta:\n{output_dir}\n\n"
            "Deseja abrir a pasta agora?",
        )

        if open_folder:
            try:
                os.startfile(output_dir)
            except Exception:
                pass

    # --------------------------- CSV --------------------------------------


    @staticmethod
    def _read_flexible_csv(path):
        """
        Lê CSV UTF-8/UTF-8-BOM e detecta ; ou , automaticamente.
        """
        path = Path(path)

        raw_text = path.read_text(
            encoding="utf-8-sig",
        )

        first_line = (
            raw_text.splitlines()[0]
            if raw_text
            else ""
        )

        delimiter = (
            ";"
            if first_line.count(";")
            >= first_line.count(",")
            else ","
        )

        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(
                file,
                delimiter=delimiter,
            )

            fieldnames = list(
                reader.fieldnames
                or []
            )

            rows = [
                dict(row)
                for row in reader
            ]

        return fieldnames, rows, delimiter

    @staticmethod
    def _normalize_header(value):
        """
        Normaliza nome de coluna para aceitar, por exemplo:
        Português, portugues, PT-BR, tradução, translation...
        """
        value = str(value or "").strip().lower()

        value = unicodedata.normalize(
            "NFD",
            value,
        )

        value = "".join(
            ch
            for ch in value
            if unicodedata.category(ch)
            != "Mn"
        )

        for old, new in [
            ("-", "_"),
            (" ", "_"),
            ("/", "_"),
        ]:
            value = value.replace(
                old,
                new,
            )

        while "__" in value:
            value = value.replace(
                "__",
                "_",
            )

        return value.strip("_")

    def _export_translation_csv(self):
        """
        Exporta uma versão limpa do CSV para tradução em massa.

        O tradutor só precisa preencher a coluna 'portugues'.
        IDs e triplets servem para reimportação segura.
        """
        if not self.rows:
            messagebox.showwarning(
                "Tradução em massa",
                "Carregue ou extraia um CSV primeiro.",
            )
            return

        if self.current_index is not None:
            self._apply_current_edit()

        current = self.csv_var.get().strip()

        if current:
            default_name = (
                Path(current).stem
                + "_PARA_TRADUZIR.csv"
            )
        else:
            default_name = (
                "legendas_PARA_TRADUZIR.csv"
            )

        path = filedialog.asksaveasfilename(
            title="Exportar CSV para tradução em massa",
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[
                ("CSV", "*.csv"),
                ("Todos", "*.*"),
            ],
        )

        if not path:
            return

        export_fields = [
            "id",
            "triplet_inicio",
            "triplet_fim",
            "original_jp",
            "portugues",
        ]

        if self.folder_mode:
            export_fields = [
                "arquivo_mcf",
                "caminho_mcf",
            ] + export_fields

        with Path(path).open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=export_fields,
                delimiter=";",
            )

            writer.writeheader()

            for row in self.rows:
                export_row = {
                    "id": row.id,
                    "triplet_inicio": (
                        row.values.get(
                            "triplet_inicio",
                            "",
                        )
                    ),
                    "triplet_fim": (
                        row.values.get(
                            "triplet_fim",
                            "",
                        )
                    ),
                    "original_jp": (
                        row.original_jp
                    ),
                    "portugues": (
                        row.text
                    ),
                }

                if self.folder_mode:
                    export_row["arquivo_mcf"] = row.values.get(
                        "arquivo_mcf", ""
                    )
                    export_row["caminho_mcf"] = row.values.get(
                        "caminho_mcf", ""
                    )

                writer.writerow(export_row)

        self.status_var.set(
            "CSV para tradução em massa exportado."
        )

        messagebox.showinfo(
            "CSV exportado",
            "Arquivo pronto para tradução em massa.\n\n"
            "Traduza somente a coluna 'portugues'.\n"
            "Não altere id, triplet_inicio ou triplet_fim.\n\n"
            + str(path),
        )

    def _import_translation_csv(self):
        """
        Mescla traduções de outro CSV na lista atualmente carregada.

        Prioridade de correspondência:
          1) id
          2) triplet_inicio + triplet_fim
          3) ordem das linhas, somente após confirmação

        Apenas a tradução PT-BR é importada. Timings, japonês, imagens e
        demais dados do projeto atual são preservados.
        """
        if not self.rows:
            messagebox.showwarning(
                "Importar traduções",
                "Primeiro carregue ou extraia o CSV base do MCF.",
            )
            return

        if self.current_index is not None:
            self._apply_current_edit()

        path = filedialog.askopenfilename(
            title="Selecionar CSV traduzido para PT-BR",
            filetypes=[
                ("CSV", "*.csv"),
                ("Todos", "*.*"),
            ],
        )

        if not path:
            return

        try:
            (
                imported_fields,
                imported_rows,
                imported_delimiter,
            ) = self._read_flexible_csv(
                path
            )
        except Exception as exc:
            messagebox.showerror(
                "Importar traduções",
                f"Não foi possível ler o CSV:\n\n{exc}",
            )
            return

        if not imported_rows:
            messagebox.showwarning(
                "Importar traduções",
                "O CSV selecionado está vazio.",
            )
            return

        # Header real -> header normalizado
        normalized = {
            self._normalize_header(name): name
            for name in imported_fields
        }

        # Vários nomes aceitos para PT-BR.
        translation_aliases = [
            "portugues",
            "portuguese",
            "ptbr",
            "pt_br",
            "pt_brasil",
            "pt_brazil",
            "traducao",
            "traducao_ptbr",
            "traducao_pt_br",
            "translation",
            "translated",
            "texto_ptbr",
            "texto_pt_br",
        ]

        translation_column = None

        for alias in translation_aliases:
            if alias in normalized:
                translation_column = normalized[
                    alias
                ]
                break

        if translation_column is None:
            messagebox.showerror(
                "Importar traduções",
                "Não encontrei a coluna de tradução.\n\n"
                "Use uma coluna chamada, por exemplo:\n"
                "portugues\n"
                "ptbr\n"
                "traducao\n"
                "translation",
            )
            return

        id_column = normalized.get("id")
        mcf_column = (
            normalized.get("caminho_mcf")
            or normalized.get("arquivo_mcf")
            or normalized.get("mcf")
        )
        start_column = (
            normalized.get("triplet_inicio")
            or normalized.get("triplet_start")
            or normalized.get("inicio")
        )
        end_column = (
            normalized.get("triplet_fim")
            or normalized.get("triplet_end")
            or normalized.get("fim")
        )

        current_by_id = {
            str(row.id).strip(): row
            for row in self.rows
            if str(row.id).strip()
        }

        current_by_mcf_id = {
            (
                str(
                    row.values.get("caminho_mcf", "")
                    or row.values.get("arquivo_mcf", "")
                ).strip().casefold(),
                str(row.id).strip(),
            ): row
            for row in self.rows
            if str(row.id).strip()
        }

        current_by_triplet = {
            (
                str(
                    row.values.get(
                        "triplet_inicio",
                        "",
                    )
                ).strip(),
                str(
                    row.values.get(
                        "triplet_fim",
                        "",
                    )
                ).strip(),
            ): row
            for row in self.rows
        }

        current_by_mcf_triplet = {
            (
                str(
                    row.values.get("caminho_mcf", "")
                    or row.values.get("arquivo_mcf", "")
                ).strip().casefold(),
                str(row.values.get("triplet_inicio", "")).strip(),
                str(row.values.get("triplet_fim", "")).strip(),
            ): row
            for row in self.rows
        }

        updated = 0
        blank = 0
        unmatched = 0
        duplicate = 0
        matched_ids = set()

        # Decide se existe uma chave confiável.
        use_id = bool(id_column)
        use_triplet = bool(
            start_column
            and end_column
        )

        if self.folder_mode and not mcf_column:
            messagebox.showerror(
                "Importar traduções",
                "No modo pasta, o CSV traduzido precisa manter a coluna "
                "caminho_mcf ou arquivo_mcf.\n\nExporte novamente usando "
                "'Exportar para tradução' para obter um arquivo seguro.",
            )
            return

        if not use_id and not use_triplet:
            if (
                len(imported_rows)
                != len(self.rows)
            ):
                messagebox.showerror(
                    "Importar traduções",
                    "O CSV não possui ID nem triplets e a quantidade "
                    "de linhas é diferente do projeto atual.\n\n"
                    "Não é seguro importar por ordem.",
                )
                return

            answer = messagebox.askyesno(
                "Importar por ordem",
                "O CSV traduzido não possui ID nem triplets.\n\n"
                f"Ele tem {len(imported_rows)} linhas, exatamente como "
                "o CSV atual.\n\n"
                "Deseja associar as traduções pela ordem das linhas?",
            )

            if not answer:
                return

            for current_row, imported_row in zip(
                self.rows,
                imported_rows,
            ):
                translated = str(
                    imported_row.get(
                        translation_column,
                        "",
                    )
                    or ""
                ).strip()

                if not translated:
                    blank += 1
                    continue

                current_row.text = translated
                updated += 1

        else:
            for imported_row in imported_rows:
                target = None
                target_key = None
                imported_mcf = ""

                if mcf_column:
                    imported_mcf = str(
                        imported_row.get(mcf_column, "")
                        or ""
                    ).strip().casefold()

                if use_id:
                    imported_id = str(
                        imported_row.get(
                            id_column,
                            "",
                        )
                        or ""
                    ).strip()

                    if imported_id:
                        if self.folder_mode:
                            target = current_by_mcf_id.get(
                                (imported_mcf, imported_id)
                            )
                        else:
                            target = current_by_id.get(imported_id)
                        target_key = (
                            "id",
                            imported_id,
                        )

                if (
                    target is None
                    and use_triplet
                ):
                    start_value = str(
                        imported_row.get(
                            start_column,
                            "",
                        )
                        or ""
                    ).strip()

                    end_value = str(
                        imported_row.get(
                            end_column,
                            "",
                        )
                        or ""
                    ).strip()

                    if (
                        start_value
                        or end_value
                    ):
                        if self.folder_mode:
                            target = current_by_mcf_triplet.get(
                                (
                                    imported_mcf,
                                    start_value,
                                    end_value,
                                )
                            )
                        else:
                            target = current_by_triplet.get(
                                (
                                    start_value,
                                    end_value,
                                )
                            )

                        target_key = (
                            "triplet",
                            start_value,
                            end_value,
                        )

                if target is None:
                    unmatched += 1
                    continue

                unique_target = id(target)

                if unique_target in matched_ids:
                    duplicate += 1
                    continue

                translated = str(
                    imported_row.get(
                        translation_column,
                        "",
                    )
                    or ""
                ).strip()

                if not translated:
                    blank += 1
                    continue

                target.text = translated
                matched_ids.add(
                    unique_target
                )
                updated += 1

        # Garante que a coluna portugues estará presente ao salvar.
        if (
            self.fieldnames
            and "portugues"
            not in self.fieldnames
        ):
            self.fieldnames.append(
                "portugues"
            )

        self._refresh_tree_statuses()

        if self.current_index is not None:
            iid = str(
                self.current_index
            )

            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self._on_tree_select()

        self.status_var.set(
            f"Traduções importadas: {updated}."
        )

        messagebox.showinfo(
            "Importação concluída",
            f"Traduções aplicadas: {updated}\n"
            f"Linhas sem tradução: {blank}\n"
            f"Sem correspondência: {unmatched}\n"
            f"Duplicadas ignoradas: {duplicate}\n\n"
            "Os triplets e o japonês original foram preservados.",
        )


    def _save_csv(self):
        if not self.rows:
            messagebox.showwarning(
                "CSV",
                "Nenhum CSV carregado.",
            )
            return

        # aplica edição aberta
        if self.current_index is not None:
            self._apply_current_edit()

        current = self.csv_var.get().strip()

        path = filedialog.asksaveasfilename(
            title="Salvar CSV",
            initialfile=(
                Path(current).name
                if current
                else "legendas.csv"
            ),
            defaultextension=".csv",
            filetypes=[
                ("CSV", "*.csv"),
                ("Todos", "*.*"),
            ],
        )

        if not path:
            return

        try:
            save_csv_file(
                path,
                self.fieldnames,
                self.rows,
                self.csv_delimiter,
            )
        except Exception as exc:
            messagebox.showerror(
                "Salvar CSV",
                str(exc),
            )
            return

        self.csv_var.set(path)
        self.status_var.set(
            "CSV salvo."
        )

    # -------------------------- validação ---------------------------------

    def _validate_all(self):
        if not self.rows:
            return

        try:
            self._engine_settings_from_ui()
        except Exception as exc:
            messagebox.showerror(
                "Configuração",
                str(exc),
            )
            return

        if not self.engine.font_ready:
            messagebox.showwarning(
                "Fonte",
                "Carregue a fonte selecionada.",
            )
            return

        errors = []

        for row in self.rows:
            ok, description, _ = (
                self.engine.validate_text(
                    row.text
                )
            )

            if not ok:
                errors.append(
                    f"ID {row.id}: {description}"
                )

        self._refresh_tree_statuses()

        if errors:
            messagebox.showwarning(
                "Validação",
                f"{len(errors)} legenda(s) precisam de ajuste.\n\n"
                + "\n".join(errors[:12])
                + (
                    "\n..."
                    if len(errors) > 12
                    else ""
                ),
            )
        else:
            messagebox.showinfo(
                "Validação",
                f"Todas as {len(self.rows)} legendas cabem.",
            )

    # -------------------------- geração -----------------------------------

    @staticmethod
    def _csv_fields_for_rows(rows: list[SubtitleRow]) -> list[str]:
        preferred = [
            "id",
            "triplet_inicio",
            "triplet_fim",
            "original_jp",
            "portugues",
            "status",
            "ocr_score",
            "imagem",
            "alterado_em_massa",
            "arquivo_mcf",
            "caminho_mcf",
            "csv_origem",
        ]
        fields = []

        for name in preferred:
            if any(name in row.values for row in rows):
                fields.append(name)

        for row in rows:
            for name in row.values:
                if name not in fields:
                    fields.append(name)

        return fields

    def _generate_folder_batch(self):
        if not self.mcf_groups:
            messagebox.showwarning(
                "Gerar MCFs em massa",
                "Nenhum grupo MCF foi carregado.",
            )
            return

        source_root = self.mcf_folder_path
        if source_root is None:
            source_root = Path(
                os.path.commonpath(
                    [str(Path(path).parent) for path in self.mcf_groups]
                )
            )

        output_root = source_root / "MCF_TRADUZIDOS"
        errors = []
        prepared_groups = []

        # Valida todos os arquivos antes de criar a pasta ou gravar saídas.
        for path_key, indices in self.mcf_groups.items():
            source_mcf = Path(path_key)
            group_rows = [self.rows[index] for index in indices]

            if not source_mcf.is_file():
                errors.append(f"{source_mcf.name}: arquivo de origem ausente.")
                continue

            if not group_rows:
                errors.append(f"{source_mcf.name}: nenhuma legenda carregada.")
                continue

            for row in group_rows:
                text = row.text.strip()

                if not text:
                    errors.append(
                        f"{source_mcf.name} — ID {row.id}: tradução vazia."
                    )
                    continue

                ok, description, _ = self.engine.validate_text(text)
                if not ok:
                    errors.append(
                        f"{source_mcf.name} — ID {row.id}: {description}"
                    )

            try:
                relative_mcf = source_mcf.relative_to(source_root)
            except ValueError:
                relative_mcf = Path(source_mcf.name)

            target_mcf = output_root / relative_mcf
            target_csv = target_mcf.with_suffix(".csv")
            prepared_groups.append(
                (source_mcf, group_rows, target_mcf, target_csv)
            )

        if errors:
            messagebox.showerror(
                "Gerar MCFs em massa",
                f"Corrija {len(errors)} problema(s) antes de gerar:\n\n"
                + "\n".join(errors[:15])
                + ("\n..." if len(errors) > 15 else ""),
            )
            return

        total_rows = sum(len(item[1]) for item in prepared_groups)
        confirmed = messagebox.askyesno(
            "Gerar MCFs em massa",
            f"Gerar {len(prepared_groups)} MCF(s) e seus CSVs?\n\n"
            f"Legendas: {total_rows}\n"
            f"Pasta de saída:\n{output_root}\n\n"
            "Arquivos de mesmo nome já existentes serão substituídos.",
        )

        if not confirmed:
            return

        generated = []
        processed_rows = 0
        self.progress["maximum"] = max(total_rows, 1)
        self.progress["value"] = 0

        try:
            for file_number, (
                source_mcf,
                group_rows,
                target_mcf,
                target_csv,
            ) in enumerate(prepared_groups, start=1):
                target_mcf.parent.mkdir(parents=True, exist_ok=True)
                row_offset = processed_rows

                def progress(current, total, row_id):
                    self.progress["value"] = row_offset + current
                    self.status_var.set(
                        f"Gerando {source_mcf.name} — "
                        f"arquivo {file_number}/{len(prepared_groups)}, "
                        f"ID {row_id} ({current}/{total})"
                    )
                    self.update_idletasks()

                self.engine.generate_mcf(
                    source_mcf,
                    group_rows,
                    target_mcf,
                    progress_callback=progress,
                )

                csv_rows = []
                for row in group_rows:
                    values = dict(row.values)
                    values["arquivo_mcf"] = target_mcf.name
                    values["caminho_mcf"] = str(target_mcf)
                    values["csv_origem"] = str(target_csv)
                    csv_rows.append(SubtitleRow(values))

                csv_fields = self._csv_fields_for_rows(csv_rows)
                save_csv_file(
                    target_csv,
                    csv_fields,
                    csv_rows,
                    ";",
                )

                processed_rows += len(group_rows)
                self.progress["value"] = processed_rows
                generated.append((target_mcf, target_csv))
                self.update_idletasks()

        except Exception as exc:
            self.status_var.set("Erro na geração em massa.")
            messagebox.showerror(
                "Gerar MCFs em massa",
                f"A geração parou após {len(generated)} arquivo(s).\n\n{exc}",
            )
            return

        self.output_var.set(str(output_root))
        self.progress["value"] = total_rows
        self.status_var.set(
            f"Geração em massa concluída: {len(generated)} MCF(s) e CSV(s)."
        )

        open_folder = messagebox.askyesno(
            "Geração concluída",
            f"MCFs gerados: {len(generated)}\n"
            f"CSVs gerados: {len(generated)}\n"
            f"Legendas processadas: {total_rows}\n\n"
            f"Pasta:\n{output_root}\n\n"
            "Deseja abrir a pasta agora?",
        )

        if open_folder:
            try:
                os.startfile(output_root)
            except Exception:
                pass

    def _generate(self):
        if self.current_index is not None:
            self._apply_current_edit()

        try:
            self._engine_settings_from_ui()
        except Exception as exc:
            messagebox.showerror(
                "Configuração",
                str(exc),
            )
            return

        ft4 = self.ft4_var.get().strip()

        if self.folder_mode:
            try:
                if (
                    self.engine.cfg.render_mode == "ft4"
                    and self.engine.atlas is None
                ):
                    if not ft4:
                        raise RuntimeError("Selecione o FONTS.FT4.")
                    self.engine.load_ft4(ft4)

                if not self.engine.font_ready:
                    raise RuntimeError(
                        "A fonte selecionada não está carregada."
                    )

            except Exception as exc:
                messagebox.showerror("Fonte", str(exc))
                return

            self._generate_folder_batch()
            return

        mcf = self.mcf_var.get().strip()
        output = self.output_var.get().strip()
        rows_to_generate = self.rows

        if not mcf:
            messagebox.showwarning(
                "MCF",
                "Selecione o MCF japonês.",
            )
            return

        if self.engine.cfg.render_mode == "ft4" and not ft4:
            messagebox.showwarning(
                "Fonte",
                "Selecione o FONTS.FT4.",
            )
            return

        if not rows_to_generate:
            messagebox.showwarning(
                "CSV",
                "O MCF selecionado não possui legendas carregadas.",
            )
            return

        if not output:
            messagebox.showwarning(
                "Saída",
                "Escolha o arquivo MCF de saída.",
            )
            return

        try:
            if (
                self.engine.cfg.render_mode == "ft4"
                and self.engine.atlas is None
            ):
                self.engine.load_ft4(ft4)

            if not self.engine.font_ready:
                raise RuntimeError("A fonte selecionada não está carregada.")

            self.progress["value"] = 0
            self.progress["maximum"] = max(
                len(rows_to_generate),
                1,
            )

            def progress(
                current,
                total,
                row_id,
            ):
                self.progress["maximum"] = total
                self.progress["value"] = current
                self.status_var.set(
                    f"Gerando ID {row_id} — "
                    f"{current}/{total}"
                )
                self.update_idletasks()

            self.engine.generate_mcf(
                mcf,
                rows_to_generate,
                output,
                progress_callback=progress,
            )

        except Exception as exc:
            messagebox.showerror(
                "Erro ao gerar MCF",
                str(exc),
            )
            self.status_var.set(
                "Erro na geração."
            )
            return

        self.progress["value"] = len(rows_to_generate)

        self.status_var.set(
            "MCF gerado com sucesso."
        )

        messagebox.showinfo(
            "Concluído",
            f"MCF gerado com sucesso ({len(rows_to_generate)} legendas):\n\n"
            + output,
        )


def main():
    app = KoudelkaGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
