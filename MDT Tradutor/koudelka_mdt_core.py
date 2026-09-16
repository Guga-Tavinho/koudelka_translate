#!/usr/bin/env python3
"""Nucleo de leitura e reinsercao de textos MDT de Koudelka (PS1)."""

from __future__ import annotations

import csv
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# O jogo organiza o ASCII em uma grade 16xN. Ex.: A=41 44, a=41 46.
DECODE: dict[bytes, str] = {}
ENCODE: dict[str, bytes] = {}
for value in range(0x20, 0x7F):
    char = chr(value)
    code = bytes((0x40 | (value & 0x0F), 0x40 | (value >> 4)))
    DECODE[code] = char
    ENCODE[char] = code

CTRL_LINEBREAK = bytes.fromhex("6860")
CTRL_LINEBREAK_ALT = bytes.fromhex("6960")
CTRL_PREFIXES = {
    bytes.fromhex("6060"): "6060",
    bytes.fromhex("6160"): "6160",
}
DECODE_INT = {code[0] | (code[1] << 8): char for code, char in DECODE.items()}
LINEBREAK_INTS = {
    CTRL_LINEBREAK[0] | (CTRL_LINEBREAK[1] << 8),
    CTRL_LINEBREAK_ALT[0] | (CTRL_LINEBREAK_ALT[1] << 8),
}
PREFIX_INTS = {
    code[0] | (code[1] << 8): label for code, label in CTRL_PREFIXES.items()
}


@dataclass
class TextEntry:
    id: int
    local_id: int
    file_path: Path
    relative_path: str
    offset: int
    payload_offset: int
    end: int
    prefix: str
    max_bytes: int
    original: str
    translation: str = ""

    @property
    def max_chars(self) -> int:
        return self.max_bytes // 2


def normalize_pt(text: str) -> str:
    """Converte pontuacao tipografica e letras acentuadas para o codec ASCII."""
    replacements = {
        "—": "-", "–": "-", "−": "-", "…": "...",
        "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
        "º": "o", "ª": "a", " ": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(
        char for char in decomposed
        if unicodedata.category(char) != "Mn"
    )


def encode_text(text: str, normalize: bool = True) -> bytes:
    """Codifica texto; quebras viram 68 60 e {ABCD} insere um codigo bruto."""
    if normalize:
        text = normalize_pt(text)

    output = bytearray()
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\n":
            output += CTRL_LINEBREAK
            index += 1
            continue

        if char == "{" and (closing := text.find("}", index + 1)) != -1:
            token = text[index + 1:closing]
            if len(token) == 4:
                try:
                    output += bytes.fromhex(token)
                    index = closing + 1
                    continue
                except ValueError:
                    pass

        code = ENCODE.get(char)
        if code is None:
            raise ValueError(
                f"Caractere nao suportado: {char!r} (U+{ord(char):04X})"
            )
        output += code
        index += 1
    return bytes(output)


def decode_code(code: bytes) -> str | None:
    if code in (CTRL_LINEBREAK, CTRL_LINEBREAK_ALT):
        return "\n"
    return DECODE.get(code)


def _looks_like_text(chars: list[str]) -> bool:
    text = "".join(chars)
    letters = sum(char.isalpha() for char in text)
    printable = sum(char.isprintable() or char == "\n" for char in text)
    return len(text) >= 4 and letters >= 3 and printable >= len(text) * 0.85


def scan_strings(
    data: bytes,
    file_path: Path | str = Path(""),
    relative_path: str = "",
    first_id: int = 1,
) -> list[TextEntry]:
    """Localiza strings MDT terminadas por 00 nas duas paridades do arquivo."""
    candidates: list[dict] = []
    seen: set[tuple[int, int]] = set()
    size = len(data)

    for parity in (0, 1):
        position = parity
        while position + 2 <= size:
            start = position
            cursor = position
            chars: list[str] = []
            prefix = ""

            first_int = data[cursor] | (data[cursor + 1] << 8)
            if first_int in PREFIX_INTS:
                prefix = PREFIX_INTS[first_int]
                cursor += 2

            while cursor + 1 < size:
                if data[cursor] == 0:
                    break
                code_int = data[cursor] | (data[cursor + 1] << 8)
                if code_int in PREFIX_INTS:
                    break
                if code_int in LINEBREAK_INTS:
                    decoded = "\n"
                else:
                    decoded = DECODE_INT.get(code_int)
                if decoded is None:
                    break
                chars.append(decoded)
                cursor += 2

            if chars and cursor < size and data[cursor] == 0 and _looks_like_text(chars):
                key = (start, cursor)
                if key not in seen:
                    seen.add(key)
                    payload = start + (2 if prefix else 0)
                    candidates.append({
                        "offset": start,
                        "payload_offset": payload,
                        "end": cursor,
                        "prefix": prefix,
                        "max_bytes": cursor - payload,
                        "original": "".join(chars),
                    })
                position = cursor + 1
                if position % 2 != parity:
                    position += 1
                continue
            position = start + 2

    candidates.sort(key=lambda item: item["offset"])
    cleaned: list[dict] = []
    for item in candidates:
        if any(
            previous["offset"] <= item["offset"]
            and previous["end"] >= item["end"]
            for previous in cleaned
        ):
            continue
        cleaned.append(item)

    source = Path(file_path)
    result: list[TextEntry] = []
    for local_id, item in enumerate(cleaned, 1):
        result.append(TextEntry(
            id=first_id + local_id - 1,
            local_id=local_id,
            file_path=source,
            relative_path=relative_path or source.name,
            offset=item["offset"],
            payload_offset=item["payload_offset"],
            end=item["end"],
            prefix=item["prefix"],
            max_bytes=item["max_bytes"],
            original=item["original"],
        ))
    return result


def load_file(path: Path | str) -> tuple[bytes, list[TextEntry]]:
    source = Path(path).resolve()
    data = source.read_bytes()
    return data, scan_strings(data, source, source.name)


def load_folder(
    root: Path | str,
) -> tuple[dict[Path, bytes], list[TextEntry], int]:
    base = Path(root).resolve()
    files = sorted(
        path for path in base.rglob("*")
        if path.is_file() and path.suffix.lower() == ".mdt"
    )
    file_data: dict[Path, bytes] = {}
    entries: list[TextEntry] = []
    next_id = 1
    for path in files:
        data = path.read_bytes()
        file_data[path] = data
        relative = path.relative_to(base).as_posix()
        found = scan_strings(data, path, relative, next_id)
        entries.extend(found)
        next_id += len(found)
    return file_data, entries, len(files)


def entry_validation(entry: TextEntry, normalize: bool = True) -> tuple[str, int, str]:
    if entry.translation == "":
        return "ORIGINAL", 0, "O texto original sera mantido."
    try:
        encoded = encode_text(entry.translation, normalize)
    except ValueError as error:
        return "ERRO_CODEC", 0, str(error)
    used = len(encoded)
    if used > entry.max_bytes:
        return (
            "EXCEDE",
            used,
            f"Excede o limite em {used - entry.max_bytes} bytes.",
        )
    return "OK", used, f"Usa {used} de {entry.max_bytes} bytes."


def patch_data(
    original: bytes,
    entries: Iterable[TextEntry],
    normalize: bool = True,
) -> tuple[bytes, int]:
    output = bytearray(original)
    changed = 0
    for entry in sorted(entries, key=lambda item: item.payload_offset):
        if entry.translation == "":
            continue
        status, _, detail = entry_validation(entry, normalize)
        if status != "OK":
            raise ValueError(f"ID {entry.id}: {detail}")
        encoded = encode_text(entry.translation, normalize)
        start = entry.payload_offset
        finish = start + entry.max_bytes
        if finish > len(output):
            raise ValueError(f"ID {entry.id}: regiao reservada fora do arquivo.")
        output[start:finish] = encoded + bytes(entry.max_bytes - len(encoded))
        changed += 1
    if len(output) != len(original):
        raise RuntimeError("Falha de seguranca: o tamanho do MDT mudou.")
    return bytes(output), changed


CSV_FIELDS = [
    "id", "local_id", "relative_path", "filename", "offset_hex",
    "offset_dec", "payload_offset_hex", "prefix_code", "max_bytes",
    "max_chars_approx", "original_text", "translation_pt", "status",
]


def _csv_text(text: str) -> str:
    return text.replace("\n", "\\n")


def _uncsv_text(text: str) -> str:
    return (text or "").replace("\\n", "\n")


def export_csv(
    entries: Iterable[TextEntry],
    path: Path | str,
    normalize: bool = True,
) -> None:
    rows = []
    for entry in entries:
        status, _, _ = entry_validation(entry, normalize)
        rows.append({
            "id": entry.id,
            "local_id": entry.local_id,
            "relative_path": entry.relative_path,
            "filename": entry.file_path.name,
            "offset_hex": f"0x{entry.offset:08X}",
            "offset_dec": entry.offset,
            "payload_offset_hex": f"0x{entry.payload_offset:08X}",
            "prefix_code": entry.prefix,
            "max_bytes": entry.max_bytes,
            "max_chars_approx": entry.max_chars,
            "original_text": _csv_text(entry.original),
            "translation_pt": _csv_text(entry.translation),
            "status": status,
        })
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def import_csv(entries: list[TextEntry], path: Path | str) -> tuple[int, int]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return 0, 0

    by_file_offset = {
        (entry.relative_path.replace("\\", "/").lower(), entry.payload_offset): entry
        for entry in entries
    }
    by_offset: dict[int, list[TextEntry]] = {}
    for entry in entries:
        by_offset.setdefault(entry.payload_offset, []).append(entry)

    imported = 0
    unmatched = 0
    for row in rows:
        raw_offset = row.get("payload_offset_hex") or row.get("payload_offset")
        try:
            offset = int(str(raw_offset), 0)
        except (TypeError, ValueError):
            unmatched += 1
            continue

        relative = (row.get("relative_path") or "").replace("\\", "/").lower()
        target = by_file_offset.get((relative, offset)) if relative else None
        if target is None and len(by_offset.get(offset, [])) == 1:
            target = by_offset[offset][0]
        if target is None:
            unmatched += 1
            continue
        target.translation = _uncsv_text(row.get("translation_pt", ""))
        imported += 1
    return imported, unmatched


def write_single(
    original: bytes,
    entries: list[TextEntry],
    destination: Path | str,
    normalize: bool = True,
) -> int:
    patched, changed = patch_data(original, entries, normalize)
    target = Path(destination)
    target.write_bytes(patched)
    if target.stat().st_size != len(original):
        raise RuntimeError("O arquivo salvo nao manteve o tamanho original.")
    return changed


def write_folder(
    source_root: Path | str,
    destination_root: Path | str,
    file_data: dict[Path, bytes],
    entries: list[TextEntry],
    normalize: bool = True,
) -> int:
    source = Path(source_root).resolve()
    destination = Path(destination_root).resolve()
    if destination.exists():
        raise FileExistsError(f"A pasta de saida ja existe: {destination}")
    if destination == source or source in destination.parents:
        raise ValueError("A saida nao pode ficar dentro da pasta MDT original.")

    shutil.copytree(source, destination)
    by_path: dict[Path, list[TextEntry]] = {}
    for entry in entries:
        by_path.setdefault(entry.file_path, []).append(entry)

    changed = 0
    try:
        for source_file, original in file_data.items():
            target = destination / source_file.relative_to(source)
            patched, local_changed = patch_data(
                original, by_path.get(source_file, []), normalize
            )
            target.write_bytes(patched)
            if target.stat().st_size != len(original):
                raise RuntimeError(f"Tamanho alterado indevidamente: {target}")
            changed += local_changed
    except Exception:
        # A pasta parcial e mantida para diagnostico; nunca apagamos dados do usuario.
        raise
    return changed
