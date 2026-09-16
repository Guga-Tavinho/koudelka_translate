"""Editor de substituicao PNG com previsualizacao da paleta real do TX8."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from koudelka_tx8_core import checkerboard, image_for
from koudelka_tx8_import import (import_layouts, match_png_batch, prepare_import,
                                prepare_import_batch, save_modified)


VIEWS = {'linear': 'Textura linear completa', 'panels': 'Painéis montados', 'screen': 'Tela 320x240'}


class ImportWindow(tk.Toplevel):
    def __init__(self, master, source, selected=0):
        super().__init__(master)
        self.source = source
        self.selected = selected
        self.changes = {}
        self.dirty = False
        self.busy = False
        self.events = queue.Queue()
        self.photos = []
        self.preview_images = None
        self.layout_var = tk.StringVar()
        self.zoom_var = tk.StringVar(value='Ajustar')
        self.transparent_var = tk.BooleanVar(value=False)
        self.info_var = tk.StringVar()
        self.title('Koudelka — Importar PNG para TX8')
        self.geometry('960x650')
        self.minsize(760, 500)
        self.transient(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, sticky='ew')
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text='TX8 de origem (não será alterado):').grid(row=0, column=0, sticky='w')
        path_var = tk.StringVar(value=str(source.path))
        self.path_var = path_var
        ttk.Entry(top, textvariable=path_var, state='readonly').grid(row=1, column=0, sticky='ew')

        choose = ttk.Frame(self, padding=(8, 0, 8, 6))
        choose.grid(row=1, column=0, sticky='ew')
        choose.columnconfigure(1, weight=1)
        ttk.Label(choose, text='Imagem a substituir:').grid(row=0, column=0, padx=(0, 8))
        self.selector = ttk.Combobox(choose, state='readonly')
        self.selector.grid(row=0, column=1, sticky='ew')
        self.selector.bind('<<ComboboxSelected>>', self.on_select)

        settings = ttk.Frame(self, padding=(8, 0, 8, 6))
        settings.grid(row=2, column=0, sticky='ew')
        ttk.Label(settings, text='Vista:').pack(side='left')
        self.layout_combo = ttk.Combobox(settings, textvariable=self.layout_var, state='readonly', width=25)
        self.layout_combo.pack(side='left', padx=5)
        self.layout_combo.bind('<<ComboboxSelected>>', lambda event: self.refresh_preview())
        ttk.Label(settings, text='Zoom:').pack(side='left')
        zoom = ttk.Combobox(settings, textvariable=self.zoom_var, state='readonly',
                            values=('Ajustar', '1x', '2x', '4x'), width=8)
        zoom.pack(side='left', padx=5)
        zoom.bind('<<ComboboxSelected>>', lambda event: self.draw_preview())
        ttk.Checkbutton(settings, text='Mostrar transparência nativa', variable=self.transparent_var,
                        command=self.refresh_preview).pack(side='left', padx=5)

        view = ttk.Frame(self)
        view.grid(row=3, column=0, sticky='nsew', padx=8)
        view.columnconfigure(0, weight=1)
        view.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(view, background='#252525', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        sx = ttk.Scrollbar(view, orient='horizontal', command=self.canvas.xview)
        sy = ttk.Scrollbar(view, orient='vertical', command=self.canvas.yview)
        sx.grid(row=1, column=0, sticky='ew')
        sy.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.bind('<Configure>', lambda event: self.draw_preview())

        self.info_label = ttk.Label(self, textvariable=self.info_var, padding=8, wraplength=720)
        self.info_label.grid(row=4, column=0, sticky='ew')
        self.footer = ttk.Frame(self, padding=(8, 0, 8, 8))
        self.footer.grid(row=5, column=0, sticky='ew')
        for column in range(3):
            self.footer.columnconfigure(column, weight=1, uniform='actions')
        self.buttons = []
        for index, (text, callback) in enumerate([
                ('Importar PNG…', self.choose_png), ('Importar vários PNGs…', self.choose_pngs),
                ('Recarregar PNG', self.reload_png), ('Desfazer nesta imagem', self.reset_current),
                ('Salvar novo TX8…', self.save_tx8)]):
            button = ttk.Button(self.footer, text=text, command=callback)
            button.grid(row=index // 3, column=index % 3, sticky='ew', padx=(0, 5), pady=3)
            self.buttons.append(button)
        self.bind('<Configure>', self.on_resize)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_selector()
        self.set_view_for_selected()
        self.grab_set()

    def on_resize(self, event):
        if event.widget is self:
            self.info_label.configure(wraplength=max(100, event.width - 24))

    def refresh_selector(self):
        self.selector.configure(values=[
            f'{i+1:03d} — bloco 0x{texture.offset:X} — {texture.width}x{texture.stored_height}'
            + ('  [PNG importado]' if i in self.changes else '')
            for i, texture in enumerate(self.source.textures)])
        self.selector.current(self.selected)

    def on_select(self, event=None):
        self.selected = self.selector.current()
        self.set_view_for_selected()

    def set_view_for_selected(self):
        layouts = import_layouts(self.source.textures[self.selected])
        self.layout_combo.configure(values=[VIEWS[key] for key in layouts])
        edit = self.changes.get(self.selected)
        key = edit.layout if edit else ('screen' if 'screen' in layouts else 'linear')
        self.layout_var.set(VIEWS[key])
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.refresh_preview()

    def refresh_preview(self):
        texture = self.source.textures[self.selected]
        edit = self.changes.get(self.selected)
        layout = next(key for key, label in VIEWS.items() if label == self.layout_var.get())
        transparency = self.transparent_var.get()
        before = image_for(texture, layout, transparency)
        after = image_for(edit.texture if edit else texture, layout, transparency)
        self.preview_images = (before, after)
        dimensions = ', '.join(f'{w}x{h}' for w, h in import_layouts(texture).values())
        detail = (f'PNG aceito: {dimensions}. Paleta original fixa; nenhuma imagem será redimensionada.\n')
        if edit:
            detail += (f'PNG: {edit.png_path.name} | {edit.changed_pixels} pixels alterados '
                       f'| {edit.approximated_pixels} pixels com cor aproximada.\n')
            if edit.stp_changes:
                detail += f'Atenção: {edit.stp_changes} pixels mudaram de classe de transparência/mistura.\n'
        detail += f'{len(self.changes)} imagem(ns) preparada(s). Salvar inclui todas no TX8 selecionado.'
        self.info_var.set(detail)
        self.draw_preview()

    def draw_preview(self):
        if not self.preview_images:
            return
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        image = self.preview_images[0]
        scale = (max(0.01, min((cw-30) / (2*image.width), (ch-36) / image.height, 8))
                 if self.zoom_var.get() == 'Ajustar' else int(self.zoom_var.get()[0]))
        size = (max(1, round(image.width*scale)), max(1, round(image.height*scale)))
        world_w = max(cw, 2*size[0]+30)
        world_h = max(ch, size[1]+36)
        self.canvas.delete('all')
        self.photos.clear()
        start = max(10, (world_w - (2*size[0]+10))//2)
        for i, (img, title) in enumerate(zip(self.preview_images, ('ANTES — original', 'DEPOIS — convertido para TX8'))):
            x = start + i*(size[0]+10)
            rgba = img.convert('RGBA').resize(size, Image.Resampling.NEAREST)
            background = checkerboard(size)
            background.alpha_composite(rgba)
            photo = ImageTk.PhotoImage(background)
            self.photos.append(photo)
            self.canvas.create_text(x, 6, text=title, fill='white', anchor='nw', font=('Arial', 9))
            self.canvas.create_image(x, 28, image=photo, anchor='nw')
        self.canvas.configure(scrollregion=(0, 0, world_w, world_h))

    def set_busy(self, busy):
        self.busy = busy
        self.selector.configure(state='disabled' if busy else 'readonly')
        self.layout_combo.configure(state='disabled' if busy else 'readonly')
        for button in self.buttons:
            button.configure(state='disabled' if busy else 'normal')

    def run_job(self, worker, text):
        if self.busy:
            return
        self.set_busy(True)
        self.info_var.set(text)
        def run():
            try:
                self.events.put(('ok', worker()))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=run, daemon=True).start()
        self.after(60, self.poll_job)

    def poll_job(self):
        try:
            kind, result = self.events.get_nowait()
        except queue.Empty:
            self.after(60, self.poll_job)
            return
        self.set_busy(False)
        if kind == 'error':
            self.refresh_preview()
            messagebox.showerror('Importação TX8', result, parent=self)
        elif result[0] == 'imported':
            _, number, prepared = result
            self.changes[number] = prepared
            self.dirty = True
            self.selected = number
            self.refresh_selector()
            self.set_view_for_selected()
        elif result[0] == 'batch_imported':
            prepared = result[1]
            self.changes.update(prepared)
            self.dirty = True
            self.selected = min(prepared)
            self.refresh_selector()
            self.set_view_for_selected()
        else:
            self.dirty = False
            self.refresh_preview()
            self.info_var.set(f'TX8 salvo e relido para conferência: {result[1]}\n'
                              'Original preservado. Este arquivo ainda precisa ser injetado no disco e testado no jogo.')
            messagebox.showinfo('TX8 salvo', f'Arquivo gerado:\n{result[1]}\n\n'
                                'Tamanho, paletas e estrutura preservados.\n'
                                'As imagens não selecionadas permaneceram intactas.\n'
                                'A prévia não simula os modos de mistura do jogo; teste no emulador.', parent=self)

    def choose_png(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title=f'PNG para a imagem {self.selected+1:03d}',
                                          filetypes=[('Imagem PNG', '*.png')])
        if path:
            self.load_png(path)

    def load_png(self, path):
        number = self.selected
        texture = self.source.textures[number]
        self.run_job(lambda: ('imported', number, prepare_import(texture, path)),
                     'Convertendo PNG para a paleta nativa e preparando a prévia…')

    def choose_pngs(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(parent=self,
                    title='Selecione um PNG por imagem: 001…, 002…, 003… (Ctrl/Shift)',
                    filetypes=[('Imagens PNG', '*.png')])
        if paths:
            self.load_pngs(paths)

    def confirm_batch_import(self, mapping):
        """Lista rolável permite conferir associações, inclusive em TX8 grandes."""
        dialog = tk.Toplevel(self)
        dialog.title('Conferir importação de vários PNGs')
        dialog.geometry('740x360')
        dialog.minsize(560, 280)
        dialog.transient(self)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(dialog, text='O número inicial do PNG define a imagem dentro do TX8.\n'
                  'Confira abaixo; os arquivos originais não serão alterados.',
                  padding=10, wraplength=520).grid(row=0, column=0, sticky='ew')
        frame = ttk.Frame(dialog, padding=(10, 0))
        frame.grid(row=1, column=0, sticky='nsew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=('number', 'png', 'status'), show='headings')
        for key, label, width in [('number', 'Imagem no TX8', 105), ('png', 'PNG selecionado', 370),
                                  ('status', 'Substituição', 190)]:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=70, stretch=(key == 'png'))
        tree.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        sy.grid(row=0, column=1, sticky='ns')
        sx = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        sx.grid(row=1, column=0, sticky='ew')
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        for number, path in mapping.items():
            tree.insert('', 'end', values=(f'{number + 1:03d}', path.name,
                        'Trocar PNG já importado' if number in self.changes else 'Nova importação'))
        accepted = False

        def finish(confirm=False):
            nonlocal accepted
            accepted = confirm
            dialog.destroy()

        footer = ttk.Frame(dialog, padding=10)
        footer.grid(row=2, column=0, sticky='ew')
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, text=f'{len(mapping)} PNG(s). Depois, confira as prévias e salve o novo TX8.',
                  wraplength=510).grid(row=0, column=0, sticky='w', pady=(0, 5))
        actions = ttk.Frame(footer)
        actions.grid(row=1, column=0, sticky='e')
        ttk.Button(actions, text='Cancelar', command=finish).pack(side='right', padx=5)
        ttk.Button(actions, text='Importar', command=lambda: finish(True)).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW', finish)
        dialog.bind('<Escape>', lambda event: finish())
        dialog.grab_set()
        self.wait_window(dialog)
        self.grab_set()
        return accepted

    def load_pngs(self, paths):
        if self.busy:
            return
        paths = tuple(paths)
        try:
            mapping = match_png_batch(self.source, paths)
        except ValueError as error:
            messagebox.showerror('Importação em lote', str(error), parent=self)
            return
        if not self.confirm_batch_import(mapping):
            return
        self.run_job(lambda: ('batch_imported', prepare_import_batch(self.source, paths)),
                     f'Convertendo {len(mapping)} PNG(s) para as paletas nativas. '
                     'O lote só será aplicado se todas as imagens forem válidas…')

    def reload_png(self):
        if self.selected in self.changes:
            self.load_png(self.changes[self.selected].png_path)
        else:
            messagebox.showinfo('Recarregar', 'Importe um PNG nesta imagem primeiro.', parent=self)

    def reset_current(self):
        if self.busy:
            return
        self.changes.pop(self.selected, None)
        self.dirty = bool(self.changes)
        self.refresh_selector()
        self.set_view_for_selected()

    def save_tx8(self):
        if self.busy:
            return
        if not self.changes:
            messagebox.showinfo('Salvar TX8', 'Importe pelo menos um PNG primeiro.', parent=self)
            return
        target = filedialog.asksaveasfilename(parent=self, title='Salvar em um NOVO arquivo TX8',
                     initialdir=str(self.source.path.parent), initialfile=f'{self.source.path.stem}_IMPORTADO.TX8',
                     defaultextension='.TX8', filetypes=[('Koudelka TX8', '*.TX8')])
        if target:
            changes = {number: edit.texture for number, edit in self.changes.items()}
            self.run_job(lambda: ('saved', save_modified(self.source, changes, target)),
                         'Salvando uma cópia TX8 e verificando os dados…')

    def close(self):
        if self.busy:
            messagebox.showinfo('Aguarde', 'Aguarde a operação terminar antes de fechar.', parent=self)
            return
        if self.dirty and not messagebox.askyesno('Alterações não salvas',
                'Fechar sem salvar o TX8? Os PNGs e o TX8 original não serão alterados.', parent=self):
            return
        self.grab_release()
        self.destroy()
