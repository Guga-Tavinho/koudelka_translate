"""Interface de extração e prévia TX8. Não modifica arquivos do jogo."""
from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
    from koudelka_tx8_core import Tx8File, checkerboard, export_tx8, image_for, read_tx8
except ImportError as error:
    raise SystemExit('Dependência ausente. Execute instalar_dependencias.bat. Detalhe: ' + str(error)) from error


LAYOUTS = {'Automático': 'auto', 'Textura linear completa': 'linear',
           'Painéis de 256 linhas': 'panels', 'Tela 320x240 (recorte)': 'screen'}


class Tx8App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Koudelka TX8 — Extrator de imagens v1')
        self.geometry('1000x680')
        self.minsize(760, 500)
        self.sources: list[Tx8File] = []
        self.lookup = {}
        self.current = None
        self.current_image = None
        self.photo = None
        self.busy = False
        self.events = queue.Queue()
        self.layout_var = tk.StringVar(value='Automático')
        self.zoom_var = tk.StringVar(value='Ajustar')
        self.transparent_var = tk.BooleanVar(value=False)
        self.path_var = tk.StringVar(value='Abra um arquivo TX8 ou uma pasta.')
        self.info_var = tk.StringVar()
        self.status_var = tk.StringVar(value='Os TX8 originais nunca são alterados.')
        self._build()
        self.bind('<Control-o>', lambda event: self.open_file())
        self.bind('<Control-s>', lambda event: self.save_current())
        self.protocol('WM_DELETE_WINDOW', self.close)
        default = Path(__file__).resolve().parent.parents[1] / 'Koudelka (Disc 1)' / 'MENU' / 'GAMEOVER'
        initial = Path(sys.argv[1]) if len(sys.argv) > 1 else default
        if initial.exists():
            self.after(100, lambda: self.load_path(initial))

    def _build(self):
        style = ttk.Style(self)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('.', font=('Arial', 10))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(self, padding=8)
        toolbar.grid(row=0, column=0, sticky='ew')
        for text, command in [('Abrir TX8…', self.open_file), ('Abrir pasta…', self.open_folder),
                              ('Recarregar', self.reload_current)]:
            ttk.Button(toolbar, text=text, command=command).pack(side='left', padx=(0, 5))
        ttk.Label(toolbar, text='Somente leitura dos arquivos originais').pack(side='right')
        settings = ttk.Frame(self, padding=(8, 0, 8, 8))
        settings.grid(row=1, column=0, sticky='ew')
        ttk.Label(settings, text='Visualização:').pack(side='left')
        layout = ttk.Combobox(settings, textvariable=self.layout_var, values=list(LAYOUTS), state='readonly', width=26)
        layout.pack(side='left', padx=5)
        layout.bind('<<ComboboxSelected>>', lambda event: self.show_current())
        ttk.Label(settings, text='Zoom:').pack(side='left')
        zoom = ttk.Combobox(settings, textvariable=self.zoom_var, values=('Ajustar', '1x', '2x', '4x'), state='readonly', width=8)
        zoom.pack(side='left', padx=5)
        zoom.bind('<<ComboboxSelected>>', lambda event: self.draw_preview())
        ttk.Checkbutton(settings, text='Cor nativa 0000 transparente', variable=self.transparent_var,
                        command=self.show_current).pack(side='left', padx=5)
        pane = ttk.Panedwindow(self, orient='horizontal')
        pane.grid(row=2, column=0, sticky='nsew', padx=8)
        left = ttk.Frame(pane, width=260)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=('size',), show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='Arquivos / imagens (↑ ↓)')
        self.tree.heading('size', text='Textura')
        self.tree.column('#0', width=180, minwidth=100)
        self.tree.column('size', width=85, minwidth=70)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        self.path_label = ttk.Label(right, textvariable=self.path_var, wraplength=360)
        self.path_label.grid(row=0, column=0, sticky='ew', padx=8, pady=(0, 4))
        self.info_label = ttk.Label(right, textvariable=self.info_var, wraplength=360)
        self.info_label.grid(row=1, column=0, sticky='ew', padx=8, pady=(0, 4))
        right.bind('<Configure>', lambda event: self.resize_labels(event.width))
        view = ttk.Frame(right)
        view.grid(row=2, column=0, sticky='nsew', padx=(8, 0))
        view.columnconfigure(0, weight=1)
        view.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(view, background='#252525', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(view, orient='vertical', command=self.canvas.yview)
        sx = ttk.Scrollbar(view, orient='horizontal', command=self.canvas.xview)
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.bind('<Configure>', lambda event: self.draw_preview())
        footer = ttk.Frame(self, padding=8)
        footer.grid(row=3, column=0, sticky='ew')
        ttk.Button(footer, text='Salvar imagem visível…', command=self.save_current).pack(side='left')
        ttk.Button(footer, text='Extrair arquivo selecionado…', command=self.extract_file).pack(side='left', padx=5)
        ttk.Button(footer, text='Extrair todos os arquivos…', command=self.extract_all).pack(side='left')
        self.status_label = ttk.Label(self, textvariable=self.status_var, padding=(8, 4), wraplength=720)
        self.status_label.grid(row=4, column=0, sticky='ew')

    def resize_labels(self, width):
        for label in (self.path_label, self.info_label):
            label.configure(wraplength=max(100, width - 24))
        self.status_label.configure(wraplength=max(100, self.winfo_width() - 24))

    def open_file(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title='Abrir TX8', filetypes=[('Koudelka TX8', '*.TX8 *.tx8')])
        if path:
            self.load_path(Path(path))

    def open_folder(self):
        if self.busy:
            return
        path = filedialog.askdirectory(parent=self, title='Abrir pasta TX8 (inclui subpastas)')
        if path:
            self.load_path(Path(path))

    def run_job(self, worker):
        if self.busy:
            return
        self.busy = True
        def run():
            try:
                self.events.put(('done', worker()))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=run, daemon=True).start()
        self.after(100, self.poll_job)

    def load_path(self, path):
        if self.busy:
            return
        self.status_var.set('Lendo TX8 e identificando imagens…')
        def worker():
            files = sorted(p for p in path.rglob('*') if p.is_file() and p.suffix.lower() == '.tx8') if path.is_dir() else [path]
            sources, errors = [], []
            for file in files:
                try:
                    sources.append(read_tx8(file))
                except Exception as error:
                    errors.append(f'{file}: {error}')
            if not sources:
                raise ValueError('Nenhum TX8 compatível encontrado.\n' + '\n'.join(errors[:5]))
            return ('loaded', sources, errors)
        self.run_job(worker)

    def poll_job(self):
        try:
            kind, result = self.events.get_nowait()
        except queue.Empty:
            self.after(100, self.poll_job)
            return
        self.busy = False
        if kind == 'error':
            self.status_var.set('Operação não concluída.')
            messagebox.showerror('TX8', result, parent=self)
            return
        if result[0] == 'loaded':
            self.sources = result[1]
            self.tree.delete(*self.tree.get_children())
            self.lookup.clear()
            self.current = None
            self.current_image = None
            for f, source in enumerate(self.sources):
                parent = self.tree.insert('', 'end', iid=f'f{f}', text=source.path.name, open=True,
                                          values=(f'{len(source.textures)} img.',))
                for n, texture in enumerate(source.textures):
                    iid = f'f{f}b{n}'
                    self.lookup[iid] = (source, n)
                    self.tree.insert(parent, 'end', iid=iid, text=f'{n+1:03d} — 0x{texture.offset:X}',
                                     values=(f'{texture.width}x{texture.stored_height}',))
            first = next(iter(self.lookup))
            self.tree.selection_set(first)
            self.tree.focus(first)
            self.tree.see(first)
            self.status_var.set(f'{len(self.sources)} arquivo(s), {len(self.lookup)} imagem(ns). Setas ↑ ↓ navegam pela lista.')
            if result[2]:
                messagebox.showwarning('Alguns arquivos não foram abertos', '\n'.join(result[2][:8]), parent=self)
        else:
            folder, count = result[1:]
            self.status_var.set(f'Extração concluída: {count} imagem(ns). Pasta: {folder}')
            messagebox.showinfo('Extração concluída', f'{count} imagem(ns) extraída(s).\n\n{folder}\n\nInclui PNGs sem recorte e dados de paleta/offset.', parent=self)

    def on_select(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        if item not in self.lookup:
            children = self.tree.get_children(item)
            if not children:
                return
            item = children[0]
        self.current = self.lookup[item]
        self.show_current()

    def show_current(self):
        if self.current is None:
            return
        source, n = self.current
        texture = source.textures[n]
        self.path_var.set(str(source.path))
        try:
            self.current_image = image_for(texture, LAYOUTS[self.layout_var.get()], self.transparent_var.get())
        except ValueError as error:
            self.current_image = None
            self.info_var.set(str(error) + ' Escolha Textura linear completa.')
            self.canvas.delete('all')
            return
        self.info_var.set(
            f'Imagem {n+1}/{len(source.textures)} | textura {texture.width}x{texture.stored_height} '
            f'| prévia {self.current_image.width}x{self.current_image.height}\n'
            f'Bloco 0x{texture.offset:X} | pixels 0x{texture.pixel_offset:X} | CLUT 256 cores'
        )
        self.draw_preview()

    def draw_preview(self):
        if self.current_image is None:
            return
        image = self.current_image
        cw, ch = max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)
        zoom = self.zoom_var.get()
        scale = min(cw / image.width, ch / image.height, 8) if zoom == 'Ajustar' else int(zoom[0])
        size = max(1, round(image.width * scale)), max(1, round(image.height * scale))
        rgba = image.convert('RGBA').resize(size, Image.Resampling.NEAREST)
        background = checkerboard(size)
        background.alpha_composite(rgba)
        self.photo = ImageTk.PhotoImage(background)
        self.canvas.delete('all')
        self.canvas.create_image(max(0, (cw-size[0])//2), max(0, (ch-size[1])//2), image=self.photo, anchor='nw')
        self.canvas.configure(scrollregion=(0, 0, max(cw, size[0]), max(ch, size[1])))

    def reload_current(self):
        if self.current:
            self.load_path(self.current[0].path)

    def save_current(self):
        if self.busy or self.current_image is None or self.current is None:
            return
        source, n = self.current
        target = filedialog.asksaveasfilename(parent=self, title='Salvar PNG na resolução nativa (sem o zoom)',
            initialfile=f'{source.path.stem}_{n+1:03d}.png', defaultextension='.png', filetypes=[('PNG', '*.png')])
        if target:
            try:
                if Path(target).suffix.lower() != '.png':
                    raise ValueError('Use um nome com extensão .png. O TX8 original não pode ser substituído.')
                self.current_image.save(target, format='PNG')
                self.status_var.set(f'PNG salvo: {target}')
            except Exception as error:
                messagebox.showerror('Salvar PNG', str(error), parent=self)

    def extract_file(self):
        if self.current:
            self.extract([self.current[0]])

    def extract_all(self):
        self.extract(list(self.sources))

    def extract(self, sources):
        if self.busy or not sources:
            return
        destination = filedialog.askdirectory(parent=self, title='Destino — será criada uma nova pasta de extração')
        if not destination:
            return
        transparent = self.transparent_var.get()
        root = Path(destination) / ('TX8_extraidos_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.status_var.set('Exportando PNGs e paletas…')
        def worker():
            root.mkdir(exist_ok=False)
            for i, source in enumerate(sources, 1):
                export_tx8(source, root / f'{i:03d}_{source.path.stem}', transparent)
            return ('exported', root, sum(len(source.textures) for source in sources))
        self.run_job(worker)

    def close(self):
        if self.busy:
            messagebox.showinfo('Operação em andamento', 'Aguarde a leitura ou extração terminar antes de fechar.', parent=self)
            return
        self.destroy()


if __name__ == '__main__':
    Tx8App().mainloop()
