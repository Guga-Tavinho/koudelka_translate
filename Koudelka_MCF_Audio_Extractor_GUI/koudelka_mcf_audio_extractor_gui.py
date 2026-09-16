from __future__ import annotations

import csv
import os
import queue
import shutil
import struct
import subprocess
import threading
import time
import wave
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Koudelka MCF - Extrator de Audio XA"
SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ExtractionJob:
    source: Path
    output_dir: Path


SECTOR_SIZE = 0x800
STRM_MAGIC = b"strm"
STRM_IN_SECTOR = 0x20
STRM_HEADER_SIZE = 0x20
FRAME_SIZE = 16
SPU_FILTERS = [(0, 0), (60, 0), (115, -52), (98, -55), (122, -60)]


def clamp16(value: int) -> int:
    return max(-32768, min(32767, int(value)))


def find_strm_blocks(data: bytes) -> list[tuple[int, int, int, bytes]]:
    blocks: list[tuple[int, int, int, bytes]] = []
    position = 0
    while True:
        offset = data.find(STRM_MAGIC, position)
        if offset < 0:
            break
        sector = offset - STRM_IN_SECTOR
        if sector >= 0 and sector % SECTOR_SIZE == 0 and offset + STRM_HEADER_SIZE <= len(data):
            header = data[offset : offset + STRM_HEADER_SIZE]
            stream_type = header[6]
            channel = header[7]
            rate = struct.unpack_from("<H", header, 0x10)[0]
            # O campo +0x12 informa o tamanho total do fluxo neste setor:
            # 0x20 bytes de cabecalho + 0x690 bytes (105 frames) de ADPCM.
            # O restante ate o fim do setor e preenchimento e nao pode ser
            # decodificado, pois criaria uma pausa periodica a cada bloco.
            stream_size = struct.unpack_from("<H", header, 0x12)[0]
            maximum_size = sector + SECTOR_SIZE - offset
            if (
                STRM_HEADER_SIZE <= stream_size <= maximum_size
                and (stream_size - STRM_HEADER_SIZE) % FRAME_SIZE == 0
            ):
                payload_start = offset + STRM_HEADER_SIZE
                payload_end = offset + stream_size
                payload = data[payload_start:payload_end]
                blocks.append((stream_type, channel, rate, payload))
        position = offset + 4
    return blocks


def decode_spu_payload(payload: bytes, state: list[int]) -> list[int]:
    samples: list[int] = []
    usable = len(payload) - (len(payload) % FRAME_SIZE)
    sample_1, sample_2 = state
    for frame_offset in range(0, usable, FRAME_SIZE):
        frame = payload[frame_offset : frame_offset + FRAME_SIZE]
        parameter = frame[0]
        shift = min(parameter & 0x0F, 12)
        filter_index = (parameter >> 4) & 0x0F
        if filter_index >= len(SPU_FILTERS):
            filter_index = 0
        filter_0, filter_1 = SPU_FILTERS[filter_index]
        for byte in frame[2:16]:
            # O MCF do Koudelka usa a ordem low-high confirmada nos testes anteriores.
            for nibble in (byte & 0x0F, byte >> 4):
                signed = nibble - 16 if nibble >= 8 else nibble
                sample = (signed << 12) >> shift
                sample += ((sample_1 * filter_0) + (sample_2 * filter_1) + 32) >> 6
                sample = clamp16(sample)
                samples.append(sample)
                sample_2, sample_1 = sample_1, sample
    state[:] = [sample_1, sample_2]
    return samples


def extract_koudelka_strm(
    source: Path,
    output_dir: Path,
    volume: int,
    cancel_event: threading.Event,
) -> tuple[Path, int, int] | None:
    data = source.read_bytes()
    blocks = find_strm_blocks(data)
    if not blocks:
        return None

    chosen_type: int | None = None
    for stream_type in sorted({block[0] for block in blocks}):
        channels = {block[1] for block in blocks if block[0] == stream_type}
        if 0 in channels and 1 in channels:
            chosen_type = stream_type
            break
    if chosen_type is None:
        raise ValueError("Foram encontrados blocos STRM, mas nao um par estereo 0/1.")

    selected = [block for block in blocks if block[0] == chosen_type]
    left = [block[3] for block in selected if block[1] == 0]
    right = [block[3] for block in selected if block[1] == 1]
    pair_count = min(len(left), len(right))
    if pair_count == 0:
        raise ValueError("O fluxo STRM nao contem pares de canais de audio.")
    rates = [block[2] for block in selected if block[2]]
    rate = Counter(rates).most_common(1)[0][0] if rates else 44100

    wav_path = output_dir / f"{source.stem}_STRM_lowhigh.wav"
    left_state = [0, 0]
    right_state = [0, 0]
    written_frames = 0
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        for left_payload, right_payload in zip(left[:pair_count], right[:pair_count]):
            if cancel_event.is_set():
                break
            left_pcm = decode_spu_payload(left_payload, left_state)
            right_pcm = decode_spu_payload(right_payload, right_state)
            count = min(len(left_pcm), len(right_pcm))
            pcm = bytearray(count * 4)
            cursor = 0
            for left_sample, right_sample in zip(left_pcm[:count], right_pcm[:count]):
                if volume != 100:
                    left_sample = clamp16(left_sample * volume // 100)
                    right_sample = clamp16(right_sample * volume // 100)
                struct.pack_into("<hh", pcm, cursor, left_sample, right_sample)
                cursor += 4
            wav_file.writeframesraw(pcm)
            written_frames += count
    return wav_path, rate, written_frames


def find_java() -> str:
    java = shutil.which("java") or shutil.which("java.exe")
    return java or ""


def find_jpsxdec() -> str:
    candidates = [
        SCRIPT_DIR / "jpsxdec.jar",
        SCRIPT_DIR / "jpsxdec_v2.1-beta" / "jpsxdec.jar",
        SCRIPT_DIR.parent / "jpsxdec_v2.1-beta" / "jpsxdec.jar",
        Path(r"C:\Users\sistemas2\Desktop\KDK\Tools\jpsxdec_v2.1-beta\jpsxdec.jar"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def unique_output_dir(path: Path) -> Path:
    if not path.exists() or not any(path.iterdir()):
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.name}_{index}")
        if not candidate.exists() or not any(candidate.iterdir()):
            return candidate
        index += 1


def wav_information(path: Path) -> tuple[str, str, str]:
    try:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            rate = wav_file.getframerate()
            frames = wav_file.getnframes()
            duration = frames / rate if rate else 0.0
        minutes, seconds = divmod(duration, 60)
        return (
            f"{int(minutes):02d}:{seconds:05.2f}",
            str(rate),
            "estereo" if channels == 2 else f"{channels} canal(is)",
        )
    except (wave.Error, OSError):
        return "", "", ""


class AudioExtractorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("880x680")
        self.root.minsize(760, 580)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.jar_var = tk.StringVar(value=find_jpsxdec())
        self.java_var = tk.StringVar(value=find_java())
        self.recursive_var = tk.BooleanVar(value=True)
        self.volume_var = tk.IntVar(value=100)
        self.status_var = tk.StringVar(value="Selecione um arquivo .MCF ou uma pasta.")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.process: subprocess.Popen[str] | None = None
        self.results: list[dict[str, str]] = []

        self._build_ui()
        self.root.after(100, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(5, weight=1)

        ttk.Label(outer, text="Origem:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(outer, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", padx=8, pady=4
        )
        source_buttons = ttk.Frame(outer)
        source_buttons.grid(row=0, column=2, sticky="e")
        ttk.Button(source_buttons, text="Arquivo MCF...", command=self._choose_file).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(source_buttons, text="Pasta...", command=self._choose_folder).pack(side="left")

        ttk.Label(outer, text="Saida:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(outer, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=4
        )
        ttk.Button(outer, text="Selecionar...", command=self._choose_output).grid(
            row=1, column=2, sticky="ew", pady=4
        )

        options = ttk.LabelFrame(outer, text="Opcoes", padding=8)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Checkbutton(
            options,
            text="Procurar .MCF nas subpastas",
            variable=self.recursive_var,
        ).pack(side="left")
        ttk.Label(options, text="Volume:").pack(side="left", padx=(24, 4))
        ttk.Spinbox(options, from_=0, to=100, width=5, textvariable=self.volume_var).pack(
            side="left"
        )
        ttk.Label(options, text="%   Formato: WAV").pack(side="left", padx=(2, 0))

        tools = ttk.LabelFrame(outer, text="Decodificador", padding=8)
        tools.grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
        tools.columnconfigure(1, weight=1)
        ttk.Label(tools, text="jPSXdec:").grid(row=0, column=0, sticky="w")
        ttk.Entry(tools, textvariable=self.jar_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(tools, text="Localizar...", command=self._choose_jar).grid(row=0, column=2)
        ttk.Label(tools, text="Java:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(tools, textvariable=self.java_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=(6, 0)
        )
        ttk.Button(tools, text="Localizar...", command=self._choose_java).grid(
            row=1, column=2, pady=(6, 0)
        )

        action = ttk.Frame(outer)
        action.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        self.start_button = ttk.Button(action, text="Extrair audios", command=self._start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(
            action, text="Cancelar", command=self._cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=6)
        self.open_button = ttk.Button(
            action, text="Abrir pasta de saida", command=self._open_output
        )
        self.open_button.pack(side="right")

        log_frame = ttk.LabelFrame(outer, text="Andamento", padding=6)
        log_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=4)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", state="disabled", height=16)
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        ttk.Label(outer, textvariable=self.status_var).grid(
            row=7, column=0, columnspan=3, sticky="w"
        )

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione um MCF", filetypes=[("Arquivos MCF", "*.MCF"), ("Todos", "*.*")]
        )
        if selected:
            source = Path(selected)
            self.source_var.set(str(source))
            self.output_var.set(str(source.parent / f"{source.stem}_AUDIOS_EXTRAIDOS"))

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta que contem os MCFs")
        if selected:
            source = Path(selected)
            self.source_var.set(str(source))
            self.output_var.set(str(source.parent / f"{source.name}_AUDIOS_EXTRAIDOS"))

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Selecione a pasta de saida")
        if selected:
            self.output_var.set(selected)

    def _choose_jar(self) -> None:
        selected = filedialog.askopenfilename(
            title="Localize jpsxdec.jar", filetypes=[("Java JAR", "*.jar"), ("Todos", "*.*")]
        )
        if selected:
            self.jar_var.set(selected)

    def _choose_java(self) -> None:
        selected = filedialog.askopenfilename(
            title="Localize java.exe", filetypes=[("Java", "java.exe"), ("Executaveis", "*.exe")]
        )
        if selected:
            self.java_var.set(selected)

    def _collect_jobs(self) -> list[ExtractionJob]:
        source = Path(self.source_var.get().strip())
        output_root = Path(self.output_var.get().strip())
        if not source.exists():
            raise ValueError("A origem selecionada nao existe.")
        if not self.output_var.get().strip():
            raise ValueError("Selecione a pasta de saida.")

        if source.is_file():
            if source.suffix.lower() != ".mcf":
                raise ValueError("O arquivo selecionado nao possui extensao .MCF.")
            return [ExtractionJob(source, unique_output_dir(output_root))]

        pattern = "**/*.MCF" if self.recursive_var.get() else "*.MCF"
        files = sorted(source.glob(pattern), key=lambda path: str(path).lower())
        if not files:
            # Em sistemas sensiveis a maiusculas, inclui tambem a extensao minuscula.
            lower_pattern = "**/*.mcf" if self.recursive_var.get() else "*.mcf"
            files = sorted(source.glob(lower_pattern), key=lambda path: str(path).lower())
        if not files:
            raise ValueError("Nenhum arquivo .MCF foi encontrado.")

        jobs: list[ExtractionJob] = []
        for mcf in files:
            relative_parent = mcf.parent.relative_to(source)
            destination = output_root / relative_parent / f"{mcf.stem}_audios"
            jobs.append(ExtractionJob(mcf, unique_output_dir(destination)))
        return jobs

    def _validate(self) -> list[ExtractionJob]:
        try:
            volume = int(self.volume_var.get())
        except (tk.TclError, ValueError) as error:
            raise ValueError("O volume deve ser um numero entre 0 e 100.") from error
        if not 0 <= volume <= 100:
            raise ValueError("O volume deve estar entre 0 e 100.")
        return self._collect_jobs()

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            jobs = self._validate()
        except ValueError as error:
            messagebox.showerror(APP_TITLE, str(error))
            return

        self.cancel_event.clear()
        self.results.clear()
        self.progress.configure(maximum=len(jobs), value=0)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set(f"Preparando {len(jobs)} arquivo(s)...")
        self._clear_log()
        java = self.java_var.get().strip()
        jar = self.jar_var.get().strip()
        volume = str(int(self.volume_var.get()))
        output_root = Path(self.output_var.get().strip())
        self.worker = threading.Thread(
            target=self._run_jobs,
            args=(jobs, java, jar, volume, output_root),
            daemon=True,
        )
        self.worker.start()

    def _run_jobs(
        self,
        jobs: list[ExtractionJob],
        java: str,
        jar: str,
        volume: str,
        output_root: Path,
    ) -> None:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        for index, job in enumerate(jobs, start=1):
            if self.cancel_event.is_set():
                break
            job.output_dir.mkdir(parents=True, exist_ok=True)
            self.events.put(("status", f"Extraindo {index}/{len(jobs)}: {job.source.name}"))
            self.events.put(("log", f"\n[{index}/{len(jobs)}] {job.source}\n"))
            command = [
                java,
                "-jar",
                jar,
                "-f",
                str(job.source),
                "-all",
                "audio",
                "-audfmt",
                "wav",
                "-vol",
                volume,
            ]
            output_lines: list[str] = []
            return_code = -1
            codec = ""
            started = time.time()
            try:
                strm_result = extract_koudelka_strm(
                    job.source, job.output_dir, int(volume), self.cancel_event
                )
                if strm_result is not None:
                    wav_path, rate, frames = strm_result
                    codec = "SPU-ADPCM STRM"
                    return_code = 0
                    message = (
                        f"Fluxo Koudelka STRM detectado: {rate} Hz, estereo, "
                        f"{frames} amostras/canal -> {wav_path.name}\n"
                    )
                    output_lines.append(message)
                    self.events.put(("log", message))
                else:
                    if not jar or not Path(jar).is_file():
                        raise OSError(
                            "Este MCF nao usa STRM e o jpsxdec.jar nao foi encontrado. "
                            "Localize o JAR na interface."
                        )
                    if not java or (("\\" in java or "/" in java) and not Path(java).is_file()):
                        raise OSError(
                            "Este MCF requer o jPSXdec, mas o Java nao foi encontrado."
                        )
                    codec = "CD-ROM XA"
                    self.process = subprocess.Popen(
                        command,
                        cwd=job.output_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                        creationflags=creationflags,
                    )
                    assert self.process.stdout is not None
                    for line in self.process.stdout:
                        output_lines.append(line)
                        clean = line.strip()
                        if clean and not clean.startswith("["):
                            self.events.put(("log", clean + "\n"))
                        if self.cancel_event.is_set() and self.process.poll() is None:
                            self.process.terminate()
                    return_code = self.process.wait()
            except (OSError, ValueError) as error:
                output_lines.append(f"ERRO: {error}\n")
                self.events.put(("log", f"ERRO: {error}\n"))
            finally:
                self.process = None

            (job.output_dir / "extracao.log").write_text(
                "".join(output_lines), encoding="utf-8", errors="replace"
            )
            wav_files = sorted(job.output_dir.glob("*.wav"))
            elapsed = time.time() - started
            if return_code == 0 and wav_files:
                status = "OK"
                self.events.put(
                    ("log", f"OK: {len(wav_files)} WAV(s) extraido(s) em {elapsed:.1f}s.\n")
                )
            elif self.cancel_event.is_set():
                status = "CANCELADO"
            elif return_code == 0:
                status = "SEM_AUDIO"
                self.events.put(("log", "Aviso: o jPSXdec nao encontrou audio XA.\n"))
            else:
                status = "ERRO"
                self.events.put(("log", f"Falha do jPSXdec (codigo {return_code}).\n"))

            if wav_files:
                for wav_path in wav_files:
                    duration, sample_rate, channels = wav_information(wav_path)
                    self.results.append(
                        {
                            "mcf": str(job.source),
                            "status": status,
                            "codec": codec,
                            "wav": str(wav_path),
                            "duracao": duration,
                            "sample_rate_hz": sample_rate,
                            "canais": channels,
                            "tamanho_bytes": str(wav_path.stat().st_size),
                        }
                    )
            else:
                self.results.append(
                    {
                        "mcf": str(job.source),
                        "status": status,
                        "codec": codec,
                        "wav": "",
                        "duracao": "",
                        "sample_rate_hz": "",
                        "canais": "",
                        "tamanho_bytes": "",
                    }
                )
            self.events.put(("progress", index))

        self._write_report(output_root)
        self.events.put(("done", self.cancel_event.is_set()))

    def _write_report(self, output_root: Path) -> None:
        output_root.mkdir(parents=True, exist_ok=True)
        report = output_root / "relatorio_extracao_audio.csv"
        fields = [
            "mcf",
            "status",
            "codec",
            "wav",
            "duracao",
            "sample_rate_hz",
            "canais",
            "tamanho_bytes",
        ]
        with report.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(self.results)

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
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    cancelled = bool(value)
                    ok_count = sum(row["status"] == "OK" for row in self.results)
                    if cancelled:
                        self.status_var.set("Extracao cancelada.")
                    else:
                        self.status_var.set(f"Concluido: {ok_count} WAV(s) extraido(s).")
                        messagebox.showinfo(
                            APP_TITLE,
                            f"Extracao concluida.\n\nWAVs extraidos: {ok_count}\n"
                            f"Relatorio: {Path(self.output_var.get()) / 'relatorio_extracao_audio.csv'}",
                        )
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

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
        path = Path(self.output_var.get().strip())
        if not path.exists():
            messagebox.showwarning(APP_TITLE, "A pasta de saida ainda nao existe.")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def _close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_TITLE, "Ha uma extracao em andamento. Deseja cancelar e sair?"):
                return
            self._cancel()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    AudioExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
