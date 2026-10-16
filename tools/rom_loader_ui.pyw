"""PureMetal NES ROM Loader: choose your .nes games and load them onto the
Pico W. Double-click this file (Windows) or run: py -3 tools/rom_loader_ui.pyw

The board must be running the PureMetal NES firmware and be plugged in by USB.
The same work is done from the command line by rom_loader.py.
"""
import queue, sys, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rom_loader
from rom_catalog import read_rom, validate, prg_views

CAPACITY = rom_loader.END - rom_loader.DATA


class LoaderWindow:
    def __init__(self, root):
        self.root = root
        self.games = []                     # [(path, cartridge)]
        self.events = queue.Queue()
        self.busy = False
        self.failed = False
        root.title('PureMetal NES ROM Loader')
        root.minsize(620, 460)
        frame = ttk.Frame(root, padding=10)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='Games to load (the boot menu shows them in this order):').pack(anchor='w')
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True, pady=(4, 6))
        self.list = ttk.Treeview(table, columns=('mapper', 'size', 'file'), show='tree headings', height=9)
        self.list.heading('#0', text='Title')
        self.list.heading('mapper', text='Mapper')
        self.list.heading('size', text='Size in store')
        self.list.heading('file', text='File')
        self.list.column('#0', width=220)
        self.list.column('mapper', width=70, anchor='center')
        self.list.column('size', width=100, anchor='e')
        self.list.column('file', width=200)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.list.yview)
        self.list.configure(yscrollcommand=scroll.set)
        self.list.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        self.add_button = ttk.Button(buttons, text='Add ROMs...', command=self.add)
        self.remove_button = ttk.Button(buttons, text='Remove', command=self.remove)
        self.up_button = ttk.Button(buttons, text='Move up', command=lambda: self.move(-1))
        self.down_button = ttk.Button(buttons, text='Move down', command=lambda: self.move(1))
        for b in (self.add_button, self.remove_button, self.up_button, self.down_button):
            b.pack(side='left', padx=(0, 6))

        self.capacity_text = tk.StringVar()
        ttk.Label(frame, textvariable=self.capacity_text).pack(anchor='w', pady=(10, 2))
        self.capacity = ttk.Progressbar(frame, maximum=CAPACITY)
        self.capacity.pack(fill='x')

        board = ttk.Frame(frame)
        board.pack(fill='x', pady=(10, 4))
        ttk.Label(board, text='Board port:').pack(side='left')
        self.port = ttk.Combobox(board, width=12, state='readonly')
        self.port.pack(side='left', padx=6)
        ttk.Button(board, text='Refresh', command=self.refresh_ports).pack(side='left')
        self.clear_button = ttk.Button(board, text='Empty the store', command=self.clear)
        self.clear_button.pack(side='right')
        self.load_button = ttk.Button(board, text='Load onto board', command=self.load)
        self.load_button.pack(side='right', padx=6)

        self.progress = ttk.Progressbar(frame, maximum=1.0)
        self.progress.pack(fill='x', pady=(4, 4))
        self.log = tk.Text(frame, height=7, state='disabled', wrap='word')
        self.log.pack(fill='both', expand=True)

        self.refresh_ports()
        self.update_capacity()
        root.after(100, self.poll)

    # ----------------------------------------------------------- the list
    def add(self, paths=None):
        paths = paths or filedialog.askopenfilenames(
            title='Choose NES ROMs', filetypes=[('NES ROMs', '*.nes'), ('All files', '*.*')])
        refused = []
        for name in paths:
            path = Path(name)
            try:
                cart = read_rom(path)
                validate(cart)
            except (OSError, ValueError) as error:
                refused.append(str(error))
                continue
            self.games.append((path, cart))
        self.redraw()
        if refused:
            messagebox.showwarning('Some files were not added', '\n\n'.join(refused))

    def selected(self):
        sel = self.list.selection()
        return self.list.index(sel[0]) if sel else None

    def remove(self):
        index = self.selected()
        if index is not None:
            del self.games[index]
            self.redraw()

    def move(self, step):
        index = self.selected()
        if index is None or not 0 <= index + step < len(self.games):
            return
        self.games[index], self.games[index + step] = self.games[index + step], self.games[index]
        self.redraw(select=index + step)

    def redraw(self, select=None):
        self.list.delete(*self.list.get_children())
        for n, (path, cart) in enumerate(self.games):
            size = self.store_size(cart)
            self.list.insert('', 'end', iid=str(n), text=cart.title[:31],
                             values=(cart.mapper, f'{size // 1024} KiB', path.name))
        if select is not None:
            self.list.selection_set(str(select))
        self.update_capacity()

    @staticmethod
    def store_size(cart):
        sector = rom_loader.SECTOR
        return (-(-len(prg_views(cart)) // sector) + -(-len(cart.chr) // sector)) * sector

    def update_capacity(self):
        used = sum(self.store_size(c) for _, c in self.games)
        self.capacity['value'] = min(used, CAPACITY)
        over = used > CAPACITY
        self.capacity_text.set(f'ROM store: {used // 1024} of {CAPACITY // 1024} KiB used, '
                               f'{len(self.games)} of {rom_loader.MAX_GAMES} games'
                               + ('  -  TOO MUCH: remove a game' if over else ''))

    # ---------------------------------------------------------- the board
    def refresh_ports(self):
        try:
            ports = rom_loader.find_ports()
        except ImportError:
            ports = []
            messagebox.showerror('pyserial is missing', 'Install it with:  py -3 -m pip install pyserial')
        self.port['values'] = ports
        # Loading reboots the chosen board, so with several Picos attached the
        # user picks one; the tool never guesses.
        if len(ports) == 1:
            self.port.set(ports[0])
        elif self.port.get() not in ports:
            self.port.set('')
        if len(ports) > 1 and not self.port.get():
            self.write_log(f'{len(ports)} Pico boards found ({", ".join(ports)}): choose the NES board in Board port.')
        if not ports:
            self.port.set('')
            self.write_log('No Pico found on USB. Plug the board in and press Refresh.')

    def load(self):
        if not self.games:
            messagebox.showinfo('Nothing to load', 'Add one or more .nes files first.')
            return
        try:
            games, directory, blobs = rom_loader.layout([p for p, _ in self.games])
        except ValueError as error:
            messagebox.showerror('Cannot load these games', str(error))
            return
        self.start(directory, blobs, f'Loading {len(games)} game(s)')

    def clear(self):
        if messagebox.askyesno('Empty the ROM store',
                               'Remove every game from the board? It will show its built-in demo.'):
            self.start(b'', [], 'Emptying the ROM store')

    def start(self, directory, blobs, title):
        port = self.port.get()
        if not port:
            messagebox.showerror('No board', 'No Pico was found on USB. Plug the board in and press Refresh.')
            return
        self.set_busy(True)
        self.write_log(title + '...')
        self.progress['value'] = 0
        report = lambda text, done: self.events.put(('progress', text, done))

        def work():
            try:
                rom_loader.load_store(directory, blobs, port, True, report)
                self.events.put(('done', None, None))
            except Exception as error:      # shown to the user, never swallowed
                self.events.put(('failed', f'{type(error).__name__}: {error}', None))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind, text, done = self.events.get()
            if kind == 'progress':
                self.write_log(text)
                self.progress['value'] = done
            elif kind == 'done':
                self.set_busy(False)
                self.write_log('Done. Choose a game on the board.')
            else:
                self.set_busy(False)
                self.failed = True
                self.write_log('FAILED: ' + text)
                messagebox.showerror('Loading failed', text + '\n\nThe board keeps its previous games only if '
                                     'nothing was written yet; otherwise load again.')
        self.root.after(100, self.poll)

    def set_busy(self, busy):
        self.busy = busy
        state = 'disabled' if busy else 'normal'
        for b in (self.add_button, self.remove_button, self.up_button, self.down_button,
                  self.load_button, self.clear_button):
            b['state'] = state

    def write_log(self, text):
        self.log['state'] = 'normal'
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log['state'] = 'disabled'


def main():
    root = tk.Tk()
    window = LoaderWindow(root)
    # Board check without showing a window: --self-test PORT ROM...
    if len(sys.argv) > 2 and sys.argv[1] == '--self-test':
        root.withdraw()
        messagebox.showwarning = messagebox.showerror = lambda title, text: print(f'{title}: {text}')
        window.port.set(sys.argv[2])
        window.add(sys.argv[3:])
        window.write_log = lambda text: print(text, flush=True)
        window.load()

        def finish():
            if window.busy:
                root.after(200, finish)
            else:
                root.destroy()
        root.after(500, finish)
    root.mainloop()
    if window.failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
