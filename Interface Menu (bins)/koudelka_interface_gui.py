#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Editor e scanner dos textos de interface de Koudelka (PS1, versão US).

Edita somente:
  MENU/REPOMENU.BIN
  MENU/BATAMENU.BIN
  MENU/GETMAGIC.BIN
  BIN/FIELD.BIN
  BIN/BATTLE.BIN
  BIN/MOVIE.BIN

Também varre os demais executáveis BIN/SLUS da pasta selecionada e mostra
sequências de texto encontradas na codificação do jogo ou em ASCII.

ITMTBL.ITM e os nomes dos itens não são lidos nem modificados.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Dependência ausente",
        "Instale o Pillow executando instalar_dependencias.bat.",
    )
    raise


APP_TITLE = "Koudelka - Editor de Interface PT-BR"
FONT_REL = "MENU/FONTS.FT4"


@dataclass
class EntrySpec:
    key: str
    group: str
    file_rel: str
    offset: int
    capacity: int
    codec: str
    original: str = ""
    target: str = ""
    length_offset: int | None = None

    @property
    def location(self) -> str:
        return f"{self.file_rel} @ 0x{self.offset:X}"


MENU_SPECS = [
    ("repo_heal", "Menu principal", "MENU/REPOMENU.BIN", 0x0014, 10, "nibble"),
    ("repo_status", "Menu principal", "MENU/REPOMENU.BIN", 0x0044, 10, "nibble"),
    ("repo_equip", "Menu principal", "MENU/REPOMENU.BIN", 0x0074, 10, "nibble"),
    ("repo_items", "Menu principal", "MENU/REPOMENU.BIN", 0x00A4, 10, "nibble"),
    ("repo_formation", "Menu principal", "MENU/REPOMENU.BIN", 0x00D4, 10, "nibble"),
    ("repo_read", "Menu principal", "MENU/REPOMENU.BIN", 0x0104, 10, "nibble"),
    ("repo_config", "Menu principal", "MENU/REPOMENU.BIN", 0x0134, 10, "nibble"),
    ("repo_map", "Menu principal", "MENU/REPOMENU.BIN", 0x0164, 10, "nibble"),
    ("repo_use", "Menu de itens", "MENU/REPOMENU.BIN", 0x0194, 10, "nibble"),
    ("repo_discard", "Menu de itens", "MENU/REPOMENU.BIN", 0x01C4, 10, "nibble"),
    ("repo_rename", "Menu de itens", "MENU/REPOMENU.BIN", 0x01F4, 10, "nibble"),
    ("repo_examine", "Menu de itens", "MENU/REPOMENU.BIN", 0x0224, 10, "nibble"),

    ("battle_move", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x0014, 10, "nibble"),
    ("battle_action", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x0044, 10, "nibble"),
    ("battle_wait", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x0074, 10, "nibble"),
    ("battle_status", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x00A4, 10, "nibble"),
    ("battle_attack", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x00D4, 10, "nibble"),
    ("battle_items", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x0104, 10, "nibble"),
    ("battle_magic", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x0134, 10, "nibble"),
    ("battle_weapon", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x0164, 10, "nibble"),
    ("battle_escape", "Comandos de batalha", "MENU/BATAMENU.BIN", 0x0194, 10, "nibble"),

    ("field_hp", "Indicadores do menu", "BIN/FIELD.BIN", 0x17EC, 4, "nibble"),
    ("field_mp", "Indicadores do menu", "BIN/FIELD.BIN", 0x17F4, 4, "nibble"),
    ("field_lv", "Indicadores do menu", "BIN/FIELD.BIN", 0x17FC, 4, "nibble"),
    ("field_time", "Indicadores do menu", "BIN/FIELD.BIN", 0x1864, 6, "nibble"),
    ("battle_hp", "Indicadores de batalha", "BIN/BATTLE.BIN", 0x0C94, 4, "nibble"),
    ("battle_mp", "Indicadores de batalha", "BIN/BATTLE.BIN", 0x0C9C, 4, "nibble"),

    ("field_got_items", "Mensagens do menu", "BIN/FIELD.BIN", 0x2794, 16, "nibble"),
    ("field_cancel", "Mensagens do menu", "BIN/FIELD.BIN", 0x27B4, 8, "nibble"),
    ("field_ok", "Mensagens do menu", "BIN/FIELD.BIN", 0x27C4, 4, "nibble"),
    ("field_throw_forbidden", "Mensagens do menu", "BIN/FIELD.BIN", 0x27CC, 28, "nibble"),
    ("field_choose", "Mensagens do menu", "BIN/FIELD.BIN", 0x2804, 8, "nibble"),
    ("field_koudelka_using", "Mensagens do menu", "BIN/FIELD.BIN", 0x2814, 24, "nibble"),
    ("field_edward_using", "Mensagens do menu", "BIN/FIELD.BIN", 0x2844, 22, "nibble"),
    ("field_james_using", "Mensagens do menu", "BIN/FIELD.BIN", 0x2870, 22, "nibble"),
    ("field_throw_count", "Mensagens do menu", "BIN/FIELD.BIN", 0x289C, 24, "nibble"),
    ("field_get", "Mensagens do menu", "BIN/FIELD.BIN", 0x29AC, 6, "nibble"),

    # Tela de carregamento/Continue exibida antes do jogo.
    ("movie_load", "Tela Continue/Load", "BIN/MOVIE.BIN", 0x097C, 6, "nibble"),
    ("movie_card_slot1", "Tela Continue/Load", "BIN/MOVIE.BIN", 0x0988, 20, "nibble"),
    ("movie_cancel", "Tela Continue/Load", "BIN/MOVIE.BIN", 0x09B0, 8, "nibble"),
    ("movie_ok", "Tela Continue/Load", "BIN/MOVIE.BIN", 0x09C0, 4, "nibble"),
    # A tela possui cópias independentes dos rótulos dos Memory Cards.
    # O jogo usa as cópias abaixo no painel central, enquanto 0x0988 é
    # referenciada por outra parte da rotina de carregamento.
    ("movie_card_slot2", "Tela Continue/Load", "BIN/MOVIE.BIN", 0x0CE4, 20, "nibble"),
    ("movie_card_slot1_label", "Tela Continue/Load", "BIN/MOVIE.BIN", 0x1174, 20, "nibble"),
    ("movie_card_slot2_label", "Tela Continue/Load", "BIN/MOVIE.BIN", 0x119C, 20, "nibble"),

    # A tela de salvar em FIELD.BIN também mantém cópias independentes.
    ("field_card_slot1", "Tela Save/Memory Card", "BIN/FIELD.BIN", 0x2CEC, 20, "nibble"),
    ("field_card_slot2", "Tela Save/Memory Card", "BIN/FIELD.BIN", 0x318C, 20, "nibble"),
    ("field_card_slot1_label", "Tela Save/Memory Card", "BIN/FIELD.BIN", 0x3348, 20, "nibble"),
    ("field_card_slot2_label", "Tela Save/Memory Card", "BIN/FIELD.BIN", 0x3370, 20, "nibble"),

    # Teclado da tela de renomear. As tabelas A-Z/a-z/0-9 não são textos.
    ("rename_space", "Tela de renomear", "MENU/RENMTEST.BIN", 0x02C0, 8, "nibble"),
    ("rename_delete", "Tela de renomear", "MENU/RENMTEST.BIN", 0x02D0, 8, "nibble"),
]


SUGGESTIONS = {
    "repo_heal": "Curar",
    "repo_status": "Estado",
    "repo_equip": "Equipar",
    "repo_items": "Itens",
    "repo_formation": "Formação",
    "repo_read": "Ler",
    "repo_config": "Config.",
    "repo_map": "Mapa",
    "repo_use": "Usar",
    "repo_discard": "Descartar",
    "repo_rename": "Renomear",
    "repo_examine": "Examinar",
    "battle_move": "Mover",
    "battle_action": "Ação",
    "battle_wait": "Esperar",
    "battle_status": "Estado",
    "battle_attack": "Atacar",
    "battle_items": "Itens",
    "battle_magic": "Magia",
    "battle_weapon": "Arma",
    "battle_escape": "Fugir",
    "field_hp": "PV",
    "field_mp": "PM",
    "field_lv": "NV",
    "field_time": "Tempo",
    "battle_hp": "PV",
    "battle_mp": "PM",
    "field_got_items": "Itens obtidos!",
    "field_cancel": "Voltar",
    "field_ok": "OK",
    "field_throw_forbidden": "Não pode jogar isso fora.",
    "field_choose": "Escolha",
    "field_koudelka_using": "Koudelka está usando.",
    "field_edward_using": "Edward está usando.",
    "field_james_using": "James está usando.",
    "field_throw_count": " itens para descartar.",
    "field_get": "Pegar",
    "movie_load": "Abrir",
    "movie_card_slot1": "Cartão de memória 1",
    "movie_card_slot2": "Cartão de memória 2",
    "movie_card_slot1_label": "Cartão de memória 1",
    "movie_card_slot2_label": "Cartão de memória 2",
    "movie_cancel": "Voltar",
    "movie_ok": "OK",
    "field_card_slot1": "Cartão de memória 1",
    "field_card_slot2": "Cartão de memória 2",
    "field_card_slot1_label": "Cartão de memória 1",
    "field_card_slot2_label": "Cartão de memória 2",
    "rename_space": "Espaço",
    "rename_delete": "Apagar",
}


# Sugestões para textos localizados pela varredura. Elas usam o texto original
# como chave porque a mesma frase pode existir em FIELD.BIN, MOVIE.BIN e SLUS.
# Todas precisam caber no bloco original; encode_nibble completa o restante com
# espaços sem tocar no terminador que fica logo depois do bloco automático.
AUTO_SUGGESTIONS = {
    # Equipamentos, comandos e configuração.
    "Weapon": "Arma",
    "Armor": "Traje",
    "Accessory": "Acessório",
    "Tool": "Item",
    "Cancel": "Voltar",
    "Monaural": "Mono",
    "Unassigned": "Sem função",
    "Look/Open": "Ver/Abrir",
    "Run/Close": "Ir/Fechar",
    "Menu   ": "Menu",
    "Zoom In ": "Ampliar",
    "Zoom Out": "Afastar",
    "Pan Left": "Esquerda",
    "Pan Right": "Direita",
    "Vibration:On": "Vibração:Sim",
    "Vibration:Off": "Vibração:Não",
    "Target?": "Alvo?",

    # Indicadores e evolução.
    "Level ": "Nível ",
    "Next": "Próx",
    "Bonus Points !": "Pontos Bônus!",
    "Level Up": "Nível +",
    "R2:AP Explanation": "R2: Explicar PA",
    "Time": "Hora",
    "Yes ": "Sim",

    # Tela de salvamento.
    "SAVE": "SALV",
    "Save": "Salv",
    "Delete": "Apagar",
    "Format": "Form.",
    "Overwrite": "Trocar",
    "Now saving...Don't remove the MEMORY CARD.":
        "Salvando... Não remova o cartão.",
    "MEMORY CARD has been replaced.": "Cartão de memória trocado.",
    "No MEMORY CARD detected.": "Nenhum cartão detectado.",
    "A save error occurred.": "Erro ao salvar.",
    "Save complete.": "Jogo salvo.",
    "Deleting Koudelka save data...": "Apagando dados de Koudelka...",
    "An access error occurred.": "Erro de acesso.",
    "Save data deleted.": "Dados apagados.",
    "Formatting...Don't remove Memory Card.":
        "Formatando... Não remova o cartão.",
    "MEMORY CARD format complete.": "Cartão formatado.",
    "A format error occurred.": "Erro ao formatar.",
    "Checking...Don't remove the MEMORY CARD.":
        "Verificando... Não remova o cartão.",
    "MEMORY CARD is full.": "Cartão cheio.",
    "MEMORY CARD is unformatted.": "Cartão não formatado.",
    "A check error occurred.": "Erro na verificação.",
    "Unable to save.": "Falha ao gravar",
    "File": "Arq.",
    "Verifying MEMORY CARD...": "Verificando cartão...",
    "In use by another game file.": "Em uso por outro jogo.",
    "Available": "Livre",

    # Tela de carregamento.
    "Now loading...Don't remove the MEMORY CARD.":
        "Carregando... Não remova o cartão.",
    "A load error occurred.": "Erro ao carregar.",
    "Load complete.": "Carregado.",
    "No Koudelka save data found!": "Jogo salvo não encontrado!",
    "Unable to load.": "Falha ao abrir.",
    "MEMORY CARD has been removed.": "Cartão removido.",
    "DISC": "CD",

    # Batalha.
    "level went up!": "Nível subiu!",
    "You can't escape!!": "Não pode fugir!!",
    "You weren't able to run away!": "Você não conseguiu fugir!",
    "You can't get past the monster!": "O monstro bloqueia a passagem!",
    "MaxHP": "PVmáx",
    "MaxMP": "PMmáx",

    # Erros de troca de disco.
    "The disc cover is open.": "A tampa do disco abriu.",
    "Please close the disc cover.": "Feche a tampa do disco.",
    "No disc found!": "Disco ausente!",
    "Please insert DISC ": "Insira o DISCO ",
    "Incorrect disc.Please insert DISC ": "Disco errado. Insira o DISCO ",
    "Incorrect disc.": "Disco errado.",

    # Nomes possessivos e atributos/elementos.
    "Koudelka's": "Koudelka",
    "Edward's": "Edward",
    "James's": "James",
    "Attack": "Ataque",
    "Weakness": "Fraqueza",
    "Speciality": "Especial",
    "Reflect": "Reflexo",
    "Absorb": "Absorv",
    "Null": "Nulo",
    "Half": "Meio",
    "Fire": "Fogo",
    "Water": "Água",
    "Earth": "Terra",
    "Wind": "Ar",
    "Light": "Luz",
    "Dark": "Somb",
    "HP Drain": "Dreno PV",
    "MP Drain": "Dreno PM",
    "Paralysis": "Paralisia",
    "Silence": "Mudez",
    "Poison": "Veneno",
    "Attack  None": "Ataque  Nulo",
    "Magic": "Magia",
}


ACCENTS = {
    "á": ("a", "acute"), "é": ("e", "acute"), "í": ("i", "acute"),
    "ó": ("o", "acute"), "ú": ("u", "acute"),
    "Á": ("A", "acute"), "É": ("E", "acute"), "Í": ("I", "acute"),
    "Ó": ("O", "acute"), "Ú": ("U", "acute"),
    "ã": ("a", "tilde"), "õ": ("o", "tilde"),
    "Ã": ("A", "tilde"), "Õ": ("O", "tilde"),
    "â": ("a", "circ"), "ê": ("e", "circ"), "ô": ("o", "circ"),
    "Â": ("A", "circ"), "Ê": ("E", "circ"), "Ô": ("O", "circ"),
    "ç": ("c", "cedilla"), "Ç": ("C", "cedilla"),
}


def cp1252_bytes(text: str) -> bytes:
    try:
        return text.encode("cp1252")
    except UnicodeEncodeError as exc:
        bad = text[exc.start:exc.end]
        raise ValueError(f"Caractere não suportado: {bad!r}") from exc


def decode_nibble(data: bytes, offset: int, capacity: int) -> str:
    result = bytearray()
    for index in range(capacity):
        pos = offset + index * 2
        if pos + 1 >= len(data):
            break
        low, high = data[pos], data[pos + 1]
        if low == 0 and high == 0:
            break
        if not (0x40 <= low <= 0x4F and 0x40 <= high <= 0x4F):
            break
        result.append(((high - 0x40) << 4) | (low - 0x40))
    return result.decode("cp1252", errors="replace")


def encode_nibble(text: str, capacity: int, pad_with_spaces: bool = False) -> bytes:
    raw = cp1252_bytes(text)
    if len(raw) > capacity:
        raise ValueError(f"{len(raw)} caracteres; o limite é {capacity}.")
    # Alguns textos são matrizes de tamanho fixo, sem byte de comprimento.
    # Neles, 00 00 não funciona como terminador: o jogo o desenha como um
    # glifo (parecido com "K"). Preencher as posições restantes com o caractere
    # espaço (0x20 => 40 42) mantém o bloco fixo e não deixa lixo visível.
    if pad_with_spaces:
        output = bytearray((0x40, 0x42) * capacity)
    else:
        output = bytearray(capacity * 2)
    for index, value in enumerate(raw):
        output[index * 2] = 0x40 + (value & 0x0F)
        output[index * 2 + 1] = 0x40 + ((value >> 4) & 0x0F)
    return bytes(output)


def encode_ascii(text: str, capacity: int) -> bytes:
    raw = cp1252_bytes(text)
    if len(raw) > capacity:
        raise ValueError(f"{len(raw)} caracteres; o limite é {capacity}.")
    return raw + bytes(capacity - len(raw))


def decode_magic_record(record: bytes) -> str:
    # O registro tem duas caixas fixas e quatro bytes finais de metadados:
    #   0x00..0x0F = primeira linha (16 bytes)
    #   0x10..0x2B = segunda linha  (28 bytes)
    #   0x2C..0x2F = metadados que não podem ser apagados
    lines = []
    for raw in (record[0:16], record[16:44]):
        raw = raw.split(b"\0", 1)[0]
        if raw.startswith(b"@B"):
            raw = raw[2:]
        lines.append(raw.decode("cp1252", errors="replace").rstrip())
    return "|".join(lines)


def encode_magic_record(text: str, original_record: bytes | None = None) -> bytes:
    parts = text.split("|")
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("A mensagem de magia precisa de duas linhas separadas por |.")
    limits = (13, 25)
    encoded_lines = []
    for number, (part, limit) in enumerate(zip(parts, limits), start=1):
        raw = cp1252_bytes(part)
        if len(raw) > limit:
            raise ValueError(
                f"Linha {number}: {len(raw)} caracteres; o limite é {limit}."
            )
        encoded_lines.append(b"@B" + raw)
    output = bytearray(original_record if original_record is not None else bytes(0x30))
    if len(output) != 0x30:
        raise ValueError("Registro GETMAGIC inválido; eram esperados 48 bytes.")
    output[0:16] = bytes(16)
    output[16:44] = bytes(28)
    output[0:len(encoded_lines[0])] = encoded_lines[0]
    output[16:16 + len(encoded_lines[1])] = encoded_lines[1]
    return bytes(output)


def looks_like_interface_text(text: str) -> bool:
    """Filtro conservador para reduzir falsos positivos da varredura."""
    if not (4 <= len(text) <= 160):
        return False
    if text[0].isspace() or not any(ch.isalpha() for ch in text):
        return False
    letters = sum(ch.isalpha() for ch in text)
    readable = sum(ch.isalnum() or ch.isspace() or ch in "!?'\".,:;+-/()" for ch in text)
    if letters < 2 or readable / len(text) < 0.82 or letters / len(text) < 0.55:
        return False
    # Grades de caracteres da tela de renomear são dados da fonte/teclado,
    # não frases traduzíveis.
    compact_text = text.replace(" ", "")
    if compact_text in {
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "abcdefghijklmnopqrstuvwxyz0123456789",
    }:
        return False
    # Sequências de um único caractere repetido normalmente são dados.
    compact = [ch.lower() for ch in text if ch.isalnum()]
    if compact and len(set(compact)) == 1 and len(compact) > 3:
        return False
    return True


def scan_nibble_texts(data: bytes) -> list[tuple[int, str]]:
    """Localiza sequências ASCII codificadas em pares de nibbles 40..4F."""
    found: list[tuple[int, str]] = []
    offset = 0
    size = len(data)
    while offset + 1 < size:
        low, high = data[offset], data[offset + 1]
        value = ((high - 0x40) << 4) | (low - 0x40)
        if (
            offset % 2 == 0
            and 0x40 <= low <= 0x4F
            and 0x40 <= high <= 0x4F
            and 0x20 <= value <= 0x7E
        ):
            start = offset
            raw = bytearray()
            while offset + 1 < size and len(raw) < 160:
                low, high = data[offset], data[offset + 1]
                if not (0x40 <= low <= 0x4F and 0x40 <= high <= 0x4F):
                    break
                value = ((high - 0x40) << 4) | (low - 0x40)
                if not (0x20 <= value <= 0x7E):
                    break
                raw.append(value)
                offset += 2
            text = raw.decode("ascii", errors="ignore")
            if looks_like_interface_text(text):
                found.append((start, text))
            if offset == start:
                offset += 2
        else:
            offset += 2
    return found


def scan_ascii_texts(data: bytes) -> list[tuple[int, str]]:
    """Localiza mensagens ASCII legíveis dentro de executáveis."""
    found: list[tuple[int, str]] = []
    for match in re.finditer(rb"[\x20-\x7E]{4,160}", data):
        raw = match.group(0)
        # Pares 40..4F são o texto codificado e não ASCII verdadeiro.
        if all(0x40 <= value <= 0x4F for value in raw):
            continue
        text = raw.decode("ascii", errors="ignore")
        if looks_like_interface_text(text):
            found.append((match.start(), text))
    return found


class NativeFont:
    ATLAS_OFFSET = 0x100
    ATLAS_W = 256
    ATLAS_H = 256
    CELL = 16
    # Uma tabela de 256 larguras, indexada pelo código do caractere.
    # Códigos latinos estendidos vêm com 16 px na fonte US e precisam
    # herdar a largura da letra-base para não criar espaços no jogo.
    WIDTH_TABLE_OFFSET = 0x100D0

    def __init__(self, path: Path):
        self.path = path
        self.file_data = path.read_bytes()
        needed = self.ATLAS_OFFSET + self.ATLAS_W * self.ATLAS_H // 2
        if len(self.file_data) < needed:
            raise ValueError("FONTS.FT4 é menor que o atlas esperado.")
        raw = self.file_data[self.ATLAS_OFFSET:needed]
        pixels = []
        for value in raw:
            pixels.extend((value & 0x0F, value >> 4))
        self.atlas = Image.new("L", (self.ATLAS_W, self.ATLAS_H))
        self.atlas.putdata(pixels)
        self._cell_cache: dict[str, Image.Image] = {}

    @staticmethod
    def cell_xy(code: int) -> tuple[int, int]:
        row = (code >> 4) & 0x0F
        col = ((code & 0x0F) - 6) % 16
        return col * 16, row * 16

    def native_cell(self, ch: str) -> Image.Image:
        code = cp1252_bytes(ch)[0]
        x, y = self.cell_xy(code)
        return self.atlas.crop((x, y, x + 16, y + 16))

    @staticmethod
    def _paint_mark(cell: Image.Image, points: list[tuple[int, int]]) -> None:
        pix = cell.load()
        for x, y in points:
            if not (0 <= x < 16 and 0 <= y < 16):
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < 16 and 0 <= ny < 16 and pix[nx, ny] == 0:
                    pix[nx, ny] = 8
            pix[x, y] = 2

    def accented_cell(self, ch: str) -> Image.Image:
        cached = self._cell_cache.get(ch)
        if cached is not None:
            return cached.copy()
        base_ch, accent = ACCENTS[ch]
        cell = self.native_cell(base_ch).copy()
        pix = cell.load()
        occupied = [
            (x, y) for y in range(16) for x in range(16) if pix[x, y] != 0
        ]
        if not occupied:
            return cell
        xs = [p[0] for p in occupied]
        ys = [p[1] for p in occupied]
        center = (min(xs) + max(xs)) // 2
        top, bottom = min(ys), max(ys)

        if accent in {"acute", "tilde", "circ"} and top < 3:
            shifted = Image.new("L", (16, 16))
            shifted.paste(cell.crop((0, 0, 16, 14)), (0, 2))
            cell = shifted
            top += 2
            bottom = min(15, bottom + 2)
        elif accent == "cedilla" and bottom > 12:
            shifted = Image.new("L", (16, 16))
            shifted.paste(cell.crop((0, 1, 16, 16)), (0, 0))
            cell = shifted
            top = max(0, top - 1)
            bottom -= 1

        if accent == "acute":
            y = max(0, top - 3)
            points = [(center + 1, y), (center, y + 1), (center - 1, y + 2)]
        elif accent == "tilde":
            y = max(0, top - 3)
            points = [
                (center - 2, y + 1), (center - 1, y), (center, y + 1),
                (center + 1, y), (center + 2, y + 1),
            ]
        elif accent == "circ":
            y = max(0, top - 3)
            points = [
                (center - 2, y + 2), (center - 1, y + 1), (center, y),
                (center + 1, y + 1), (center + 2, y + 2),
            ]
        else:
            y = min(13, bottom + 1)
            points = [(center, y), (center + 1, y + 1), (center, y + 2)]
        self._paint_mark(cell, points)
        self._cell_cache[ch] = cell.copy()
        return cell

    def cell_for_char(self, ch: str) -> Image.Image:
        if ch in ACCENTS:
            return self.accented_cell(ch)
        try:
            return self.native_cell(ch)
        except (ValueError, IndexError):
            return self.native_cell("?")

    def advance_width(self, ch: str) -> int:
        """Largura horizontal real consultada pelo jogo."""
        if ch in ACCENTS:
            ch = ACCENTS[ch][0]
        try:
            code = cp1252_bytes(ch)[0]
        except (ValueError, IndexError):
            code = ord("?")
        pos = self.WIDTH_TABLE_OFFSET + code
        if pos >= len(self.file_data):
            return 8
        width = self.file_data[pos]
        return width if 1 <= width <= 16 else 8

    def text_width(self, text: str) -> int:
        lines = text.split("|")
        return max((self._line_width(line) for line in lines), default=0)

    def _line_width(self, text: str) -> int:
        return sum(self.advance_width(ch) for ch in text)

    def render(self, text: str, width: int = 210, selected: bool = False) -> Image.Image:
        lines = text.split("|")[:2]
        height = 34 if len(lines) == 1 else 52
        background = (28, 27, 26) if selected else (231, 193, 147)
        main = (242, 169, 0) if selected else (36, 30, 24)
        outline = (94, 63, 36) if selected else (133, 91, 58)
        canvas = Image.new("RGB", (width, height), background)

        for line_index, line in enumerate(lines):
            glyphs: list[tuple[Image.Image | None, int]] = []
            line_width = 0
            for ch in line:
                advance = self.advance_width(ch)
                if ch == " ":
                    glyphs.append((None, advance))
                    line_width += advance
                    continue
                # Mesma altura real de 15 px usada pelo renderizador.
                # Incluir a linha 16 criava falsos sublinhados na prévia.
                cell = self.cell_for_char(ch).crop((0, 0, 16, 15))
                bbox = cell.getbbox()
                if bbox:
                    glyph = cell.crop((bbox[0], 0, bbox[2], 15))
                else:
                    glyph = None
                glyphs.append((glyph, advance))
                line_width += advance
            x = max(4, (width - line_width) // 2)
            y = 8 + line_index * 18
            for glyph, advance in glyphs:
                if glyph is not None:
                    colored = Image.new("RGB", glyph.size, main)
                    mask_main = glyph.point(lambda p: 255 if p in (1, 2) else 0)
                    mask_outline = glyph.point(lambda p: 255 if p not in (0, 1, 2) else 0)
                    outline_img = Image.new("RGB", glyph.size, outline)
                    canvas.paste(outline_img, (x, y), mask_outline)
                    canvas.paste(colored, (x, y), mask_main)
                x += advance
        return canvas.resize((width * 2, height * 2), Image.Resampling.NEAREST)

    def patched_bytes(self, characters: set[str]) -> bytes:
        atlas = self.atlas.copy()
        for ch in sorted(characters):
            if ch not in ACCENTS:
                continue
            code = cp1252_bytes(ch)[0]
            x, y = self.cell_xy(code)
            atlas.paste(self.accented_cell(ch), (x, y))
        pixels = list(atlas.getdata())
        packed = bytearray(len(pixels) // 2)
        for index in range(0, len(pixels), 2):
            packed[index // 2] = (pixels[index] & 0x0F) | ((pixels[index + 1] & 0x0F) << 4)
        output = bytearray(self.file_data)
        output[self.ATLAS_OFFSET:self.ATLAS_OFFSET + len(packed)] = packed

        if len(output) < self.WIDTH_TABLE_OFFSET + 256:
            raise ValueError("FONTS.FT4 não contém a tabela de larguras esperada.")
        for ch in sorted(characters):
            if ch not in ACCENTS:
                continue
            base_ch, _accent = ACCENTS[ch]
            accent_code = cp1252_bytes(ch)[0]
            base_code = cp1252_bytes(base_ch)[0]
            output[self.WIDTH_TABLE_OFFSET + accent_code] = output[
                self.WIDTH_TABLE_OFFSET + base_code
            ]
        return bytes(output)


class InterfaceEditorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1120x720")
        self.minsize(860, 590)
        self.option_add("*Font", "Arial 10")

        self.game_root: Path | None = None
        self.source_data: dict[str, bytes] = {}
        self.entries: list[EntrySpec] = []
        self.by_key: dict[str, EntrySpec] = {}
        self.folder_iids: dict[str, str] = {}
        self.native_font: NativeFont | None = None
        self.current: EntrySpec | None = None
        self.loading_editor = False
        self.before_photo: ImageTk.PhotoImage | None = None
        self.after_photo: ImageTk.PhotoImage | None = None

        self.path_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="Todos")
        self.edit_var = tk.StringVar()
        self.location_var = tk.StringVar(value="Selecione a pasta extraída do jogo.")
        self.selected_path_var = tk.StringVar()
        self.limit_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pronto.")
        self.selected_color_var = tk.BooleanVar(value=False)
        self.edit_var.trace_add("write", self._on_text_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Pasta extraída do jogo:").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(top, textvariable=self.path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="Selecionar...", command=self.select_game_folder).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(top, text="Carregar", command=self.load_game).grid(row=0, column=3, padx=(6, 0))

        toolbar = ttk.Frame(self, padding=(8, 0, 8, 6))
        toolbar.grid(row=1, column=0, sticky="ew")
        toolbar_top = ttk.Frame(toolbar)
        toolbar_top.pack(fill="x", pady=(0, 3))
        toolbar_bottom = ttk.Frame(toolbar)
        toolbar_bottom.pack(fill="x")
        ttk.Label(toolbar_top, text="Grupo:").pack(side="left")
        self.filter_combo = ttk.Combobox(toolbar_top, textvariable=self.filter_var, state="readonly", width=25)
        self.filter_combo.pack(side="left", padx=(5, 12))
        self.filter_combo["values"] = ("Todos",)
        self.filter_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_tree())
        ttk.Button(toolbar_top, text="Sugestões em tudo", command=self.apply_suggestions).pack(side="left", padx=3)
        ttk.Button(toolbar_top, text="Sugestões PT-BR do grupo", command=self.apply_group_suggestions).pack(side="left", padx=3)
        ttk.Button(toolbar_top, text="Restaurar selecionado", command=self.restore_selected).pack(side="left", padx=3)
        ttk.Button(toolbar_bottom, text="Varrer novamente", command=self.rescan_folder).pack(side="left", padx=3)
        ttk.Button(toolbar_bottom, text="Expandir tudo", command=lambda: self.set_all_folders(True)).pack(side="left", padx=3)
        ttk.Button(toolbar_bottom, text="Recolher tudo", command=lambda: self.set_all_folders(False)).pack(side="left", padx=3)
        ttk.Button(toolbar_bottom, text="Exportar CSV", command=self.export_csv).pack(side="right", padx=3)
        ttk.Button(toolbar_bottom, text="Importar CSV", command=self.import_csv).pack(side="right", padx=3)

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.grid(row=2, column=0, sticky="nsew", padx=8)
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        left = ttk.Frame(pane)
        right = ttk.Frame(pane, padding=(10, 0, 0, 0))
        pane.add(left, weight=3)
        pane.add(right, weight=2)

        columns = ("original", "traducao", "limite")
        self.tree = ttk.Treeview(left, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Pasta / endereço")
        self.tree.heading("original", text="Original")
        self.tree.heading("traducao", text="PT-BR / edição")
        self.tree.heading("limite", text="Uso")
        self.tree.column("#0", width=210, stretch=True)
        self.tree.column("original", width=190)
        self.tree.column("traducao", width=210)
        self.tree.column("limite", width=70, anchor="center", stretch=False)
        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._select_entry)
        self.tree.bind("<Double-1>", self._toggle_folder_on_double_click)

        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="Texto selecionado", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.location_var, foreground="#555555", wraplength=420).grid(row=1, column=0, sticky="ew", pady=(2, 8))
        path_row = ttk.Frame(right)
        path_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        path_row.columnconfigure(0, weight=1)
        self.selected_path_entry = ttk.Entry(
            path_row,
            textvariable=self.selected_path_var,
            state="readonly",
        )
        self.selected_path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(path_row, text="Copiar", width=7, command=self.copy_selected_path).grid(row=0, column=1, padx=(5, 0))
        self.editor = ttk.Entry(right, textvariable=self.edit_var, font=("Arial", 12))
        self.editor.grid(row=3, column=0, sticky="ew")
        self.editor.bind("<Up>", lambda _event: self.navigate_entries(-1))
        self.editor.bind("<Down>", lambda _event: self.navigate_entries(1))
        ttk.Label(
            right,
            text="Use ↑/↓ para navegar. Em mensagens de magia, use | entre as linhas.",
            foreground="#555555",
            wraplength=420,
        ).grid(row=4, column=0, sticky="w", pady=(4, 3))
        self.limit_label = ttk.Label(right, textvariable=self.limit_var)
        self.limit_label.grid(row=5, column=0, sticky="w", pady=(0, 10))

        preview = ttk.LabelFrame(right, text="Prévia em tempo real", padding=7)
        preview.grid(row=6, column=0, sticky="nsew")
        preview.columnconfigure(0, weight=1)
        right.rowconfigure(6, weight=1)
        ttk.Label(preview, text="Antes").grid(row=0, column=0, sticky="w")
        self.before_label = ttk.Label(preview, anchor="center")
        self.before_label.grid(row=1, column=0, sticky="ew", pady=(2, 8))
        ttk.Label(preview, text="Depois").grid(row=2, column=0, sticky="w")
        self.after_label = ttk.Label(preview, anchor="center")
        self.after_label.grid(row=3, column=0, sticky="ew", pady=(2, 4))
        ttk.Checkbutton(
            preview,
            text="Simular texto selecionado (amarelo)",
            variable=self.selected_color_var,
            command=self.update_preview,
        ).grid(row=4, column=0, sticky="w", pady=(5, 0))

        bottom = ttk.Frame(self, padding=8)
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.generate_button = ttk.Button(bottom, text="Gerar arquivos traduzidos...", command=self.generate_output, state="disabled")
        self.generate_button.grid(row=0, column=1, padx=(8, 0))

    def select_game_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Selecionar pasta extraída de Koudelka")
        if chosen:
            self.path_var.set(chosen)
            self.load_game()

    def load_game(self) -> None:
        root = Path(self.path_var.get().strip().strip('"'))
        required = {
            "MENU/REPOMENU.BIN", "MENU/BATAMENU.BIN", "MENU/GETMAGIC.BIN",
            "MENU/RENMTEST.BIN", "BIN/FIELD.BIN", "BIN/BATTLE.BIN",
            "BIN/MOVIE.BIN", FONT_REL,
        }
        missing = [rel for rel in sorted(required) if not (root / Path(rel)).is_file()]
        if missing:
            messagebox.showerror(
                "Pasta inválida",
                "Não encontrei os seguintes arquivos:\n\n" + "\n".join(missing),
            )
            return
        try:
            self.game_root = root
            self.source_data = {
                rel: (root / Path(rel)).read_bytes() for rel in required if rel != FONT_REL
            }
            self.native_font = NativeFont(root / Path(FONT_REL))
            self.entries = []
            for values in MENU_SPECS:
                spec = EntrySpec(*values)
                data = self.source_data[spec.file_rel]
                spec.original = decode_nibble(data, spec.offset, spec.capacity)
                spec.target = spec.original
                self.entries.append(spec)
            self._load_magic_entries()
            scanned_files, detected = self._scan_entire_folder()
            self.by_key = {entry.key: entry for entry in self.entries}
            groups = sorted({entry.group for entry in self.entries})
            self.filter_combo["values"] = ("Todos", *groups)
            self.filter_var.set("Todos")
            self.refresh_tree()
            self.generate_button.configure(state="normal")
            self.status_var.set(
                f"{len(self.entries)} textos carregados; {detected} encontrados pela "
                f"varredura em {scanned_files} arquivos. Nomes de itens ignorados."
            )
            if self.entries:
                first = self.entries[0].key
                self.tree.selection_set(first)
                self.tree.focus(first)
                self.tree.see(first)
        except Exception as exc:
            messagebox.showerror("Erro ao carregar", str(exc))

    @staticmethod
    def _entry_span(entry: EntrySpec) -> tuple[int, int]:
        if entry.codec == "magic":
            size = entry.capacity
        elif entry.codec.startswith("nibble"):
            size = entry.capacity * 2
        else:
            size = entry.capacity
        return entry.offset, entry.offset + size

    def _overlaps_known(self, file_rel: str, start: int, end: int) -> bool:
        for entry in self.entries:
            if entry.file_rel != file_rel:
                continue
            known_start, known_end = self._entry_span(entry)
            if start < known_end and end > known_start:
                return True
        return False

    @staticmethod
    def _eligible_scan_file(root: Path, path: Path) -> bool:
        try:
            relative = path.relative_to(root)
        except ValueError:
            return False
        ignored_parts = {
            "original", "bins traduzidas", "interface-traduzida",
            "mdt_traduzido", "mdt_textos_extraidos", "__pycache__",
        }
        for part in relative.parts[:-1]:
            lowered = part.lower()
            if lowered in ignored_parts or "backup" in lowered or "traduzid" in lowered:
                return False
        name_upper = path.name.upper()
        is_executable = path.suffix.upper() == ".BIN" or bool(
            re.match(r"^(SLUS|SLES|SCUS|SLPS)_", name_upper)
        )
        if not is_executable or path.stat().st_size > 8 * 1024 * 1024:
            return False
        # A tabela de nomes dos itens permanece explicitamente fora do escopo.
        return path.name.upper() != "ITMTBL.ITM"

    def _scan_entire_folder(self) -> tuple[int, int]:
        if not self.game_root:
            return 0, 0
        added = 0
        scanned_files = 0
        auto_entries: list[EntrySpec] = []
        for path in sorted(self.game_root.rglob("*")):
            if not path.is_file() or not self._eligible_scan_file(self.game_root, path):
                continue
            scanned_files += 1
            file_rel = path.relative_to(self.game_root).as_posix()
            data = self.source_data.get(file_rel)
            if data is None:
                data = path.read_bytes()
                self.source_data[file_rel] = data

            for offset, text in scan_nibble_texts(data):
                end = offset + len(text) * 2
                if self._overlaps_known(file_rel, offset, end):
                    continue
                length_offset = None
                if (
                    offset >= 4
                    and data[offset - 4] == len(text)
                    and data[offset - 3:offset] == b"\xFF\xFF\xFF"
                ):
                    length_offset = offset - 4
                auto_entries.append(EntrySpec(
                    key=f"scan_n_{added:05d}",
                    group=f"Varrido: {file_rel}",
                    file_rel=file_rel,
                    offset=offset,
                    capacity=len(text),
                    codec="nibble_auto",
                    original=text,
                    target=text,
                    length_offset=length_offset,
                ))
                added += 1

            # Não expomos ASCII encontrado por heurística. A auditoria mostrou
            # que esses candidatos eram nomes internos, caminhos, mensagens de
            # depuração, tabelas e falsos positivos; editá-los pode corromper a
            # lógica do executável. A interface visível usa o formato nibble.

        auto_entries.sort(key=lambda entry: (entry.file_rel.lower(), entry.offset, entry.codec))
        self.entries.extend(auto_entries)
        return scanned_files, len(auto_entries)

    def rescan_folder(self) -> None:
        if not self.game_root:
            self.load_game()
            return
        if any(entry.target != entry.original for entry in self.entries):
            if not messagebox.askyesno(
                "Varrer novamente",
                "A nova varredura recarregará os arquivos e descartará edições não geradas. Continuar?",
            ):
                return
        self.load_game()

    def navigate_entries(self, direction: int):
        ordered = [entry.key for entry in self.entries if self.tree.exists(entry.key)]
        if not ordered:
            return "break"
        selection = self.tree.selection()
        try:
            index = ordered.index(selection[0]) if selection and selection[0] in self.by_key else 0
        except ValueError:
            index = 0
        index = (index + direction) % len(ordered)
        key = ordered[index]
        parent = self.tree.parent(key)
        if parent:
            self.tree.item(parent, open=True)
        self.tree.selection_set(key)
        self.tree.focus(key)
        self.tree.see(key)
        self._select_entry()
        return "break"

    def focus_entry(self, key: str) -> None:
        """Abre a pasta e seleciona uma entrada pelo identificador interno."""
        if not self.tree.exists(key):
            # O filtro atual pode estar escondendo a entrada.
            self.filter_var.set("Todos")
            self.refresh_tree()
        if not self.tree.exists(key):
            return
        parent = self.tree.parent(key)
        if parent:
            self.tree.item(parent, open=True)
        self.tree.selection_set(key)
        self.tree.focus(key)
        self.tree.see(key)
        self._select_entry()

    def _load_magic_entries(self) -> None:
        data = self.source_data["MENU/GETMAGIC.BIN"]
        count = 0
        for offset in range(0x300, len(data) - 0x2F, 0x30):
            record = data[offset:offset + 0x30]
            if not record.startswith(b"@B"):
                continue
            text = decode_magic_record(record)
            if not text or not all(ch.isprintable() or ch == "|" for ch in text):
                continue
            spec = EntrySpec(
                key=f"magic_{count:02d}",
                group="Aprendizado de magia",
                file_rel="MENU/GETMAGIC.BIN",
                offset=offset,
                capacity=0x30,
                codec="magic",
                original=text,
                target=text,
            )
            self.entries.append(spec)
            count += 1

    def refresh_tree(self) -> None:
        selected = self.current.key if self.current else None
        had_folders = bool(self.folder_iids)
        expanded_groups = {
            group for group, iid in self.folder_iids.items()
            if self.tree.exists(iid) and bool(self.tree.item(iid, "open"))
        }
        self.tree.delete(*self.tree.get_children())
        self.folder_iids = {}
        wanted = self.filter_var.get()
        grouped: dict[str, list[EntrySpec]] = {}
        for entry in self.entries:
            if wanted == "Todos" or entry.group == wanted:
                grouped.setdefault(entry.group, []).append(entry)

        for folder_index, (group, group_entries) in enumerate(grouped.items()):
            folder_iid = f"folder_{folder_index:04d}"
            self.folder_iids[group] = folder_iid
            open_folder = group in expanded_groups or (not had_folders and folder_index == 0)
            self.tree.insert(
                "", "end", iid=folder_iid, text=group, open=open_folder,
                values=(f"{len(group_entries)} textos", "", ""),
            )
            for entry in group_entries:
                used, maximum = self.usage(entry, entry.target)
                self.tree.insert(
                    folder_iid, "end", iid=entry.key,
                    text=f"0x{entry.offset:X}",
                    values=(
                        entry.original.replace("|", " / "),
                        entry.target.replace("|", " / "),
                        f"{used}/{maximum}",
                    ),
                )
        if selected and self.tree.exists(selected):
            parent = self.tree.parent(selected)
            if parent:
                self.tree.item(parent, open=True)
            self.tree.selection_set(selected)

    def set_all_folders(self, opened: bool) -> None:
        for iid in self.tree.get_children(""):
            self.tree.item(iid, open=opened)

    def _toggle_folder_on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.by_key:
            self.tree.item(iid, open=not bool(self.tree.item(iid, "open")))
            return "break"
        return None

    def _select_entry(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        entry = self.by_key.get(selection[0])
        if entry is None:
            return
        self.current = entry
        self.loading_editor = True
        self.edit_var.set(entry.target)
        self.loading_editor = False
        self.location_var.set(f"{entry.group}  •  {entry.location}")
        if self.game_root:
            self.selected_path_var.set(str(self.game_root / Path(entry.file_rel)))
        else:
            self.selected_path_var.set(entry.file_rel)
        self.editor.focus_set()
        self.editor.icursor("end")
        self._update_validation()
        self.update_preview()

    def copy_selected_path(self) -> None:
        path = self.selected_path_var.get()
        if not path:
            return
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status_var.set(f"Caminho copiado: {path}")

    @staticmethod
    def _requires_internal_terminator(entry: EntrySpec) -> bool:
        """Indica blocos cujo último par deve continuar sendo 00 00."""
        return (
            entry.codec == "nibble"
            and entry.file_rel not in {"MENU/REPOMENU.BIN", "MENU/BATAMENU.BIN"}
            and entry.length_offset is None
        )

    def text_limit(self, entry: EntrySpec) -> int:
        if self._requires_internal_terminator(entry):
            return max(0, entry.capacity - 1)
        return entry.capacity

    def usage(self, entry: EntrySpec, text: str) -> tuple[int, int]:
        if entry.codec == "magic":
            try:
                parts = text.split("|")
                used = sum(len(cp1252_bytes(part)) for part in parts)
            except ValueError:
                used = 999
            return used, 38
        try:
            return len(cp1252_bytes(text)), self.text_limit(entry)
        except ValueError:
            return 999, self.text_limit(entry)

    def validate_entry(self, entry: EntrySpec, text: str) -> tuple[bool, str]:
        try:
            if not text:
                return False, "O texto não pode ficar vazio."
            if entry.codec == "magic":
                encode_magic_record(text)
            elif entry.codec == "ascii_auto":
                encode_ascii(text, entry.capacity)
            else:
                used = len(cp1252_bytes(text))
                safe_limit = self.text_limit(entry)
                if used > safe_limit:
                    suffix = (
                        "; 1 posição é reservada para o terminador."
                        if self._requires_internal_terminator(entry)
                        else "."
                    )
                    raise ValueError(
                        f"{used} caracteres; o limite seguro é {safe_limit}{suffix}"
                    )
                encode_nibble(text, entry.capacity)
            return True, "OK"
        except ValueError as exc:
            return False, str(exc)

    def _on_text_changed(self, *_args) -> None:
        if self.loading_editor or self.current is None:
            return
        self.current.target = self.edit_var.get()
        if self.tree.exists(self.current.key):
            used, maximum = self.usage(self.current, self.current.target)
            self.tree.item(
                self.current.key,
                values=(
                    self.current.original.replace("|", " / "),
                    self.current.target.replace("|", " / "),
                    f"{used}/{maximum}",
                ),
            )
        self._update_validation()
        self.update_preview()

    def _update_validation(self) -> None:
        if not self.current:
            return
        valid, detail = self.validate_entry(self.current, self.current.target)
        used, maximum = self.usage(self.current, self.current.target)
        pixels = self.native_font.text_width(self.current.target) if self.native_font else 0
        if self.current.codec == "magic" and "|" in self.current.target:
            parts = self.current.target.split("|", 1)
            try:
                line_info = f"L1 {len(cp1252_bytes(parts[0]))}/13 • L2 {len(cp1252_bytes(parts[1]))}/25"
            except ValueError:
                line_info = f"Uso: {used}/{maximum}"
        else:
            line_info = f"Uso: {used}/{maximum} bytes/caracteres"
        self.limit_var.set(f"{line_info}  •  largura: {pixels} px  •  {detail}")
        self.limit_label.configure(foreground="#16713c" if valid else "#b3261e")

    def update_preview(self) -> None:
        if not self.current or not self.native_font:
            return
        selected = self.selected_color_var.get()
        before_width = max(210, self.native_font.text_width(self.current.original) + 16)
        after_width = max(210, self.native_font.text_width(self.current.target) + 16)
        before = self.native_font.render(self.current.original, width=before_width, selected=selected)
        after = self.native_font.render(self.current.target, width=after_width, selected=selected)
        max_width = 420
        self.before_photo = ImageTk.PhotoImage(before.resize((max_width, max(34, int(before.height * max_width / before.width))), Image.Resampling.NEAREST))
        self.after_photo = ImageTk.PhotoImage(after.resize((max_width, max(34, int(after.height * max_width / after.width))), Image.Resampling.NEAREST))
        self.before_label.configure(image=self.before_photo)
        self.after_label.configure(image=self.after_photo)

    def apply_suggestions(self) -> None:
        if not self.entries:
            return
        changed = 0
        for entry in self.entries:
            # Preserva traduções digitadas ou importadas pelo usuário; as
            # sugestões servem para completar o que ainda está no original.
            if entry.target != entry.original:
                continue
            suggested = self._suggestion_for_entry(entry)
            if suggested:
                valid, _ = self.validate_entry(entry, suggested)
                if valid:
                    if entry.target != suggested:
                        changed += 1
                    entry.target = suggested
        self.refresh_tree()
        if self.current:
            self.loading_editor = True
            self.edit_var.set(self.current.target)
            self.loading_editor = False
            self._update_validation()
            self.update_preview()
        self.status_var.set(f"Sugestões PT-BR aplicadas a {changed} textos. Revise antes de gerar.")

    @staticmethod
    def _suggestion_for_entry(entry: EntrySpec) -> str | None:
        suggested = SUGGESTIONS.get(entry.key)
        if suggested is None:
            suggested = AUTO_SUGGESTIONS.get(entry.original)
        if entry.codec == "magic":
            match = re.search(r'"([^"]+)"', entry.original)
            if match:
                suggested = f'Você aprendeu|a magia "{match.group(1)}".'
        return suggested

    def _selected_group(self) -> str | None:
        selection = self.tree.selection()
        if selection:
            iid = selection[0]
            entry = self.by_key.get(iid)
            if entry:
                return entry.group
            for group, folder_iid in self.folder_iids.items():
                if iid == folder_iid:
                    return group
        filtered = self.filter_var.get()
        return filtered if filtered != "Todos" else None

    def apply_group_suggestions(self) -> None:
        group = self._selected_group()
        if not group:
            messagebox.showinfo(
                "Selecionar grupo",
                "Selecione uma pasta ou um texto do grupo desejado.",
            )
            return
        selection = self.tree.selection()
        selected_folder = bool(selection and selection[0] not in self.by_key)
        changed = 0
        for entry in self.entries:
            if entry.group != group:
                continue
            if entry.target != entry.original:
                continue
            suggested = self._suggestion_for_entry(entry)
            if not suggested:
                continue
            valid, _detail = self.validate_entry(entry, suggested)
            if valid:
                if entry.target != suggested:
                    changed += 1
                entry.target = suggested
        self.refresh_tree()
        if selected_folder:
            folder_iid = self.folder_iids.get(group)
            if folder_iid:
                self.tree.selection_set(folder_iid)
                self.tree.focus(folder_iid)
        if self.current and self.current.group == group:
            self.loading_editor = True
            self.edit_var.set(self.current.target)
            self.loading_editor = False
            self._update_validation()
            self.update_preview()
        self.status_var.set(
            f"Sugestões aplicadas ao grupo '{group}': {changed} textos."
        )

    def restore_selected(self) -> None:
        if not self.current:
            return
        self.current.target = self.current.original
        self.loading_editor = True
        self.edit_var.set(self.current.original)
        self.loading_editor = False
        self.refresh_tree()
        self._update_validation()
        self.update_preview()

    def export_csv(self) -> None:
        if not self.entries:
            return
        path = filedialog.asksaveasfilename(
            title="Exportar traduções",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
            initialfile="koudelka_interface_ptbr.csv",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(("id", "grupo", "arquivo", "offset", "original", "portugues", "limite", "codec"))
            for entry in self.entries:
                writer.writerow((
                    entry.key,
                    entry.group,
                    entry.file_rel,
                    f"0x{entry.offset:X}",
                    entry.original,
                    entry.target,
                    self.text_limit(entry),
                    entry.codec,
                ))
        self.status_var.set(f"CSV exportado: {path}")

    def import_csv(self) -> None:
        if not self.entries:
            return
        path = filedialog.askopenfilename(title="Importar traduções", filetypes=(("CSV", "*.csv"), ("Todos", "*.*")))
        if not path:
            return
        changed, rejected = 0, []
        by_location = {
            (entry.file_rel.casefold(), entry.offset): entry
            for entry in self.entries
        }
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                key = (row.get("id") or "").strip()
                text = row.get("portugues")
                entry = self.by_key.get(key)
                file_rel = (row.get("arquivo") or "").strip().replace("\\", "/")
                offset_text = (row.get("offset") or "").strip()
                try:
                    offset = int(offset_text, 0)
                except ValueError:
                    offset = -1
                entry_by_location = by_location.get((file_rel.casefold(), offset))
                if entry_by_location is not None:
                    entry = entry_by_location
                if not entry or text is None:
                    continue
                # Um CSV antigo pode conter o inglês nas linhas que ainda não
                # tinham sugestão. Não deixe isso apagar uma tradução atual.
                if text == entry.original and entry.target != entry.original:
                    continue
                valid, detail = self.validate_entry(entry, text)
                if valid:
                    entry.target = text
                    changed += 1
                else:
                    rejected.append(f"{key}: {detail}")
        self.refresh_tree()
        if self.current:
            self.loading_editor = True
            self.edit_var.set(self.current.target)
            self.loading_editor = False
            self._update_validation()
            self.update_preview()
        message = f"{changed} traduções importadas."
        if rejected:
            message += "\n\nIgnoradas por excederem o limite:\n" + "\n".join(rejected[:12])
        messagebox.showinfo("Importação concluída", message)

    def _verify_generated_buffers(
        self,
        buffers: dict[str, bytearray],
        changed: list[EntrySpec],
    ) -> None:
        """Auditoria final: nenhuma alteração pode escapar dos blocos previstos."""
        entries_by_file: dict[str, list[EntrySpec]] = {}
        for entry in changed:
            entries_by_file.setdefault(entry.file_rel, []).append(entry)

        for rel, file_entries in entries_by_file.items():
            source = self.source_data[rel]
            generated = buffers[rel]
            if len(source) != len(generated):
                raise ValueError(f"O tamanho de {rel} foi alterado indevidamente.")

            spans = sorted(
                (self._entry_span(entry)[0], self._entry_span(entry)[1], entry)
                for entry in file_entries
            )
            for (_start_a, end_a, entry_a), (start_b, _end_b, entry_b) in zip(spans, spans[1:]):
                if end_a > start_b:
                    raise ValueError(
                        "Blocos de texto sobrepostos: "
                        f"{entry_a.location} e {entry_b.location}."
                    )

            allowed = bytearray(len(source))
            for start, end, entry in spans:
                allowed[start:end] = b"\x01" * (end - start)
                if entry.length_offset is not None:
                    allowed[entry.length_offset] = 1
                elif (
                    entry.codec.startswith("nibble")
                    and entry.file_rel in {"MENU/REPOMENU.BIN", "MENU/BATAMENU.BIN"}
                ):
                    # Esses registros guardam o contador quatro bytes antes
                    # do primeiro glifo; generate_output o atualiza abaixo.
                    allowed[entry.offset - 4] = 1

                if entry.codec == "magic":
                    decoded = decode_magic_record(bytes(generated[start:end]))
                    if decoded != entry.target:
                        raise ValueError(f"Falha ao reler {entry.location}.")
                elif entry.codec.startswith("nibble"):
                    raw = cp1252_bytes(entry.target)
                    expected_prefix = encode_nibble(entry.target, len(raw))
                    if bytes(generated[start:start + len(expected_prefix)]) != expected_prefix:
                        raise ValueError(f"Falha ao reler {entry.location}.")
                    if self._requires_internal_terminator(entry):
                        terminator = start + len(raw) * 2
                        if bytes(generated[terminator:terminator + 2]) != b"\x00\x00":
                            raise ValueError(
                                f"Terminador ausente em {entry.location}."
                            )
                else:
                    raw = cp1252_bytes(entry.target)
                    if bytes(generated[start:start + len(raw)]) != raw:
                        raise ValueError(f"Falha ao reler {entry.location}.")

            escaped = next(
                (
                    index for index, (before, after) in enumerate(zip(source, generated))
                    if before != after and not allowed[index]
                ),
                None,
            )
            if escaped is not None:
                raise ValueError(
                    f"Alteração fora de um bloco autorizado em {rel} @ 0x{escaped:X}."
                )

    def generate_output(self) -> None:
        if not self.game_root or not self.entries or not self.native_font:
            return
        invalid: list[tuple[EntrySpec, str]] = []
        changed = []
        for entry in self.entries:
            if entry.target == entry.original:
                continue
            valid, detail = self.validate_entry(entry, entry.target)
            if not valid:
                invalid.append((entry, detail))
            else:
                changed.append(entry)
        if invalid:
            descriptions = []
            for entry, detail in invalid[:12]:
                descriptions.append(
                    f"• {entry.file_rel} @ 0x{entry.offset:X}\n"
                    f"  Grupo: {entry.group}\n"
                    f"  Texto: {entry.target!r}\n"
                    f"  Erro: {detail}"
                )
            remaining = len(invalid) - len(descriptions)
            if remaining > 0:
                descriptions.append(f"• ...e mais {remaining} texto(s).")
            first_entry = invalid[0][0]
            messagebox.showerror(
                "Textos inválidos",
                "Corrija estes textos antes de gerar:\n\n" + "\n\n".join(descriptions)
                + "\n\nO primeiro erro será selecionado automaticamente.",
            )
            self.focus_entry(first_entry.key)
            self.status_var.set(
                f"Primeiro texto inválido selecionado: {first_entry.location}"
            )
            return
        if not changed:
            messagebox.showinfo("Nada para gerar", "Nenhum texto foi alterado.")
            return
        chosen = filedialog.askdirectory(
            title="Selecionar a pasta de saída (os originais não serão alterados)",
            initialdir=str(self.game_root.parent),
        )
        if not chosen:
            return
        output_root = Path(chosen)
        try:
            if output_root.resolve() == self.game_root.resolve():
                messagebox.showerror("Saída inválida", "Escolha uma pasta diferente da pasta original do jogo.")
                return
        except OSError:
            pass

        buffers = {rel: bytearray(data) for rel, data in self.source_data.items()}
        modified_files: set[str] = set()
        for entry in changed:
            if entry.codec == "magic":
                original_record = self.source_data[entry.file_rel][
                    entry.offset:entry.offset + entry.capacity
                ]
                encoded = encode_magic_record(entry.target, original_record)
            elif entry.codec == "ascii_auto":
                encoded = encode_ascii(entry.target, entry.capacity)
            else:
                encoded = encode_nibble(
                    entry.target,
                    entry.capacity,
                    # Nas entradas automáticas, capacity é exatamente o
                    # comprimento original e o terminador fica logo depois do
                    # bloco. Espaços removem glifos residuais em campos fixos
                    # sem apagar esse terminador externo. Entradas conhecidas
                    # mantêm preenchimento 00 00 dentro do bloco.
                    pad_with_spaces=entry.codec == "nibble_auto",
                )
            buffer = buffers[entry.file_rel]
            end = entry.offset + len(encoded)
            if end > len(buffer):
                raise ValueError(f"Entrada fora do arquivo: {entry.location}")
            buffer[entry.offset:end] = encoded

            # REPOMENU e BATAMENU guardam o comprimento do texto no
            # primeiro byte do registro, quatro bytes antes dos glifos.
            # Sem atualizar esse contador, textos maiores são cortados e
            # textos menores fazem o jogo ler pares 00 00 como caracteres.
            if (
                entry.codec.startswith("nibble")
                and entry.file_rel in {"MENU/REPOMENU.BIN", "MENU/BATAMENU.BIN"}
            ):
                buffer[entry.offset - 4] = len(cp1252_bytes(entry.target))
            elif entry.length_offset is not None:
                buffer[entry.length_offset] = len(cp1252_bytes(entry.target))
            modified_files.add(entry.file_rel)

        try:
            self._verify_generated_buffers(buffers, changed)
            for rel in sorted(modified_files):
                destination = output_root / Path(rel)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(buffers[rel])

            accent_chars = {
                ch for entry in changed for ch in entry.target if ch in ACCENTS
            }
            if accent_chars:
                font_destination = output_root / Path(FONT_REL)
                font_destination.parent.mkdir(parents=True, exist_ok=True)
                font_destination.write_bytes(self.native_font.patched_bytes(accent_chars))
                modified_files.add(FONT_REL)

            report = output_root / "RELATORIO_INTERFACE_PTBR.txt"
            lines = [
                "Koudelka - arquivos de interface gerados",
                "",
                "Originais não modificados.",
                "ITMTBL.ITM e nomes de itens não foram processados.",
                "",
                "Arquivos gerados:",
                *[f"- {rel}" for rel in sorted(modified_files)],
                "",
                "Textos alterados:",
                *[f"- {entry.location}: {entry.original!r} -> {entry.target!r}" for entry in changed],
            ]
            report.write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Erro ao gerar", str(exc))
            return

        self.status_var.set(f"Arquivos gerados em: {output_root}")
        messagebox.showinfo(
            "Concluído",
            f"{len(changed)} textos gerados em:\n\n{output_root}\n\n"
            "A estrutura MENU/BIN foi preservada. Os arquivos originais não foram alterados.",
        )


def main() -> None:
    app = InterfaceEditorApp()
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1].strip('"'))
        if candidate.is_dir():
            app.path_var.set(str(candidate))
            app.after(100, app.load_game)
    app.mainloop()


if __name__ == "__main__":
    main()
