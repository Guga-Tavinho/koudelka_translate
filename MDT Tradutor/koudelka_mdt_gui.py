#!/usr/bin/env python3
"""Interface grafica para ler, traduzir e gerar MDTs de Koudelka."""

from __future__ import annotations

import sys
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from koudelka_mdt_core import (
    TextEntry,
    encode_text,
    entry_validation,
    export_csv,
    import_csv,
    load_file,
    load_folder,
    normalize_pt,
    write_folder,
    write_single,
)


APP_TITLE = "Koudelka MDT Tradutor GUI v6"


class MDTApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1460x850")
        self.minsize(1080, 680)

        self.entries: list[TextEntry] = []
        self.file_data: dict[Path, bytes] = {}
        self.single_data: bytes | None = None
        self.single_path: Path | None = None
        self.root_folder: Path | None = None
        self.file_count = 0
        self.current_index: int | None = None
        self.dirty = False
        self._editor_loading = False
        self._refresh_job: str | None = None
        self._load_queue: queue.Queue = queue.Queue()
        self.busy = False

        self.normalize_var = tk.BooleanVar(value=True)
        self.filter_var = tk.StringVar()
        self.filter_status_var = tk.StringVar(value="Todos")
        self.source_var = tk.StringVar(value="Nenhum MDT aberto")
        self.summary_var = tk.StringVar(value="Abra um arquivo ou uma pasta MDT.")
        self.detail_var = tk.StringVar(value="Selecione um texto na lista.")
        self.bytes_var = tk.StringVar(value="0 / 0 bytes")
        self.exceeds_var = tk.StringVar(value="Nenhum texto excedendo o limite.")
        self.status_var = tk.StringVar(value="Pronto")

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<Control-o>", lambda _event: self.open_mdt())
        self.bind_all("<Control-Shift-O>", lambda _event: self.open_folder())
        self.bind_all("<Control-e>", lambda _event: self.export_csv_dialog())
        self.bind_all("<Control-Shift-E>", lambda _event: self.export_exceeds_csv_dialog())
        self.bind_all("<Control-i>", lambda _event: self.import_csv_dialog())
        self.bind_all("<F7>", lambda _event: self.goto_exceeds(-1))
        self.bind_all("<F8>", lambda _event: self.goto_exceeds(1))

        if len(sys.argv) > 1:
            candidate = Path(sys.argv[1])
            self.after(100, lambda: self.open_path(candidate))

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=("Arial", 10))
        style.configure("Treeview", font=("Arial", 10), rowheight=25)
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))
        style.configure("Title.TLabel", font=("Arial", 12, "bold"))
        style.configure("Info.TLabel", foreground="#405166")
        style.configure("Good.TLabel", foreground="#117a37", font=("Arial", 10, "bold"))
        style.configure("Bad.TLabel", foreground="#b42318", font=("Arial", 10, "bold"))

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Abrir MDT...   Ctrl+O", command=self.open_mdt)
        file_menu.add_command(label="Abrir pasta MDT...   Ctrl+Shift+O", command=self.open_folder)
        file_menu.add_separator()
        file_menu.add_command(
            label="Importar CSV completo ou de revisao...   Ctrl+I",
            command=self.import_csv_dialog,
        )
        file_menu.add_command(label="Exportar CSV...   Ctrl+E", command=self.export_csv_dialog)
        file_menu.add_command(
            label="Exportar somente EXCEDE...   Ctrl+Shift+E",
            command=self.export_exceeds_csv_dialog,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Gerar MDT traduzido...", command=self.generate_output)
        file_menu.add_separator()
        file_menu.add_command(label="Sair", command=self.on_close)
        menu.add_cascade(label="Arquivo", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Tabela do codec", command=self.show_codec)
        help_menu.add_command(label="Sobre", command=self.show_about)
        menu.add_cascade(label="Ajuda", menu=help_menu)
        self.config(menu=menu)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Abrir MDT", command=self.open_mdt).pack(side="left")
        ttk.Button(toolbar, text="Abrir pasta", command=self.open_folder).pack(side="left", padx=(6, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=9)
        ttk.Button(toolbar, text="Importar CSV", command=self.import_csv_dialog).pack(side="left")
        ttk.Button(toolbar, text="Exportar CSV", command=self.export_csv_dialog).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Gerar MDT traduzido", command=self.generate_output).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(
            toolbar,
            text="Converter acentos para ASCII ao gravar",
            variable=self.normalize_var,
            command=self.on_normalize_change,
        ).pack(side="right")

        source_frame = ttk.Frame(self, padding=(10, 0, 10, 7))
        source_frame.pack(fill="x")
        ttk.Label(source_frame, textvariable=self.source_var, style="Title.TLabel").pack(anchor="w")
        ttk.Label(source_frame, textvariable=self.summary_var, style="Info.TLabel").pack(anchor="w", pady=(2, 0))

        filter_frame = ttk.Frame(self, padding=(10, 0, 10, 7))
        filter_frame.pack(fill="x")
        ttk.Label(filter_frame, text="Filtrar:").pack(side="left")
        filter_entry = ttk.Entry(filter_frame, textvariable=self.filter_var, width=45)
        filter_entry.pack(side="left", padx=(6, 12))
        filter_entry.bind("<KeyRelease>", lambda _event: self.refresh_tree())
        ttk.Label(filter_frame, text="Estado:").pack(side="left")
        status_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_status_var,
            values=("Todos", "Pendentes", "Traduzidos", "Erros"),
            width=13,
            state="readonly",
        )
        status_combo.pack(side="left", padx=(6, 0))
        status_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_tree())
        ttk.Button(filter_frame, text="Limpar filtro", command=self.clear_filter).pack(side="left", padx=(8, 0))
        ttk.Button(
            filter_frame,
            text="Exportar EXCEDE",
            command=self.export_exceeds_csv_dialog,
        ).pack(side="left", padx=(8, 0))

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        list_frame = ttk.Frame(pane)
        editor_frame = ttk.Frame(pane, padding=(10, 0, 0, 0))
        pane.add(list_frame, weight=3)
        pane.add(editor_frame, weight=2)

        columns = ("file", "id", "offset", "limit", "used", "state", "original", "translation")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "file": "Arquivo", "id": "ID", "offset": "Offset", "limit": "Limite",
            "used": "Usado", "state": "Estado", "original": "Original",
            "translation": "Tradução",
        }
        widths = {
            "file": 145, "id": 48, "offset": 92, "limit": 65,
            "used": 62, "state": 88, "original": 310, "translation": 310,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=45, stretch=column in ("original", "translation"))
        self.tree.tag_configure("original", foreground="#5e6978")
        self.tree.tag_configure("ok", foreground="#117a37")
        self.tree.tag_configure("error", foreground="#b42318")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        y_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        ttk.Label(editor_frame, text="Editor do texto", style="Title.TLabel").pack(anchor="w")
        ttk.Label(editor_frame, textvariable=self.detail_var, style="Info.TLabel", wraplength=520).pack(anchor="w", pady=(2, 8))

        ttk.Label(editor_frame, text="Original (somente leitura)").pack(anchor="w")
        self.original_text = self._make_text(editor_frame, height=8, readonly=True)
        self.original_text.pack(fill="both", expand=True, pady=(3, 9))

        translation_header = ttk.Frame(editor_frame)
        translation_header.pack(fill="x")
        ttk.Label(translation_header, text="Tradução PT-BR").pack(side="left")
        ttk.Label(translation_header, textvariable=self.bytes_var).pack(side="right")
        self.translation_text = self._make_text(editor_frame, height=8, readonly=False)
        self.translation_text.pack(fill="both", expand=True, pady=(3, 7))
        self.translation_text.bind("<<Modified>>", self.on_translation_modified)

        button_row = ttk.Frame(editor_frame)
        button_row.pack(fill="x", pady=(0, 8))
        ttk.Button(button_row, text="Copiar original", command=self.copy_original).pack(side="left")
        ttk.Button(button_row, text="Limpar tradução", command=self.clear_translation).pack(side="left", padx=(6, 0))
        ttk.Button(button_row, text="Anterior pendente", command=lambda: self.goto_pending(-1)).pack(side="right")
        ttk.Button(button_row, text="Próximo pendente", command=lambda: self.goto_pending(1)).pack(side="right", padx=(0, 6))

        ttk.Label(editor_frame, text="Texto que será gravado (ASCII)").pack(anchor="w")
        self.preview_text = self._make_text(editor_frame, height=5, readonly=True)
        self.preview_text.pack(fill="both", expand=True, pady=(3, 5))
        self.validation_label = ttk.Label(editor_frame, text="", style="Info.TLabel", wraplength=520)
        self.validation_label.pack(fill="x")

        exceed_row = ttk.Frame(editor_frame)
        exceed_row.pack(fill="x", pady=(7, 0))
        ttk.Label(exceed_row, textvariable=self.exceeds_var, style="Bad.TLabel").pack(anchor="w")
        exceed_buttons = ttk.Frame(exceed_row)
        exceed_buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(
            exceed_buttons,
            text="Anterior EXCEDE  F7",
            command=lambda: self.goto_exceeds(-1),
        ).pack(side="right")
        ttk.Button(
            exceed_buttons,
            text="Próximo EXCEDE  F8",
            command=lambda: self.goto_exceeds(1),
        ).pack(side="right", padx=(0, 6))

        statusbar = ttk.Frame(self, relief="sunken", padding=(8, 4))
        statusbar.pack(fill="x", side="bottom")
        ttk.Label(statusbar, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(statusbar, mode="indeterminate", length=150)
        self.progress.pack(side="right")

    @staticmethod
    def _make_text(parent: tk.Misc, height: int, readonly: bool) -> tk.Text:
        widget = tk.Text(
            parent,
            height=height,
            wrap="word",
            font=("Arial", 11),
            undo=not readonly,
            padx=7,
            pady=6,
        )
        if readonly:
            widget.configure(state="disabled", background="#f4f6f8")
        return widget

    @staticmethod
    def _set_text(widget: tk.Text, value: str, readonly: bool = False) -> None:
        if readonly:
            widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        if readonly:
            widget.configure(state="disabled")
        widget.edit_modified(False)

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno(
            "Traduções não exportadas",
            "Há traduções alteradas que ainda não foram exportadas para CSV.\n\nDeseja descartá-las e continuar?",
            parent=self,
        )

    def open_mdt(self) -> None:
        path = filedialog.askopenfilename(
            title="Abrir arquivo MDT",
            filetypes=(("Arquivos MDT", "*.MDT *.mdt"), ("Todos os arquivos", "*.*")),
        )
        if path:
            self.open_path(Path(path))

    def open_folder(self) -> None:
        path = filedialog.askdirectory(title="Abrir pasta com arquivos MDT")
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        if self.busy:
            messagebox.showinfo(
                "Leitura em andamento",
                "Aguarde a leitura atual terminar.",
                parent=self,
            )
            return
        if not self.confirm_discard():
            return
        self.busy = True
        self.status_var.set("Lendo arquivos MDT em segundo plano...")
        self.progress.start(12)
        threading.Thread(
            target=self._load_worker,
            args=(path,),
            daemon=True,
        ).start()
        self.after(100, self._poll_load)

    def _load_worker(self, path: Path) -> None:
        try:
            if path.is_dir():
                file_data, entries, file_count = load_folder(path)
                if file_count == 0:
                    raise ValueError("Nenhum arquivo .MDT foi encontrado nessa pasta.")
                result = ("folder", path.resolve(), file_data, entries, file_count)
            else:
                if path.suffix.lower() != ".mdt":
                    raise ValueError("Selecione um arquivo com extensão .MDT.")
                data, entries = load_file(path)
                result = ("file", path.resolve(), data, entries, 1)
            self._load_queue.put((True, result))
        except Exception as error:
            self._load_queue.put((False, str(error)))

    def _poll_load(self) -> None:
        try:
            success, payload = self._load_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_load)
            return

        self.busy = False
        self.progress.stop()
        if not success:
            self.status_var.set("Falha ao abrir MDT.")
            messagebox.showerror("Erro ao abrir", payload, parent=self)
            return

        mode, source, data_or_files, entries, file_count = payload
        if mode == "folder":
            self.file_data = data_or_files
            self.entries = entries
            self.file_count = file_count
            self.root_folder = source
            self.single_path = None
            self.single_data = None
            self.source_var.set(f"Pasta: {self.root_folder}")
        else:
            self.single_data = data_or_files
            self.entries = entries
            self.single_path = source
            self.root_folder = None
            self.file_data = {self.single_path: self.single_data}
            self.file_count = 1
            self.source_var.set(f"Arquivo: {self.single_path}")
        try:
            self.current_index = None
            self.dirty = False
            self.clear_editor()
            self.refresh_tree(select_first=True)
            self.update_summary()
            self.status_var.set(f"Leitura concluída: {len(self.entries)} textos encontrados.")
        except Exception as error:
            self.status_var.set("Falha ao abrir MDT.")
            messagebox.showerror("Erro ao abrir", str(error), parent=self)

    def clear_filter(self) -> None:
        self.filter_var.set("")
        self.filter_status_var.set("Todos")
        self.refresh_tree()

    def visible_indices(self) -> list[int]:
        query = self.filter_var.get().strip().casefold()
        state_filter = self.filter_status_var.get()
        result = []
        for index, entry in enumerate(self.entries):
            status, _, _ = entry_validation(entry, self.normalize_var.get())
            if state_filter == "Pendentes" and status != "ORIGINAL":
                continue
            if state_filter == "Traduzidos" and status != "OK":
                continue
            if state_filter == "Erros" and status not in ("EXCEDE", "ERRO_CODEC"):
                continue
            haystack = f"{entry.relative_path}\n{entry.original}\n{entry.translation}".casefold()
            if query and query not in haystack:
                continue
            result.append(index)
        return result

    def refresh_tree(self, select_first: bool = False) -> None:
        selected_index = self.current_index
        self.tree.delete(*self.tree.get_children())
        for index in self.visible_indices():
            entry = self.entries[index]
            status, used, _ = entry_validation(entry, self.normalize_var.get())
            tag = "original" if status == "ORIGINAL" else ("ok" if status == "OK" else "error")
            self.tree.insert(
                "", "end", iid=str(index), tags=(tag,), values=(
                    entry.relative_path,
                    entry.local_id,
                    f"0x{entry.offset:08X}",
                    entry.max_bytes,
                    "-" if status == "ORIGINAL" else used,
                    status,
                    entry.original.replace("\n", " ↵ "),
                    entry.translation.replace("\n", " ↵ "),
                ),
            )
        target = str(selected_index) if selected_index is not None else None
        if target and self.tree.exists(target):
            self.tree.selection_set(target)
            self.tree.see(target)
        elif select_first and self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)

    def on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        index = int(selection[0])
        if index == self.current_index:
            return
        self.current_index = index
        self.load_editor(index)

    def load_editor(self, index: int) -> None:
        entry = self.entries[index]
        self._editor_loading = True
        self._set_text(self.original_text, entry.original, readonly=True)
        self._set_text(self.translation_text, entry.translation)
        self.detail_var.set(
            f"{entry.relative_path}  •  ID {entry.local_id}  •  offset 0x{entry.offset:08X}  •  "
            f"payload 0x{entry.payload_offset:08X}  •  prefixo {entry.prefix or 'nenhum'}"
        )
        self._editor_loading = False
        self.update_validation()

    def clear_editor(self) -> None:
        self._editor_loading = True
        self._set_text(self.original_text, "", readonly=True)
        self._set_text(self.translation_text, "")
        self._set_text(self.preview_text, "", readonly=True)
        self._editor_loading = False
        self.detail_var.set("Selecione um texto na lista.")
        self.bytes_var.set("0 / 0 bytes")
        self.validation_label.configure(text="", style="Info.TLabel")

    def on_translation_modified(self, _event=None) -> None:
        if self._editor_loading or not self.translation_text.edit_modified():
            return
        self.translation_text.edit_modified(False)
        if self.current_index is None:
            return
        self.entries[self.current_index].translation = self.translation_text.get("1.0", "end-1c")
        self.dirty = True
        self.update_validation()
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(220, self.refresh_after_edit)

    def refresh_after_edit(self) -> None:
        self._refresh_job = None
        selected = self.current_index
        self.refresh_tree()
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
        self.update_summary()

    def update_validation(self) -> None:
        if self.current_index is None:
            return
        entry = self.entries[self.current_index]
        status, used, detail = entry_validation(entry, self.normalize_var.get())
        self.bytes_var.set(f"{used} / {entry.max_bytes} bytes  ({entry.max_chars} caracteres aprox.)")
        if entry.translation:
            preview = normalize_pt(entry.translation) if self.normalize_var.get() else entry.translation
        else:
            preview = entry.original
        self._set_text(self.preview_text, preview, readonly=True)
        if status in ("EXCEDE", "ERRO_CODEC"):
            self.validation_label.configure(text=f"ERRO: {detail}", style="Bad.TLabel")
        elif status == "OK":
            self.validation_label.configure(text=f"OK: {detail}", style="Good.TLabel")
        else:
            self.validation_label.configure(text=detail, style="Info.TLabel")

    def on_normalize_change(self) -> None:
        self.update_validation()
        self.refresh_tree()
        self.update_summary()

    def copy_original(self) -> None:
        if self.current_index is None:
            return
        self._editor_loading = True
        value = self.entries[self.current_index].original
        self._set_text(self.translation_text, value)
        self.entries[self.current_index].translation = value
        self._editor_loading = False
        self.dirty = True
        self.update_validation()
        self.refresh_tree()
        self.update_summary()

    def clear_translation(self) -> None:
        if self.current_index is None:
            return
        self._editor_loading = True
        self._set_text(self.translation_text, "")
        self.entries[self.current_index].translation = ""
        self._editor_loading = False
        self.dirty = True
        self.update_validation()
        self.refresh_tree()
        self.update_summary()

    def goto_pending(self, direction: int) -> None:
        if not self.entries:
            return
        start = self.current_index if self.current_index is not None else (-1 if direction > 0 else 0)
        for step in range(1, len(self.entries) + 1):
            index = (start + direction * step) % len(self.entries)
            status, _, _ = entry_validation(self.entries[index], self.normalize_var.get())
            if status == "ORIGINAL":
                self.select_entry(index)
                return

    def select_entry(self, index: int) -> None:
        """Exibe um registro mesmo quando ele estava oculto pelos filtros."""
        self.filter_var.set("")
        self.filter_status_var.set("Todos")
        self.refresh_tree()
        item_id = str(index)
        if not self.tree.exists(item_id):
            return
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self.tree.see(item_id)
        self.current_index = index
        self.load_editor(index)
        self.after_idle(self.translation_text.focus_set)

    def goto_exceeds(self, direction: int = 1) -> None:
        """Navega somente pelos textos cujo estado atual e EXCEDE."""
        matching = [
            index
            for index, entry in enumerate(self.entries)
            if entry_validation(entry, self.normalize_var.get())[0] == "EXCEDE"
        ]
        if not matching:
            self.status_var.set("Nenhum texto com estado EXCEDE.")
            self.bell()
            return

        if self.current_index in matching:
            position = (matching.index(self.current_index) + direction) % len(matching)
        elif self.current_index is None:
            position = 0 if direction > 0 else len(matching) - 1
        elif direction > 0:
            position = next(
                (item for item, index in enumerate(matching) if index > self.current_index),
                0,
            )
        else:
            position = next(
                (item for item in range(len(matching) - 1, -1, -1) if matching[item] < self.current_index),
                len(matching) - 1,
            )

        target = matching[position]
        self.select_entry(target)
        entry = self.entries[target]
        self.status_var.set(
            f"EXCEDE {position + 1}/{len(matching)}: "
            f"{entry.relative_path} - ID {entry.local_id}"
        )

    def update_summary(self) -> None:
        translated = errors = exceeds = 0
        for entry in self.entries:
            status, _, _ = entry_validation(entry, self.normalize_var.get())
            if status == "OK":
                translated += 1
            elif status not in ("ORIGINAL", "OK"):
                errors += 1
                if status == "EXCEDE":
                    exceeds += 1
        pending = len(self.entries) - translated - errors
        if exceeds:
            self.exceeds_var.set(f"{exceeds} texto(s) com estado EXCEDE")
        else:
            self.exceeds_var.set("Nenhum texto excedendo o limite.")
        self.summary_var.set(
            f"{self.file_count} arquivo(s) • {len(self.entries)} texto(s) • "
            f"{translated} traduzido(s) • {pending} pendente(s) • {errors} erro(s)"
        )

    def import_csv_dialog(self) -> None:
        if not self.entries:
            messagebox.showinfo("Importar CSV", "Abra primeiro um MDT ou uma pasta MDT.", parent=self)
            return
        path = filedialog.askopenfilename(
            title="Importar CSV completo ou de revisão EXCEDE",
            filetypes=(("Planilha CSV", "*.csv"), ("Todos os arquivos", "*.*")),
        )
        if not path:
            return
        try:
            imported, unmatched = import_csv(self.entries, path)
            self.dirty = True
            self.current_index = None
            self.clear_editor()
            self.refresh_tree(select_first=True)
            self.update_summary()
            messagebox.showinfo(
                "Importação concluída",
                f"Traduções associadas: {imported}\n"
                f"Linhas não associadas: {unmatched}\n\n"
                "O estado e os limites foram recalculados automaticamente.",
                parent=self,
            )
        except Exception as error:
            messagebox.showerror("Erro ao importar CSV", str(error), parent=self)

    def export_csv_dialog(self) -> None:
        if not self.entries:
            messagebox.showinfo("Exportar CSV", "Abra primeiro um MDT ou uma pasta MDT.", parent=self)
            return
        if self.single_path:
            default = f"{self.single_path.stem}_textos.csv"
            initial = self.single_path.parent
        else:
            default = "koudelka_mdt_TODOS_TEXTOS.csv"
            initial = self.root_folder or Path.cwd()
        path = filedialog.asksaveasfilename(
            title="Exportar textos e traduções",
            initialdir=initial,
            initialfile=default,
            defaultextension=".csv",
            filetypes=(("Planilha CSV", "*.csv"),),
        )
        if not path:
            return
        try:
            export_csv(self.entries, path, self.normalize_var.get())
            self.dirty = False
            self.status_var.set(f"CSV exportado: {path}")
        except Exception as error:
            messagebox.showerror("Erro ao exportar CSV", str(error), parent=self)

    def export_exceeds_csv_dialog(self) -> None:
        if not self.entries:
            messagebox.showinfo(
                "Exportar EXCEDE",
                "Abra primeiro um MDT ou uma pasta MDT.",
                parent=self,
            )
            return

        exceeds = [
            entry
            for entry in self.entries
            if entry_validation(entry, self.normalize_var.get())[0] == "EXCEDE"
        ]
        if not exceeds:
            messagebox.showinfo(
                "Exportar EXCEDE",
                "Não há nenhum texto com estado EXCEDE.",
                parent=self,
            )
            return

        if self.single_path:
            default = f"{self.single_path.stem}_EXCEDE.csv"
            initial = self.single_path.parent
        else:
            default = "koudelka_mdt_TEXTOS_EXCEDE.csv"
            initial = self.root_folder or Path.cwd()

        path = filedialog.asksaveasfilename(
            title="Exportar somente textos que excedem o limite",
            initialdir=initial,
            initialfile=default,
            defaultextension=".csv",
            filetypes=(("Planilha CSV", "*.csv"),),
        )
        if not path:
            return

        try:
            export_csv(exceeds, path, self.normalize_var.get())
            self.status_var.set(f"CSV EXCEDE exportado: {path}")
            messagebox.showinfo(
                "CSV EXCEDE exportado",
                f"{len(exceeds)} texto(s) foram exportados.\n\n"
                "Depois de corrigir a coluna translation_pt, use Importar CSV. "
                "O arquivo parcial será associado novamente aos MDTs abertos.",
                parent=self,
            )
        except Exception as error:
            messagebox.showerror("Erro ao exportar EXCEDE", str(error), parent=self)

    def validate_all(self) -> list[str]:
        errors = []
        for entry in self.entries:
            status, _, detail = entry_validation(entry, self.normalize_var.get())
            if status not in ("ORIGINAL", "OK"):
                errors.append(f"{entry.relative_path} / ID {entry.local_id}: {detail}")
        return errors

    def generate_output(self) -> None:
        if not self.entries:
            messagebox.showinfo("Gerar MDT", "Abra primeiro um MDT ou uma pasta MDT.", parent=self)
            return
        errors = self.validate_all()
        if errors:
            excerpt = "\n".join(errors[:12])
            if len(errors) > 12:
                excerpt += f"\n... e mais {len(errors) - 12} erro(s)."
            messagebox.showerror(
                "Traduções inválidas",
                "Corrija os textos marcados em vermelho antes de gerar:\n\n" + excerpt,
                parent=self,
            )
            return
        changed = sum(bool(entry.translation) for entry in self.entries)
        if changed == 0:
            messagebox.showinfo("Gerar MDT", "Ainda não há nenhuma tradução preenchida.", parent=self)
            return

        try:
            if self.single_path and self.single_data is not None:
                default = f"{self.single_path.stem}_PTBR.MDT"
                destination = filedialog.asksaveasfilename(
                    title="Salvar MDT traduzido",
                    initialdir=self.single_path.parent,
                    initialfile=default,
                    defaultextension=".MDT",
                    filetypes=(("Arquivo MDT", "*.MDT"),),
                )
                if not destination:
                    return
                output = Path(destination)
                if output.resolve() == self.single_path:
                    raise ValueError("Escolha outro nome: o MDT original não será sobrescrito.")
                count = write_single(
                    self.single_data, self.entries, output, self.normalize_var.get()
                )
                csv_path = output.with_name(output.stem + "_traducoes.csv")
                export_csv(self.entries, csv_path, self.normalize_var.get())
                result = f"MDT: {output}\nCSV: {csv_path}"
            else:
                parent = filedialog.askdirectory(
                    title="Escolha onde criar a pasta MDT_TRADUZIDO"
                )
                if not parent:
                    return
                suggested = (self.root_folder.name if self.root_folder else "MDT") + "_TRADUZIDO"
                name = simpledialog.askstring(
                    "Nome da pasta de saída",
                    "A ferramenta criará uma pasta nova. Informe o nome:",
                    initialvalue=suggested,
                    parent=self,
                )
                if not name:
                    return
                output = Path(parent) / name
                count = write_folder(
                    self.root_folder,
                    output,
                    self.file_data,
                    self.entries,
                    self.normalize_var.get(),
                )
                csv_path = output / "koudelka_mdt_traducoes.csv"
                export_csv(self.entries, csv_path, self.normalize_var.get())
                result = f"Pasta: {output}\nCSV: {csv_path}"
            self.dirty = False
            self.status_var.set(f"Saída gerada com {count} texto(s) reinserido(s).")
            messagebox.showinfo(
                "Concluído",
                f"{count} texto(s) reinserido(s).\nO tamanho de cada MDT foi preservado.\n\n{result}",
                parent=self,
            )
        except Exception as error:
            messagebox.showerror("Erro ao gerar MDT", str(error), parent=self)

    def show_codec(self) -> None:
        messagebox.showinfo(
            "Codec MDT",
            "Cada caractere ASCII ocupa 2 bytes na grade do jogo.\n\n"
            "Exemplos:\nA = 41 44\na = 41 46\n1 = 41 43\n! = 41 42\n"
            "quebra de linha = 68 60\n\n"
            "Caracteres acentuados são convertidos para ASCII quando a opção da barra está ativa.\n"
            "Um código bruto também pode ser preservado como {ABCD}.",
            parent=self,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "Sobre",
            f"{APP_TITLE}\n\n"
            "Leitura, edição, CSV e reinserção conservadora de textos MDT.\n"
            "A ferramenta não move ponteiros, não aumenta arquivos e nunca sobrescreve o MDT original.",
            parent=self,
        )

    def on_close(self) -> None:
        if self.confirm_discard():
            self.destroy()


def main() -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = MDTApp()
    app.mainloop()


if __name__ == "__main__":
    main()
