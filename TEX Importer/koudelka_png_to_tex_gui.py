from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageChops, ImageDraw, ImageStat, ImageTk
except ImportError as error:
    raise SystemExit(
        "A biblioteca Pillow nao esta instalada. Execute instalar_dependencias.bat."
    ) from error


APP_TITLE = "Koudelka - Importador PNG para TEX"
SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SCRIPT_DIR / "koudelka_png_to_tex_settings.json"
HEADER_SIZE = 24
PALETTE_COLORS = 256
PALETTE_SIZE = PALETTE_COLORS * 2
PIXEL_OFFSET = HEADER_SIZE + PALETTE_SIZE
TITLE_SHARED_TEXTURES = {"BACK1", "BACK2", "LOGOL", "LOGOR"}


@dataclass(frozen=True)
class TexTemplate:
    path: Path
    data: bytes
    declared_size: int
    format_id: int
    width: int
    height: int
    flags: int
    palette_words: tuple[int, ...]


@dataclass(frozen=True)
class ConversionResult:
    template: TexTemplate
    output_data: bytes
    preview: Image.Image
    palette_words: tuple[int, ...]
    transparent_pixels: int
    input_colors: int
    output_colors: int
    mean_error: float
    max_error: int


def psx_word_to_rgb(word: int) -> tuple[int, int, int]:
    red = word & 0x1F
    green = (word >> 5) & 0x1F
    blue = (word >> 10) & 0x1F
    return (
        (red << 3) | (red >> 2),
        (green << 3) | (green >> 2),
        (blue << 3) | (blue >> 2),
    )


def rgb_to_psx_word(red: int, green: int, blue: int) -> int:
    return (red >> 3) | ((green >> 3) << 5) | ((blue >> 3) << 10)


def parse_template(path: Path) -> TexTemplate:
    data = path.read_bytes()
    if len(data) < PIXEL_OFFSET or data[:4] != b"\xFF\xFF\xFF\xFF":
        raise ValueError(f"Nao e um TEX valido do Koudelka: {path}")
    declared_size = struct.unpack_from("<I", data, 8)[0]
    format_id, width, height, flags = struct.unpack_from("<HHHH", data, 12)
    if format_id != 1:
        raise ValueError(f"Formato TEX nao suportado: {format_id}.")
    expected_size = PIXEL_OFFSET + width * height
    if len(data) < expected_size:
        raise ValueError(
            f"TEX truncado: {len(data)} bytes; esperado pelo menos {expected_size}."
        )
    palette_words = struct.unpack_from(f"<{PALETTE_COLORS}H", data, HEADER_SIZE)
    return TexTemplate(
        path=path,
        data=data,
        declared_size=declared_size,
        format_id=format_id,
        width=width,
        height=height,
        flags=flags,
        palette_words=tuple(palette_words),
    )


def alpha_is_enabled(template: TexTemplate, alpha_mode: str) -> bool:
    if alpha_mode == "transparent":
        return True
    if alpha_mode == "opaque":
        return False
    return not template.path.stem.upper().startswith("BACK")


def decode_tex_data(data: bytes, template: TexTemplate, alpha_mode: str) -> Image.Image:
    palette_words = struct.unpack_from(f"<{PALETTE_COLORS}H", data, HEADER_SIZE)
    transparency = alpha_is_enabled(template, alpha_mode)
    palette = []
    for word in palette_words:
        red, green, blue = psx_word_to_rgb(word)
        alpha = 0 if transparency and word == 0 else 255
        palette.append((red, green, blue, alpha))
    pixels = data[PIXEL_OFFSET : PIXEL_OFFSET + template.width * template.height]
    image = Image.new("RGBA", (template.width, template.height))
    image.putdata([palette[index] for index in pixels])
    return image


def make_fixed_palette(words: tuple[int, ...]) -> Image.Image:
    palette_image = Image.new("P", (1, 1))
    flat: list[int] = []
    for word in words:
        flat.extend(psx_word_to_rgb(word))
    palette_image.putpalette(flat[:768] + [0] * max(0, 768 - len(flat)))
    return palette_image


def convert_with_original_palette(
    image: Image.Image,
    template: TexTemplate,
    transparency: bool,
    dither: bool,
) -> tuple[tuple[int, ...], bytes, int]:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")
    palette_image = make_fixed_palette(template.palette_words)
    dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    indexed = rgb.quantize(palette=palette_image, dither=dither_mode)
    indices = bytearray(indexed.tobytes())
    transparent_pixels = 0
    if transparency:
        transparent_index = next(
            (index for index, word in enumerate(template.palette_words) if word == 0), 0
        )
        mask = alpha.tobytes()
        for index, value in enumerate(mask):
            if value < 128:
                indices[index] = transparent_index
                transparent_pixels += 1
    return template.palette_words, bytes(indices), transparent_pixels


def quantize_psx_precision(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    table = [((value >> 3) << 3) | ((value >> 3) >> 2) for value in range(256)]
    return rgb.point(table * 3)


def convert_with_new_palette(
    image: Image.Image,
    template: TexTemplate,
    transparency: bool,
    dither: bool,
) -> tuple[tuple[int, ...], bytes, int]:
    rgba = image.convert("RGBA")
    alpha_bytes = rgba.getchannel("A").tobytes()
    rgb = quantize_psx_precision(rgba)
    reserve = 1 if transparency else 0
    color_limit = PALETTE_COLORS - reserve
    dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    indexed = rgb.quantize(colors=color_limit, method=Image.Quantize.MEDIANCUT, dither=dither_mode)
    raw_palette = indexed.getpalette() or []
    source_indices = indexed.tobytes()

    # O bit 15 da cor PS1 (STP) faz parte do formato da textura, nao da cor
    # RGB do PNG. BACK1/BACK2, por exemplo, usam STP nas 256 entradas. Apagar
    # esse bit ao criar uma CLUT nova faz os outros elementos da tela serem
    # compostos incorretamente no jogo.
    non_transparent_words = [word for word in template.palette_words if word != 0]
    force_stp = bool(non_transparent_words) and all(
        word & 0x8000 for word in non_transparent_words
    )

    palette_words: list[int] = [0] if transparency else []
    for index in range(color_limit):
        offset = index * 3
        if offset + 2 < len(raw_palette):
            word = rgb_to_psx_word(
                raw_palette[offset], raw_palette[offset + 1], raw_palette[offset + 2]
            )
        else:
            word = 0
        # Em texturas transparentes, a cor 0 e reservada. Evita transformar
        # preto opaco em transparente por acidente.
        if transparency and word == 0:
            word = 1
        if force_stp:
            word |= 0x8000
        palette_words.append(word)
    palette_words.extend([0] * (PALETTE_COLORS - len(palette_words)))

    indices = bytearray(len(source_indices))
    transparent_pixels = 0
    for index, palette_index in enumerate(source_indices):
        if transparency and alpha_bytes[index] < 128:
            indices[index] = 0
            transparent_pixels += 1
        else:
            indices[index] = palette_index + reserve
    return tuple(palette_words[:PALETTE_COLORS]), bytes(indices), transparent_pixels


def make_conversion_result(
    template: TexTemplate,
    image: Image.Image,
    palette_words: tuple[int, ...],
    indices: bytes,
    transparent_pixels: int,
    alpha_mode: str,
) -> ConversionResult:
    expected_pixels = template.width * template.height
    if len(indices) != expected_pixels:
        raise ValueError(
            f"Quantidade de pixels invalida: {len(indices)}; esperado {expected_pixels}."
        )
    output = bytearray(template.data)
    struct.pack_into(f"<{PALETTE_COLORS}H", output, HEADER_SIZE, *palette_words)
    pixel_end = PIXEL_OFFSET + expected_pixels
    output[PIXEL_OFFSET:pixel_end] = indices
    if len(output) != len(template.data):
        raise RuntimeError("O TEX convertido ficou com tamanho diferente do molde.")
    preview = decode_tex_data(bytes(output), template, alpha_mode)
    mean_error, max_error = image_error(image, preview)
    return ConversionResult(
        template=template,
        output_data=bytes(output),
        preview=preview,
        palette_words=palette_words,
        transparent_pixels=transparent_pixels,
        input_colors=color_count(image),
        output_colors=len(set(indices)),
        mean_error=mean_error,
        max_error=max_error,
    )


def build_title_tex(
    templates: tuple[TexTemplate, TexTemplate],
    full_image: Image.Image,
    alpha_mode: str,
    dither: bool,
) -> tuple[ConversionResult, ConversionResult]:
    left, right = templates
    if left.height != right.height:
        raise ValueError("BACK1.TEX e BACK2.TEX precisam ter a mesma altura.")
    if left.palette_words != right.palette_words:
        raise ValueError(
            "BACK1.TEX e BACK2.TEX nao possuem a mesma paleta original. "
            "Use 'Preservar paleta original'."
        )
    expected_size = (left.width + right.width, left.height)
    if full_image.size != expected_size:
        raise ValueError(
            f"A tela inicial precisa ter {expected_size[0]}x{expected_size[1]}."
        )

    transparency = alpha_is_enabled(left, alpha_mode)
    palette_words, full_indices, transparent_pixels = convert_with_new_palette(
        full_image, left, transparency, dither
    )
    indexed = Image.frombytes("P", expected_size, full_indices)
    left_indices = indexed.crop((0, 0, left.width, left.height)).tobytes()
    right_indices = indexed.crop(
        (left.width, 0, left.width + right.width, right.height)
    ).tobytes()
    left_image = full_image.crop((0, 0, left.width, left.height))
    right_image = full_image.crop(
        (left.width, 0, left.width + right.width, right.height)
    )

    if transparency:
        alpha = full_image.getchannel("A")
        left_transparent = sum(value < 128 for value in alpha.crop(
            (0, 0, left.width, left.height)
        ).tobytes())
        right_transparent = transparent_pixels - left_transparent
    else:
        left_transparent = right_transparent = 0

    return (
        make_conversion_result(
            left, left_image, palette_words, left_indices, left_transparent, alpha_mode
        ),
        make_conversion_result(
            right, right_image, palette_words, right_indices, right_transparent, alpha_mode
        ),
    )


def color_count(image: Image.Image) -> int:
    colors = image.convert("RGBA").getcolors(maxcolors=image.width * image.height)
    return len(colors) if colors is not None else image.width * image.height


def image_error(source: Image.Image, result: Image.Image) -> tuple[float, int]:
    source_rgb = source.convert("RGB")
    result_rgb = result.convert("RGB")
    difference = ImageChops.difference(source_rgb, result_rgb)
    stat = ImageStat.Stat(difference)
    mean = sum(stat.mean) / 3
    extrema = difference.getextrema()
    maximum = max(channel[1] for channel in extrema)
    return mean, maximum


def build_tex(
    template: TexTemplate,
    image: Image.Image,
    palette_mode: str,
    alpha_mode: str,
    dither: bool,
) -> ConversionResult:
    if image.size != (template.width, template.height):
        raise ValueError(
            f"O PNG possui {image.width}x{image.height}; o molde exige "
            f"{template.width}x{template.height}."
        )
    transparency = alpha_is_enabled(template, alpha_mode)
    input_colors = color_count(image)
    if palette_mode == "original":
        palette_words, indices, transparent_pixels = convert_with_original_palette(
            image, template, transparency, dither
        )
    else:
        palette_words, indices, transparent_pixels = convert_with_new_palette(
            image, template, transparency, dither
        )
    return make_conversion_result(
        template, image, palette_words, indices, transparent_pixels, alpha_mode
    )


def checkerboard(image: Image.Image, cell: int = 8) -> Image.Image:
    background = Image.new("RGBA", image.size, (48, 48, 48, 255))
    draw = ImageDraw.Draw(background)
    for y in range(0, image.height, cell):
        for x in range(0, image.width, cell):
            shade = 58 if ((x // cell) + (y // cell)) & 1 else 88
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(shade, shade, shade, 255))
    background.alpha_composite(image)
    return background


class PngToTexApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x720")
        self.minsize(760, 540)

        self.mode_var = tk.StringVar(value="single")
        self.template_var = tk.StringVar()
        self.png_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.palette_var = tk.StringVar(value="Preservar paleta original")
        self.alpha_var = tk.StringVar(value="Automatica")
        self.dither_var = tk.BooleanVar(value=False)
        self.zoom_var = tk.StringVar(value="Ajustar")
        self.status_var = tk.StringVar(value="Selecione o molde TEX e o PNG editado.")
        self.info_var = tk.StringVar(value="Conversao ainda nao analisada.")

        self.previews: dict[str, Image.Image] = {}
        self.results: tuple[ConversionResult, ...] = ()
        self.photo_before: ImageTk.PhotoImage | None = None
        self.photo_after: ImageTk.PhotoImage | None = None
        self.input_state: tuple[tuple[str, int, int], ...] = ()

        self._load_settings()
        self._configure_style()
        self._build_ui()
        self._mode_changed()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(700, self._watch_inputs)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=("Arial", 10))
        style.configure("Title.TLabel", font=("Arial", 13, "bold"))

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=8)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Importador de PNG para TEX", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            main,
            text="Converte PNG para a textura indexada de 8 bits do Koudelka usando um TEX original como molde.",
        ).pack(anchor="w", pady=(1, 5))

        mode_row = ttk.Frame(main)
        mode_row.pack(fill="x")
        ttk.Radiobutton(
            mode_row,
            text="Um PNG para um TEX",
            value="single",
            variable=self.mode_var,
            command=self._mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_row,
            text="Tela inicial 320x240 para BACK1 + BACK2",
            value="title",
            variable=self.mode_var,
            command=self._mode_changed,
        ).pack(side="left", padx=(18, 0))

        paths = ttk.LabelFrame(main, text="Arquivos", padding=7)
        paths.pack(fill="x", pady=(5, 0))
        self.template_label = ttk.Label(paths, text="TEX original:", width=18)
        self.template_label.grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(paths, textvariable=self.template_var).grid(
            row=0, column=1, sticky="ew", padx=5, pady=2
        )
        self.template_button = ttk.Button(paths, text="Selecionar...", command=self.browse_template)
        self.template_button.grid(row=0, column=2, pady=2)
        ttk.Label(paths, text="PNG editado:", width=18).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(paths, textvariable=self.png_var).grid(
            row=1, column=1, sticky="ew", padx=5, pady=2
        )
        ttk.Button(paths, text="Selecionar...", command=self.browse_png).grid(row=1, column=2, pady=2)
        self.output_label = ttk.Label(paths, text="TEX de saida:", width=18)
        self.output_label.grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(paths, textvariable=self.output_var).grid(
            row=2, column=1, sticky="ew", padx=5, pady=2
        )
        self.output_button = ttk.Button(paths, text="Selecionar...", command=self.browse_output)
        self.output_button.grid(row=2, column=2, pady=2)
        paths.columnconfigure(1, weight=1)

        conversion = ttk.Frame(main)
        conversion.pack(fill="x", pady=(5, 0))
        ttk.Label(conversion, text="Paleta:").pack(side="left")
        palette_box = ttk.Combobox(
            conversion,
            textvariable=self.palette_var,
            values=("Preservar paleta original", "Gerar nova paleta de 256 cores"),
            state="readonly",
            width=30,
        )
        palette_box.pack(side="left", padx=(4, 14))
        palette_box.bind("<<ComboboxSelected>>", lambda _event: self._live_preview_now())
        ttk.Label(conversion, text="Transparencia:").pack(side="left")
        alpha_box = ttk.Combobox(
            conversion,
            textvariable=self.alpha_var,
            values=("Automatica", "Usar transparencia do PNG", "Tudo opaco"),
            state="readonly",
            width=25,
        )
        alpha_box.pack(side="left", padx=(4, 14))
        alpha_box.bind("<<ComboboxSelected>>", lambda _event: self._live_preview_now())
        ttk.Checkbutton(
            conversion,
            text="Dithering",
            variable=self.dither_var,
            command=self._live_preview_now,
        ).pack(side="left")

        actions = ttk.Frame(main)
        actions.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="GERAR TEX", command=self.generate).pack(side="right")
        ttk.Button(actions, text="Pre-visualizar", command=self.preview_conversion).pack(
            side="right", padx=(0, 5)
        )

        preview_tools = ttk.Frame(main)
        preview_tools.pack(fill="x", pady=(5, 0))
        ttk.Label(preview_tools, text="Zoom:").pack(side="left")
        zoom_box = ttk.Combobox(
            preview_tools,
            textvariable=self.zoom_var,
            values=("Ajustar", "1x", "2x", "3x", "4x", "6x"),
            state="readonly",
            width=8,
        )
        zoom_box.pack(side="left", padx=(4, 0))
        zoom_box.bind("<<ComboboxSelected>>", lambda _event: self._render_pair())
        ttk.Label(
            preview_tools,
            text="A prévia é atualizada automaticamente ao salvar o PNG.",
        ).pack(side="left", padx=(16, 0))
        ttk.Label(preview_tools, textvariable=self.info_var).pack(side="right")

        preview_frame = ttk.Panedwindow(main, orient="horizontal")
        preview_frame.pack(fill="both", expand=True, pady=(5, 0))
        before_frame = ttk.LabelFrame(preview_frame, text="ANTES — TEX original", padding=4)
        after_frame = ttk.LabelFrame(
            preview_frame, text="DEPOIS — prévia no formato/paleta do jogo", padding=4
        )
        preview_frame.add(before_frame, weight=1)
        preview_frame.add(after_frame, weight=1)
        self.before_canvas = self._create_preview_canvas(before_frame)
        self.after_canvas = self._create_preview_canvas(after_frame)
        self.before_canvas.bind("<Configure>", lambda _event: self.after_idle(self._render_pair))
        self.after_canvas.bind("<Configure>", lambda _event: self.after_idle(self._render_pair))

    @staticmethod
    def _create_preview_canvas(parent) -> tk.Canvas:
        canvas = tk.Canvas(parent, background="#202020", highlightthickness=0)
        vertical = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(parent, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        return canvas

    def _palette_mode(self) -> str:
        return "original" if self.palette_var.get().startswith("Preservar") else "new"

    def _alpha_mode(self) -> str:
        return {
            "Automatica": "auto",
            "Usar transparencia do PNG": "transparent",
            "Tudo opaco": "opaque",
        }.get(self.alpha_var.get(), "auto")

    def _mode_changed(self) -> None:
        title_mode = self.mode_var.get() == "title"
        self.template_label.configure(text="Pasta com BACKs:" if title_mode else "TEX original:")
        self.output_label.configure(text="Pasta de saida:" if title_mode else "TEX de saida:")
        self.results = ()
        self.previews.clear()
        self.input_state = ()
        self.info_var.set("Conversao ainda nao analisada.")
        if hasattr(self, "before_canvas"):
            self.before_canvas.delete("all")
            self.after_canvas.delete("all")

    def browse_template(self) -> None:
        if self.mode_var.get() == "title":
            selected = filedialog.askdirectory(title="Selecione a pasta com BACK1.TEX e BACK2.TEX")
        else:
            selected = filedialog.askopenfilename(
                title="Selecione o TEX original",
                filetypes=(("Textura TEX", "*.TEX *.tex"), ("Todos", "*.*")),
            )
        if selected:
            self.template_var.set(selected)
            if self.mode_var.get() == "single":
                path = Path(selected)
                self.output_var.set(str(path.with_name(f"{path.stem}_IMPORTADO.TEX")))
            self._live_preview_now()

    def browse_png(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o PNG editado",
            filetypes=(("Imagem PNG", "*.png"), ("Todos", "*.*")),
        )
        if selected:
            self.png_var.set(selected)
            if self.mode_var.get() == "title" and not self.output_var.get().strip():
                self.output_var.set(str(Path(selected).parent / "TEX_IMPORTADO"))
            self._live_preview_now()

    def browse_output(self) -> None:
        if self.mode_var.get() == "title":
            selected = filedialog.askdirectory(title="Selecione a pasta de saida")
        else:
            selected = filedialog.asksaveasfilename(
                title="Salvar TEX convertido",
                defaultextension=".TEX",
                initialfile=Path(self.output_var.get()).name if self.output_var.get() else "IMPORTADO.TEX",
                filetypes=(("Textura TEX", "*.TEX"),),
            )
        if selected:
            self.output_var.set(selected)

    def _load_inputs(self) -> tuple[tuple[TexTemplate, ...], tuple[Image.Image, ...], Image.Image]:
        png_path = Path(self.png_var.get().strip())
        if not png_path.is_file():
            raise ValueError("Selecione um PNG editado valido.")
        try:
            full_png = Image.open(png_path).convert("RGBA")
        except OSError as error:
            raise ValueError(f"Nao foi possivel abrir o PNG: {error}") from error

        if self.mode_var.get() == "title":
            folder = Path(self.template_var.get().strip())
            left_path, right_path = folder / "BACK1.TEX", folder / "BACK2.TEX"
            if not left_path.is_file() or not right_path.is_file():
                raise ValueError("A pasta precisa conter BACK1.TEX e BACK2.TEX.")
            templates = (parse_template(left_path), parse_template(right_path))
            expected = (templates[0].width + templates[1].width, templates[0].height)
            if full_png.size != expected:
                raise ValueError(
                    f"A tela inicial precisa ter {expected[0]}x{expected[1]}; "
                    f"o PNG possui {full_png.width}x{full_png.height}."
                )
            left_png = full_png.crop((0, 0, templates[0].width, templates[0].height))
            right_png = full_png.crop(
                (templates[0].width, 0, templates[0].width + templates[1].width, templates[1].height)
            )
            return templates, (left_png, right_png), full_png

        template_path = Path(self.template_var.get().strip())
        if not template_path.is_file():
            raise ValueError("Selecione um TEX original valido.")
        template = parse_template(template_path)
        return (template,), (full_png,), full_png

    def preview_conversion(self, silent: bool = False) -> bool:
        try:
            templates, images, full_png = self._load_inputs()
            palette_mode = self._palette_mode()
            if (
                self.mode_var.get() == "single"
                and palette_mode == "new"
                and templates[0].path.stem.upper() in TITLE_SHARED_TEXTURES
            ):
                raise ValueError(
                    f"{templates[0].path.name} compartilha a paleta da tela inicial.\n"
                    "Para gerar uma nova paleta com seguranca, selecione o modo "
                    "'Tela inicial 320x240 para BACK1 + BACK2'.\n"
                    "Para converter somente este arquivo, use 'Preservar paleta original'."
                )
            if self.mode_var.get() == "title" and palette_mode == "new":
                results = build_title_tex(
                    (templates[0], templates[1]),
                    full_png,
                    self._alpha_mode(),
                    self.dither_var.get(),
                )
            else:
                results = tuple(
                    build_tex(
                        template,
                        image,
                        palette_mode,
                        self._alpha_mode(),
                        self.dither_var.get(),
                    )
                    for template, image in zip(templates, images)
                )
        except (OSError, ValueError, RuntimeError) as error:
            if silent:
                self.status_var.set(f"Aguardando arquivo válido: {error}")
            else:
                messagebox.showerror(APP_TITLE, str(error))
            return False

        originals = [decode_tex_data(template.data, template, self._alpha_mode()) for template in templates]
        if len(results) == 2:
            original = Image.new("RGBA", full_png.size)
            result_image = Image.new("RGBA", full_png.size)
            original.alpha_composite(originals[0], (0, 0))
            original.alpha_composite(originals[1], (templates[0].width, 0))
            result_image.alpha_composite(results[0].preview, (0, 0))
            result_image.alpha_composite(results[1].preview, (templates[0].width, 0))
        else:
            original = originals[0]
            result_image = results[0].preview

        self.results = results
        self.previews = {
            "TEX original": original,
            "PNG editado": full_png,
            "Resultado simulado": result_image,
        }
        mean_error = sum(result.mean_error for result in results) / len(results)
        max_error = max(result.max_error for result in results)
        input_colors = color_count(full_png)
        output_colors = sum(result.output_colors for result in results)
        self.info_var.set(
            f"Cores PNG: {input_colors} | TEX: {output_colors} | "
            f"erro medio: {mean_error:.2f} | maximo: {max_error}"
        )
        self.status_var.set("Pre-visualizacao pronta. Confira o resultado antes de gerar.")
        self.input_state = self._capture_input_state()
        self._render_pair()
        return True

    def generate(self) -> None:
        if not self.preview_conversion():
            return
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showerror(APP_TITLE, "Selecione o caminho de saida.")
            return
        try:
            if self.mode_var.get() == "title":
                output_folder = Path(output_text)
                output_folder.mkdir(parents=True, exist_ok=True)
                destinations = (output_folder / "BACK1.TEX", output_folder / "BACK2.TEX")
            else:
                destination = Path(output_text)
                if destination.suffix.lower() != ".tex":
                    raise ValueError("O arquivo de saida precisa ter extensao .TEX.")
                template_path = self.results[0].template.path.resolve()
                if destination.resolve() == template_path:
                    raise ValueError("O TEX convertido nao pode sobrescrever diretamente o molde original.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destinations = (destination,)

            existing = [path for path in destinations if path.exists()]
            if existing and not messagebox.askyesno(
                APP_TITLE,
                "Os seguintes arquivos ja existem e serao substituidos:\n"
                + "\n".join(str(path) for path in existing)
                + "\n\nContinuar?",
            ):
                return

            for destination, result in zip(destinations, self.results):
                temporary = destination.with_name(f".{destination.name}.tmp")
                try:
                    temporary.write_bytes(result.output_data)
                    if temporary.stat().st_size != result.template.path.stat().st_size:
                        raise RuntimeError("O TEX gravado ficou com tamanho diferente do molde.")
                    os.replace(temporary, destination)
                finally:
                    if temporary.exists():
                        temporary.unlink()

            report_path = (
                Path(output_text) / "relatorio_importacao_tex.json"
                if self.mode_var.get() == "title"
                else Path(output_text).with_suffix(".tex_import_report.json")
            )
            report = {
                "mode": self.mode_var.get(),
                "png": self.png_var.get(),
                "palette_mode": self.palette_var.get(),
                "alpha_mode": self.alpha_var.get(),
                "dither": self.dither_var.get(),
                "files": [
                    {
                        "template": str(result.template.path),
                        "output": str(destination),
                        "width": result.template.width,
                        "height": result.template.height,
                        "size": len(result.output_data),
                        "input_colors": result.input_colors,
                        "output_colors": result.output_colors,
                        "transparent_pixels": result.transparent_pixels,
                        "mean_rgb_error": result.mean_error,
                        "max_rgb_error": result.max_error,
                    }
                    for destination, result in zip(destinations, self.results)
                ],
            }
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror(APP_TITLE, str(error))
            return

        self.status_var.set("TEX gerado e validado com sucesso.")
        messagebox.showinfo(
            APP_TITLE,
            "TEX gerado com sucesso:\n"
            + "\n".join(str(path) for path in destinations)
            + f"\n\nRelatorio: {report_path}",
        )

    def _render_canvas(self, canvas: tk.Canvas, image: Image.Image | None, side: str) -> None:
        if image is None:
            return
        preview = checkerboard(image)
        zoom_text = self.zoom_var.get()
        if zoom_text == "Ajustar":
            available_width = max(1, canvas.winfo_width() - 24)
            available_height = max(1, canvas.winfo_height() - 24)
            scale = max(0.1, min(available_width / image.width, available_height / image.height))
        else:
            scale = float(zoom_text.rstrip("x"))
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        preview = preview.resize(size, Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(preview)
        if side == "before":
            self.photo_before = photo
        else:
            self.photo_after = photo
        canvas.delete("all")
        canvas_width, canvas_height = canvas.winfo_width(), canvas.winfo_height()
        x = max(0, (canvas_width - size[0]) // 2)
        y = max(0, (canvas_height - size[1]) // 2)
        canvas.create_image(x, y, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, max(canvas_width, size[0]), max(canvas_height, size[1])))

    def _render_pair(self) -> None:
        self._render_canvas(self.before_canvas, self.previews.get("TEX original"), "before")
        self._render_canvas(self.after_canvas, self.previews.get("Resultado simulado"), "after")

    def _input_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        template_text = self.template_var.get().strip()
        png_text = self.png_var.get().strip()
        if template_text:
            template = Path(template_text)
            if self.mode_var.get() == "title":
                paths.extend((template / "BACK1.TEX", template / "BACK2.TEX"))
            else:
                paths.append(template)
        if png_text:
            paths.append(Path(png_text))
        return tuple(paths)

    def _capture_input_state(self) -> tuple[tuple[str, int, int], ...]:
        state: list[tuple[str, int, int]] = []
        for path in self._input_paths():
            try:
                stat = path.stat()
                state.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                state.append((str(path), -1, -1))
        return tuple(state)

    def _live_preview_now(self) -> None:
        if self.template_var.get().strip() and self.png_var.get().strip():
            self.after_idle(lambda: self.preview_conversion(silent=True))

    def _watch_inputs(self) -> None:
        state = self._capture_input_state()
        if state and state != self.input_state:
            if self.preview_conversion(silent=True):
                self.status_var.set("Prévia atualizada automaticamente após alteração do PNG/TEX.")
        self.after(700, self._watch_inputs)

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.is_file():
            return
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.template_var.set(settings.get("template", ""))
        self.palette_var.set(settings.get("palette", "Preservar paleta original"))
        self.alpha_var.set(settings.get("alpha", "Automatica"))
        self.dither_var.set(bool(settings.get("dither", False)))

    def _close(self) -> None:
        settings = {
            "template": self.template_var.get(),
            "palette": self.palette_var.get(),
            "alpha": self.alpha_var.get(),
            "dither": self.dither_var.get(),
        }
        try:
            SETTINGS_FILE.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
        self.destroy()


def main() -> None:
    app = PngToTexApp()
    app.mainloop()


if __name__ == "__main__":
    main()
