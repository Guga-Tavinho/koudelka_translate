#!/usr/bin/env python3
"""Interface gráfica para injetar arquivos arbitrários no BIN de Koudelka."""

from __future__ import annotations

import csv
import json
import queue
import re
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from koudelka_inject_mdt_mass_v3_msys2 import (
    APP_TITLE as BACKEND_TITLE,
    DEFAULT_BASH,
    InjectionItem,
    InjectionResult,
    discover_default_psxinject,
    inject_items,
    normalize_internal_path,
    validate_tools,
)


APP_TITLE = "Koudelka - Injetor de Arquivos v1"
SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SCRIPT_DIR / "koudelka_inject_arquivo_settings.json"
ROOT_MARKERS = {
    "BATTLE", "DATA", "EVENT", "FONT", "MENU", "MDT", "MOVIE",
    "SOUND", "SYSTEM", "VOICE",
}
TRANSLATION_SUFFIX = re.compile(
    r"(?i)(?:_TRADUZID[OA]|_PTBR|_PT_BR|_REVISAD[OA]|_FINAL)"
    r"(?:_[A-Z0-9]+)*$"
)


def clean_injected_filename(filename: str) -> str:
    path = Path(filename)
    clean_stem = TRANSLATION_SUFFIX.sub("", path.stem)
    return clean_stem + path.suffix


def suggest_internal_path(file_path: Path | str) -> str:
    path = Path(file_path).resolve()
    parts = list(path.parts)
    start = None
    for index, part in enumerate(parts[:-1]):
        if part.upper() in ROOT_MARKERS:
            start = index
            break
    clean_name = clean_injected_filename(path.name)
    if start is None:
        return clean_name
    return "/".join(parts[start:-1] + [clean_name])


class GenericInjectorGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1240x870")
        self.minsize(1000, 720)

        self.items: list[InjectionItem] = []
        self.selected_index: int | None = None
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None

        self.file_var = tk.StringVar()
        self.internal_var = tk.StringVar()
        self.bin_var = tk.StringVar()
        self.output_bin_var = tk.StringVar()
        self.psxinject_var = tk.StringVar(value=discover_default_psxinject())
        self.bash_var = tk.StringVar(value=str(DEFAULT_BASH))
        self.log_var = tk.StringVar()
        self.copy_var = tk.BooleanVar(value=True)
        self.continue_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=True)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.summary_var = tk.StringVar(value="Nenhum arquivo na fila.")
        self.status_var = tk.StringVar(value="Pronto")

        self._load_settings()
        self._configure_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=("Arial", 10))
        style.configure("Title.TLabel", font=("Arial", 13, "bold"))
        style.configure("Treeview", font=("Arial", 9), rowheight=25)
        style.configure("Treeview.Heading", font=("Arial", 9, "bold"))

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Injetor genérico de arquivos", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            main,
            text=(
                "Substitui arquivos dentro do BIN usando psxinject/MSYS2. "
                "Confira cuidadosamente cada caminho interno."
            ),
        ).pack(anchor="w", pady=(2, 10))

        add_frame = ttk.LabelFrame(main, text="1. Arquivo de substituição", padding=10)
        add_frame.pack(fill="x")
        self._path_row(add_frame, "Arquivo novo:", self.file_var, self.browse_file)
        internal_row = ttk.Frame(add_frame)
        internal_row.pack(fill="x", pady=(7, 0))
        ttk.Label(internal_row, text="Caminho no CD:", width=17).pack(side="left")
        ttk.Entry(internal_row, textvariable=self.internal_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Label(
            internal_row, text="Ex.: MENU/ITEMS/001.TX4"
        ).pack(side="left", padx=(8, 0))
        buttons = ttk.Frame(add_frame)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(
            buttons, text="Adicionar à fila", command=self.add_or_update
        ).pack(side="right")
        ttk.Button(
            buttons, text="Limpar campos", command=self.clear_editor
        ).pack(side="right", padx=(0, 7))

        queue_frame = ttk.LabelFrame(main, text="2. Fila de injeção", padding=8)
        queue_frame.pack(fill="both", expand=True, pady=(10, 0))
        top_queue = ttk.Frame(queue_frame)
        top_queue.pack(fill="x", pady=(0, 6))
        ttk.Label(top_queue, textvariable=self.summary_var).pack(side="left")
        ttk.Button(top_queue, text="Importar lista CSV", command=self.import_queue).pack(
            side="right"
        )
        ttk.Button(top_queue, text="Exportar lista CSV", command=self.export_queue).pack(
            side="right", padx=(0, 6)
        )
        ttk.Button(top_queue, text="Remover selecionado", command=self.remove_selected).pack(
            side="right", padx=(0, 6)
        )
        ttk.Button(top_queue, text="Limpar fila", command=self.clear_queue).pack(
            side="right", padx=(0, 6)
        )

        tree_holder = ttk.Frame(queue_frame)
        tree_holder.pack(fill="both", expand=True)
        columns = ("n", "internal", "source", "size")
        self.tree = ttk.Treeview(
            tree_holder, columns=columns, show="headings", selectmode="browse", height=8
        )
        self.tree.heading("n", text="#")
        self.tree.heading("internal", text="Caminho interno no CD")
        self.tree.heading("source", text="Arquivo de substituição")
        self.tree.heading("size", text="Bytes")
        self.tree.column("n", width=45, stretch=False, anchor="center")
        self.tree.column("internal", width=350)
        self.tree.column("source", width=580)
        self.tree.column("size", width=100, stretch=False, anchor="e")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        scroll = ttk.Scrollbar(tree_holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        bin_frame = ttk.LabelFrame(main, text="3. Imagem do jogo", padding=10)
        bin_frame.pack(fill="x", pady=(10, 0))
        self._path_row(bin_frame, "BIN original:", self.bin_var, self.browse_bin)
        self._path_row(bin_frame, "BIN de saída:", self.output_bin_var, self.browse_output)
        ttk.Checkbutton(
            bin_frame,
            text="Trabalhar em uma cópia do BIN original (recomendado)",
            variable=self.copy_var,
            command=self.copy_changed,
        ).pack(anchor="w", pady=(6, 0))

        tools = ttk.LabelFrame(main, text="4. Ferramentas e opções", padding=10)
        tools.pack(fill="x", pady=(10, 0))
        self._path_row(tools, "psxinject.exe:", self.psxinject_var, self.browse_psxinject)
        self._path_row(tools, "Bash MSYS2:", self.bash_var, self.browse_bash)
        log_row = ttk.Frame(tools)
        log_row.pack(fill="x", pady=(7, 0))
        ttk.Label(log_row, text="Log CSV:", width=17).pack(side="left")
        ttk.Entry(log_row, textvariable=self.log_var).pack(side="left", fill="x", expand=True)
        ttk.Button(log_row, text="Escolher...", command=self.browse_log).pack(
            side="left", padx=(6, 0)
        )
        options = ttk.Frame(tools)
        options.pack(fill="x", pady=(7, 0))
        ttk.Checkbutton(
            options, text="Usar -v (detalhado)", variable=self.verbose_var
        ).pack(side="left")
        ttk.Checkbutton(
            options, text="Continuar após erro", variable=self.continue_var
        ).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(
            options, text="Somente simular", variable=self.dry_run_var
        ).pack(side="left", padx=(16, 0))

        progress_frame = ttk.LabelFrame(main, text="Progresso", padding=8)
        progress_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(
            progress_frame,
            height=7,
            wrap="word",
            font=("Consolas", 9),
            state="disabled",
            background="#111827",
            foreground="#e5e7eb",
        )
        log_scroll = ttk.Scrollbar(
            progress_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(10, 0))
        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(actions, textvariable=self.status_var, width=28).pack(
            side="left", padx=10
        )
        self.cancel_button = ttk.Button(
            actions, text="Cancelar", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="right")
        self.start_button = ttk.Button(
            actions, text="INJETAR ARQUIVOS", command=self.start
        )
        self.start_button.pack(side="right", padx=(0, 7))

    @staticmethod
    def _path_row(parent, label: str, variable: tk.StringVar, command) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text=label, width=17).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Escolher...", command=command).pack(
            side="left", padx=(6, 0)
        )

    def browse_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar arquivo de substituição",
            filetypes=(("Todos os arquivos", "*.*"),),
        )
        if selected:
            self.file_var.set(selected)
            self.internal_var.set(suggest_internal_path(selected))

    def browse_bin(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar BIN original",
            filetypes=(("Imagem BIN", "*.bin *.BIN"), ("Todos", "*.*")),
        )
        if selected:
            self.bin_var.set(selected)
            source = Path(selected)
            self.output_bin_var.set(
                str(source.with_name(f"{source.stem}_MOD{source.suffix}"))
            )
            self.log_var.set(str(source.with_name("koudelka_inject_arquivos_log.csv")))

    def browse_output(self) -> None:
        source = Path(self.bin_var.get()) if self.bin_var.get() else Path.cwd() / "Koudelka.bin"
        selected = filedialog.asksaveasfilename(
            title="Salvar BIN modificado",
            initialdir=source.parent,
            initialfile=f"{source.stem}_MOD{source.suffix or '.bin'}",
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
            title="Selecionar bash.exe",
            filetypes=(("Executável", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.bash_var.set(selected)

    def browse_log(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Salvar log",
            initialfile="koudelka_inject_arquivos_log.csv",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
        )
        if selected:
            self.log_var.set(selected)

    def copy_changed(self) -> None:
        if self.copy_var.get() and self.bin_var.get() and not self.output_bin_var.get():
            source = Path(self.bin_var.get())
            self.output_bin_var.set(
                str(source.with_name(f"{source.stem}_MOD{source.suffix}"))
            )

    def add_or_update(self) -> None:
        try:
            source = Path(self.file_var.get()).resolve()
            if not source.is_file():
                raise ValueError(f"Arquivo não encontrado: {source}")
            internal = normalize_internal_path(self.internal_var.get())
            duplicate = next(
                (
                    index for index, item in enumerate(self.items)
                    if item.internal_path.casefold() == internal.casefold()
                    and index != self.selected_index
                ),
                None,
            )
            if duplicate is not None:
                raise ValueError(
                    f"Já existe um arquivo destinado a:\n{internal}"
                )
        except Exception as error:
            messagebox.showerror("Entrada inválida", str(error), parent=self)
            return

        item = InjectionItem(source, source.name, internal)
        if self.selected_index is None:
            self.items.append(item)
        else:
            self.items[self.selected_index] = item
        self.refresh_tree()
        self.clear_editor()

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    index + 1,
                    item.internal_path,
                    str(item.source_file),
                    item.source_file.stat().st_size if item.source_file.exists() else "AUSENTE",
                ),
            )
        total = sum(
            item.source_file.stat().st_size
            for item in self.items if item.source_file.is_file()
        )
        self.summary_var.set(
            f"{len(self.items)} arquivo(s) na fila • {total:,} bytes"
            if self.items else "Nenhum arquivo na fila."
        )

    def on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        self.selected_index = int(selected[0])
        item = self.items[self.selected_index]
        self.file_var.set(str(item.source_file))
        self.internal_var.set(item.internal_path)

    def clear_editor(self) -> None:
        self.selected_index = None
        self.file_var.set("")
        self.internal_var.set("")
        self.tree.selection_remove(self.tree.selection())

    def remove_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        del self.items[int(selected[0])]
        self.clear_editor()
        self.refresh_tree()

    def clear_queue(self) -> None:
        if self.items and not messagebox.askyesno(
            "Limpar fila", "Remover todos os arquivos da fila?", parent=self
        ):
            return
        self.items.clear()
        self.clear_editor()
        self.refresh_tree()

    def export_queue(self) -> None:
        if not self.items:
            messagebox.showinfo("Exportar lista", "A fila está vazia.", parent=self)
            return
        selected = filedialog.asksaveasfilename(
            title="Exportar lista",
            initialfile="koudelka_lista_injecao.csv",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
        )
        if not selected:
            return
        with Path(selected).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=("source_file", "internal_path")
            )
            writer.writeheader()
            for item in self.items:
                writer.writerow({
                    "source_file": str(item.source_file),
                    "internal_path": item.internal_path,
                })

    def import_queue(self) -> None:
        selected = filedialog.askopenfilename(
            title="Importar lista",
            filetypes=(("CSV", "*.csv"), ("Todos", "*.*")),
        )
        if not selected:
            return
        try:
            imported = []
            with Path(selected).open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    source = Path(row.get("source_file", "")).resolve()
                    internal = normalize_internal_path(row.get("internal_path", ""))
                    if not source.is_file():
                        raise ValueError(f"Arquivo não encontrado: {source}")
                    imported.append(InjectionItem(source, source.name, internal))
            paths = [item.internal_path.casefold() for item in imported]
            if len(paths) != len(set(paths)):
                raise ValueError("O CSV contém caminhos internos duplicados.")
            self.items = imported
            self.clear_editor()
            self.refresh_tree()
        except Exception as error:
            messagebox.showerror("Erro ao importar", str(error), parent=self)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.items:
            messagebox.showerror("Fila vazia", "Adicione ao menos um arquivo.", parent=self)
            return
        missing = [str(item.source_file) for item in self.items if not item.source_file.is_file()]
        if missing:
            messagebox.showerror(
                "Arquivos ausentes", "\n".join(missing[:10]), parent=self
            )
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
                Path(self.output_bin_var.get()).resolve() if make_copy else original
            )
            if make_copy and not self.output_bin_var.get():
                raise ValueError("Escolha o BIN de saída.")
            if make_copy and target == original:
                raise ValueError("O BIN de saída precisa ter outro nome.")
            log = (
                Path(self.log_var.get()).resolve()
                if self.log_var.get()
                else target.with_name("koudelka_inject_arquivos_log.csv")
            )
        except Exception as error:
            messagebox.showerror("Configuração inválida", str(error), parent=self)
            return

        overwrite = False
        if make_copy and target.exists() and not self.dry_run_var.get():
            overwrite = messagebox.askyesno(
                "Substituir cópia?",
                f"O arquivo já existe:\n{target}\n\nSubstituir pela nova cópia?",
                parent=self,
            )
            if not overwrite:
                return

        mapping = "\n".join(
            f"• {item.source_file.name} → {item.internal_path}"
            for item in self.items[:12]
        )
        if len(self.items) > 12:
            mapping += f"\n• ... e mais {len(self.items) - 12}"
        if not self.dry_run_var.get():
            warning = (
                f"Arquivos: {len(self.items)}\nBIN usado: {target}\n\n{mapping}\n\n"
            )
            if not make_copy:
                warning += "ATENÇÃO: o BIN original será modificado diretamente.\n\n"
            warning += "Confirma os caminhos e deseja continuar?"
            if not messagebox.askyesno("Confirmar injeção", warning, parent=self):
                return

        self._save_settings()
        self.cancel_event.clear()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(maximum=len(self.items), value=0)
        self.status_var.set("Preparando...")
        self._append_log("=" * 72)
        self._append_log(f"Início — {len(self.items)} arquivo(s)")

        options = {
            "items": list(self.items),
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
                    messagebox.showerror("Falha", payload, parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _finish(self, result: InjectionResult) -> None:
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        state = (
            "Cancelado" if result.cancelled
            else f"Concluído com {result.errors} erro(s)" if result.errors
            else "Concluído"
        )
        self.status_var.set(state)
        self._append_log(
            f"Resultado: {result.ok} OK, {result.errors} erro(s), "
            f"{len(result.rows)} processado(s)."
        )
        self._append_log(f"BIN: {result.target_bin}")
        self._append_log(f"Log: {result.log_path}")
        messagebox.showinfo(
            "Processo finalizado",
            f"{state}\n\nProcessados: {len(result.rows)}\n"
            f"Sucesso: {result.ok}\nErros: {result.errors}\n\n"
            f"BIN: {result.target_bin}\nLog: {result.log_path}",
            parent=self,
        )

    def cancel(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Cancelamento solicitado...")

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.is_file():
            return
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        self.psxinject_var.set(data.get("psxinject", self.psxinject_var.get()))
        self.bash_var.set(data.get("bash", self.bash_var.get()))
        self.bin_var.set(data.get("last_bin", ""))
        self.copy_var.set(bool(data.get("make_copy", True)))

    def _save_settings(self) -> None:
        data = {
            "psxinject": self.psxinject_var.get(),
            "bash": self.bash_var.get(),
            "last_bin": self.bin_var.get(),
            "make_copy": self.copy_var.get(),
        }
        try:
            SETTINGS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Processo em andamento",
                "Solicitar cancelamento e fechar?",
                parent=self,
            ):
                return
            self.cancel_event.set()
        self._save_settings()
        self.destroy()


def main() -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    GenericInjectorGUI().mainloop()


if __name__ == "__main__":
    main()
