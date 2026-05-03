import os
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

from ..version import APP_VERSION
from ..progress import DownloadProgressMeter, format_duration
from ..network.utils import format_bytes

from .env import *
from .constants import *
from .dependencies import *
from .dat_parser import parse_dat_file, strip_rom_extension
from .scanner import (
    scan_local_roms,
    find_missing_games,
    find_roms_not_in_dat,
    move_files_to_tosort,
    build_analysis_summary,
    format_analysis_summary,
    analyze_dat_folder,
    print_analysis_summary,
)
from .dat_profile import (
    detect_dat_profile,
    finalize_dat_profile,
    prepare_sources_for_profile,
    describe_dat_profile,
    resolve_dat_output_folder,
)
from .sources import (
    get_default_sources,
    build_custom_source,
    normalize_source_label,
    source_order_key,
    optional_positive_int,
    source_policy_summary,
)
from .reports import write_download_report
from .torrentzip import repack_verified_archives_to_torrentzip
from .download_orchestrator import download_missing_games_sequentially
from .verification import file_exists_in_folder, verify_downloaded_md5, cleanup_invalid_download
from .interactive import create_download_session
from .diagnostics import export_diagnostic_report
from .cli import discover_dat_menu_items
from .api_keys import load_api_keys, save_api_keys


def detect_system_name(dat_file_path: str) -> str:
    from .scanner import detect_system_name as _detect_system_name
    return _detect_system_name(dat_file_path)


def tkinterdnd_backend_responds(timeout_seconds: int = 3) -> bool:
    """Teste tkdnd hors processus pour eviter de bloquer le demarrage GUI."""
    if os.environ.get('ROM_DOWNLOADER_DISABLE_DND', '').strip().lower() in {'1', 'true', 'yes', 'oui'}:
        return False

    probe = (
        "import tkinter as tk\n"
        "import tkinterdnd2\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "tkinterdnd2.TkinterDnD._require(root)\n"
        "root.destroy()\n"
    )
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, '-c', probe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
        return process.wait(timeout=timeout_seconds) == 0
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass
        return False
    except Exception:
        return False


def enable_tkinterdnd(root) -> object | None:
    """Active les methodes drop_target_register/dnd_bind sur une racine Tk."""
    if not tkinterdnd_backend_responds():
        return None
    try:
        tkinterdnd2 = import_optional_package('tkinterdnd2', auto_install=False)
        if tkinterdnd2 is None:
            return None
        tkinterdnd2.TkinterDnD._require(root)
        return tkinterdnd2
    except Exception:
        return None


def gui_mode():
    """GUI sombre inspiree de la charte Balrog Toolkit."""
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        from tkinter import filedialog, messagebox, scrolledtext, ttk
        import threading

        from . import _facade

        tkinterdnd2 = None
        has_dnd = False

        class App:
            def __init__(self, root, use_dnd=False):
                self.root = root
                self.use_dnd = use_dnd
                self.font = "Roboto" if "Roboto" in tkfont.families() else "Segoe UI"
                self.session = requests.Session()
                self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                self.preferences = _facade.load_preferences()
                self.default_sources = [source.copy() for source in get_default_sources()]
                self.source_enabled = dict(self.preferences.get('source_enabled', {}))
                self.source_order = list(self.preferences.get('source_order', []))
                self.source_policies = dict(self.preferences.get('source_policies', {}))
                self.provider_stats = dict(self.preferences.get('provider_stats', {}))
                self.source_vars = {}
                self.source_widgets = {}
                self.images = {}
                self.running = False
                self.dat_profile = finalize_dat_profile({'family': 'unknown', 'family_label': 'Inconnu', 'system_name': '', 'is_retool': False, 'retool_label': 'DAT brut'})
                self.dat_file = tk.StringVar()
                self.dat_display = tk.StringVar(value="Selectionner un DAT")
                self.dat_dropdown = None
                self.dat_menu_items = []
                self.dat_files = []
                self.rom_folder = tk.StringVar()
                self.output_root_by_dat_var = tk.BooleanVar(value=bool(self.preferences.get('output_root_by_dat', False)))
                self.myrient_url = tk.StringVar()
                self.parallel_var = tk.IntVar(value=max(1, int(self.preferences.get('parallel_downloads', DEFAULT_PARALLEL_DOWNLOADS) or DEFAULT_PARALLEL_DOWNLOADS)))
                self.analysis_candidate_var = tk.StringVar(value=str(self.preferences.get('analysis_candidate_limit', '8') or '8'))
                self.progress_var = tk.DoubleVar(value=0)
                self.clean_torrentzip_var = tk.BooleanVar(value=False)
                self.status_var = tk.StringVar(value="Pret a telecharger les jeux manquants")
                self.log_visible = tk.BooleanVar(value=bool(self.preferences.get('logs_visible', False)))
                self.hint_var = tk.StringVar(value="Selectionne un DAT du dossier dat, puis un dossier de sortie.")
                self.root.title(f"ROM Downloader {APP_VERSION}")
                self.root.geometry("1040x760")
                self.root.minsize(940, 660)
                self.root.configure(bg=UI_COLOR_BG)
                self.root.columnconfigure(0, weight=1)
                self.root.rowconfigure(0, weight=1)
                self.style = ttk.Style(self.root)
                try:
                    self.style.theme_use('clam')
                except Exception:
                    pass
                self.style.configure('Balrog.Horizontal.TProgressbar', troughcolor=UI_COLOR_INPUT_BG, background=UI_COLOR_ACCENT, bordercolor=UI_COLOR_CARD_BORDER, lightcolor=UI_COLOR_ACCENT, darkcolor=UI_COLOR_ACCENT)
                try:
                    if BALROG_WINDOW_ICON.exists():
                        self.root.iconbitmap(str(BALROG_WINDOW_ICON))
                except Exception:
                    pass
                self.images['hero'] = self.load_photo(BALROG_1G1R_ICON, 16)
                self.images['folder'] = None
                self.apply_preferences()
                self.build_ui()
                self.dat_file.trace_add('write', lambda *_: self.root.after(120, self.refresh_profile))
                if self.use_dnd:
                    self.dat_entry.drop_target_register(tkinterdnd2.DND_FILES)
                    self.rom_entry.drop_target_register(tkinterdnd2.DND_FILES)
                    self.dat_entry.dnd_bind('<<Drop>>', lambda e: self._drop(self.dat_file, e))
                    self.rom_entry.dnd_bind('<<Drop>>', lambda e: self._drop(self.rom_folder, e))
                self.refresh_profile()
                self.root.after_idle(self.fit_window_to_content)

            def load_photo(self, path, subsample):
                if not path.exists():
                    return None
                try:
                    image = tk.PhotoImage(file=str(path))
                    return image.subsample(subsample, subsample) if subsample > 1 else image
                except Exception:
                    return None

            def fit_window_to_content(self):
                """Ajuste la taille initiale de la fenetre au contenu visible."""
                self.root.update_idletasks()

                extra_width = 48
                extra_height = 56
                target_width = max(self.root.winfo_reqwidth() + extra_width, 940)
                target_height = max(self.root.winfo_reqheight() + extra_height, 660)

                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()

                target_width = min(target_width, max(screen_width - 80, 940))
                target_height = min(target_height, max(screen_height - 80, 660))

                self.root.geometry(f"{target_width}x{target_height}")

            def card(self, parent, row, expand=False):
                outer = tk.Frame(parent, bg=UI_COLOR_CARD_BG, highlightbackground=UI_COLOR_CARD_BORDER, highlightthickness=1)
                outer.grid(row=row, column=0, sticky='nsew' if expand else 'ew', padx=18, pady=(18 if row == 0 else 0, 12))
                inner = tk.Frame(outer, bg=UI_COLOR_CARD_BG)
                inner.pack(fill='both', expand=True, padx=16, pady=16)
                return inner

            def entry(self, parent, var):
                return tk.Entry(parent, textvariable=var, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', bd=0, highlightthickness=1, highlightbackground=UI_COLOR_INPUT_BORDER, highlightcolor=UI_COLOR_ACCENT, font=(self.font, 11))

            def button(self, parent, text, command, kind='ghost', width=14, image=None):
                palette = {'accent': (UI_COLOR_ACCENT, UI_COLOR_ACCENT_HOVER), 'danger': (UI_COLOR_ERROR, '#c0392b'), 'ghost': (UI_COLOR_GHOST, UI_COLOR_GHOST_HOVER)}
                bg, active = palette[kind]
                btn = tk.Button(parent, text=text, command=command, bg=bg, fg=UI_COLOR_TEXT_MAIN, activebackground=active, activeforeground=UI_COLOR_TEXT_MAIN, relief='flat', bd=0, padx=14, pady=10, width=width, font=(self.font, 10, 'bold'), cursor='hand2')
                if image:
                    btn.configure(image=image, compound='left')
                return btn

            def toggle(self, parent, text, var):
                return tk.Checkbutton(parent, text=text, variable=var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, activebackground=UI_COLOR_CARD_BG, activeforeground=UI_COLOR_TEXT_MAIN, selectcolor=UI_COLOR_INPUT_BG, anchor='w', font=(self.font, 10), disabledforeground=UI_COLOR_TEXT_SUB)

            def apply_preferences(self):
                dat_path = self.preferences.get('dat_file', '')
                dat_files = [
                    path for path in self.preferences.get('dat_files', [])
                    if path and os.path.exists(path)
                ]
                if not dat_files and dat_path and os.path.exists(dat_path):
                    dat_files = [dat_path]
                rom_folder = self.preferences.get('rom_folder', '')
                if dat_files:
                    self.set_dat_selection(dat_files, persist=False)
                if rom_folder and os.path.isdir(rom_folder):
                    self.rom_folder.set(rom_folder)

            def persist_preferences(self):
                self.preferences.update({
                    'dat_file': self.dat_file.get().strip(),
                    'dat_label': self.dat_display.get().strip(),
                    'dat_files': self.selected_dat_paths(),
                    'rom_folder': self.rom_folder.get().strip(),
                    'output_root_by_dat': bool(self.output_root_by_dat_var.get()),
                    'move_to_tosort': bool(getattr(self, 'move_to_tosort_var', tk.BooleanVar(value=False)).get()),
                    'prefer_1fichier': bool(getattr(self, 'prefer_1fichier_var', tk.BooleanVar(value=False)).get()),
                    'clean_torrentzip': bool(self.clean_torrentzip_var.get()),
                    'parallel_downloads': max(1, int(self.parallel_var.get() or 1)),
                    'analysis_candidate_limit': self.analysis_candidate_var.get().strip() or '8',
                    'logs_visible': bool(self.log_visible.get()),
                    'source_enabled': self.source_enabled,
                    'source_order': self.source_order,
                    'source_policies': self.source_policies,
                    'provider_stats': self.provider_stats,
                })
                _facade.save_preferences(self.preferences)

            def build_ui(self):
                main = tk.Frame(self.root, bg=UI_COLOR_BG)
                main.grid(row=0, column=0, sticky='nsew')
                main.columnconfigure(0, weight=1)
                main.rowconfigure(3, weight=0)

                header = self.card(main, 0)
                header.columnconfigure(1, weight=1)
                tk.Frame(header, bg=UI_COLOR_ACCENT, width=6).grid(row=0, column=0, rowspan=2, sticky='ns', padx=(0, 14))
                tk.Label(header, text=f"ROM Downloader {APP_VERSION}", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 18, 'bold')).grid(row=0, column=1, sticky='w')
                tk.Label(header, text="Charge un DAT No-Intro ou Redump retraite avec Retool, compare le dossier cible et telecharge les ROMs manquantes en DDL, puis via Minerva, puis archive.org si besoin.", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=760, font=(self.font, 10)).grid(row=1, column=1, sticky='w', pady=(2, 0))
                self.family_badge = None
                self.mode_badge = None
                if self.images.get('hero'):
                    tk.Label(header, image=self.images['hero'], bg=UI_COLOR_CARD_BG).grid(row=0, column=2, rowspan=2, sticky='e')

                fields = self.card(main, 1)
                fields.columnconfigure(1, weight=1)
                tk.Label(fields, text="Fichier DAT", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 11, 'bold')).grid(row=0, column=0, sticky='w')
                self.dat_entry = tk.Button(fields, textvariable=self.dat_display, command=self.toggle_dat_dropdown, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, activebackground=UI_COLOR_GHOST_HOVER, activeforeground=UI_COLOR_TEXT_MAIN, relief='flat', bd=0, highlightthickness=1, highlightbackground=UI_COLOR_INPUT_BORDER, font=(self.font, 11), anchor='w', cursor='hand2')
                self.dat_entry.grid(row=0, column=1, sticky='ew', padx=(14, 12), ipady=10)
                self.button(fields, "Parcourir", self.browse_dat, kind='ghost', width=12).grid(row=0, column=2, sticky='e')
                self.dat_dropdown_host = tk.Frame(fields, bg=UI_COLOR_CARD_BG)
                self.dat_dropdown_host.grid(row=1, column=1, columnspan=2, sticky='ew', padx=(14, 0), pady=(4, 0))
                self.dat_dropdown_host.grid_remove()
                self.populate_dat_menu()

                tk.Label(fields, text="Dossier de sortie", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 11, 'bold')).grid(row=2, column=0, sticky='w', pady=(14, 0))
                self.rom_entry = self.entry(fields, self.rom_folder)
                self.rom_entry.grid(row=2, column=1, sticky='ew', padx=(14, 12), pady=(14, 0), ipady=10)
                self.button(fields, "Parcourir", self.browse_rom, kind='ghost', width=12).grid(row=2, column=2, sticky='e', pady=(14, 0))
                self.toggle(fields, "Utiliser un sous-dossier nomme comme le DAT", self.output_root_by_dat_var).grid(row=3, column=1, columnspan=2, sticky='w', padx=(14, 0), pady=(8, 0))
                tk.Label(fields, textvariable=self.hint_var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=860, font=(self.font, 9)).grid(row=4, column=0, columnspan=3, sticky='w', pady=(10, 0))

                sources = self.card(main, 2)
                tk.Label(sources, text="Sources de telechargement", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 13, 'bold')).grid(row=0, column=0, sticky='w')
                source_names = ', '.join(source['name'] for source in self.default_sources)
                tk.Label(sources, text="Toutes les sources disponibles sont utilisees automatiquement. Les DDL passent avant Minerva, et archive.org reste le dernier recours.", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=880, font=(self.font, 9)).grid(row=1, column=0, sticky='w', pady=(6, 8))
                tk.Label(sources, text=source_names, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=880, font=(self.font, 9)).grid(row=2, column=0, sticky='w')
                self.button(sources, "Configurer les sources", self.open_source_settings, kind='ghost', width=20).grid(row=3, column=0, sticky='w', pady=(10, 0))
                self.move_to_tosort_var = tk.BooleanVar(value=bool(self.preferences.get('move_to_tosort', False)))
                self.prefer_1fichier_var = tk.BooleanVar(value=bool(self.preferences.get('prefer_1fichier', False)))
                self.clean_torrentzip_var.set(bool(self.preferences.get('clean_torrentzip', False)))
                self.toggle(sources, "Deplacer les ROMs hors DAT dans un sous-dossier ToSort", self.move_to_tosort_var).grid(row=4, column=0, sticky='w', pady=(14, 0))
                self.toggle(sources, "Privilegier les sources 1fichier (RetroGameSets, StartGame)", self.prefer_1fichier_var).grid(row=5, column=0, sticky='w', pady=(8, 0))
                self.toggle(sources, "Apres verification MD5, recompresser les archives en ZIP TorrentZip/RomVault", self.clean_torrentzip_var).grid(row=6, column=0, sticky='w', pady=(8, 0))
                parallel_row = tk.Frame(sources, bg=UI_COLOR_CARD_BG)
                parallel_row.grid(row=7, column=0, sticky='w', pady=(10, 0))
                tk.Label(parallel_row, text="Telechargements simultanes", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 10)).pack(side='left')
                parallel_spin = tk.Spinbox(parallel_row, from_=1, to=12, textvariable=self.parallel_var, width=5, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, buttonbackground=UI_COLOR_GHOST, relief='flat', font=(self.font, 10), command=self.persist_preferences)
                parallel_spin.pack(side='left', padx=(10, 0))
                parallel_spin.bind('<FocusOut>', lambda _event: self.persist_preferences())

                progress = self.card(main, 3)
                progress.columnconfigure(0, weight=1)
                tk.Label(progress, text="Telechargement", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 13, 'bold')).grid(row=0, column=0, sticky='w')
                ttk.Progressbar(progress, variable=self.progress_var, maximum=100, mode='determinate', style='Balrog.Horizontal.TProgressbar').grid(row=1, column=0, sticky='ew', pady=(10, 8))
                tk.Label(progress, textvariable=self.status_var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 10), justify='left', wraplength=980).grid(row=2, column=0, sticky='w')
                actions = tk.Frame(progress, bg=UI_COLOR_CARD_BG)
                actions.grid(row=3, column=0, sticky='ew', pady=(16, 0))
                actions.columnconfigure(0, weight=1)
                self.analyze_button = None
                self.start_button = self.button(actions, "Lancer le telechargement", self.start, kind='accent', width=24)
                self.start_button.grid(row=0, column=0, sticky='w', padx=(0, 10))
                self.stop_button = self.button(actions, "Arreter", self.stop, kind='danger', width=12)
                self.stop_button.grid(row=0, column=1, padx=(0, 10))
                self.stop_button.configure(state=tk.DISABLED)
                self.button(actions, "Logs", self.toggle_logs, width=10).grid(row=0, column=2, padx=(0, 10))
                self.button(actions, "Quitter", self.root.quit, width=12).grid(row=0, column=3)
                self.log_frame = tk.Frame(progress, bg=UI_COLOR_CARD_BG)
                self.log_frame.grid(row=4, column=0, sticky='nsew', pady=(12, 0))
                self.log_frame.columnconfigure(0, weight=1)
                self.log_text = tk.Text(self.log_frame, height=9, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', wrap='word', font=(self.font, 9))
                log_scroll = tk.Scrollbar(self.log_frame, orient='vertical', command=self.log_text.yview)
                self.log_text.configure(yscrollcommand=log_scroll.set)
                self.log_text.grid(row=0, column=0, sticky='nsew')
                log_scroll.grid(row=0, column=1, sticky='ns')
                if not self.log_visible.get():
                    self.log_frame.grid_remove()

            def _drop(self, variable, event):
                value = self._clean(event.data)
                if variable is self.dat_file:
                    try:
                        values = [self._clean(item) for item in self.root.tk.splitlist(event.data)]
                    except Exception:
                        values = [value]
                    self.set_dat_selection(values)
                else:
                    variable.set(value)
                    self.persist_preferences()
                return event.action

            def _clean(self, path):
                path = path.strip()
                if path.startswith('"') and path.endswith('"'):
                    path = path[1:-1]
                if path.startswith('{') and path.endswith('}'):
                    path = path[1:-1]
                return path.split('\n')[0].strip()

            def _path_key(self, path):
                return os.path.normcase(os.path.abspath(path))

            def _ui(self, callback):
                if threading.current_thread() is threading.main_thread():
                    callback()
                else:
                    self.root.after(0, callback)

            def toggle_logs(self):
                self.log_visible.set(not self.log_visible.get())
                if self.log_visible.get():
                    self.log_frame.grid()
                else:
                    self.log_frame.grid_remove()
                self.persist_preferences()

            def append_log(self, message):
                if not hasattr(self, 'log_text'):
                    return
                self.log_text.configure(state='normal')
                self.log_text.insert('end', str(message) + '\n')
                self.log_text.see('end')
                self.log_text.configure(state='normal')

            def populate_dat_menu(self):
                from .cli import discover_dat_menu_items
                self.dat_menu_items = discover_dat_menu_items()

            def close_dat_dropdown(self):
                if self.dat_dropdown is None:
                    return
                for child in self.dat_dropdown_host.winfo_children():
                    child.destroy()
                self.dat_dropdown_host.grid_remove()
                self.dat_dropdown = None

            def toggle_dat_dropdown(self):
                if self.dat_dropdown is not None:
                    self.close_dat_dropdown()
                    return
                self.open_dat_dropdown()

            def open_dat_dropdown(self):
                from .cli import discover_dat_menu_items
                self.close_dat_dropdown()
                self.dat_menu_items = discover_dat_menu_items()
                self.root.update_idletasks()

                self.dat_dropdown_host.grid()
                dropdown = self.dat_dropdown_host
                self.dat_dropdown = dropdown

                outer = tk.Frame(dropdown, bg=UI_COLOR_CARD_BORDER)
                outer.pack(fill='both', expand=True)
                controls = tk.Frame(outer, bg=UI_COLOR_INPUT_BG)
                controls.pack(fill='x')
                filter_var = tk.StringVar()
                family_var = tk.StringVar(value='all')
                search = tk.Entry(controls, textvariable=filter_var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', font=(self.font, 10))
                search.pack(fill='x', padx=8, pady=(8, 6), ipady=6)
                filter_row = tk.Frame(controls, bg=UI_COLOR_INPUT_BG)
                filter_row.pack(fill='x', padx=8, pady=(0, 6))
                selection_row = tk.Frame(controls, bg=UI_COLOR_INPUT_BG)
                selection_row.pack(fill='x', padx=8, pady=(0, 8))
                selection_label = tk.Label(selection_row, text="", bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 9), anchor='w')
                selection_label.pack(side='left', fill='x', expand=True)

                canvas = tk.Canvas(outer, bg=UI_COLOR_INPUT_BG, highlightthickness=0, bd=0, height=320)
                scrollbar = tk.Scrollbar(outer, orient='vertical', command=canvas.yview)
                content = tk.Frame(canvas, bg=UI_COLOR_INPUT_BG)
                canvas_window = canvas.create_window((0, 0), window=content, anchor='nw')
                canvas.configure(yscrollcommand=scrollbar.set)
                canvas.pack(side='left', fill='both', expand=True)
                scrollbar.pack(side='right', fill='y')

                section_font = (self.font, 10, 'italic')
                item_font = (self.font, 10)
                content.columnconfigure(0, weight=1)

                def update_scrollregion(_event=None):
                    canvas.configure(scrollregion=canvas.bbox('all'))
                    canvas.itemconfigure(canvas_window, width=canvas.winfo_width())

                def on_mousewheel(event):
                    if getattr(event, 'num', None) == 4:
                        units = -8
                    elif getattr(event, 'num', None) == 5:
                        units = 8
                    else:
                        units = -int(event.delta / 120) * 8 if event.delta else 0
                    if units:
                        canvas.yview_scroll(units, 'units')
                    return 'break'

                def bind_scroll(widget):
                    widget.bind('<MouseWheel>', on_mousewheel)
                    widget.bind('<Button-4>', on_mousewheel)
                    widget.bind('<Button-5>', on_mousewheel)

                def visible_items():
                    selected_family = family_var.get()
                    query = filter_var.get().strip().lower()
                    grouped = []
                    current_section = ''
                    current_files = []
                    for item in self.dat_menu_items:
                        if item['type'] == 'section':
                            if current_section and current_files:
                                grouped.append((current_section, current_files))
                            current_section = item['label']
                            current_files = []
                            continue
                        section_key = current_section.lower()
                        label = item['label']
                        haystack = f"{current_section} {label}".lower()
                        if selected_family != 'all' and section_key != selected_family:
                            continue
                        if query and query not in haystack:
                            continue
                        current_files.append(item)
                    if current_section and current_files:
                        grouped.append((current_section, current_files))
                    return grouped

                def refresh_selection_label():
                    count = len(self.selected_dat_paths())
                    selection_label.configure(text=f"{count} DAT selectionne(s)")

                def selected_keys():
                    return {self._path_key(path) for path in self.selected_dat_paths()}

                def toggle_menu_item(path):
                    self.toggle_dat_selection(path)
                    render_items()

                def clear_selection():
                    self.set_dat_selection([])
                    render_items()

                def render_items(*_args):
                    for child in content.winfo_children():
                        child.destroy()
                    row = 0
                    file_count = 0
                    current_selection = selected_keys()
                    for section, files in visible_items():
                        label = tk.Label(content, text=section, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_ACCENT, font=section_font, anchor='w', padx=12, pady=8)
                        label.grid(row=row, column=0, sticky='ew')
                        bind_scroll(label)
                        row += 1
                        for item in files:
                            file_count += 1
                            item_label = item['label']
                            is_selected = self._path_key(item['path']) in current_selection
                            bg_color = UI_COLOR_ACCENT if is_selected else UI_COLOR_INPUT_BG
                            active_bg = UI_COLOR_ACCENT_HOVER if is_selected else UI_COLOR_GHOST_HOVER
                            row_text = f"[x] {item_label}" if is_selected else f"[ ] {item_label}"
                            button = tk.Button(
                                content,
                                text=row_text,
                                command=lambda path=item['path']: toggle_menu_item(path),
                                bg=bg_color,
                                fg=UI_COLOR_TEXT_MAIN,
                                activebackground=active_bg,
                                activeforeground=UI_COLOR_TEXT_MAIN,
                                relief='flat',
                                bd=0,
                                font=item_font,
                                anchor='w',
                                padx=24,
                                pady=5,
                                cursor='hand2',
                            )
                            button.grid(row=row, column=0, sticky='ew')
                            bind_scroll(button)
                            row += 1
                    if file_count == 0:
                        empty = tk.Label(content, text="Aucun DAT ne correspond au filtre", bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_SUB, font=item_font, anchor='w', padx=12, pady=10)
                        empty.grid(row=0, column=0, sticky='ew')
                        bind_scroll(empty)
                    refresh_selection_label()
                    update_scrollregion()

                def set_family(value):
                    family_var.set(value)
                    render_items()

                sections = [item['label'] for item in self.dat_menu_items if item['type'] == 'section']
                for value, text in [('all', 'Tous')] + [(section.lower(), section) for section in sections]:
                    tk.Button(
                        filter_row,
                        text=text,
                        command=lambda value=value: set_family(value),
                        bg=UI_COLOR_GHOST,
                        fg=UI_COLOR_TEXT_MAIN,
                        activebackground=UI_COLOR_GHOST_HOVER,
                        activeforeground=UI_COLOR_TEXT_MAIN,
                        relief='flat',
                        bd=0,
                        padx=10,
                        pady=4,
                        font=(self.font, 9),
                        cursor='hand2',
                    ).pack(side='left', padx=(0, 6))
                tk.Button(
                    selection_row,
                    text="Effacer",
                    command=clear_selection,
                    bg=UI_COLOR_GHOST,
                    fg=UI_COLOR_TEXT_MAIN,
                    activebackground=UI_COLOR_GHOST_HOVER,
                    activeforeground=UI_COLOR_TEXT_MAIN,
                    relief='flat',
                    bd=0,
                    padx=10,
                    pady=4,
                    font=(self.font, 9),
                    cursor='hand2',
                ).pack(side='left', padx=(8, 0))
                tk.Button(
                    selection_row,
                    text="Fermer",
                    command=self.close_dat_dropdown,
                    bg=UI_COLOR_GHOST,
                    fg=UI_COLOR_TEXT_MAIN,
                    activebackground=UI_COLOR_GHOST_HOVER,
                    activeforeground=UI_COLOR_TEXT_MAIN,
                    relief='flat',
                    bd=0,
                    padx=10,
                    pady=4,
                    font=(self.font, 9),
                    cursor='hand2',
                ).pack(side='left', padx=(6, 0))

                filter_var.trace_add('write', render_items)
                content.bind('<Configure>', update_scrollregion)
                canvas.bind('<Configure>', update_scrollregion)
                for widget in (dropdown, outer, controls, filter_row, selection_row, search, canvas, content):
                    bind_scroll(widget)

                dropdown.bind('<Escape>', lambda _event: self.close_dat_dropdown())
                render_items()
                search.focus_set()
                self.root.update_idletasks()

            def select_dat(self, path, label=None):
                self.close_dat_dropdown()
                self.set_dat_selection([path], [label] if label else None)

            def browse_dat(self):
                filenames = filedialog.askopenfilenames(title="Selectionner un ou plusieurs fichiers DAT", filetypes=[("DAT files", "*.dat"), ("All files", "*.*")])
                if filenames:
                    self.set_dat_selection(list(filenames))

            def set_dat_selection(self, paths, labels=None, persist=True):
                valid_paths = []
                seen = set()
                for path in paths or []:
                    clean_path = self._clean(str(path))
                    key = self._path_key(clean_path)
                    if clean_path and os.path.exists(clean_path) and key not in seen:
                        valid_paths.append(clean_path)
                        seen.add(key)
                self.dat_files = valid_paths
                if valid_paths:
                    self.dat_file.set(valid_paths[0])
                    if len(valid_paths) == 1:
                        label = (labels or [None])[0] or os.path.basename(valid_paths[0])
                        self.dat_display.set(label)
                    else:
                        self.dat_display.set(f"{len(valid_paths)} DAT selectionnes")
                else:
                    self.dat_file.set('')
                    self.dat_display.set("Selectionner un DAT")
                if persist:
                    self.persist_preferences()

            def toggle_dat_selection(self, path):
                clean_path = self._clean(str(path))
                if not clean_path or not os.path.exists(clean_path):
                    return
                target_key = self._path_key(clean_path)
                current_paths = self.selected_dat_paths()
                current_keys = [self._path_key(item) for item in current_paths]
                if target_key in current_keys:
                    next_paths = [
                        item for item in current_paths
                        if self._path_key(item) != target_key
                    ]
                else:
                    next_paths = current_paths + [clean_path]
                self.set_dat_selection(next_paths)

            def selected_dat_paths(self):
                paths = list(getattr(self, 'dat_files', []) or [])
                if not paths and self.dat_file.get().strip():
                    paths = [self.dat_file.get().strip()]
                return [path for path in paths if path and os.path.exists(path)]

            def browse_rom(self):
                title = "Selectionner le dossier racine" if self.output_root_by_dat_var.get() else "Selectionner le dossier de sortie"
                folder = filedialog.askdirectory(title=title)
                if folder:
                    self.rom_folder.set(folder)
                    self.persist_preferences()

            def effective_rom_folder(self, dat_path=None, create=False):
                folder = resolve_dat_output_folder(
                    (dat_path or self.dat_file.get()).strip(),
                    self.rom_folder.get().strip(),
                    bool(self.output_root_by_dat_var.get()),
                )
                if create and folder:
                    os.makedirs(folder, exist_ok=True)
                return folder

            def auto_source(self):
                default_url = self.dat_profile.get('default_source_url', '')
                if default_url:
                    self.myrient_url.set(default_url)
                    self.status_var.set("URL Minerva renseignee depuis le DAT")
                else:
                    messagebox.showwarning("DAT", "Impossible de proposer une URL auto pour ce DAT.")

            def refresh_profile(self):
                path = self.dat_file.get().strip()
                profile = finalize_dat_profile(detect_dat_profile(path)) if path and os.path.exists(path) else finalize_dat_profile({'family': 'unknown', 'family_label': 'Inconnu', 'system_name': '', 'is_retool': False, 'retool_label': 'DAT brut'})
                self.dat_profile = profile
                self.hint_var.set("Les sources automatiques sont utilisees dans l'ordre DDL, Minerva, puis archive.org." if profile.get('system_name') else "Selectionne un DAT du dossier dat ou choisis un fichier manuellement.")
                if self.family_badge:
                    self.family_badge.configure(text=profile.get('family_label') if profile.get('family') != 'unknown' else "Profil manuel", bg={'no-intro': UI_COLOR_ACCENT, 'redump': UI_COLOR_SUCCESS, 'tosec': UI_COLOR_WARNING}.get(profile.get('family'), UI_COLOR_WARNING))
                if self.mode_badge:
                    self.mode_badge.configure(text="Retool / 1G1R" if profile.get('is_retool') else "DAT brut", bg=UI_COLOR_SUCCESS if profile.get('is_retool') else UI_COLOR_GHOST_HOVER)

            def selected_sources(self, dat_profile=None):
                profile = dat_profile or self.dat_profile
                order = {name: index for index, name in enumerate(self.source_order)}
                ordered_sources = sorted(
                    self.default_sources,
                    key=lambda source: (order.get(source['name'], len(order) + source_order_key(source)[0]), source_order_key(source))
                )
                sources = []
                for source in ordered_sources:
                    item = source.copy()
                    item['enabled'] = bool(self.source_enabled.get(item['name'], item.get('enabled', True)))
                    policy = self.source_policies.get(item['name'], {})
                    timeout = optional_positive_int(policy.get('timeout_seconds'), minimum=3, maximum=1800)
                    quota = optional_positive_int(policy.get('quota_per_run'), minimum=1, maximum=100000)
                    delay = policy.get('delay_seconds')
                    if timeout is not None:
                        item['timeout_seconds'] = timeout
                    if quota is not None:
                        item['quota_per_run'] = quota
                    if delay is not None:
                        try:
                            item['delay_seconds'] = max(0.0, min(float(delay), 60.0))
                        except (TypeError, ValueError):
                            pass
                    sources.append(item)
                return prepare_sources_for_profile(sources, profile, prefer_1fichier=bool(self.prefer_1fichier_var.get()))

            def provider_stats_text(self, source_name):
                stats = self.provider_stats.get(source_name)
                if not stats:
                    return ""
                attempts = int(stats.get('attempts', 0) or 0)
                if attempts <= 0:
                    return ""
                ok = int(stats.get('downloaded', 0) or 0)
                failed = int(stats.get('failed', 0) or 0)
                dry = int(stats.get('dry_run', 0) or 0)
                return f"stats {attempts} essais/{ok} ok/{failed} echec/{dry} dry"

            def update_provider_stats(self, run_summary):
                from ..pipeline import build_pipeline_summary as _bps, merge_provider_metrics as _mpm
                metrics = _bps(run_summary).get('provider_metrics', {})
                if not metrics:
                    return
                self.provider_stats = _mpm(self.provider_stats, metrics)
                self.persist_preferences()

            def open_source_settings(self):
                window = tk.Toplevel(self.root)
                window.title("Sources")
                window.configure(bg=UI_COLOR_CARD_BG)
                window.geometry("680x500")
                window.transient(self.root)
                window.columnconfigure(0, weight=1)
                window.rowconfigure(1, weight=1)

                tk.Label(window, text="Ordre et activation des sources", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 13, 'bold')).grid(row=0, column=0, sticky='w', padx=14, pady=(14, 8))
                body = tk.Frame(window, bg=UI_COLOR_CARD_BG)
                body.grid(row=1, column=0, sticky='nsew', padx=14)
                body.columnconfigure(0, weight=1)
                body.rowconfigure(0, weight=1)
                cache_status_var = tk.StringVar(value=self.cache_status_text())

                order = self.source_order or [source['name'] for source in self.default_sources]
                known = {source['name']: source for source in self.default_sources}
                for source in self.default_sources:
                    if source['name'] not in order:
                        order.append(source['name'])
                vars_by_name = {
                    name: tk.BooleanVar(value=bool(self.source_enabled.get(name, known[name].get('enabled', True))))
                    for name in order if name in known
                }
                policies_by_name = {
                    name: dict(self.source_policies.get(name, {}))
                    for name in order if name in known
                }

                listbox = tk.Listbox(body, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, selectbackground=UI_COLOR_ACCENT, relief='flat', font=(self.font, 10), height=14)
                listbox.grid(row=0, column=0, sticky='nsew')
                scrollbar = tk.Scrollbar(body, orient='vertical', command=listbox.yview)
                scrollbar.grid(row=0, column=1, sticky='ns')
                listbox.configure(yscrollcommand=scrollbar.set)

                side = tk.Frame(body, bg=UI_COLOR_CARD_BG)
                side.grid(row=0, column=2, sticky='ns', padx=(10, 0))
                enabled_var = tk.BooleanVar(value=True)
                enabled_check = self.toggle(side, "Active", enabled_var)
                enabled_check.pack(anchor='w', pady=(0, 10))
                tk.Label(side, text="Timeout requetes (s)", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 9)).pack(anchor='w', pady=(8, 2))
                timeout_var = tk.StringVar()
                timeout_entry = tk.Entry(side, textvariable=timeout_var, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', width=10, font=(self.font, 10))
                timeout_entry.pack(fill='x', pady=(0, 6), ipady=4)
                tk.Label(side, text="Quota essais/run", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 9)).pack(anchor='w', pady=(4, 2))
                quota_var = tk.StringVar()
                quota_entry = tk.Entry(side, textvariable=quota_var, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', width=10, font=(self.font, 10))
                quota_entry.pack(fill='x', pady=(0, 6), ipady=4)
                tk.Label(side, text="Delai telechargement (s)", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 9)).pack(anchor='w', pady=(4, 2))
                delay_var = tk.StringVar()
                delay_entry = tk.Entry(side, textvariable=delay_var, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', width=10, font=(self.font, 10))
                delay_entry.pack(fill='x', pady=(0, 10), ipady=4)
                tk.Label(side, text="Les passerelles servent uniquement quand une source renvoie un lien heberge.", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=155, font=(self.font, 8)).pack(anchor='w', pady=(0, 8))
                current_policy_name = {'name': None}

                def save_policy_fields():
                    name = current_policy_name.get('name')
                    if not name:
                        return
                    policy = policies_by_name.setdefault(name, {})
                    timeout = optional_positive_int(timeout_var.get().strip(), minimum=3, maximum=1800)
                    quota = optional_positive_int(quota_var.get().strip(), minimum=1, maximum=100000)
                    delay_text = delay_var.get().strip()
                    if timeout is None:
                        policy.pop('timeout_seconds', None)
                    else:
                        policy['timeout_seconds'] = timeout
                    if quota is None:
                        policy.pop('quota_per_run', None)
                    else:
                        policy['quota_per_run'] = quota
                    if not delay_text:
                        policy.pop('delay_seconds', None)
                    else:
                        try:
                            policy['delay_seconds'] = max(0.0, min(float(delay_text), 60.0))
                        except (TypeError, ValueError):
                            policy.pop('delay_seconds', None)
                    if not policy:
                        policies_by_name.pop(name, None)

                def load_policy_fields(name):
                    current_policy_name['name'] = name
                    policy = policies_by_name.get(name, {})
                    timeout_var.set(str(policy.get('timeout_seconds', '')))
                    quota_var.set(str(policy.get('quota_per_run', '')))
                    delay_var.set(str(policy.get('delay_seconds', '')))

                def render_list(selected_index=None):
                    listbox.delete(0, 'end')
                    for name in order:
                        if name not in known:
                            continue
                        mark = "[x]" if vars_by_name[name].get() else "[ ]"
                        source = known[name]
                        policy_text = source_policy_summary(policies_by_name.get(name, {}))
                        stats_text = self.provider_stats_text(name)
                        suffix_parts = [part for part in (policy_text, stats_text) if part]
                        suffix = f" - {'; '.join(suffix_parts)}" if suffix_parts else ""
                        listbox.insert('end', f"{mark} {name} ({source.get('type', '')}){suffix}")
                    if selected_index is not None and listbox.size():
                        selected_index = max(0, min(selected_index, listbox.size() - 1))
                        listbox.selection_set(selected_index)
                        listbox.activate(selected_index)
                        on_select()

                def selected_name():
                    selection = listbox.curselection()
                    if not selection:
                        return None, None
                    names = [name for name in order if name in known]
                    index = selection[0]
                    return names[index], index

                def on_select(_event=None):
                    previous = current_policy_name.get('name')
                    if previous:
                        save_policy_fields()
                    name, _index = selected_name()
                    if name:
                        enabled_var.set(vars_by_name[name].get())
                        load_policy_fields(name)

                def sync_enabled():
                    name, index = selected_name()
                    if name:
                        vars_by_name[name].set(enabled_var.get())
                        render_list(index)

                def move(delta):
                    name, index = selected_name()
                    if name is None:
                        return
                    new_index = max(0, min(index + delta, len(order) - 1))
                    order.remove(name)
                    order.insert(new_index, name)
                    render_list(new_index)

                def save_and_close():
                    save_policy_fields()
                    self.source_order = [name for name in order if name in known]
                    self.source_enabled = {name: var.get() for name, var in vars_by_name.items()}
                    self.source_policies = {name: policy for name, policy in policies_by_name.items() if policy}
                    self.persist_preferences()
                    window.destroy()
                    self.status_var.set("Configuration des sources enregistree")

                def clear_caches_and_refresh():
                    self.clear_remote_caches()
                    cache_status_var.set(self.cache_status_text())

                def clear_selected_source_cache():
                    name, _index = selected_name()
                    if not name:
                        self.status_var.set("Selectionnez une source a invalider")
                        return
                    removed = _facade.clear_caches_for_source(name)
                    cache_status_var.set(self.cache_status_text())
                    self.status_var.set(
                        f"Cache {name}: {removed.get('resolution', 0)} resolution, "
                        f"{removed.get('listing', 0)} listing supprime(s)"
                    )

                enabled_check.configure(command=sync_enabled)
                timeout_entry.bind('<FocusOut>', lambda _event: save_policy_fields())
                quota_entry.bind('<FocusOut>', lambda _event: save_policy_fields())
                delay_entry.bind('<FocusOut>', lambda _event: save_policy_fields())
                self.button(side, "Monter", lambda: move(-1), width=10).pack(fill='x', pady=(0, 8))
                self.button(side, "Descendre", lambda: move(1), width=10).pack(fill='x', pady=(0, 8))
                self.button(side, "Cles API", self.open_api_settings, width=10).pack(fill='x', pady=(8, 8))
                self.button(side, "Vider source", clear_selected_source_cache, width=10).pack(fill='x', pady=(0, 8))
                self.button(side, "Vider tout", clear_caches_and_refresh, width=10).pack(fill='x', pady=(0, 8))
                self.button(side, "Sauver", save_and_close, kind='accent', width=10).pack(fill='x', pady=(16, 8))
                self.button(side, "Annuler", window.destroy, width=10).pack(fill='x')
                tk.Label(window, textvariable=cache_status_var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, justify='left', wraplength=640, font=(self.font, 9)).grid(row=2, column=0, sticky='ew', padx=14, pady=(10, 14))
                listbox.bind('<<ListboxSelect>>', on_select)
                render_list(0)

            def open_api_settings(self):
                from .api_keys import load_api_keys, save_api_keys
                window = tk.Toplevel(self.root)
                window.title("Cles API")
                window.configure(bg=UI_COLOR_CARD_BG)
                window.geometry("600x380")
                window.transient(self.root)
                window.columnconfigure(1, weight=1)
                keys = load_api_keys()
                variables = {}
                labels = [
                    ('1fichier', '1fichier'),
                    ('alldebrid', 'AllDebrid'),
                    ('realdebrid', 'RealDebrid'),
                    ('archive_access_key', 'Archive.org access key'),
                    ('archive_secret_key', 'Archive.org secret key'),
                ]
                tk.Label(window, text="Cles API locales (.env)", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 13, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', padx=14, pady=(14, 12))
                for row, (key, label) in enumerate(labels, start=1):
                    tk.Label(window, text=label, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 10)).grid(row=row, column=0, sticky='w', padx=14, pady=6)
                    var = tk.StringVar(value=keys.get(key, ''))
                    variables[key] = var
                    tk.Entry(window, textvariable=var, show='*', bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief='flat', font=(self.font, 10)).grid(row=row, column=1, sticky='ew', padx=(8, 14), pady=6, ipady=5)

                actions = tk.Frame(window, bg=UI_COLOR_CARD_BG)
                actions.grid(row=len(labels) + 1, column=0, columnspan=2, sticky='e', padx=14, pady=(16, 0))

                def save_keys():
                    new_keys = {key: var.get().strip() for key, var in variables.items()}
                    if save_api_keys(new_keys):
                        self.status_var.set("Cles API enregistrees dans .env")
                        window.destroy()
                    else:
                        messagebox.showerror("Cles API", "Impossible d'enregistrer les cles API.")

                self.button(actions, "Sauver", save_keys, kind='accent', width=10).pack(side='left', padx=(0, 8))
                self.button(actions, "Annuler", window.destroy, width=10).pack(side='left')

            def clear_remote_caches(self):
                _facade.clear_resolution_cache()
                _facade.clear_listing_cache()
                self.status_var.set("Caches de resolution et listings vides")

            def cache_status_text(self):
                resolution_status = _facade.describe_cache_file(RESOLUTION_CACHE_FILE, RESOLUTION_CACHE_TTL_SECONDS)
                listing_status = _facade.describe_cache_file(LISTING_CACHE_FILE, LISTING_CACHE_TTL_SECONDS)
                return (
                    _facade.format_cache_status("Resolution", resolution_status)
                    + " | "
                    + _facade.format_cache_status("Listings", listing_status)
                )

            def export_diagnostic(self):
                base_folder = self.effective_rom_folder() if self.rom_folder.get().strip() else str(APP_ROOT)
                if not os.path.isdir(base_folder):
                    base_folder = str(APP_ROOT)
                filename = f"rom_downloader_diagnostic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                path = filedialog.asksaveasfilename(
                    title="Exporter le diagnostic",
                    initialdir=base_folder,
                    initialfile=filename,
                    defaultextension=".json",
                    filetypes=[("JSON", "*.json"), ("All files", "*.*")]
                )
                if not path:
                    return
                try:
                    exported = export_diagnostic_report(path)
                    self.status_var.set(f"Diagnostic exporte: {exported}")
                    messagebox.showinfo("Diagnostic", f"Diagnostic exporte:\n{exported}")
                except Exception as e:
                    messagebox.showerror("Diagnostic", f"Export impossible:\n{e}")

            def log(self, message):
                self._ui(lambda msg=message: self.append_log(msg))

            def validate_paths(self):
                dat_paths = self.selected_dat_paths()
                if not dat_paths:
                    messagebox.showerror("Erreur", "Veuillez selectionner au moins un fichier DAT valide")
                    return False
                if not self.rom_folder.get() or not os.path.exists(self.rom_folder.get()):
                    messagebox.showerror("Erreur", "Veuillez selectionner un dossier de sortie valide")
                    return False
                if self.output_root_by_dat_var.get():
                    try:
                        for dat_path in dat_paths:
                            self.effective_rom_folder(dat_path, create=True)
                    except Exception as e:
                        messagebox.showerror("Erreur", f"Impossible de creer le sous-dossier DAT:\n{e}")
                        return False
                return True

            def start_analysis(self):
                if not self.validate_paths():
                    return
                self.persist_preferences()
                self.status_var.set("Analyse du DAT et du dossier...")
                if self.analyze_button is not None:
                    self.analyze_button.configure(state=tk.DISABLED)
                threading.Thread(target=self.run_analysis, daemon=True).start()

            def run_analysis(self):
                try:
                    dat_path = self.selected_dat_paths()[0]
                    dat_profile = finalize_dat_profile(detect_dat_profile(dat_path))
                    summary = analyze_dat_folder(
                        dat_path,
                        self.effective_rom_folder(dat_path, create=True),
                        include_tosort=self.move_to_tosort_var.get(),
                        custom_sources=self.selected_sources(dat_profile),
                        candidate_limit=self.analysis_candidate_var.get().strip()
                    )
                    message = format_analysis_summary(summary)
                    status = (
                        f"Analyse: {summary['present_games']} presents, "
                        f"{summary['missing_games']} manquants, "
                        f"{format_bytes(summary['missing_size'])} estimes"
                    )
                    self._ui(lambda msg=status: self.status_var.set(msg))
                    self._ui(lambda msg=message, data=summary: self.show_analysis_window(msg, data))
                except Exception as e:
                    error_message = str(e)
                    self._ui(lambda msg=error_message: messagebox.showerror("Erreur", f"Analyse impossible:\n{msg}"))
                    self._ui(lambda: self.status_var.set("Erreur analyse"))
                finally:
                    if self.analyze_button is not None:
                        self._ui(lambda: self.analyze_button.configure(state=tk.NORMAL))

            def show_analysis_window(self, message, summary):
                samples = summary.get('candidate_samples') or []
                if not samples:
                    messagebox.showinfo("Pre-analyse", message)
                    return

                window = tk.Toplevel(self.root)
                window.title("Pre-analyse")
                window.configure(bg=UI_COLOR_CARD_BG)
                window.geometry("760x520")
                window.transient(self.root)
                window.columnconfigure(0, weight=1)
                window.rowconfigure(1, weight=1)

                top = tk.Text(window, height=12, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, relief='flat', wrap='word', font=(self.font, 9))
                top.insert('end', message)
                top.configure(state='disabled')
                top.grid(row=0, column=0, sticky='ew', padx=14, pady=(14, 10))

                listbox = tk.Listbox(window, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, selectbackground=UI_COLOR_ACCENT, relief='flat', font=(self.font, 10), height=10)
                listbox.grid(row=1, column=0, sticky='nsew', padx=14)

                page_var = tk.IntVar(value=0)
                page_size = 25
                footer = tk.Frame(window, bg=UI_COLOR_CARD_BG)
                footer.grid(row=2, column=0, sticky='ew', padx=14, pady=14)
                footer.columnconfigure(1, weight=1)
                page_label = tk.Label(footer, text="", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 9))
                page_label.grid(row=0, column=1)

                def render_page():
                    page = max(0, page_var.get())
                    start = page * page_size
                    end = min(start + page_size, len(samples))
                    listbox.delete(0, 'end')
                    for sample in samples[start:end]:
                        sources = ', '.join(sample.get('sources') or [])
                        listbox.insert('end', f"{sample.get('game_name')}: {sources or 'aucune source'}")
                    total_pages = max(1, (len(samples) + page_size - 1) // page_size)
                    page_label.configure(text=f"Page {page + 1}/{total_pages} - {len(samples)} jeu(x)")

                def move_page(delta):
                    total_pages = max(1, (len(samples) + page_size - 1) // page_size)
                    page_var.set(max(0, min(page_var.get() + delta, total_pages - 1)))
                    render_page()

                self.button(footer, "Precedent", lambda: move_page(-1), width=12).grid(row=0, column=0, sticky='w')
                self.button(footer, "Suivant", lambda: move_page(1), width=12).grid(row=0, column=2, sticky='e', padx=(8, 0))
                self.button(footer, "Fermer", window.destroy, kind='accent', width=10).grid(row=0, column=3, sticky='e', padx=(8, 0))
                render_page()

            def start(self):
                if not self.validate_paths():
                    return
                self.persist_preferences()
                self.running = True
                self.start_button.configure(state=tk.DISABLED)
                self.stop_button.configure(state=tk.NORMAL)
                self.progress_var.set(0)
                self.status_var.set("Preparation de l'analyse du DAT...")
                threading.Thread(target=self.run_download, daemon=True).start()

            def stop(self):
                self.running = False
                self.status_var.set("Arret en cours...")

            def run_download(self):
                dat_paths = self.selected_dat_paths()
                total = len(dat_paths)
                totals = {'downloaded': 0, 'failed': 0, 'skipped': 0, 'completed': 0}
                for dat_index, dat_path in enumerate(dat_paths, start=1):
                    if not self.running:
                        break
                    if total > 1:
                        label = os.path.basename(dat_path)
                        self.log(f"DAT {dat_index}/{total}: {label}")
                        self._ui(lambda idx=dat_index, count=total, name=label: self.status_var.set(f"DAT {idx}/{count}: {name}"))
                    result = self.run_download_one(dat_path, dat_index, total)
                    if result:
                        totals['completed'] += 1
                        totals['downloaded'] += int(result.get('downloaded', 0) or 0)
                        totals['failed'] += int(result.get('failed', 0) or 0)
                        totals['skipped'] += int(result.get('skipped', 0) or 0)
                if total > 1 and totals['completed']:
                    self._ui(lambda data=totals: messagebox.showinfo(
                        "Termine",
                        "Telechargements DAT termines.\n\n"
                        f"DAT traites: {data['completed']}/{total}\n"
                        f"Telecharges: {data['downloaded']}\n"
                        f"Echecs: {data['failed']}\n"
                        f"Ignores: {data['skipped']}"
                    ))

            def run_download_one(self, dat_path=None, dat_index=1, dat_total=1):
                try:
                    dat_path = (dat_path or self.dat_file.get()).strip()
                    rom_folder = self.effective_rom_folder(dat_path, create=True)
                    prefix = f"DAT {dat_index}/{dat_total} - " if dat_total > 1 else ""
                    source_url = ''
                    dat_profile = finalize_dat_profile(detect_dat_profile(dat_path))
                    system_name = dat_profile.get('system_name') or detect_system_name(dat_path)
                    sources = self.selected_sources(dat_profile)
                    dat_games = parse_dat_file(dat_path)
                    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)
                    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
                    analysis_summary = build_analysis_summary(dat_path, rom_folder, dat_games, missing_games, dat_profile, sources)
                    self.log(format_analysis_summary(analysis_summary))
                    self._ui(lambda summary=analysis_summary, msg_prefix=prefix: self.status_var.set(
                        f"{msg_prefix}Analyse: {summary['present_games']} presents, {summary['missing_games']} manquants"
                    ))
                    downloaded_items = []
                    failed_items = []
                    skipped_items = []
                    to_download = []
                    not_available = []
                    moved = move_failed = 0
                    torrentzip_summary = {'repacked': 0, 'skipped': 0, 'failed': 0, 'deleted': 0}
                    if not missing_games:
                        if self.move_to_tosort_var.get():
                            tosort_folder = os.path.join(rom_folder, "ToSort")
                            files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
                            if files_to_move:
                                moved, move_failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, False)
                                self.log(f"ToSort -> deplaces: {moved}, echecs: {move_failed}")
                        if self.clean_torrentzip_var.get():
                            torrentzip_summary = repack_verified_archives_to_torrentzip(
                                dat_games,
                                rom_folder,
                                False,
                                self.log,
                                lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                                is_running=lambda: self.running
                            )
                        report_path = write_download_report(rom_folder, {
                            'dat_file': dat_path,
                            'system_name': system_name,
                            'dat_profile': describe_dat_profile(dat_profile),
                            'output_folder': rom_folder,
                            'source_url': source_url,
                            'active_sources': [s['name'] for s in sources if s.get('enabled', True)],
                            'total_dat_games': len(dat_games),
                            'missing_before': 0,
                            'resolved_items': [],
                            'downloaded_items': [],
                            'failed_items': [],
                            'skipped_items': [],
                            'not_available': [],
                            'tosort_moved': moved,
                            'tosort_failed': move_failed,
                            'torrentzip_repacked': torrentzip_summary.get('repacked', 0),
                            'torrentzip_skipped': torrentzip_summary.get('skipped', 0),
                            'torrentzip_deleted': torrentzip_summary.get('deleted', 0),
                            'torrentzip_failed': torrentzip_summary.get('failed', 0),
                        })
                        self.status_var.set(f"{prefix}Termine - dossier deja complet")
                        if dat_total <= 1:
                            self._ui(lambda path=report_path: messagebox.showinfo("Termine", f"Tous les jeux du DAT sont deja presents localement.\n\nRapport:\n{path}"))
                        return {'downloaded': 0, 'failed': 0, 'skipped': 0}
                    self.log(f"DAT detecte: {describe_dat_profile(dat_profile)}")
                    self.log(f"Sources actives: {', '.join([s['name'] for s in sources if s.get('enabled', True)])}")
                    progress = lambda value: self._ui(lambda: self.progress_var.set(value))
                    status_callback = lambda message: self._ui(lambda msg=message: self.status_var.set(msg))
                    result = download_missing_games_sequentially(
                        missing_games,
                        sources,
                        self.session,
                        system_name,
                        dat_profile,
                        rom_folder,
                        source_url,
                        False,
                        None,
                        progress,
                        self.log,
                        status_callback,
                        is_running=lambda: self.running,
                        parallel_downloads=max(1, int(self.parallel_var.get() or 1))
                    )
                    to_download = result['resolved_items']
                    not_available = result['not_available']
                    downloaded_items = result['downloaded_items']
                    failed_items = result['failed_items']
                    skipped_items = result['skipped_items']
                    self.update_provider_stats({
                        'resolved_items': to_download,
                        'failed_items': failed_items,
                        'not_available': not_available,
                    })
                    if not_available:
                        self.log(f"{len(not_available)} jeux non disponibles:")
                        for game in not_available[:20]:
                            self.log(f"  - {game['game_name']}")
                    if not to_download and not not_available:
                        self.status_var.set(f"{prefix}Aucun jeu trouve sur les sources")
                        if dat_total <= 1:
                            self._ui(lambda: messagebox.showwarning("Attention", "Aucun jeu manquant n'a ete trouve sur les sources actives."))
                        return {'downloaded': 0, 'failed': 0, 'skipped': 0}
                    downloaded = result['downloaded']
                    failed = result['failed']
                    skipped = result['skipped']
                    if self.move_to_tosort_var.get():
                        tosort_folder = os.path.join(rom_folder, "ToSort")
                        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, rom_folder)
                        if files_to_move:
                            moved, move_failed = move_files_to_tosort(files_to_move, rom_folder, tosort_folder, False)
                            self.log(f"ToSort -> deplaces: {moved}, echecs: {move_failed}")
                    if self.clean_torrentzip_var.get():
                        torrentzip_summary = repack_verified_archives_to_torrentzip(
                            dat_games,
                            rom_folder,
                            False,
                            self.log,
                            status_callback,
                            is_running=lambda: self.running
                        )
                    report_path = write_download_report(rom_folder, {
                        'dat_file': dat_path,
                        'system_name': system_name,
                        'dat_profile': describe_dat_profile(dat_profile),
                        'output_folder': rom_folder,
                        'source_url': source_url,
                        'active_sources': [s['name'] for s in sources if s.get('enabled', True)],
                        'total_dat_games': len(dat_games),
                        'missing_before': len(missing_games),
                        'resolved_items': to_download,
                        'downloaded_items': downloaded_items,
                        'failed_items': failed_items,
                        'skipped_items': skipped_items,
                        'not_available': not_available,
                        'tosort_moved': moved,
                        'tosort_failed': move_failed,
                        'torrentzip_repacked': torrentzip_summary.get('repacked', 0),
                        'torrentzip_skipped': torrentzip_summary.get('skipped', 0),
                        'torrentzip_deleted': torrentzip_summary.get('deleted', 0),
                        'torrentzip_failed': torrentzip_summary.get('failed', 0),
                    })
                    self.status_var.set(f"{prefix}Termine - {downloaded} telecharge(s)")
                    if dat_total <= 1:
                        self._ui(lambda path=report_path: messagebox.showinfo("Termine", f"Telechargement termine.\n\nTelecharges: {downloaded}\nEchecs: {failed}\nIgnores: {skipped}\n\nRapport:\n{path}"))
                    return {'downloaded': downloaded, 'failed': failed, 'skipped': skipped}
                except Exception as e:
                    self.running = False
                    error_message = str(e)
                    self.log(f"ERREUR: {error_message}")
                    self.status_var.set("Erreur")
                    self._ui(lambda msg=error_message: messagebox.showerror("Erreur", f"Une erreur est survenue:\n{msg}"))
                finally:
                    should_finish = dat_total <= 1 or dat_index >= dat_total or not self.running
                    if should_finish:
                        self.running = False
                        self._ui(lambda: (self.start_button.configure(state=tk.NORMAL), self.stop_button.configure(state=tk.DISABLED)))

        root = tk.Tk()
        tkinterdnd2 = enable_tkinterdnd(root)
        has_dnd = tkinterdnd2 is not None
        app = App(root, use_dnd=has_dnd)
        if not has_dnd:
            app.status_var.set("Pret - glisser-deposer indisponible, boutons Parcourir actifs")
        root.protocol("WM_DELETE_WINDOW", root.quit)
        root.mainloop()
        root.destroy()
    except Exception as e:
        error_message = f"Erreur GUI: {e}"
        log_path = APP_ROOT / "rom_downloader_gui_error.log"
        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                log_file.write(error_message + "\n")
        except Exception:
            pass
        print(error_message)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("ROM Downloader", f"{error_message}\n\nDetail ecrit dans:\n{log_path}")
            root.destroy()
        except Exception:
            pass


__all__ = [
    'detect_system_name',
    'tkinterdnd_backend_responds',
    'enable_tkinterdnd',
    'gui_mode',
]
