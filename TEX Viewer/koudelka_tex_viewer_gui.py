from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError as error:
    raise SystemExit(
        "A biblioteca Pillow nao esta instalada. Execute instalar_dependencias.bat."
    ) from error


APP_TITLE = "Koudelka TEX - Visualizador e Exportador"
SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SCRIPT_DIR / "koudelka_tex_viewer_settings.json"
HEADER_SIZE = 24
PALETTE_COLORS = 256
PALETTE_SIZE = PALETTE_COLORS * 2
PIXEL_OFFSET = HEADER_SIZE + PALETTE_SIZE


@dataclass(frozen=True)
class TexData:
    path: Path
    declared_size: int
    format_id: int
    width: int
    height: int
    flags: int
    palette_words: tuple[int, ...]
    image: Image.Image


def psx_color(word: int, alpha: int = 255) -> tuple[int, int, int, int]:
    red_5 = word & 0x1F
    green_5 = (word >> 5) & 0x1F
    blue_5 = (word >> 10) & 0x1F
    return (
        (red_5 << 3) | (red_5 >> 2),
        (green_5 << 3) | (green_5 >> 2),
        (blue_5 << 3) | (blue_5 >> 2),
        alpha,
    )


def decode_tex(path: Path, alpha_mode: str = "auto") -> TexData:
    data = path.read_bytes()
    if len(data) < PIXEL_OFFSET:
        raise ValueError("Arquivo pequeno demais para ser um TEX do Koudelka.")
    if data[:4] != b"\xFF\xFF\xFF\xFF":
        raise ValueError("Assinatura TEX do Koudelka nao encontrada.")

    declared_size = struct.unpack_from("<I", data, 8)[0]
    format_id, width, height, flags = struct.unpack_from("<HHHH", data, 12)
    if format_id != 1:
        raise ValueError(f"Formato TEX nao suportado: {format_id}.")
    if not width or not height:
        raise ValueError(f"Dimensoes invalidas: {width}x{height}.")
    expected_size = PIXEL_OFFSET + width * height
    if len(data) < expected_size:
        raise ValueError(
            f"TEX truncado: {len(data)} bytes; pelo menos {expected_size} eram esperados."
        )

    palette_words = struct.unpack_from(f"<{PALETTE_COLORS}H", data, HEADER_SIZE)
    transparent_zero = alpha_mode == "transparent" or (
        alpha_mode == "auto" and not path.stem.upper().startswith("BACK")
    )
    palette: list[tuple[int, int, int, int]] = []
    for word in palette_words:
        alpha = 0 if transparent_zero and word == 0 else 255
        palette.append(psx_color(word, alpha))

    indices = data[PIXEL_OFFSET : PIXEL_OFFSET + width * height]
    image = Image.new("RGBA", (width, height))
    image.putdata([palette[index] for index in indices])
    return TexData(
        path=path,
        declared_size=declared_size,
        format_id=format_id,
        width=width,
        height=height,
        flags=flags,
        palette_words=tuple(palette_words),
        image=image,
    )


def make_checkerboard(size: tuple[int, int], cell: int = 8) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (48, 48, 48, 255))
    draw = ImageDraw.Draw(image)
    colors = ((58, 58, 58, 255), (88, 88, 88, 255))
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            color = colors[((x // cell) + (y // cell)) & 1]
            draw.rectangle((x, y, min(x + cell - 1, width), min(y + cell - 1, height)), fill=color)
    return image


class TexViewerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x700")
        self.minsize(760, 520)

        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Selecione um arquivo TEX ou uma pasta.")
        self.info_var = tk.StringVar(value="Nenhuma imagem carregada.")
        self.zoom_var = tk.StringVar(value="Ajustar")
        self.alpha_var = tk.StringVar(value="Automatica")
        self.recursive_var = tk.BooleanVar(value=False)
        self.live_var = tk.BooleanVar(value=True)

        self.files: list[Path] = []
        self.current_tex: TexData | None = None
        self.current_image: Image.Image | None = None
        self.current_name = ""
        self.photo: ImageTk.PhotoImage | None = None
        self.watched_paths: tuple[Path, ...] = ()
        self.watched_state: tuple[tuple[int, int], ...] = ()
        self.composite_mode = False

        self._load_settings()
        self._configure_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(700, self._watch_files)

        initial = Path(self.folder_var.get()) if self.folder_var.get() else None
        if initial and initial.is_dir():
            self.refresh_files()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=("Arial", 10))
        style.configure("Title.TLabel", font=("Arial", 13, "bold"))

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=8)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Visualizador de texturas TEX", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            main,
            text="Prévia em tempo real dos TEX indexados de 8 bits do Koudelka.",
        ).pack(anchor="w", pady=(1, 5))

        folder_row = ttk.Frame(main)
        folder_row.pack(fill="x")
        ttk.Label(folder_row, text="Pasta:").pack(side="left")
        ttk.Entry(folder_row, textvariable=self.folder_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(folder_row, text="Abrir TEX...", command=self.open_file).pack(side="right")
        ttk.Button(folder_row, text="Abrir pasta...", command=self.open_folder).pack(
            side="right", padx=(0, 5)
        )
        ttk.Button(folder_row, text="Atualizar", command=self.refresh_files).pack(
            side="right", padx=(0, 5)
        )

        options = ttk.Frame(main)
        options.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(
            options, text="Subpastas", variable=self.recursive_var, command=self.refresh_files
        ).pack(side="left")
        ttk.Checkbutton(
            options, text="Atualização automática", variable=self.live_var
        ).pack(side="left", padx=(12, 0))
        ttk.Label(options, text="Transparência:").pack(side="left", padx=(18, 4))
        alpha_box = ttk.Combobox(
            options,
            textvariable=self.alpha_var,
            values=("Automatica", "Cor 0 transparente", "Tudo opaco"),
            state="readonly",
            width=20,
        )
        alpha_box.pack(side="left")
        alpha_box.bind("<<ComboboxSelected>>", lambda _event: self.reload_current())
        ttk.Label(options, text="Zoom:").pack(side="left", padx=(18, 4))
        zoom_box = ttk.Combobox(
            options,
            textvariable=self.zoom_var,
            values=("Ajustar", "1x", "2x", "3x", "4x", "6x", "8x"),
            state="readonly",
            width=8,
        )
        zoom_box.pack(side="left")
        zoom_box.bind("<<ComboboxSelected>>", lambda _event: self._render_preview())

        actions = ttk.Frame(main)
        actions.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Exportar todos", command=self.export_all).pack(side="right")
        ttk.Button(actions, text="Exportar PNG", command=self.export_current).pack(
            side="right", padx=(0, 5)
        )
        ttk.Button(actions, text="Ver BACK1 + BACK2", command=self.show_title).pack(
            side="right", padx=(0, 5)
        )

        body = ttk.Panedwindow(main, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(6, 0))

        left = ttk.Frame(body, padding=4)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=4)

        ttk.Label(left, text="Arquivos TEX").pack(anchor="w", pady=(0, 3))
        list_holder = ttk.Frame(left)
        list_holder.pack(fill="both", expand=True)
        self.file_list = tk.Listbox(list_holder, exportselection=False, font=("Consolas", 9))
        list_scroll = ttk.Scrollbar(list_holder, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=list_scroll.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        self.file_list.bind("<<ListboxSelect>>", self._file_selected)

        tabs = ttk.Notebook(right)
        tabs.pack(fill="both", expand=True)
        preview_tab = ttk.Frame(tabs)
        palette_tab = ttk.Frame(tabs, padding=8)
        tabs.add(preview_tab, text="Prévia")
        tabs.add(palette_tab, text="Paleta / informações")

        self.canvas = tk.Canvas(preview_tab, background="#202020", highlightthickness=0)
        canvas_v = ttk.Scrollbar(preview_tab, orient="vertical", command=self.canvas.yview)
        canvas_h = ttk.Scrollbar(preview_tab, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=canvas_v.set, xscrollcommand=canvas_h.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        canvas_v.grid(row=0, column=1, sticky="ns")
        canvas_h.grid(row=1, column=0, sticky="ew")
        preview_tab.rowconfigure(0, weight=1)
        preview_tab.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda _event: self.after_idle(self._render_preview))
        self.canvas.bind("<Control-MouseWheel>", self._wheel_zoom)

        ttk.Label(
            palette_tab,
            textvariable=self.info_var,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.palette_canvas = tk.Canvas(
            palette_tab, width=512, height=320, background="#202020", highlightthickness=0
        )
        self.palette_canvas.pack(anchor="nw", fill="both", expand=True)

    def _alpha_mode(self) -> str:
        return {
            "Automatica": "auto",
            "Cor 0 transparente": "transparent",
            "Tudo opaco": "opaque",
        }.get(self.alpha_var.get(), "auto")

    def open_folder(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta com arquivos TEX")
        if selected:
            self.folder_var.set(selected)
            self.refresh_files()

    def open_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione um TEX",
            filetypes=(("Texturas Koudelka", "*.TEX *.tex"), ("Todos", "*.*")),
        )
        if not selected:
            return
        path = Path(selected)
        self.folder_var.set(str(path.parent))
        self.refresh_files(select_path=path)

    def refresh_files(self, select_path: Path | None = None) -> None:
        folder_text = self.folder_var.get().strip()
        if not folder_text:
            return
        folder = Path(folder_text)
        if not folder.is_dir():
            self.status_var.set("A pasta selecionada nao existe.")
            return
        iterator = folder.rglob("*") if self.recursive_var.get() else folder.iterdir()
        self.files = sorted(
            (path for path in iterator if path.is_file() and path.suffix.lower() == ".tex"),
            key=lambda path: str(path).lower(),
        )
        self.file_list.delete(0, "end")
        for path in self.files:
            try:
                relative = path.relative_to(folder)
            except ValueError:
                relative = path.name
            self.file_list.insert("end", str(relative))
        self.status_var.set(f"{len(self.files)} arquivo(s) TEX encontrado(s).")
        if not self.files:
            return
        index = 0
        if select_path:
            resolved = select_path.resolve()
            for candidate_index, path in enumerate(self.files):
                if path.resolve() == resolved:
                    index = candidate_index
                    break
        self.file_list.selection_clear(0, "end")
        self.file_list.selection_set(index)
        self.file_list.see(index)
        self.load_file(self.files[index])

    def _file_selected(self, _event=None) -> None:
        selection = self.file_list.curselection()
        if selection:
            self.load_file(self.files[selection[0]])

    def load_file(self, path: Path) -> None:
        try:
            tex = decode_tex(path, self._alpha_mode())
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_TITLE, str(error))
            return
        self.current_tex = tex
        self.current_image = tex.image
        self.current_name = path.name
        self.composite_mode = False
        self._set_watched((path,))
        self.info_var.set(
            f"Arquivo: {path}\n"
            f"Dimensoes: {tex.width} x {tex.height}\n"
            f"Formato: {tex.format_id} (8 bits indexado)\n"
            f"Paleta: 256 cores PS1 BGR555\n"
            f"Flags: 0x{tex.flags:04X}\n"
            f"Tamanho declarado: {tex.declared_size} bytes\n"
            f"Tamanho real: {path.stat().st_size} bytes"
        )
        self.status_var.set(f"Visualizando {path.name} — {tex.width}x{tex.height}")
        self._draw_palette(tex.palette_words)
        self._render_preview()

    def show_title(self) -> None:
        folder = Path(self.folder_var.get().strip())
        left = folder / "BACK1.TEX"
        right = folder / "BACK2.TEX"
        if not left.is_file() or not right.is_file():
            messagebox.showwarning(
                APP_TITLE, "BACK1.TEX e BACK2.TEX nao foram encontrados na pasta atual."
            )
            return
        try:
            tex_left = decode_tex(left, "opaque")
            tex_right = decode_tex(right, "opaque")
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_TITLE, str(error))
            return
        image = Image.new(
            "RGBA",
            (tex_left.width + tex_right.width, max(tex_left.height, tex_right.height)),
        )
        image.alpha_composite(tex_left.image, (0, 0))
        image.alpha_composite(tex_right.image, (tex_left.width, 0))
        self.current_tex = None
        self.current_image = image
        self.current_name = "BACK_COMPLETO.png"
        self.composite_mode = True
        self._set_watched((left, right))
        self.info_var.set(
            f"Composicao da tela inicial\nEsquerda: {left}\nDireita: {right}\n"
            f"Dimensoes finais: {image.width} x {image.height}"
        )
        self.palette_canvas.delete("all")
        self.status_var.set("Visualizando BACK1.TEX + BACK2.TEX — 320x240")
        self._render_preview()

    def reload_current(self) -> None:
        if self.composite_mode:
            self.show_title()
        elif self.current_tex:
            self.load_file(self.current_tex.path)

    def _set_watched(self, paths: tuple[Path, ...]) -> None:
        self.watched_paths = paths
        self.watched_state = self._file_state(paths)

    @staticmethod
    def _file_state(paths: tuple[Path, ...]) -> tuple[tuple[int, int], ...]:
        state = []
        for path in paths:
            try:
                stat = path.stat()
                state.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                state.append((-1, -1))
        return tuple(state)

    def _watch_files(self) -> None:
        if self.live_var.get() and self.watched_paths:
            state = self._file_state(self.watched_paths)
            if state != self.watched_state:
                self.watched_state = state
                self.reload_current()
                self.status_var.set(f"Atualizado automaticamente: {self.current_name}")
        self.after(700, self._watch_files)

    def _render_preview(self) -> None:
        image = self.current_image
        if image is None or not self.canvas.winfo_exists():
            return
        preview = make_checkerboard(image.size)
        preview.alpha_composite(image)
        zoom_text = self.zoom_var.get()
        if zoom_text == "Ajustar":
            available_width = max(1, self.canvas.winfo_width() - 24)
            available_height = max(1, self.canvas.winfo_height() - 24)
            scale = min(available_width / image.width, available_height / image.height)
            scale = max(0.1, scale)
        else:
            scale = float(zoom_text.rstrip("x"))
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        preview = preview.resize(size, Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        x = max(0, (canvas_width - size[0]) // 2)
        y = max(0, (canvas_height - size[1]) // 2)
        self.canvas.create_image(x, y, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, max(canvas_width, size[0]), max(canvas_height, size[1])))

    def _wheel_zoom(self, event) -> str:
        choices = ["1x", "2x", "3x", "4x", "6x", "8x"]
        current = self.zoom_var.get()
        index = choices.index(current) if current in choices else 0
        index = min(len(choices) - 1, index + 1) if event.delta > 0 else max(0, index - 1)
        self.zoom_var.set(choices[index])
        self._render_preview()
        return "break"

    def _draw_palette(self, words: tuple[int, ...]) -> None:
        canvas = self.palette_canvas
        canvas.delete("all")
        width = max(320, canvas.winfo_width())
        cell = max(12, min(24, width // 16))
        for index, word in enumerate(words):
            row, column = divmod(index, 16)
            red, green, blue, _ = psx_color(word)
            color = f"#{red:02x}{green:02x}{blue:02x}"
            x0, y0 = column * cell, row * cell
            canvas.create_rectangle(x0, y0, x0 + cell, y0 + cell, fill=color, outline="#303030")
        canvas.configure(scrollregion=(0, 0, 16 * cell, 16 * cell))

    def export_current(self) -> None:
        if self.current_image is None:
            messagebox.showwarning(APP_TITLE, "Nenhuma imagem carregada.")
            return
        selected = filedialog.asksaveasfilename(
            title="Exportar PNG",
            defaultextension=".png",
            initialfile=Path(self.current_name).with_suffix(".png").name,
            filetypes=(("Imagem PNG", "*.png"),),
        )
        if selected:
            self.current_image.save(selected)
            self.status_var.set(f"PNG exportado: {selected}")

    def export_all(self) -> None:
        if not self.files:
            messagebox.showwarning(APP_TITLE, "Nenhum TEX na lista.")
            return
        selected = filedialog.askdirectory(title="Selecione a pasta para os PNGs")
        if not selected:
            return
        output_root = Path(selected)
        source_root = Path(self.folder_var.get())
        errors: list[str] = []
        exported = 0
        for path in self.files:
            try:
                tex = decode_tex(path, self._alpha_mode())
                relative = path.relative_to(source_root).with_suffix(".png")
                destination = output_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                tex.image.save(destination)
                exported += 1
            except (OSError, ValueError) as error:
                errors.append(f"{path}: {error}")
        self.status_var.set(f"Exportados {exported}/{len(self.files)} TEX.")
        if errors:
            messagebox.showwarning(APP_TITLE, "Alguns arquivos falharam:\n" + "\n".join(errors[:8]))
        else:
            messagebox.showinfo(APP_TITLE, f"{exported} PNG(s) exportado(s) com sucesso.")

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.is_file():
            return
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.folder_var.set(settings.get("folder", ""))
        self.zoom_var.set(settings.get("zoom", "Ajustar"))
        self.alpha_var.set(settings.get("alpha", "Automatica"))
        self.recursive_var.set(bool(settings.get("recursive", False)))
        self.live_var.set(bool(settings.get("live", True)))

    def _close(self) -> None:
        settings = {
            "folder": self.folder_var.get(),
            "zoom": self.zoom_var.get(),
            "alpha": self.alpha_var.get(),
            "recursive": self.recursive_var.get(),
            "live": self.live_var.get(),
        }
        try:
            SETTINGS_FILE.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
        self.destroy()


def main() -> None:
    app = TexViewerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
