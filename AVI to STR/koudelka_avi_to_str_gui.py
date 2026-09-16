#!/usr/bin/env python3
"""Interface gráfica para converter AVI em STR compatível com Koudelka/PS1."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Koudelka - Conversor AVI para STR v1.1"
SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SCRIPT_DIR / "koudelka_avi_to_str_settings.json"

PSXAVENC_CANDIDATES = (
    SCRIPT_DIR / "psxavenc.exe",
    Path(r"E:\KDK\Koudelka (Disc 1)\MOVIE\psxavenc-windows\bin\psxavenc.exe"),
    Path(r"C:\Users\sistemas2\Desktop\KDK\Koudelka (Disc 1)\MOVIE\psxavenc-windows\bin\psxavenc.exe"),
    Path(r"C:\msys64\home\sistemas2\psxavenc-windows\bin\psxavenc.exe"),
)
FFPROBE_CANDIDATES = (
    Path(r"C:\msys64\mingw64\bin\ffprobe.exe"),
    Path(r"C:\msys64\ucrt64\bin\ffprobe.exe"),
    Path(r"C:\msys64\clang64\bin\ffprobe.exe"),
)
FFMPEG_CANDIDATES = (
    Path(r"C:\msys64\mingw64\bin\ffmpeg.exe"),
    Path(r"C:\msys64\ucrt64\bin\ffmpeg.exe"),
    Path(r"C:\msys64\clang64\bin\ffmpeg.exe"),
)
JPSXDEC_CANDIDATES = (
    SCRIPT_DIR / "jpsxdec.jar",
    SCRIPT_DIR.parent / "jpsxdec_v2.1-beta" / "jpsxdec.jar",
    Path(r"E:\KDK\Tools\jpsxdec_v2.1-beta\jpsxdec.jar"),
    Path(r"C:\Users\sistemas2\Desktop\KDK\Tools\jpsxdec_v2.1-beta\jpsxdec.jar"),
)


@dataclass(frozen=True)
class ConversionJob:
    avi: Path
    output: Path
    original_str: Path | None
    relative_path: str


def find_program(candidates: tuple[Path, ...], executable_name: str) -> str:
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    discovered = shutil.which(executable_name)
    return discovered or str(candidates[0])


def derive_str_stem(avi: Path | str) -> str:
    """SC00.STR[0].avi ou SC00.STR[0]_PTBR.avi -> SC00."""
    name = Path(avi).name
    without_avi = name[:-4] if name.lower().endswith(".avi") else Path(name).stem
    match = re.match(r"(?i)^(?P<stem>.+?)\.STR(?:\[\d+\])?(?:[_ -].*)?$", without_avi)
    if match:
        return match.group("stem")
    return re.sub(
        r"(?i)(?:_EDITAD[OA]|_TRADUZID[OA]|_IMPORTAD[OA]|_PTBR|_PT_BR|_FINAL|_NOVO)$",
        "",
        without_avi,
    )


def find_original_str(
    avi: Path,
    stem: str,
    original_hint: Path | None,
    relative_parent: Path | None = None,
) -> Path | None:
    expected_name = f"{stem}.STR"
    if original_hint:
        if original_hint.is_file():
            return original_hint
        if original_hint.is_dir():
            if relative_parent is not None:
                direct = original_hint / relative_parent / expected_name
                if direct.is_file():
                    return direct
            direct = original_hint / expected_name
            if direct.is_file():
                return direct
            matches = sorted(original_hint.rglob(expected_name))
            if matches:
                return matches[0]

    # Fluxo comum: MOVIE/revisado/STR/SC00.STR[0].avi e MOVIE/SC00.STR.
    for ancestor in (avi.parent, *tuple(avi.parents)[:6]):
        candidate = ancestor / expected_name
        if candidate.is_file():
            return candidate
    return None


def build_jobs(
    source: Path | str,
    output_folder: Path | str,
    original_hint: Path | str | None,
    folder_mode: bool,
) -> list[ConversionJob]:
    source_path = Path(source).resolve()
    output_root = Path(output_folder).resolve()
    hint = Path(original_hint).resolve() if original_hint else None

    if folder_mode:
        if not source_path.is_dir():
            raise ValueError(f"Pasta de AVI não encontrada: {source_path}")
        avis = sorted(
            path for path in source_path.rglob("*")
            if path.is_file() and path.suffix.lower() == ".avi"
        )
        if not avis:
            raise ValueError("Nenhum arquivo AVI foi encontrado na pasta selecionada.")
    else:
        if not source_path.is_file() or source_path.suffix.lower() != ".avi":
            raise ValueError("Selecione um arquivo com extensão .AVI.")
        avis = [source_path]

    jobs: list[ConversionJob] = []
    seen_outputs: set[str] = set()
    for avi in avis:
        relative_parent = avi.relative_to(source_path).parent if folder_mode else Path()
        stem = derive_str_stem(avi)
        output = output_root / relative_parent / f"{stem}_NOVO.STR"
        output_key = str(output).casefold()
        if output_key in seen_outputs:
            raise ValueError(f"Dois AVI gerariam o mesmo arquivo de saída: {output}")
        seen_outputs.add(output_key)
        original = find_original_str(avi, stem, hint, relative_parent)
        jobs.append(
            ConversionJob(
                avi=avi,
                output=output,
                original_str=original,
                relative_path=avi.relative_to(source_path).as_posix() if folder_mode else avi.name,
            )
        )
    return jobs


def probe_avi(ffprobe: Path | str, avi: Path | str) -> dict:
    command = [
        str(ffprobe), "-v", "error", "-count_frames", "-show_streams",
        "-of", "json", str(avi),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "O ffprobe não conseguiu analisar o AVI.")
    data = json.loads(completed.stdout)
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video:
        raise RuntimeError("O arquivo não contém uma faixa de vídeo reconhecida.")
    return {"video": video, "audio": audio}


def analyze_str(java: Path | str, jpsxdec: Path | str, source: Path, index_path: Path) -> dict:
    command = [str(java), "-jar", str(jpsxdec), "-f", str(source), "-x", str(index_path)]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not index_path.is_file():
        raise RuntimeError(
            completed.stderr.strip() or completed.stdout.strip()
            or f"O jPSXdec não conseguiu analisar {source.name}."
        )
    text = index_path.read_text(encoding="utf-8-sig", errors="replace")
    video_line = next((line for line in text.splitlines() if "Type:Video" in line), "")
    audio_line = next((line for line in text.splitlines() if "Type:XA" in line), "")
    frame_match = re.search(r"Frame Count:(\d+)", video_line)
    dimension_match = re.search(r"Dimensions:(\d+)x(\d+)", video_line)
    result = {
        "frames": int(frame_match.group(1)) if frame_match else None,
        "width": int(dimension_match.group(1)) if dimension_match else None,
        "height": int(dimension_match.group(2)) if dimension_match else None,
        "video_line": video_line,
        "audio_line": audio_line,
    }
    for key, pattern in (
        ("xa_file", r"File:(\d+)"), ("xa_channel", r"Channel:(\d+)"),
        ("sample_rate", r"Samples/Sec:(\d+)"), ("bits", r"Bits/Sample:(\d+)"),
    ):
        match = re.search(pattern, audio_line)
        result[key] = int(match.group(1)) if match else None
    return result


def build_ffmpeg_command(
    executable: Path | str,
    avi: Path | str,
    output: Path | str,
    *,
    width: int,
    height: int,
    fps: str,
    sample_rate: int,
    channels: int,
    pad_frames: int = 0,
    target_frames: int | None = None,
    audio_target_frames: int | None = None,
) -> list[str]:
    video_filter = f"scale={width}:{height}:flags=lanczos,fps={fps}"
    command = [
        str(executable), "-hide_banner", "-loglevel", "warning", "-y",
        "-i", str(avi),
    ]
    if target_frames is not None:
        if target_frames <= 0:
            raise ValueError("A quantidade alvo de quadros precisa ser maior que zero.")
        frame_rate = Fraction(fps)
        audio_frames = audio_target_frames or target_frames
        if audio_frames <= 0:
            raise ValueError("A duracao alvo do audio precisa ser maior que zero.")
        duration = float(Fraction(audio_frames * frame_rate.denominator, frame_rate.numerator))
        # tpad garante quadros suficientes quando o AVI ficou curto; trim limita
        # exatamente a quantidade do STR original quando o AVI ficou longo.
        video_filter += (
            f",tpad=stop_mode=clone:stop=-1,trim=end_frame={target_frames},"
            "setpts=PTS-STARTPTS"
        )
        audio_filter = (
            f"apad,atrim=end={duration:.10f},asetpts=PTS-STARTPTS"
        )
        command.extend(("-vf", video_filter, "-af", audio_filter))
    elif pad_frames > 0:
        duration = float(Fraction(fps).denominator * pad_frames / Fraction(fps).numerator)
        video_filter += f",tpad=stop_mode=clone:stop_duration={duration:.10f}"
        command.extend(("-vf", video_filter, "-af", f"apad=pad_dur={duration:.10f}", "-shortest"))
    else:
        command.extend(("-vf", video_filter))
    command.extend((
        "-c:v", "ffv1", "-level", "3",
        "-c:a", "pcm_s16le", "-ar", str(sample_rate), "-ac", str(channels),
        str(output),
    ))
    return command


def build_psxavenc_command(
    executable: Path | str,
    avi: Path | str,
    output: Path | str,
    *,
    codec: str,
    width: int,
    height: int,
    fps: str,
    sample_rate: int,
    channels: int,
    bits: int,
    disc_speed: int,
    xa_file: int,
    xa_channel: int,
    audio_after: bool = True,
) -> list[str]:
    command = [
        str(executable),
        "-t", "str",
        "-v", codec,
        "-f", str(sample_rate),
        "-b", str(bits),
        "-c", str(channels),
        "-F", str(xa_file),
        "-C", str(xa_channel),
        "-s", f"{width}x{height}",
        "-r", fps,
        "-x", str(disc_speed),
    ]
    if audio_after:
        command.append("-X")
    command.extend((str(avi), str(output)))
    return command


class AviToStrApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1020x720")
        self.minsize(760, 560)

        self.mode_var = tk.StringVar(value="file")
        self.source_var = tk.StringVar()
        self.original_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.psxavenc_var = tk.StringVar(
            value=find_program(PSXAVENC_CANDIDATES, "psxavenc.exe")
        )
        self.ffprobe_var = tk.StringVar(
            value=find_program(FFPROBE_CANDIDATES, "ffprobe.exe")
        )
        self.ffmpeg_var = tk.StringVar(
            value=find_program(FFMPEG_CANDIDATES, "ffmpeg.exe")
        )
        self.jpsxdec_var = tk.StringVar(
            value=find_program(JPSXDEC_CANDIDATES, "jpsxdec.jar")
        )
        self.java_var = tk.StringVar(value=shutil.which("java.exe") or shutil.which("java") or "java.exe")

        self.codec_var = tk.StringVar(value="v2")
        self.width_var = tk.StringVar(value="320")
        self.height_var = tk.StringVar(value="240")
        self.fps_var = tk.StringVar(value="15")
        self.sample_rate_var = tk.StringVar(value="37800")
        self.channels_var = tk.StringVar(value="2")
        self.bits_var = tk.StringVar(value="4")
        self.speed_var = tk.StringVar(value="2")
        self.xa_file_var = tk.StringVar(value="1")
        self.xa_channel_var = tk.StringVar(value="1")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.continue_var = tk.BooleanVar(value=True)
        self.probe_var = tk.BooleanVar(value=True)
        self.normalize_var = tk.BooleanVar(value=True)
        self.match_frames_var = tk.BooleanVar(value=True)
        self.audio_after_var = tk.BooleanVar(value=True)

        self.status_var = tk.StringVar(value="Selecione um AVI ou uma pasta.")
        self.summary_var = tk.StringVar(value="Nenhum AVI na fila.")
        self.jobs: list[ConversionJob] = []
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.process: subprocess.Popen | None = None

        self._load_settings()
        self._configure_style()
        self._build_ui()
        self._mode_changed()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=("Arial", 10))
        style.configure("Title.TLabel", font=("Arial", 13, "bold"))
        style.configure("Treeview", font=("Arial", 9), rowheight=22)
        style.configure("Treeview.Heading", font=("Arial", 9, "bold"))

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=8)
        main.pack(fill="both", expand=True)

        actions = ttk.Frame(main)
        actions.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(actions, text="Cancelar", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="right")
        self.convert_button = ttk.Button(actions, text="CONVERTER PARA STR", command=self._start)
        self.convert_button.pack(side="right", padx=(0, 6))
        ttk.Button(actions, text="Abrir saída", command=self._open_output).pack(
            side="right", padx=(0, 6)
        )

        ttk.Label(main, text="Conversor AVI para STR", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            main,
            text="Gera STR MDEC + XA compatível com as cutscenes do Koudelka usando psxavenc.",
        ).pack(anchor="w", pady=(1, 5))

        mode_row = ttk.Frame(main)
        mode_row.pack(fill="x")
        ttk.Radiobutton(
            mode_row, text="Um AVI", variable=self.mode_var, value="file",
            command=self._mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_row, text="Pasta de AVI (lote)", variable=self.mode_var, value="folder",
            command=self._mode_changed,
        ).pack(side="left", padx=(18, 0))
        ttk.Button(mode_row, text="Atualizar fila", command=self._refresh_jobs).pack(side="right")

        notebook = ttk.Notebook(main)
        notebook.pack(fill="x", pady=(5, 0))
        files_tab = ttk.Frame(notebook, padding=7)
        options_tab = ttk.Frame(notebook, padding=7)
        notebook.add(files_tab, text="1. Arquivos")
        notebook.add(options_tab, text="2. Parâmetros e ferramentas")

        self.source_label = ttk.Label(files_tab, text="AVI:", width=22)
        self.source_label.grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(files_tab, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", padx=5, pady=2
        )
        ttk.Button(files_tab, text="Selecionar...", command=self._browse_source).grid(
            row=0, column=2, pady=2
        )

        self.original_label = ttk.Label(files_tab, text="STR original (opcional):", width=22)
        self.original_label.grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(files_tab, textvariable=self.original_var).grid(
            row=1, column=1, sticky="ew", padx=5, pady=2
        )
        ttk.Button(files_tab, text="Selecionar...", command=self._browse_original).grid(
            row=1, column=2, pady=2
        )

        ttk.Label(files_tab, text="Pasta de saída:", width=22).grid(
            row=2, column=0, sticky="w", pady=2
        )
        ttk.Entry(files_tab, textvariable=self.output_var).grid(
            row=2, column=1, sticky="ew", padx=5, pady=2
        )
        ttk.Button(files_tab, text="Selecionar...", command=self._browse_output).grid(
            row=2, column=2, pady=2
        )
        ttk.Label(
            files_tab,
            text="O STR original é usado para comparar o tamanho. A ferramenta também tenta localizá-lo automaticamente.",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        files_tab.columnconfigure(1, weight=1)

        parameters = ttk.LabelFrame(options_tab, text="Padrão Koudelka", padding=6)
        parameters.pack(fill="x")
        fields = (
            ("Codec", self.codec_var, ("v2", "v3", "v3dc"), 8),
            ("Largura", self.width_var, None, 7),
            ("Altura", self.height_var, None, 7),
            ("FPS", self.fps_var, None, 8),
            ("Áudio Hz", self.sample_rate_var, ("37800", "18900"), 9),
            ("Canais", self.channels_var, ("2", "1"), 7),
            ("Bits XA", self.bits_var, ("4", "8"), 7),
            ("CD x", self.speed_var, ("2", "1"), 6),
            ("XA File", self.xa_file_var, None, 7),
            ("XA Canal", self.xa_channel_var, None, 7),
        )
        for index, (label, variable, values, width) in enumerate(fields):
            row, group = divmod(index, 5)
            column = group * 2
            ttk.Label(parameters, text=f"{label}:").grid(row=row, column=column, sticky="e", padx=(4, 2), pady=2)
            if values:
                widget = ttk.Combobox(
                    parameters, textvariable=variable, values=values,
                    state="readonly", width=width,
                )
            else:
                widget = ttk.Entry(parameters, textvariable=variable, width=width)
            widget.grid(row=row, column=column + 1, sticky="w", padx=(0, 8), pady=2)

        tools = ttk.LabelFrame(options_tab, text="Executáveis", padding=6)
        tools.pack(fill="x", pady=(5, 0))
        self._tool_row(tools, 0, "psxavenc.exe:", self.psxavenc_var, self._browse_psxavenc)
        self._tool_row(tools, 1, "ffprobe.exe:", self.ffprobe_var, self._browse_ffprobe)
        self._tool_row(tools, 2, "ffmpeg.exe:", self.ffmpeg_var, self._browse_ffmpeg)
        self._tool_row(tools, 3, "jpsxdec.jar:", self.jpsxdec_var, self._browse_jpsxdec)
        self._tool_row(tools, 4, "java.exe:", self.java_var, self._browse_java)

        flags = ttk.Frame(options_tab)
        flags.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(
            flags, text="Analisar AVI antes de converter", variable=self.probe_var
        ).pack(side="left")
        ttk.Checkbutton(
            flags, text="Normalizar com FFmpeg", variable=self.normalize_var
        ).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(
            flags, text="Igualar quadros ao original", variable=self.match_frames_var
        ).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(
            flags, text="Áudio depois do vídeo (-X)", variable=self.audio_after_var
        ).pack(side="left", padx=(14, 0))
        flags2 = ttk.Frame(options_tab)
        flags2.pack(fill="x", pady=(3, 0))
        ttk.Checkbutton(
            flags2, text="Substituir STR de saída existente", variable=self.overwrite_var
        ).pack(side="left")
        ttk.Checkbutton(
            flags2, text="Continuar após erro no lote", variable=self.continue_var
        ).pack(side="left", padx=(14, 0))

        queue_frame = ttk.LabelFrame(main, text="Fila de conversão", padding=5)
        queue_frame.pack(fill="both", expand=True, pady=(5, 0))
        columns = ("n", "avi", "output", "original", "status")
        self.tree = ttk.Treeview(queue_frame, columns=columns, show="headings", height=7)
        headings = {
            "n": "#", "avi": "AVI", "output": "STR de saída",
            "original": "STR original", "status": "Situação",
        }
        widths = {"n": 42, "avi": 245, "output": 210, "original": 200, "status": 105}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column != "n")
        vertical = ttk.Scrollbar(queue_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(queue_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        ttk.Label(queue_frame, textvariable=self.summary_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(3, 0)
        )
        queue_frame.rowconfigure(0, weight=1)
        queue_frame.columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(main, text="Log", padding=4)
        log_frame.pack(fill="x", pady=(5, 0))
        self.log_text = tk.Text(
            log_frame, height=6, wrap="word", font=("Consolas", 9),
            background="#171717", foreground="#e5e5e5", insertbackground="white",
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    @staticmethod
    def _tool_row(parent, row: int, label: str, variable: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label, width=17).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=5, pady=2)
        ttk.Button(parent, text="Selecionar...", command=command).grid(row=row, column=2, pady=2)
        parent.columnconfigure(1, weight=1)

    def _mode_changed(self) -> None:
        folder = self.mode_var.get() == "folder"
        self.source_label.configure(text="Pasta com AVI:" if folder else "AVI:")
        self.original_label.configure(
            text="Pasta com STR originais:" if folder else "STR original (opcional):"
        )
        self.jobs = []
        self._show_jobs()

    def _browse_source(self) -> None:
        if self.mode_var.get() == "folder":
            selected = filedialog.askdirectory(title="Selecione a pasta com os AVI")
        else:
            selected = filedialog.askopenfilename(
                title="Selecione o AVI editado",
                filetypes=(("Vídeo AVI", "*.avi *.AVI"), ("Todos", "*.*")),
            )
        if not selected:
            return
        self.source_var.set(selected)
        source = Path(selected)
        if not self.output_var.get().strip():
            base = source if source.is_dir() else source.parent
            self.output_var.set(str(base / "STR_CONVERTIDOS"))
        self._refresh_jobs()

    def _browse_original(self) -> None:
        if self.mode_var.get() == "folder":
            selected = filedialog.askdirectory(title="Selecione a pasta com os STR originais")
        else:
            selected = filedialog.askopenfilename(
                title="Selecione o STR original",
                filetypes=(("Vídeo STR", "*.str *.STR"), ("Todos", "*.*")),
            )
        if selected:
            self.original_var.set(selected)
            self._refresh_jobs()

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta de saída")
        if selected:
            self.output_var.set(selected)
            self._refresh_jobs()

    def _browse_psxavenc(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o psxavenc.exe",
            filetypes=(("psxavenc", "psxavenc.exe"), ("Executável", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.psxavenc_var.set(selected)

    def _browse_ffprobe(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o ffprobe.exe",
            filetypes=(("ffprobe", "ffprobe.exe"), ("Executável", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.ffprobe_var.set(selected)

    def _browse_ffmpeg(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o ffmpeg.exe",
            filetypes=(("ffmpeg", "ffmpeg.exe"), ("Executável", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.ffmpeg_var.set(selected)

    def _browse_jpsxdec(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o jpsxdec.jar",
            filetypes=(("Java JAR", "*.jar"), ("Todos", "*.*")),
        )
        if selected:
            self.jpsxdec_var.set(selected)

    def _browse_java(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o java.exe",
            filetypes=(("Java", "java.exe"), ("Executável", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.java_var.set(selected)

    def _validate_parameters(self) -> dict:
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            sample_rate = int(self.sample_rate_var.get())
            channels = int(self.channels_var.get())
            bits = int(self.bits_var.get())
            speed = int(self.speed_var.get())
            xa_file = int(self.xa_file_var.get())
            xa_channel = int(self.xa_channel_var.get())
        except ValueError as error:
            raise ValueError("Os parâmetros numéricos contêm um valor inválido.") from error
        if width < 16 or height < 16 or width % 16 or height % 16:
            raise ValueError("Largura e altura devem ser múltiplos de 16.")
        if sample_rate not in (18900, 37800):
            raise ValueError("A frequência XA precisa ser 18900 ou 37800 Hz.")
        if channels not in (1, 2) or bits not in (4, 8) or speed not in (1, 2):
            raise ValueError("Canais, bits XA ou velocidade do CD são inválidos.")
        if not 0 <= xa_file <= 255 or not 0 <= xa_channel <= 31:
            raise ValueError("XA File deve ser 0–255 e XA Canal deve ser 0–31.")
        fps = self.fps_var.get().strip()
        if not re.fullmatch(r"\d+(?:/\d+)?", fps):
            raise ValueError("FPS deve ser inteiro ou fração, por exemplo 15 ou 30000/1001.")
        return {
            "codec": self.codec_var.get(), "width": width, "height": height,
            "fps": fps, "sample_rate": sample_rate, "channels": channels,
            "bits": bits, "disc_speed": speed, "xa_file": xa_file,
            "xa_channel": xa_channel, "audio_after": self.audio_after_var.get(),
        }

    def _refresh_jobs(self) -> bool:
        if not self.source_var.get().strip() or not self.output_var.get().strip():
            self.jobs = []
            self._show_jobs()
            return False
        try:
            self.jobs = build_jobs(
                self.source_var.get(), self.output_var.get(),
                self.original_var.get().strip() or None,
                self.mode_var.get() == "folder",
            )
        except (OSError, ValueError) as error:
            self.jobs = []
            self._show_jobs()
            messagebox.showerror(APP_TITLE, str(error), parent=self)
            return False
        self._show_jobs()
        self.status_var.set("Fila atualizada. Confira os nomes antes de converter.")
        return True

    def _show_jobs(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, job in enumerate(self.jobs, 1):
            self.tree.insert(
                "", "end", iid=str(index - 1),
                values=(
                    index, job.relative_path, job.output.name,
                    job.original_str.name if job.original_str else "não localizado",
                    "Pronto",
                ),
            )
        originals = sum(1 for job in self.jobs if job.original_str)
        self.summary_var.set(
            f"{len(self.jobs)} AVI(s) • {originals} STR original(is) localizado(s)"
            if self.jobs else "Nenhum AVI na fila."
        )

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self._refresh_jobs():
            return
        try:
            parameters = self._validate_parameters()
            psxavenc = Path(self.psxavenc_var.get()).resolve()
            if not psxavenc.is_file():
                raise ValueError(f"psxavenc.exe não encontrado: {psxavenc}")
            ffprobe = Path(self.ffprobe_var.get()).resolve()
            if self.probe_var.get() and not ffprobe.is_file():
                raise ValueError(f"ffprobe.exe não encontrado: {ffprobe}")
            ffmpeg = Path(self.ffmpeg_var.get()).resolve()
            if self.normalize_var.get() and not ffmpeg.is_file():
                raise ValueError(f"ffmpeg.exe não encontrado: {ffmpeg}")
            jpsxdec = Path(self.jpsxdec_var.get()).resolve()
            java = Path(self.java_var.get()).resolve()
            needs_frame_check = self.match_frames_var.get() and any(
                job.original_str for job in self.jobs
            )
            if needs_frame_check and not jpsxdec.is_file():
                raise ValueError(f"jpsxdec.jar não encontrado: {jpsxdec}")
            if needs_frame_check and not java.is_file():
                discovered_java = shutil.which(self.java_var.get())
                if discovered_java:
                    java = Path(discovered_java).resolve()
                else:
                    raise ValueError(f"java.exe não encontrado: {java}")
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_TITLE, str(error), parent=self)
            return

        existing = [job.output for job in self.jobs if job.output.exists()]
        if existing and not self.overwrite_var.get():
            messagebox.showerror(
                APP_TITLE,
                "Já existem arquivos de saída. Marque a opção para substituí-los ou escolha outra pasta:\n"
                + "\n".join(str(path) for path in existing[:8]),
                parent=self,
            )
            return
        if existing and not messagebox.askyesno(
            APP_TITLE,
            f"{len(existing)} STR de saída já existe(m) e será(ão) substituído(s). Continuar?",
            parent=self,
        ):
            return

        mapping = "\n".join(f"• {job.avi.name} → {job.output.name}" for job in self.jobs[:10])
        if len(self.jobs) > 10:
            mapping += f"\n• ... e mais {len(self.jobs) - 10}"
        if not messagebox.askyesno(
            APP_TITLE,
            f"Converter {len(self.jobs)} AVI(s)?\n\n{mapping}\n\nOs AVI e STR originais não serão alterados.",
            parent=self,
        ):
            return

        self._save_settings()
        self.cancel_event.clear()
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set("Convertendo...")
        self._append_log("=" * 72)
        self._append_log(f"Início — {len(self.jobs)} arquivo(s)")
        options = {
            "jobs": list(self.jobs), "parameters": parameters,
            "psxavenc": psxavenc, "ffprobe": ffprobe,
            "ffmpeg": ffmpeg, "jpsxdec": jpsxdec, "java": java,
            "probe": self.probe_var.get(), "normalize": self.normalize_var.get(),
            "match_frames": self.match_frames_var.get(),
            "continue_on_error": self.continue_var.get(),
        }
        self.worker = threading.Thread(target=self._worker_run, args=(options,), daemon=True)
        self.worker.start()

    def _worker_run(self, options: dict) -> None:
        rows: list[dict] = []

        def run_external(command: list[str], label: str) -> tuple[str, str]:
            self.events.put(("log", f"{label}: {subprocess.list2cmdline(command)}"))
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stdout, stderr = self.process.communicate()
            returncode = self.process.returncode
            self.process = None
            if self.cancel_event.is_set():
                raise InterruptedError("Conversão cancelada.")
            if returncode != 0:
                raise RuntimeError(
                    stderr.strip() or stdout.strip()
                    or f"{label} terminou com código {returncode}."
                )
            return stdout, stderr

        for index, job in enumerate(options["jobs"], 1):
            if self.cancel_event.is_set():
                break
            self.events.put(("progress", (index - 1, len(options["jobs"]), index - 1, "Convertendo")))
            temporary = job.output.with_name(f".{job.output.stem}.parcial.STR")
            normalized = job.output.with_name(f".{job.output.stem}.normalizado.mkv")
            original_index = job.output.with_name(f".{job.output.stem}.original.idx")
            output_index = job.output.with_name(f".{job.output.stem}.novo.idx")
            work_files = (temporary, normalized, original_index, output_index)
            try:
                job.output.parent.mkdir(parents=True, exist_ok=True)
                for work_file in work_files:
                    if work_file.exists():
                        work_file.unlink()
                probe_data = None
                if options["probe"]:
                    probe_data = probe_avi(options["ffprobe"], job.avi)
                    video = probe_data["video"]
                    audio = probe_data["audio"]
                    if not audio:
                        raise RuntimeError("O AVI não contém áudio; o STR do Koudelka precisa de áudio XA.")
                    frames = video.get("nb_read_frames") or video.get("nb_frames") or "?"
                    audio_text = (
                        f"{audio.get('sample_rate', '?')} Hz, {audio.get('channels', '?')} canal(is)"
                        if audio else "sem áudio"
                    )
                    self.events.put((
                        "log",
                        f"[{index}/{len(options['jobs'])}] {job.avi.name}: "
                        f"{video.get('width', '?')}x{video.get('height', '?')}, "
                        f"{video.get('avg_frame_rate', '?')} FPS, {frames} frames, {audio_text}",
                    ))

                original_analysis = None
                if options["match_frames"] and job.original_str:
                    original_analysis = analyze_str(
                        options["java"], options["jpsxdec"], job.original_str, original_index
                    )
                    self.events.put((
                        "log",
                        f"Original: {original_analysis.get('frames') or '?'} frames, "
                        f"{original_analysis.get('width') or '?'}x{original_analysis.get('height') or '?'}.",
                    ))

                encoded_source = job.avi
                commands: list[str] = []
                if options["normalize"]:
                    normalize_command = build_ffmpeg_command(
                        options["ffmpeg"], job.avi, normalized,
                        width=options["parameters"]["width"],
                        height=options["parameters"]["height"],
                        fps=options["parameters"]["fps"],
                        sample_rate=options["parameters"]["sample_rate"],
                        channels=options["parameters"]["channels"],
                    )
                    commands.append(subprocess.list2cmdline(normalize_command))
                    run_external(normalize_command, "FFmpeg")
                    encoded_source = normalized

                command = build_psxavenc_command(
                    options["psxavenc"], encoded_source, temporary, **options["parameters"]
                )
                commands.append(subprocess.list2cmdline(command))
                run_external(command, "psxavenc")
                if not temporary.is_file():
                    raise RuntimeError("O psxavenc terminou sem criar o STR.")

                output_analysis = None
                frame_adjustment = 0
                target_frames = original_analysis.get("frames") if original_analysis else None
                if target_frames:
                    output_analysis = analyze_str(
                        options["java"], options["jpsxdec"], temporary, output_index
                    )
                    generated_frames = output_analysis.get("frames")
                    difference = target_frames - generated_frames if generated_frames else 0
                    if difference != 0 and abs(difference) <= 10 and options["normalize"]:
                        # O psxavenc normalmente retém dois quadros de vídeo para
                        # finalizar o fluxo MDEC quando o áudio termina exatamente
                        # junto com o vídeo. Alimentamos esses dois quadros de
                        # compensação, mas limitamos o áudio à duração do original.
                        input_target_frames = target_frames + 2
                        self.events.put((
                            "log",
                            f"Ajuste automático: o primeiro STR ficou com {generated_frames} frames; "
                            f"o alvo é {target_frames}. Corrigindo vídeo e áudio.",
                        ))
                        for adjustment_attempt in range(1, 4):
                            frame_adjustment = input_target_frames - target_frames
                            for path in (temporary, normalized, output_index):
                                if path.exists():
                                    path.unlink()
                            normalize_command = build_ffmpeg_command(
                                options["ffmpeg"], job.avi, normalized,
                                width=options["parameters"]["width"],
                                height=options["parameters"]["height"],
                                fps=options["parameters"]["fps"],
                                sample_rate=options["parameters"]["sample_rate"],
                                channels=options["parameters"]["channels"],
                                target_frames=input_target_frames,
                                audio_target_frames=target_frames,
                            )
                            commands.append(subprocess.list2cmdline(normalize_command))
                            run_external(
                                normalize_command,
                                f"FFmpeg (ajuste {adjustment_attempt}/3)",
                            )
                            command = build_psxavenc_command(
                                options["psxavenc"], normalized, temporary,
                                **options["parameters"],
                            )
                            commands.append(subprocess.list2cmdline(command))
                            run_external(
                                command,
                                f"psxavenc (ajuste {adjustment_attempt}/3)",
                            )
                            output_analysis = analyze_str(
                                options["java"], options["jpsxdec"], temporary, output_index
                            )
                            generated_frames = output_analysis.get("frames")
                            if generated_frames == target_frames:
                                self.events.put((
                                    "log",
                                    f"Ajuste concluído: {generated_frames} quadros.",
                                ))
                                break
                            if not generated_frames:
                                break
                            residual = target_frames - generated_frames
                            if abs(residual) > 10:
                                break
                            input_target_frames += residual
                            self.events.put((
                                "log",
                                f"Nova tentativa: resultado {generated_frames}; "
                                f"compensação alterada em {residual:+d} quadro(s).",
                            ))

                output_size = temporary.stat().st_size
                if output_size == 0 or output_size % 2336:
                    raise RuntimeError(
                        f"O STR gerado é inválido: {output_size} bytes não formam setores de 2336 bytes."
                    )
                os.replace(temporary, job.output)
                original_size = job.original_str.stat().st_size if job.original_str else None
                too_large = original_size is not None and output_size > original_size
                output_frames = output_analysis.get("frames") if output_analysis else None
                frames_differ = bool(target_frames and output_frames != target_frames)
                status = (
                    "MAIOR QUE ORIGINAL" if too_large else
                    "QUADROS DIFERENTES" if frames_differ else
                    "OK"
                )
                comparison = (
                    f" / original {original_size:,} bytes" if original_size is not None
                    else " / original não localizado"
                )
                self.events.put((
                    "log",
                    f"[{index}/{len(options['jobs'])}] {status}: {job.output} — "
                    f"{output_size:,} bytes{comparison}",
                ))
                rows.append({
                    "avi": str(job.avi), "output": str(job.output),
                    "original_str": str(job.original_str) if job.original_str else "",
                    "output_size": output_size, "original_size": original_size,
                    "status": status, "commands": commands,
                    "probe": probe_data, "original_analysis": original_analysis,
                    "output_analysis": output_analysis,
                    "frame_adjustment": frame_adjustment,
                })
                self.events.put(("item", (index - 1, status)))
                for work_file in (normalized, original_index, output_index):
                    if work_file.exists():
                        work_file.unlink()
            except InterruptedError:
                for work_file in work_files:
                    if work_file.exists():
                        try:
                            work_file.unlink()
                        except OSError:
                            pass
                break
            except Exception as error:
                self.process = None
                for work_file in work_files:
                    try:
                        if work_file.exists():
                            work_file.unlink()
                    except OSError:
                        pass
                rows.append({
                    "avi": str(job.avi), "output": str(job.output),
                    "original_str": str(job.original_str) if job.original_str else "",
                    "status": "ERRO", "error": str(error),
                })
                self.events.put(("log", f"[{index}/{len(options['jobs'])}] ERRO: {error}"))
                self.events.put(("item", (index - 1, "ERRO")))
                if not options["continue_on_error"]:
                    break

        report_path = Path(self.output_var.get()).resolve() / "relatorio_conversao_str.json"
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report = {
                "parameters": options["parameters"],
                "psxavenc": str(options["psxavenc"]),
                "ffmpeg": str(options["ffmpeg"]),
                "jpsxdec": str(options["jpsxdec"]),
                "cancelled": self.cancel_event.is_set(),
                "files": rows,
            }
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            self.events.put(("log", f"Aviso: não foi possível gravar o relatório: {error}"))
        self.events.put(("done", (rows, report_path)))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "progress":
                    current, total, item_index, status = payload
                    self.status_var.set(f"{current}/{total} — {status}")
                    if str(item_index) in self.tree.get_children():
                        values = list(self.tree.item(str(item_index), "values"))
                        values[4] = status
                        self.tree.item(str(item_index), values=values)
                elif kind == "item":
                    item_index, status = payload
                    if str(item_index) in self.tree.get_children():
                        values = list(self.tree.item(str(item_index), "values"))
                        values[4] = status
                        self.tree.item(str(item_index), values=values)
                elif kind == "done":
                    self._finish(*payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _finish(self, rows: list[dict], report_path: Path) -> None:
        self.convert_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        ok = sum(1 for row in rows if row.get("status") == "OK")
        size_warnings = sum(1 for row in rows if row.get("status") == "MAIOR QUE ORIGINAL")
        frame_warnings = sum(1 for row in rows if row.get("status") == "QUADROS DIFERENTES")
        warnings = size_warnings + frame_warnings
        errors = sum(1 for row in rows if row.get("status") == "ERRO")
        if self.cancel_event.is_set():
            state = "Cancelado"
        elif errors:
            state = f"Concluído com {errors} erro(s)"
        elif warnings:
            state = f"Concluído com {warnings} aviso(s) de tamanho"
        else:
            state = "Concluído"
        self.status_var.set(state)
        self._append_log(
            f"Resultado: {ok} OK, {size_warnings} maior(es), "
            f"{frame_warnings} com quadros diferentes, {errors} erro(s)."
        )
        self._append_log(f"Relatório: {report_path}")
        messagebox.showinfo(
            APP_TITLE,
            f"{state}\n\nOK: {ok}\nMaiores que o original: {size_warnings}\n"
            f"Quadros diferentes: {frame_warnings}\nErros: {errors}\n\nRelatório: {report_path}",
            parent=self,
        )

    def _cancel(self) -> None:
        self.cancel_event.set()
        process = self.process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        self.status_var.set("Cancelamento solicitado...")

    def _open_output(self) -> None:
        text = self.output_var.get().strip()
        if not text:
            return
        folder = Path(text)
        if not folder.exists():
            messagebox.showerror(APP_TITLE, "A pasta de saída ainda não existe.", parent=self)
            return
        try:
            os.startfile(folder)
        except OSError as error:
            messagebox.showerror(APP_TITLE, str(error), parent=self)

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.is_file():
            return
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for key, variable in (
            ("psxavenc", self.psxavenc_var),
            ("ffprobe", self.ffprobe_var),
            ("ffmpeg", self.ffmpeg_var),
            ("jpsxdec", self.jpsxdec_var),
            ("java", self.java_var),
        ):
            saved_path = data.get(key, "")
            if saved_path and Path(saved_path).is_file():
                variable.set(saved_path)
        for key, variable in (
            ("codec", self.codec_var), ("width", self.width_var),
            ("height", self.height_var), ("fps", self.fps_var),
            ("sample_rate", self.sample_rate_var), ("channels", self.channels_var),
            ("bits", self.bits_var), ("speed", self.speed_var),
            ("xa_file", self.xa_file_var), ("xa_channel", self.xa_channel_var),
        ):
            if key in data:
                variable.set(str(data[key]))
        self.probe_var.set(bool(data.get("probe", True)))
        self.normalize_var.set(bool(data.get("normalize", True)))
        self.match_frames_var.set(bool(data.get("match_frames", True)))
        self.audio_after_var.set(bool(data.get("audio_after", True)))
        self.continue_var.set(bool(data.get("continue_on_error", True)))

    def _save_settings(self) -> None:
        data = {
            "psxavenc": self.psxavenc_var.get(), "ffprobe": self.ffprobe_var.get(),
            "ffmpeg": self.ffmpeg_var.get(), "jpsxdec": self.jpsxdec_var.get(),
            "java": self.java_var.get(),
            "codec": self.codec_var.get(), "width": self.width_var.get(),
            "height": self.height_var.get(), "fps": self.fps_var.get(),
            "sample_rate": self.sample_rate_var.get(), "channels": self.channels_var.get(),
            "bits": self.bits_var.get(), "speed": self.speed_var.get(),
            "xa_file": self.xa_file_var.get(), "xa_channel": self.xa_channel_var.get(),
            "probe": self.probe_var.get(), "normalize": self.normalize_var.get(),
            "match_frames": self.match_frames_var.get(),
            "audio_after": self.audio_after_var.get(),
            "continue_on_error": self.continue_var.get(),
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                APP_TITLE, "Há uma conversão em andamento. Cancelar e fechar?", parent=self
            ):
                return
            self._cancel()
        self._save_settings()
        self.destroy()


def main() -> None:
    AviToStrApp().mainloop()


if __name__ == "__main__":
    main()
