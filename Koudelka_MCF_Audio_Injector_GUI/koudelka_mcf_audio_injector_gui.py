from __future__ import annotations

import hashlib
import os
import queue
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Koudelka MCF - Injetor de Audio STRM"
SCRIPT_DIR = Path(__file__).resolve().parent
SECTOR_SIZE = 0x800
STRM_MAGIC = b"strm"
STRM_OFFSET = 0x20
STRM_HEADER_SIZE = 0x20
ADPCM_FRAME_SIZE = 16
SAMPLES_PER_ADPCM_FRAME = 28
SPUI_ALIGNMENT = 2048


@dataclass(frozen=True)
class AudioBlock:
    stream_type: int
    channel: int
    rate: int
    payload_start: int
    payload_size: int


@dataclass(frozen=True)
class MCFLayout:
    stream_type: int
    rate: int
    payload_size: int
    frames_per_block: int
    groups: int
    required_samples: int
    left: tuple[AudioBlock, ...]
    right: tuple[AudioBlock, ...]

    @property
    def duration_seconds(self) -> float:
        return self.required_samples / self.rate

    @property
    def spui_group_stride(self) -> int:
        raw_pair_size = self.payload_size * 2
        return ((raw_pair_size + SPUI_ALIGNMENT - 1) // SPUI_ALIGNMENT) * SPUI_ALIGNMENT

    @property
    def expected_spui_size(self) -> int:
        return self.groups * self.spui_group_stride


@dataclass(frozen=True)
class WavInfo:
    channels: int
    sample_width: int
    rate: int
    frames: int

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def format_duration(seconds: float) -> str:
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes):02d}:{remainder:05.2f}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_psxavenc() -> str:
    candidates = [
        SCRIPT_DIR / "psxavenc.exe",
        SCRIPT_DIR / "psxavenc-windows" / "bin" / "psxavenc.exe",
        SCRIPT_DIR.parent / "psxavenc-windows" / "bin" / "psxavenc.exe",
        Path(
            r"C:\Users\sistemas2\Desktop\KDK\Koudelka (Disc 1)\MOVIE\psxavenc-windows\bin\psxavenc.exe"
        ),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which("psxavenc") or shutil.which("psxavenc.exe")
    return executable or ""


def parse_mcf_layout(data: bytes) -> MCFLayout:
    blocks: list[AudioBlock] = []
    position = 0
    while True:
        offset = data.find(STRM_MAGIC, position)
        if offset < 0:
            break
        sector = offset - STRM_OFFSET
        if sector >= 0 and sector % SECTOR_SIZE == 0 and offset + STRM_HEADER_SIZE <= len(data):
            header = data[offset : offset + STRM_HEADER_SIZE]
            stream_size = struct.unpack_from("<H", header, 0x12)[0]
            maximum_size = sector + SECTOR_SIZE - offset
            payload_size = stream_size - STRM_HEADER_SIZE
            if (
                STRM_HEADER_SIZE <= stream_size <= maximum_size
                and payload_size > 0
                and payload_size % ADPCM_FRAME_SIZE == 0
            ):
                blocks.append(
                    AudioBlock(
                        stream_type=header[6],
                        channel=header[7],
                        rate=struct.unpack_from("<H", header, 0x10)[0],
                        payload_start=offset + STRM_HEADER_SIZE,
                        payload_size=payload_size,
                    )
                )
        position = offset + 4

    if not blocks:
        raise ValueError(
            "Nenhum audio STRM foi encontrado. Esta ferramenta e para os MCFs de cenas SCxx; "
            "o ENDING.MCF usa audio XA."
        )

    chosen_type: int | None = None
    for stream_type in sorted({block.stream_type for block in blocks}):
        channels = {block.channel for block in blocks if block.stream_type == stream_type}
        if 0 in channels and 1 in channels:
            chosen_type = stream_type
            break
    if chosen_type is None:
        raise ValueError("Foram encontrados blocos STRM, mas nao um par estereo 0/1.")

    left = tuple(
        block for block in blocks if block.stream_type == chosen_type and block.channel == 0
    )
    right = tuple(
        block for block in blocks if block.stream_type == chosen_type and block.channel == 1
    )
    if len(left) != len(right):
        raise ValueError(f"Quantidade diferente de blocos L/R: {len(left)} / {len(right)}.")

    payload_sizes = {block.payload_size for block in left + right}
    rates = {block.rate for block in left + right if block.rate}
    if len(payload_sizes) != 1:
        raise ValueError(f"Os blocos STRM possuem tamanhos diferentes: {sorted(payload_sizes)}.")
    if len(rates) != 1:
        raise ValueError(f"Os blocos STRM possuem frequencias diferentes: {sorted(rates)}.")

    payload_size = payload_sizes.pop()
    rate = rates.pop() if rates else 44100
    frames_per_block = payload_size // ADPCM_FRAME_SIZE
    groups = len(left)
    required_samples = groups * frames_per_block * SAMPLES_PER_ADPCM_FRAME
    return MCFLayout(
        stream_type=chosen_type,
        rate=rate,
        payload_size=payload_size,
        frames_per_block=frames_per_block,
        groups=groups,
        required_samples=required_samples,
        left=left,
        right=right,
    )


def read_wav_info(path: Path) -> WavInfo:
    try:
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise ValueError("O WAV precisa ser PCM sem compressao.")
            return WavInfo(
                channels=wav_file.getnchannels(),
                sample_width=wav_file.getsampwidth(),
                rate=wav_file.getframerate(),
                frames=wav_file.getnframes(),
            )
    except wave.Error as error:
        raise ValueError(f"WAV invalido ou nao suportado: {error}") from error


def prepare_wav(
    source: Path,
    destination: Path,
    layout: MCFLayout,
    pad_short: bool,
    cancel_event: threading.Event,
) -> tuple[WavInfo, int]:
    info = read_wav_info(source)
    if info.channels != 2:
        raise ValueError(f"O WAV precisa ser estereo; encontrado: {info.channels} canal(is).")
    if info.sample_width != 2:
        raise ValueError(
            f"O WAV precisa ser PCM 16-bit; encontrado: {info.sample_width * 8} bits."
        )
    if info.rate != layout.rate:
        raise ValueError(
            f"O WAV precisa ter {layout.rate} Hz; encontrado: {info.rate} Hz."
        )
    if info.frames > layout.required_samples:
        extra = info.frames - layout.required_samples
        raise ValueError(
            f"O WAV e maior que a capacidade do MCF por {extra} amostras "
            f"({extra / layout.rate:.3f} s). Reduza sua duracao."
        )
    missing = layout.required_samples - info.frames
    if missing and not pad_short:
        raise ValueError(
            f"O WAV e menor que o MCF por {missing} amostras ({missing / layout.rate:.3f} s). "
            "Ative a opcao de completar com silencio."
        )

    with wave.open(str(source), "rb") as source_wav, wave.open(str(destination), "wb") as output_wav:
        output_wav.setnchannels(2)
        output_wav.setsampwidth(2)
        output_wav.setframerate(layout.rate)
        remaining = info.frames
        while remaining:
            if cancel_event.is_set():
                raise InterruptedError("Operacao cancelada.")
            count = min(remaining, 65536)
            chunk = source_wav.readframes(count)
            output_wav.writeframesraw(chunk)
            remaining -= count
        silence_frames = missing
        silence_chunk = b"\x00" * (65536 * 4)
        while silence_frames:
            if cancel_event.is_set():
                raise InterruptedError("Operacao cancelada.")
            count = min(silence_frames, 65536)
            output_wav.writeframesraw(silence_chunk[: count * 4])
            silence_frames -= count
    return info, missing


def run_psxavenc(
    executable: Path,
    wav_path: Path,
    spui_path: Path,
    layout: MCFLayout,
    cancel_event: threading.Event,
    process_callback,
    log_callback,
) -> None:
    command = [
        str(executable),
        "-t",
        "spui",
        "-f",
        str(layout.rate),
        "-c",
        "2",
        "-i",
        str(layout.payload_size),
        "-a",
        str(SPUI_ALIGNMENT),
        "-n",
        "-D",
        str(wav_path),
        str(spui_path),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )
    process_callback(process)
    try:
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.strip()
            if clean:
                log_callback(clean)
            if cancel_event.is_set() and process.poll() is None:
                process.terminate()
        return_code = process.wait()
    finally:
        process_callback(None)
    if cancel_event.is_set():
        raise InterruptedError("Operacao cancelada.")
    if return_code != 0:
        raise RuntimeError(f"O psxavenc terminou com codigo {return_code}.")
    if not spui_path.is_file():
        raise RuntimeError("O psxavenc nao gerou o arquivo SPUI.")
    actual_size = spui_path.stat().st_size
    if actual_size != layout.expected_spui_size:
        raise RuntimeError(
            f"Tamanho SPUI inesperado: {actual_size} bytes; esperado: "
            f"{layout.expected_spui_size} bytes."
        )


def inject_spui(
    original_data: bytes,
    spui: bytes,
    layout: MCFLayout,
    cancel_event: threading.Event,
    progress_callback,
) -> tuple[bytes, int]:
    if len(spui) != layout.expected_spui_size:
        raise ValueError(
            f"SPUI com {len(spui)} bytes; esperado: {layout.expected_spui_size}."
        )
    output = bytearray(original_data)
    changed_bytes = 0
    for index, (left_block, right_block) in enumerate(zip(layout.left, layout.right)):
        if cancel_event.is_set():
            raise InterruptedError("Operacao cancelada.")
        group_start = index * layout.spui_group_stride
        left_payload = spui[group_start : group_start + layout.payload_size]
        right_start = group_start + layout.payload_size
        right_payload = spui[right_start : right_start + layout.payload_size]

        for block, new_payload in ((left_block, left_payload), (right_block, right_payload)):
            for frame_index in range(layout.frames_per_block):
                destination = block.payload_start + frame_index * ADPCM_FRAME_SIZE
                source = frame_index * ADPCM_FRAME_SIZE
                # Mantem o segundo byte/flag original (loop start/end/streaming).
                if output[destination] != new_payload[source]:
                    changed_bytes += 1
                output[destination] = new_payload[source]
                old_data = output[destination + 2 : destination + ADPCM_FRAME_SIZE]
                new_data = new_payload[source + 2 : source + ADPCM_FRAME_SIZE]
                changed_bytes += sum(old != new for old, new in zip(old_data, new_data))
                output[destination + 2 : destination + ADPCM_FRAME_SIZE] = new_data
        if index % 50 == 0 or index + 1 == layout.groups:
            progress_callback(index + 1, layout.groups)
    return bytes(output), changed_bytes


def validate_output(original: bytes, output: bytes, layout: MCFLayout) -> None:
    if len(original) != len(output):
        raise RuntimeError("O MCF novo ficou com tamanho diferente do original.")
    parsed = parse_mcf_layout(output)
    if (
        parsed.groups != layout.groups
        or parsed.payload_size != layout.payload_size
        or parsed.rate != layout.rate
    ):
        raise RuntimeError("A estrutura STRM mudou depois da injecao.")
    for original_block, output_block in zip(layout.left + layout.right, parsed.left + parsed.right):
        for frame_index in range(layout.frames_per_block):
            flag_offset_original = (
                original_block.payload_start + frame_index * ADPCM_FRAME_SIZE + 1
            )
            flag_offset_output = output_block.payload_start + frame_index * ADPCM_FRAME_SIZE + 1
            if original[flag_offset_original] != output[flag_offset_output]:
                raise RuntimeError("Uma flag ADPCM original foi alterada.")


def write_report(
    report_path: Path,
    original_mcf: Path,
    edited_wav: Path,
    output_mcf: Path,
    layout: MCFLayout,
    wav_info: WavInfo,
    padded_samples: int,
    changed_bytes: int,
    elapsed: float,
) -> None:
    report = f"""Koudelka MCF - Relatorio de injecao de audio
================================================
MCF original: {original_mcf}
WAV editado:  {edited_wav}
MCF gerado:   {output_mcf}

Formato: SPU-ADPCM STRM
Tipo STRM: 0x{layout.stream_type:02X}
Frequencia: {layout.rate} Hz
Canais: 2 (estereo)
Blocos por canal: {layout.groups}
Frames ADPCM por bloco: {layout.frames_per_block}
Bytes de audio por canal/bloco: {layout.payload_size}
Capacidade: {layout.required_samples} amostras/canal ({format_duration(layout.duration_seconds)})
WAV recebido: {wav_info.frames} amostras/canal ({format_duration(wav_info.duration_seconds)})
Silencio acrescentado: {padded_samples} amostras ({padded_samples / layout.rate:.3f} s)
Bytes efetivamente diferentes: {changed_bytes}
Tamanho original: {original_mcf.stat().st_size}
Tamanho gerado: {output_mcf.stat().st_size}
SHA-256 original: {sha256_file(original_mcf)}
SHA-256 gerado:   {sha256_file(output_mcf)}
Tempo de processamento: {elapsed:.2f} s

VALIDACOES: OK
- tamanho do MCF preservado
- estrutura e cabecalhos STRM preservados
- flags ADPCM originais preservadas
- preenchimento fora dos payloads preservado
"""
    report_path.write_text(report, encoding="utf-8")


class AudioInjectorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x700")
        self.root.minsize(780, 600)

        self.mcf_var = tk.StringVar()
        self.wav_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.psxavenc_var = tk.StringVar(value=find_psxavenc())
        self.pad_short_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Selecione o MCF original e o WAV editado.")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.process: subprocess.Popen[str] | None = None

        self._build_ui()
        self.root.after(100, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(6, weight=1)

        ttk.Label(outer, text="MCF original:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(outer, textvariable=self.mcf_var).grid(
            row=0, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(outer, text="Selecionar...", command=self._choose_mcf).grid(
            row=0, column=2, sticky="ew", pady=4
        )

        ttk.Label(outer, text="WAV editado:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(outer, textvariable=self.wav_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(outer, text="Selecionar...", command=self._choose_wav).grid(
            row=1, column=2, sticky="ew", pady=4
        )

        ttk.Label(outer, text="Novo MCF:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(outer, textvariable=self.output_var).grid(
            row=2, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(outer, text="Salvar como...", command=self._choose_output).grid(
            row=2, column=2, sticky="ew", pady=4
        )

        tools = ttk.LabelFrame(outer, text="Codificador", padding=8)
        tools.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        tools.columnconfigure(1, weight=1)
        ttk.Label(tools, text="psxavenc.exe:").grid(row=0, column=0, sticky="w")
        ttk.Entry(tools, textvariable=self.psxavenc_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(tools, text="Localizar...", command=self._choose_psxavenc).grid(
            row=0, column=2
        )

        options = ttk.LabelFrame(outer, text="Seguranca e sincronizacao", padding=8)
        options.grid(row=4, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Checkbutton(
            options,
            text="Completar WAV mais curto com silencio ate a duracao exata do MCF",
            variable=self.pad_short_var,
        ).pack(anchor="w")
        ttk.Label(
            options,
            text=(
                "WAVs maiores sao recusados. Requisitos: PCM 16-bit, estereo e a mesma "
                "frequencia do MCF (normalmente 44.100 Hz)."
            ),
        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(
            options,
            text="Esta ferramenta e para cenas SCxx com STRM; nao use no ENDING.MCF (audio XA).",
            foreground="#9a3d00",
        ).pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        self.start_button = ttk.Button(
            actions, text="Gerar MCF com audio editado", command=self._start
        )
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(
            actions, text="Cancelar", state="disabled", command=self._cancel
        )
        self.cancel_button.pack(side="left", padx=6)
        ttk.Button(actions, text="Abrir pasta de saida", command=self._open_output).pack(
            side="right"
        )

        log_frame = ttk.LabelFrame(outer, text="Andamento e validacoes", padding=6)
        log_frame.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=4)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", state="disabled", height=17)
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        ttk.Label(outer, textvariable=self.status_var).grid(
            row=8, column=0, columnspan=3, sticky="w"
        )

    def _choose_mcf(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o MCF original",
            filetypes=[("Arquivos MCF", "*.MCF"), ("Todos", "*.*")],
        )
        if selected:
            path = Path(selected)
            self.mcf_var.set(str(path))
            self.output_var.set(str(path.with_name(f"{path.stem}_AUDIO_EDITADO.MCF")))

    def _choose_wav(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o WAV editado",
            filetypes=[("Audio WAV", "*.wav"), ("Todos", "*.*")],
        )
        if selected:
            self.wav_var.set(selected)

    def _choose_output(self) -> None:
        initial = self.output_var.get().strip()
        selected = filedialog.asksaveasfilename(
            title="Salvar novo MCF",
            defaultextension=".MCF",
            initialfile=Path(initial).name if initial else "AUDIO_EDITADO.MCF",
            filetypes=[("Arquivos MCF", "*.MCF"), ("Todos", "*.*")],
        )
        if selected:
            self.output_var.set(selected)

    def _choose_psxavenc(self) -> None:
        selected = filedialog.askopenfilename(
            title="Localize psxavenc.exe",
            filetypes=[("psxavenc", "psxavenc.exe"), ("Executaveis", "*.exe")],
        )
        if selected:
            self.psxavenc_var.set(selected)

    def _validate_paths(self) -> tuple[Path, Path, Path, Path]:
        mcf = Path(self.mcf_var.get().strip())
        wav = Path(self.wav_var.get().strip())
        output_text = self.output_var.get().strip()
        output = Path(output_text) if output_text else Path()
        encoder = Path(self.psxavenc_var.get().strip())
        if not mcf.is_file():
            raise ValueError("Selecione um MCF original valido.")
        if mcf.suffix.lower() != ".mcf":
            raise ValueError("O arquivo original precisa ter extensao .MCF.")
        if not wav.is_file():
            raise ValueError("Selecione um WAV editado valido.")
        if not output_text:
            raise ValueError("Selecione o caminho do novo MCF.")
        if output.suffix.lower() != ".mcf":
            raise ValueError("O arquivo de saida precisa ter extensao .MCF.")
        if mcf.resolve() == output.resolve():
            raise ValueError("O novo MCF nao pode sobrescrever diretamente o MCF original.")
        if not encoder.is_file():
            raise ValueError("psxavenc.exe nao foi encontrado. Use o botao Localizar.")
        return mcf, wav, output, encoder

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            paths = self._validate_paths()
        except ValueError as error:
            messagebox.showerror(APP_TITLE, str(error))
            return
        output = paths[2]
        if output.exists() and not messagebox.askyesno(
            APP_TITLE, f"O arquivo ja existe:\n{output}\n\nDeseja substitui-lo?"
        ):
            return

        self.cancel_event.clear()
        self._clear_log()
        self.progress.configure(value=0)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set("Analisando MCF e WAV...")
        self.worker = threading.Thread(
            target=self._run,
            args=(*paths, bool(self.pad_short_var.get())),
            daemon=True,
        )
        self.worker.start()

    def _run(
        self,
        mcf_path: Path,
        wav_path: Path,
        output_path: Path,
        encoder_path: Path,
        pad_short: bool,
    ) -> None:
        started = time.time()
        try:
            original_data = mcf_path.read_bytes()
            layout = parse_mcf_layout(original_data)
            self._emit_log(
                f"STRM: {layout.groups} blocos/canal, {layout.frames_per_block} frames/bloco, "
                f"{layout.payload_size} bytes, {layout.rate} Hz."
            )
            self._emit_log(
                f"Capacidade: {layout.required_samples} amostras/canal "
                f"({format_duration(layout.duration_seconds)})."
            )
            self.events.put(("progress", 5))

            with tempfile.TemporaryDirectory(prefix="koudelka_mcf_inject_") as temporary:
                temporary_dir = Path(temporary)
                prepared_wav = temporary_dir / "audio_preparado.wav"
                spui_path = temporary_dir / "audio.spui"
                wav_info, padded_samples = prepare_wav(
                    wav_path,
                    prepared_wav,
                    layout,
                    pad_short,
                    self.cancel_event,
                )
                self._emit_log(
                    f"WAV: {wav_info.frames} amostras/canal "
                    f"({format_duration(wav_info.duration_seconds)})."
                )
                if padded_samples:
                    self._emit_log(
                        f"Completado com {padded_samples} amostras de silencio "
                        f"({padded_samples / layout.rate:.3f} s)."
                    )
                self.events.put(("progress", 15))
                self.events.put(("status", "Codificando WAV para SPU-ADPCM..."))

                run_psxavenc(
                    encoder_path,
                    prepared_wav,
                    spui_path,
                    layout,
                    self.cancel_event,
                    self._set_process,
                    self._emit_log,
                )
                self._emit_log(f"SPUI validado: {spui_path.stat().st_size} bytes.")
                self.events.put(("progress", 35))
                self.events.put(("status", "Injetando nos blocos STRM..."))

                spui = spui_path.read_bytes()

                def injection_progress(done: int, total: int) -> None:
                    percent = 35 + int((done / total) * 50)
                    self.events.put(("progress", percent))
                    if done % 250 == 0 or done == total:
                        self._emit_log(f"Blocos injetados: {done}/{total}")

                output_data, changed_bytes = inject_spui(
                    original_data,
                    spui,
                    layout,
                    self.cancel_event,
                    injection_progress,
                )
                validate_output(original_data, output_data, layout)
                self.events.put(("progress", 90))
                self.events.put(("status", "Salvando e verificando o novo MCF..."))

                output_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_output = output_path.with_name(f".{output_path.name}.tmp")
                try:
                    temporary_output.write_bytes(output_data)
                    if temporary_output.stat().st_size != mcf_path.stat().st_size:
                        raise RuntimeError("Falha na verificacao do tamanho gravado.")
                    os.replace(temporary_output, output_path)
                finally:
                    if temporary_output.exists():
                        temporary_output.unlink()

                report_path = output_path.with_suffix(".audio_inject_report.txt")
                write_report(
                    report_path,
                    mcf_path,
                    wav_path,
                    output_path,
                    layout,
                    wav_info,
                    padded_samples,
                    changed_bytes,
                    time.time() - started,
                )

            self._emit_log("VALIDACAO OK: tamanho, estrutura, flags e preenchimento preservados.")
            self._emit_log(f"MCF criado: {output_path}")
            self.events.put(("progress", 100))
            self.events.put(("done", (output_path, report_path)))
        except InterruptedError:
            self.events.put(("cancelled", None))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _set_process(self, process: subprocess.Popen[str] | None) -> None:
        self.process = process

    def _emit_log(self, message: str) -> None:
        self.events.put(("log", message + "\n"))

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Cancelando...")
        process = self.process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _poll_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(value))
                elif kind == "status":
                    self.status_var.set(str(value))
                elif kind == "progress":
                    self.progress.configure(value=int(value))
                elif kind == "done":
                    self._finish_controls()
                    output_path, report_path = value  # type: ignore[misc]
                    self.status_var.set("MCF gerado e validado com sucesso.")
                    messagebox.showinfo(
                        APP_TITLE,
                        f"MCF gerado com sucesso:\n{output_path}\n\nRelatorio:\n{report_path}",
                    )
                elif kind == "cancelled":
                    self._finish_controls()
                    self.status_var.set("Operacao cancelada.")
                    self._append_log("Operacao cancelada. O MCF original nao foi alterado.\n")
                elif kind == "error":
                    self._finish_controls()
                    self.status_var.set("Falha na geracao do MCF.")
                    self._append_log(f"ERRO: {value}\n")
                    messagebox.showerror(APP_TITLE, str(value))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish_controls(self) -> None:
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.process = None

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open_output(self) -> None:
        output = Path(self.output_var.get().strip())
        folder = output.parent
        if not folder.exists():
            messagebox.showwarning(APP_TITLE, "A pasta de saida ainda nao existe.")
            return
        os.startfile(folder)  # type: ignore[attr-defined]

    def _close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_TITLE, "Ha uma operacao em andamento. Cancelar e sair?"):
                return
            self._cancel()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    AudioInjectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
