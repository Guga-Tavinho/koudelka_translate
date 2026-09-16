#!/usr/bin/env python3
"""
Koudelka - Injetor MDT via MSYS2 v4 GUI
=======================================

Sem argumentos, abre a interface gráfica.
Com argumentos, mantém o fluxo de linha de comando compatível com a v3.

Modos da interface:
- um MDT isolado, com caminho interno editável;
- uma pasta MDT estruturada, preservando os caminhos relativos.

Por segurança, a interface trabalha em uma cópia do BIN por padrão.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Koudelka MDT Injector v4 - MSYS2"
SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SCRIPT_DIR / "koudelka_inject_gui_settings.json"
DEFAULT_BASH = Path(r"C:\msys64\usr\bin\bash.exe")
PSXINJECT_CANDIDATES = (
    Path(r"C:\msys64\home\sistemas2\psximager\src\psxinject.exe"),
    Path(r"C:\msys64\home\sistemas2\psximager-v2.2\src\psxinject.exe"),
)
LOG_FIELDS = (
    "index", "relative_path", "internal_path", "source_file",
    "status", "returncode", "command", "stdout", "stderr",
)


@dataclass(frozen=True)
class InjectionItem:
    source_file: Path
    relative_path: str
    internal_path: str


@dataclass
class InjectionResult:
    rows: list[dict]
    ok: int
    errors: int
    cancelled: bool
    log_path: Path
    target_bin: Path
    cue_path: Path | None = None


def windows_to_msys(path: Path | str) -> str:
    """Converte C:\foo\bar para /c/foo/bar."""
    value = str(Path(path).resolve())
    if len(value) >= 2 and value[1] == ":":
        drive = value[0].lower()
        remainder = value[2:].replace("\\", "/")
        return f"/{drive}{remainder}"
    return value.replace("\\", "/")


def shell_quote(value: str) -> str:
    return shlex.quote(str(value))


def normalize_internal_path(value: str) -> str:
    value = (value or "").strip().replace("\\", "/")
    value = re.sub(r"/+", "/", value).lstrip("/")
    if not value:
        raise ValueError("O caminho interno no CD está vazio.")
    if value.startswith("../") or "/../" in f"/{value}/":
        raise ValueError("O caminho interno não pode conter '..'.")
    return value


def guess_internal_path(file_path: Path | str, prefix: str = "MDT") -> str:
    path = Path(file_path).resolve()
    parts = list(path.parts)
    for index in range(len(parts) - 2, -1, -1):
        if parts[index].lower() == "mdt":
            return "/".join(parts[index:])
    parent_name = path.parent.name
    if parent_name and parent_name.lower() not in ("mdt-traduzido", "mdt_traduzido"):
        return f"{prefix.rstrip('/')}/{parent_name}/{path.name}"
    return f"{prefix.rstrip('/')}/{path.name}"


def discover_items(
    source: Path | str,
    prefix: str = "MDT",
    internal_single: str = "",
) -> list[InjectionItem]:
    source_path = Path(source).resolve()
    prefix = normalize_internal_path(prefix).rstrip("/")

    if source_path.is_file():
        if source_path.suffix.lower() != ".mdt":
            raise ValueError("O arquivo selecionado não possui extensão .MDT.")
        internal = normalize_internal_path(
            internal_single or guess_internal_path(source_path, prefix)
        )
        return [InjectionItem(source_path, source_path.name, internal)]

    if not source_path.is_dir():
        raise ValueError(f"Arquivo ou pasta não encontrado: {source_path}")

    files = sorted(
        path for path in source_path.rglob("*")
        if path.is_file() and path.suffix.lower() == ".mdt"
    )
    if not files:
        raise ValueError(f"Nenhum arquivo .MDT encontrado em: {source_path}")

    return [
        InjectionItem(
            source_file=path,
            relative_path=path.relative_to(source_path).as_posix(),
            internal_path=f"{prefix}/{path.relative_to(source_path).as_posix()}",
        )
        for path in files
    ]


def validate_tools(
    bash_exe: Path | str,
    psxinject: Path | str,
    bin_path: Path | str,
    *,
    dry_run: bool = False,
) -> tuple[Path, Path, Path]:
    bash = Path(bash_exe).resolve()
    injector = Path(psxinject).resolve()
    image = Path(bin_path).resolve()
    if not image.is_file():
        raise ValueError(f"BIN não encontrado: {image}")
    if not dry_run:
        if not injector.is_file():
            raise ValueError(f"psxinject.exe não encontrado: {injector}")
        if not bash.is_file():
            raise ValueError(f"Bash do MSYS2 não encontrado: {bash}")
    return bash, injector, image


def build_psxinject_command(
    psxinject_msys: str,
    bin_msys: str,
    internal_path: str,
    file_msys: str,
    verbose: bool = False,
) -> str:
    parts = [shell_quote(psxinject_msys)]
    if verbose:
        parts.append("-v")
    parts.extend((
        shell_quote(bin_msys),
        shell_quote(internal_path),
        shell_quote(file_msys),
    ))
    return " ".join(parts)


def run_psxinject(
    bash_exe: Path,
    psxinject_msys: str,
    bin_msys: str,
    item: InjectionItem,
    verbose: bool = False,
) -> tuple[int, str, str, str]:
    command = build_psxinject_command(
        psxinject_msys,
        bin_msys,
        item.internal_path,
        windows_to_msys(item.source_file),
        verbose,
    )
    completed = subprocess.run(
        [str(bash_exe), "-lc", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode, completed.stdout, completed.stderr, command


def find_free_log(path: Path | str) -> Path:
    requested = Path(path).resolve()
    if not requested.exists():
        return requested
    for number in range(2, 1000):
        candidate = requested.with_name(
            f"{requested.stem}_{number}{requested.suffix}"
        )
        if not candidate.exists():
            return candidate
    raise RuntimeError("Não foi possível escolher um nome de log livre.")


def write_log(rows: list[dict], requested_path: Path | str) -> Path:
    log_path = find_free_log(requested_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return log_path


def copy_companion_cue(original_bin: Path, target_bin: Path) -> Path | None:
    source_cue = original_bin.with_suffix(".cue")
    if not source_cue.is_file():
        return None
    target_cue = target_bin.with_suffix(".cue")
    raw = source_cue.read_bytes()
    text = None
    encoding_used = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            # Read with utf-8-sig to tolerate/remove an existing BOM, but do
            # not write the BOM back: psxinject would read "\ufeffFILE" instead
            # of the required CUE keyword "FILE".
            encoding_used = "utf-8" if encoding == "utf-8-sig" else encoding
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        shutil.copy2(source_cue, target_cue)
        return target_cue
    text = re.sub(
        re.escape(original_bin.name),
        target_bin.name,
        text,
        flags=re.IGNORECASE,
    )
    # Preserve the line endings already present in the source CUE. Using
    # write_text on Windows would expand CRLF into CRCRLF in this case.
    target_cue.write_bytes(text.encode(encoding_used or "utf-8"))
    return target_cue


def inject_items(
    items: list[InjectionItem],
    original_bin: Path | str,
    target_bin: Path | str,
    bash_exe: Path | str,
    psxinject: Path | str,
    log_path: Path | str,
    *,
    make_copy: bool = True,
    overwrite_copy: bool = False,
    continue_on_error: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
    cancel_event: threading.Event | None = None,
    event_callback=None,
) -> InjectionResult:
    callback = event_callback or (lambda _kind, _payload: None)
    bash, injector, original = validate_tools(
        bash_exe, psxinject, original_bin, dry_run=dry_run
    )
    target = Path(target_bin).resolve() if make_copy else original

    if make_copy:
        if target == original:
            raise ValueError("A cópia de saída precisa ter outro nome.")
        if target.exists() and not overwrite_copy:
            raise FileExistsError(f"O BIN de saída já existe: {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            callback("message", f"Copiando BIN original para:\n{target}")
            shutil.copy2(original, target)
            cue_path = copy_companion_cue(original, target)
        else:
            cue_path = None
    else:
        cue_path = None

    bin_msys = windows_to_msys(target)
    injector_msys = windows_to_msys(injector)
    rows: list[dict] = []
    ok = errors = 0
    cancelled = False

    for index, item in enumerate(items, 1):
        if cancel_event and cancel_event.is_set():
            cancelled = True
            callback("message", "Cancelamento solicitado; interrompendo entre arquivos.")
            break

        callback("progress", (index - 1, len(items), item.internal_path))
        if dry_run:
            command = build_psxinject_command(
                injector_msys,
                bin_msys,
                item.internal_path,
                windows_to_msys(item.source_file),
                verbose,
            )
            status, returncode, stdout, stderr = "DRY_RUN", "", "", ""
            callback("message", f"[{index}/{len(items)}] {item.internal_path} — SIMULAÇÃO")
        else:
            returncode, stdout, stderr, command = run_psxinject(
                bash, injector_msys, bin_msys, item, verbose
            )
            if returncode == 0:
                ok += 1
                status = "OK"
                callback("message", f"[{index}/{len(items)}] {item.internal_path} — OK")
            else:
                errors += 1
                status = "ERRO"
                callback(
                    "message",
                    f"[{index}/{len(items)}] {item.internal_path} — ERRO ({returncode})\n"
                    f"{stderr.strip() or stdout.strip() or '(sem detalhes)'}",
                )

        rows.append({
            "index": index,
            "relative_path": item.relative_path,
            "internal_path": item.internal_path,
            "source_file": str(item.source_file),
            "status": status,
            "returncode": returncode,
            "command": command,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
        })
        if status == "ERRO" and not continue_on_error:
            callback("message", "Injeção interrompida no primeiro erro.")
            break

    callback("progress", (len(rows), len(items), "Concluído"))
    actual_log = write_log(rows, log_path)
    return InjectionResult(rows, ok, errors, cancelled, actual_log, target, cue_path)


def discover_default_psxinject() -> str:
    for path in PSXINJECT_CANDIDATES:
        if path.is_file():
            return str(path)
    return str(PSXINJECT_CANDIDATES[0])


class InjectorGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x700")
        self.minsize(720, 520)
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.preview_items: list[InjectionItem] = []

        self.mode_var = tk.StringVar(value="folder")
        self.source_var = tk.StringVar()
        self.internal_var = tk.StringVar()
        self.bin_var = tk.StringVar()
        self.output_bin_var = tk.StringVar()
        self.psxinject_var = tk.StringVar(value=discover_default_psxinject())
        self.bash_var = tk.StringVar(value=str(DEFAULT_BASH))
        self.prefix_var = tk.StringVar(value="MDT")
        self.log_var = tk.StringVar()
        self.copy_var = tk.BooleanVar(value=True)
        self.continue_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.summary_var = tk.StringVar(value="Selecione um MDT ou uma pasta estruturada.")
        self.status_var = tk.StringVar(value="Pronto")

        self._load_settings()
        self._configure_style()
        self._build_ui()
        self._mode_changed()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=("Arial", 10))
        style.configure("Title.TLabel", font=("Arial", 12, "bold"))
        style.configure("Treeview", font=("Arial", 9), rowheight=22)
        style.configure("Treeview.Heading", font=("Arial", 9, "bold"))

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=8)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Injeção de MDT no BIN do Koudelka",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            container,
            text="Executa psxinject dentro do MSYS2. A cópia de segurança do BIN fica ativa por padrão.",
        ).pack(anchor="w", pady=(1, 5))

        # As configuracoes ficam em abas para a janela caber em telas menores.
        # O rodape de acao e empacotado antes da area expansivel para permanecer
        # sempre visivel, mesmo quando a altura disponivel for pequena.
        settings_tabs = ttk.Notebook(container)
        settings_tabs.pack(fill="x")

        source_frame = ttk.Frame(settings_tabs, padding=7)
        bin_frame = ttk.Frame(settings_tabs, padding=7)
        tools_frame = ttk.Frame(settings_tabs, padding=7)
        settings_tabs.add(source_frame, text="1. Arquivos MDT")
        settings_tabs.add(bin_frame, text="2. Imagem do jogo")
        settings_tabs.add(tools_frame, text="3. Ferramentas e opções")

        mode_row = ttk.Frame(source_frame)
        mode_row.pack(fill="x")
        ttk.Radiobutton(
            mode_row, text="Um MDT isolado", value="file",
            variable=self.mode_var, command=self._mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_row, text="Pasta MDT estruturada", value="folder",
            variable=self.mode_var, command=self._mode_changed,
        ).pack(side="left", padx=(18, 0))
        self._path_row(source_frame, "Origem:", self.source_var, self.browse_source)
        internal_row = ttk.Frame(source_frame)
        internal_row.pack(fill="x", pady=(4, 0))
        ttk.Label(internal_row, text="Caminho interno:", width=15).pack(side="left")
        self.internal_entry = ttk.Entry(internal_row, textvariable=self.internal_var)
        self.internal_entry.pack(side="left", fill="x", expand=True)
        ttk.Label(
            internal_row,
            text="Ex.: MDT/OMO/OMO07000.MDT",
        ).pack(side="left", padx=(5, 0))
        ttk.Button(
            source_frame, text="Atualizar lista de MDTs",
            command=self.refresh_preview,
        ).pack(anchor="e", pady=(5, 0))

        self._path_row(bin_frame, "BIN original:", self.bin_var, self.browse_bin)
        self._path_row(bin_frame, "BIN de saída:", self.output_bin_var, self.browse_output_bin)
        ttk.Checkbutton(
            bin_frame,
            text="Trabalhar em uma cópia do BIN original (recomendado)",
            variable=self.copy_var,
            command=self._copy_changed,
        ).pack(anchor="w", pady=(4, 0))

        self._path_row(tools_frame, "psxinject.exe:", self.psxinject_var, self.browse_psxinject)
        self._path_row(tools_frame, "Bash MSYS2:", self.bash_var, self.browse_bash)
        small_row = ttk.Frame(tools_frame)
        small_row.pack(fill="x", pady=(4, 0))
        ttk.Label(small_row, text="Prefixo no CD:", width=15).pack(side="left")
        ttk.Entry(small_row, textvariable=self.prefix_var, width=15).pack(side="left")
        ttk.Label(small_row, text="Log CSV:", width=11).pack(side="left", padx=(15, 0))
        ttk.Entry(small_row, textvariable=self.log_var).pack(side="left", fill="x", expand=True)
        ttk.Button(small_row, text="Escolher...", command=self.browse_log).pack(side="left", padx=(6, 0))
        options = ttk.Frame(tools_frame)
        options.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(
            options, text="Continuar após erro", variable=self.continue_var
        ).pack(side="left")
        ttk.Checkbutton(
            options, text="Saída detalhada do psxinject", variable=self.verbose_var
        ).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(
            options, text="Somente simular (não altera o BIN)", variable=self.dry_run_var
        ).pack(side="left", padx=(16, 0))

        action_row = ttk.Frame(container)
        action_row.pack(side="bottom", fill="x", pady=(6, 0))
        self.progress = ttk.Progressbar(action_row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(action_row, textvariable=self.status_var, width=20).pack(side="left", padx=7)
        self.cancel_button = ttk.Button(
            action_row, text="Cancelar", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="right")
        self.start_button = ttk.Button(
            action_row, text="INJETAR MDT", command=self.start
        )
        self.start_button.pack(side="right", padx=(0, 7))

        results_tabs = ttk.Notebook(container)
        results_tabs.pack(fill="both", expand=True, pady=(6, 0))

        preview_frame = ttk.Frame(results_tabs, padding=6)
        log_frame = ttk.Frame(results_tabs, padding=6)
        results_tabs.add(preview_frame, text="Arquivos que serão injetados")
        results_tabs.add(log_frame, text="Progresso / log")

        ttk.Label(preview_frame, textvariable=self.summary_var).pack(anchor="w", pady=(0, 5))
        columns = ("n", "internal", "source", "size")
        tree_area = ttk.Frame(preview_frame)
        tree_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_area, columns=columns, show="headings", height=6)
        self.tree.heading("n", text="#")
        self.tree.heading("internal", text="Caminho interno no CD")
        self.tree.heading("source", text="Arquivo de origem")
        self.tree.heading("size", text="Bytes")
        self.tree.column("n", width=45, stretch=False, anchor="center")
        self.tree.column("internal", width=330)
        self.tree.column("source", width=560)
        self.tree.column("size", width=90, stretch=False, anchor="e")
        scrollbar = ttk.Scrollbar(tree_area, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(tree_area, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        tree_area.rowconfigure(0, weight=1)
        tree_area.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame, height=6, wrap="word", font=("Consolas", 9),
            state="disabled", background="#111827", foreground="#e5e7eb",
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    @staticmethod
    def _path_row(parent, label: str, variable: tk.StringVar, command) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text=label, width=15).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Escolher...", command=command).pack(side="left", padx=(6, 0))

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.is_file():
            return
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        self.psxinject_var.set(settings.get("psxinject", self.psxinject_var.get()))
        self.bash_var.set(settings.get("bash", self.bash_var.get()))
        self.prefix_var.set(settings.get("prefix", "MDT"))
        self.bin_var.set(settings.get("last_bin", ""))
        self.copy_var.set(bool(settings.get("make_copy", True)))

    def _save_settings(self) -> None:
        settings = {
            "psxinject": self.psxinject_var.get(),
            "bash": self.bash_var.get(),
            "prefix": self.prefix_var.get(),
            "last_bin": self.bin_var.get(),
            "make_copy": self.copy_var.get(),
        }
        try:
            SETTINGS_FILE.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _mode_changed(self) -> None:
        state = "normal" if self.mode_var.get() == "file" else "disabled"
        if hasattr(self, "internal_entry"):
            self.internal_entry.configure(state=state)
        self.preview_items = []
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        self.summary_var.set(
            "Selecione um arquivo MDT." if state == "normal"
            else "Selecione a pasta raiz estruturada, como MDT-Traduzido."
        )

    def _copy_changed(self) -> None:
        if self.copy_var.get() and self.bin_var.get() and not self.output_bin_var.get():
            self._set_default_output()

    def browse_source(self) -> None:
        if self.mode_var.get() == "file":
            selected = filedialog.askopenfilename(
                title="Selecionar MDT",
                filetypes=(("Arquivos MDT", "*.MDT *.mdt"), ("Todos", "*.*")),
            )
        else:
            selected = filedialog.askdirectory(title="Selecionar pasta MDT estruturada")
        if not selected:
            return
        self.source_var.set(selected)
        if self.mode_var.get() == "file":
            self.internal_var.set(guess_internal_path(selected, self.prefix_var.get() or "MDT"))
        self.refresh_preview()

    def browse_bin(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar BIN original",
            filetypes=(("Imagem BIN", "*.bin *.BIN"), ("Todos", "*.*")),
        )
        if selected:
            self.bin_var.set(selected)
            self._set_default_output()

    def _set_default_output(self) -> None:
        source = Path(self.bin_var.get())
        if not source.name:
            return
        self.output_bin_var.set(str(source.with_name(f"{source.stem}_PTBR{source.suffix}")))
        self.log_var.set(str(source.with_name("koudelka_inject_mdt_log.csv")))

    def browse_output_bin(self) -> None:
        source = Path(self.bin_var.get()) if self.bin_var.get() else Path.cwd() / "Koudelka.bin"
        selected = filedialog.asksaveasfilename(
            title="Salvar cópia do BIN",
            initialdir=source.parent,
            initialfile=f"{source.stem}_PTBR{source.suffix or '.bin'}",
            defaultextension=".bin",
            filetypes=(("Imagem BIN", "*.bin"),),
        )
        if selected:
            self.output_bin_var.set(selected)

    def browse_psxinject(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar psxinject.exe",
            filetypes=(("Executável", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.psxinject_var.set(selected)

    def browse_bash(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar bash.exe do MSYS2",
            filetypes=(("Executável", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.bash_var.set(selected)

    def browse_log(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Salvar log CSV",
            initialfile="koudelka_inject_mdt_log.csv",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
        )
        if selected:
            self.log_var.set(selected)

    def refresh_preview(self) -> None:
        try:
            items = discover_items(
                self.source_var.get(),
                self.prefix_var.get() or "MDT",
                self.internal_var.get() if self.mode_var.get() == "file" else "",
            )
        except Exception as error:
            self.preview_items = []
            self.tree.delete(*self.tree.get_children())
            self.summary_var.set(str(error))
            return
        self.preview_items = items
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(items, 1):
            self.tree.insert("", "end", values=(
                index, item.internal_path, str(item.source_file),
                item.source_file.stat().st_size,
            ))
        total_bytes = sum(item.source_file.stat().st_size for item in items)
        self.summary_var.set(
            f"{len(items)} MDT(s) • {total_bytes:,} bytes • confira os caminhos internos antes de injetar"
        )

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.refresh_preview()
        if not self.preview_items:
            messagebox.showerror("Nada para injetar", self.summary_var.get(), parent=self)
            return
        try:
            bash, injector, original = validate_tools(
                self.bash_var.get(),
                self.psxinject_var.get(),
                self.bin_var.get(),
                dry_run=self.dry_run_var.get(),
            )
            make_copy = self.copy_var.get()
            target = (
                Path(self.output_bin_var.get()).resolve()
                if make_copy else original
            )
            if make_copy and not self.output_bin_var.get():
                raise ValueError("Escolha o BIN de saída.")
            if make_copy and target == original:
                raise ValueError("O BIN de saída não pode ser o BIN original.")
            log = (
                Path(self.log_var.get()).resolve()
                if self.log_var.get()
                else target.with_name("koudelka_inject_mdt_log.csv")
            )
        except Exception as error:
            messagebox.showerror("Configuração inválida", str(error), parent=self)
            return

        overwrite = False
        if make_copy and target.exists() and not self.dry_run_var.get():
            overwrite = messagebox.askyesno(
                "Substituir cópia existente?",
                f"O BIN de saída já existe:\n{target}\n\nDeseja substituí-lo pela nova cópia?",
                parent=self,
            )
            if not overwrite:
                return

        if not self.dry_run_var.get():
            warning = (
                f"Serão injetados {len(self.preview_items)} MDT(s).\n\n"
                f"BIN usado: {target}\n\n"
            )
            if not make_copy:
                warning += "ATENÇÃO: o BIN selecionado será modificado diretamente.\n\n"
            warning += "Deseja continuar?"
            if not messagebox.askyesno("Confirmar injeção", warning, parent=self):
                return

        self._save_settings()
        self.cancel_event.clear()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(maximum=len(self.preview_items), value=0)
        self.status_var.set("Preparando...")
        self._append_log("=" * 72)
        self._append_log(f"Início — {len(self.preview_items)} MDT(s)")

        options = {
            "items": list(self.preview_items),
            "original_bin": original,
            "target_bin": target,
            "bash_exe": bash,
            "psxinject": injector,
            "log_path": log,
            "make_copy": make_copy,
            "overwrite_copy": overwrite,
            "continue_on_error": self.continue_var.get(),
            "verbose": self.verbose_var.get(),
            "dry_run": self.dry_run_var.get(),
            "cancel_event": self.cancel_event,
            "event_callback": lambda kind, payload: self.events.put((kind, payload)),
        }
        self.worker = threading.Thread(
            target=self._worker_run, args=(options,), daemon=True
        )
        self.worker.start()

    def _worker_run(self, options: dict) -> None:
        try:
            result = inject_items(**options)
            self.events.put(("done", result))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "message":
                    self._append_log(str(payload))
                elif kind == "progress":
                    current, total, label = payload
                    self.progress.configure(maximum=max(1, total), value=current)
                    self.status_var.set(f"{current}/{total} — {label}")
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.status_var.set("Erro")
                    self._append_log(f"ERRO: {payload}")
                    messagebox.showerror("Falha na injeção", payload, parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _finish(self, result: InjectionResult) -> None:
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        if result.cancelled:
            state = "Cancelado"
        elif result.errors:
            state = f"Concluído com {result.errors} erro(s)"
        else:
            state = "Concluído"
        self.status_var.set(state)
        self._append_log(
            f"Resultado: {result.ok} OK, {result.errors} erro(s), "
            f"{len(result.rows)} processado(s)."
        )
        self._append_log(f"Log CSV: {result.log_path}")
        if result.cue_path:
            self._append_log(f"CUE ajustado: {result.cue_path}")
        messagebox.showinfo(
            "Injeção finalizada",
            f"{state}\n\n"
            f"Processados: {len(result.rows)}\n"
            f"Sucesso: {result.ok}\n"
            f"Erros: {result.errors}\n\n"
            f"BIN: {result.target_bin}\n"
            f"Log: {result.log_path}",
            parent=self,
        )

    def cancel(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Cancelamento solicitado...")

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Injeção em andamento",
                "A injeção ainda está em andamento. Solicitar cancelamento e fechar?",
                parent=self,
            ):
                return
            self.cancel_event.set()
        self._save_settings()
        self.destroy()


def cli_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Injeta um MDT ou uma pasta estruturada usando psxinject via MSYS2."
    )
    parser.add_argument("source", help="Arquivo MDT ou pasta estruturada")
    parser.add_argument("bin", help="Arquivo BIN do jogo")
    parser.add_argument("--psxinject", required=True, help="Caminho do psxinject.exe")
    parser.add_argument("--bash", default=str(DEFAULT_BASH), help="Bash do MSYS2")
    parser.add_argument("--prefix", default="MDT", help="Prefixo interno para pasta")
    parser.add_argument(
        "--internal-path",
        default="",
        help="Caminho interno obrigatório/recomendado para MDT isolado",
    )
    parser.add_argument(
        "--output-bin",
        default="",
        help="Cria uma cópia do BIN neste caminho antes da injeção",
    )
    parser.add_argument("--log", default="koudelka_inject_mdt_log.csv")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--verbose-psxinject", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite-output", action="store_true")
    args = parser.parse_args(argv)

    items = discover_items(
        args.source, args.prefix, args.internal_path
    )
    make_copy = bool(args.output_bin)
    target = args.output_bin or args.bin

    def callback(kind, payload):
        if kind == "message":
            print(payload, flush=True)
        elif kind == "progress":
            current, total, label = payload
            print(f"[{current}/{total}] {label}", flush=True)

    result = inject_items(
        items=items,
        original_bin=args.bin,
        target_bin=target,
        bash_exe=args.bash,
        psxinject=args.psxinject,
        log_path=args.log,
        make_copy=make_copy,
        overwrite_copy=args.overwrite_output,
        continue_on_error=args.continue_on_error,
        verbose=args.verbose_psxinject,
        dry_run=args.dry_run,
        event_callback=callback,
    )
    print("\n=== RESULTADO ===")
    print(f"Processados: {len(result.rows)}")
    print(f"Sucesso:     {result.ok}")
    print(f"Erros:       {result.errors}")
    print(f"BIN:         {result.target_bin}")
    print(f"Log:         {result.log_path}")
    return 1 if result.errors else 0


def gui_main() -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = InjectorGUI()
    app.mainloop()


def main() -> int:
    if len(sys.argv) == 1 or sys.argv[1:] == ["--gui"]:
        gui_main()
        return 0
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
