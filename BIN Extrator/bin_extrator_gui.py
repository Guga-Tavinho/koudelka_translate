from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Koudelka — Extrator de BIN/CUE"
BASE_DIR = Path(__file__).resolve().parent
LOCAL_PSXRIP = BASE_DIR / "psxrip.exe"
FALLBACK_PSXRIP = Path(r"C:\msys64\home\sistemas2\psximager\src\psxrip.exe")
FILE_LINE_RE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)


def find_psxrip() -> Path | None:
    for candidate in (LOCAL_PSXRIP, FALLBACK_PSXRIP):
        if candidate.is_file():
            return candidate
    return None


def read_cue_file_references(cue_path: Path) -> list[Path]:
    raw = cue_path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("latin-1", errors="replace")

    references: list[Path] = []
    for line in text.splitlines():
        match = FILE_LINE_RE.match(line)
        if match:
            references.append(cue_path.parent / (match.group(1) or match.group(2)))
    return references


def default_output_for(image_path: Path) -> Path:
    return image_path.parent / f"{image_path.stem}_EXTRAIDO"


class BinExtractorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("880x610")
        self.root.minsize(720, 500)

        self.image_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.lbns_var = tk.BooleanVar(value=True)
        self.verbose_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Selecione uma imagem CUE ou BIN.")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None

        self._build_ui()
        self._set_running(False)
        self.root.after(80, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        input_box = ttk.LabelFrame(outer, text="Imagem do disco", padding=10)
        input_box.grid(row=0, column=0, sticky="ew")
        input_box.columnconfigure(0, weight=1)
        self.image_entry = ttk.Entry(input_box, textvariable=self.image_var)
        self.image_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input_button = ttk.Button(input_box, text="Selecionar CUE/BIN...", command=self._select_image)
        self.input_button.grid(row=0, column=1)
        ttk.Label(
            input_box,
            text="Use o CUE quando estiver disponível. O BIN referenciado será localizado na mesma pasta.",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 0))

        output_box = ttk.LabelFrame(outer, text="Pasta de saída", padding=10)
        output_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        output_box.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(output_box, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.output_button = ttk.Button(output_box, text="Escolher pasta...", command=self._select_output)
        self.output_button.grid(row=0, column=1)

        options = ttk.Frame(outer)
        options.grid(row=2, column=0, sticky="ew", pady=10)
        self.lbns_check = ttk.Checkbutton(
            options,
            text="Preservar LBNs no catálogo (-l) — recomendado para reinjeção",
            variable=self.lbns_var,
        )
        self.lbns_check.pack(side="left")
        self.verbose_check = ttk.Checkbutton(options, text="Log detalhado (-v)", variable=self.verbose_var)
        self.verbose_check.pack(side="left", padx=(18, 0))

        log_box = ttk.LabelFrame(outer, text="Progresso e log", padding=8)
        log_box.grid(row=3, column=0, sticky="nsew")
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=150)
        self.progress.grid(row=0, column=1, padx=10)
        self.open_button = ttk.Button(footer, text="Abrir pasta", command=self._open_output)
        self.open_button.grid(row=0, column=2, padx=(0, 8))
        self.cancel_button = ttk.Button(footer, text="Cancelar", command=self._cancel)
        self.cancel_button.grid(row=0, column=3, padx=(0, 8))
        self.extract_button = ttk.Button(footer, text="Extrair", command=self._start_extract)
        self.extract_button.grid(row=0, column=4)

    def _select_image(self) -> None:
        current = self.image_var.get().strip()
        initial = str(Path(current).parent) if current else r"E:\KDK"
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Selecionar imagem do disco",
            initialdir=initial,
            filetypes=(("Imagem PlayStation", "*.cue *.bin"), ("CUE", "*.cue"), ("BIN", "*.bin"), ("Todos", "*.*")),
        )
        if not selected:
            return
        image_path = Path(selected)
        self.image_var.set(str(image_path))
        self.output_var.set(str(default_output_for(image_path)))
        self.status_var.set("Imagem selecionada. Clique em Extrair.")

    def _select_output(self) -> None:
        current = self.output_var.get().strip()
        initial = current or (str(Path(self.image_var.get()).parent) if self.image_var.get().strip() else r"E:\KDK")
        selected = filedialog.askdirectory(parent=self.root, title="Selecionar pasta de saída", initialdir=initial)
        if selected:
            self.output_var.set(selected)

    def _validate(self) -> tuple[Path, Path, Path] | None:
        psxrip = find_psxrip()
        if psxrip is None:
            messagebox.showerror(
                APP_TITLE,
                "psxrip.exe não foi encontrado. Coloque a versão modificada na mesma pasta desta ferramenta.",
                parent=self.root,
            )
            return None

        image_text = self.image_var.get().strip().strip('"')
        output_text = self.output_var.get().strip().strip('"')
        if not image_text:
            messagebox.showwarning(APP_TITLE, "Selecione um arquivo .cue ou .bin.", parent=self.root)
            return None
        image_path = Path(image_text)
        if not image_path.is_file():
            messagebox.showerror(APP_TITLE, f"Imagem não encontrada:\n{image_path}", parent=self.root)
            return None
        if image_path.suffix.lower() not in {".cue", ".bin"}:
            messagebox.showerror(APP_TITLE, "Selecione um arquivo com extensão .cue ou .bin.", parent=self.root)
            return None
        if not output_text:
            messagebox.showwarning(APP_TITLE, "Escolha a pasta de saída.", parent=self.root)
            return None

        output_path = Path(output_text)
        try:
            if output_path.resolve() == image_path.parent.resolve():
                messagebox.showerror(APP_TITLE, "A saída deve ser uma subpasta separada da pasta da imagem.", parent=self.root)
                return None
        except OSError:
            pass

        if image_path.suffix.lower() == ".cue":
            references = read_cue_file_references(image_path)
            if not references:
                messagebox.showerror(APP_TITLE, "O CUE não contém uma linha FILE válida.", parent=self.root)
                return None
            missing = [path for path in references if not path.is_file()]
            if missing:
                names = "\n".join(str(path) for path in missing)
                messagebox.showerror(APP_TITLE, f"Arquivo(s) referenciado(s) pelo CUE não encontrado(s):\n\n{names}", parent=self.root)
                return None

        if output_path.exists() and not output_path.is_dir():
            messagebox.showerror(APP_TITLE, f"O caminho de saída aponta para um arquivo:\n{output_path}", parent=self.root)
            return None

        output_has_content = output_path.is_dir() and any(output_path.iterdir())
        sidecars_exist = output_path.with_suffix(".cat").exists() or output_path.with_suffix(".sys").exists()
        if output_has_content or sidecars_exist:
            proceed = messagebox.askyesno(
                APP_TITLE,
                "A saída selecionada já possui arquivos, catálogo ou área de sistema. "
                "Itens com o mesmo nome poderão ser substituídos.\n\nDeseja continuar?",
                parent=self.root,
            )
            if not proceed:
                return None
        return psxrip, image_path, output_path

    def _start_extract(self) -> None:
        validated = self._validate()
        if validated is None:
            return
        psxrip, image_path, output_path = validated
        output_path.parent.mkdir(parents=True, exist_ok=True)

        command = [str(psxrip)]
        if self.lbns_var.get():
            command.append("-l")
        if self.verbose_var.get():
            command.append("-v")
        # psxrip/libcdio resolves FILE entries in a CUE against its current
        # working directory, so run inside the image directory and pass only
        # the image filename. This also supports paths containing spaces.
        command.extend([image_path.name, str(output_path)])

        self._clear_log()
        self._append_log("Koudelka — Extrator de BIN/CUE\n")
        self._append_log("Compatibilidade ativa: modo de disco 16 continua com aviso.\n")
        self._append_log(f"Entrada: {image_path}\nSaída:   {output_path}\n\n")
        self.status_var.set("Extraindo arquivos...")
        self._set_running(True)
        self.worker = threading.Thread(
            target=self._run_process,
            args=(command, image_path.parent, output_path),
            daemon=True,
        )
        self.worker.start()

    def _run_process(self, command: list[str], working_dir: Path, output_path: Path) -> None:
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                command,
                cwd=str(working_dir),
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
                self.events.put(("log", line))
            return_code = self.process.wait()
            self.events.put(("done", (return_code, output_path)))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.process = None

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "done":
                    return_code, output_path = payload  # type: ignore[misc]
                    self._finish(int(return_code), Path(output_path))
                elif kind == "error":
                    self._set_running(False)
                    self.status_var.set("Falha ao iniciar a extração.")
                    self._append_log(f"\nERRO: {payload}\n")
                    messagebox.showerror(APP_TITLE, f"Não foi possível executar o extrator:\n\n{payload}", parent=self.root)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)

    def _finish(self, return_code: int, output_path: Path) -> None:
        self._set_running(False)
        if return_code == 0:
            self.status_var.set("Extração concluída com sucesso.")
            self._append_log("\nExtração concluída com sucesso.\n")
            messagebox.showinfo(
                APP_TITLE,
                f"Extração concluída.\n\nArquivos: {output_path}\nCatálogo: {output_path.with_suffix('.cat')}\nSistema: {output_path.with_suffix('.sys')}",
                parent=self.root,
            )
        else:
            self.status_var.set(f"Extração encerrada com erro (código {return_code}).")
            self._append_log(f"\nExtração falhou com código {return_code}. Consulte o log acima.\n")
            messagebox.showerror(APP_TITLE, "A extração não foi concluída. Consulte o log da ferramenta.", parent=self.root)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in (
            self.image_entry,
            self.input_button,
            self.output_entry,
            self.output_button,
            self.lbns_check,
            self.verbose_check,
            self.extract_button,
        ):
            widget.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.open_button.configure(state="disabled" if running else "normal")
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _cancel(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        if not messagebox.askyesno(APP_TITLE, "Cancelar a extração em andamento?", parent=self.root):
            return
        process.terminate()
        self.status_var.set("Cancelando...")
        self._append_log("\nCancelamento solicitado pelo usuário.\n")

    def _open_output(self) -> None:
        text = self.output_var.get().strip().strip('"')
        if not text:
            return
        path = Path(text)
        target = path if path.exists() else path.parent
        if not target.exists():
            messagebox.showwarning(APP_TITLE, "A pasta de saída ainda não existe.", parent=self.root)
            return
        os.startfile(str(target))

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno(APP_TITLE, "Há uma extração em andamento. Cancelar e fechar?", parent=self.root):
                return
            self.process.terminate()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    BinExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
