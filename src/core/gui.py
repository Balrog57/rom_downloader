import os
import threading
import time
from pathlib import Path

import requests

from ..network.metrics import prioritize_sources
from ..network.utils import format_bytes
from ..pipeline import build_pipeline_summary, merge_provider_metrics
from ..progress import format_duration
from ..version import APP_VERSION

from .api_keys import load_api_keys, save_api_keys
from .catalog import (
    build_catalog_index,
    get_catalog_system,
    list_catalog_games,
    list_catalog_sections,
    list_catalog_systems,
)
from .constants import *
from .dat_parser import parse_dat_file
from .dat_profile import (
    describe_dat_profile,
    detect_dat_profile,
    finalize_dat_profile,
    prepare_sources_for_profile,
    resolve_dat_output_folder,
)
from .download_history import list_download_history, record_download_history
from .download_orchestrator import download_missing_games_sequentially
from .env import *
from .reports import write_download_report
from .scanner import (
    build_analysis_summary,
    find_missing_games,
    find_roms_not_in_dat,
    move_files_to_tosort,
    scan_local_roms,
)
from .sources import (
    apply_source_policies,
    get_default_sources,
    optional_positive_int,
    source_order_key,
    source_policy_summary,
)
from .torrentzip import repack_verified_archives_to_torrentzip


def detect_system_name(dat_file_path: str) -> str:
    from .scanner import detect_system_name as _detect_system_name
    return _detect_system_name(dat_file_path)


def tkinterdnd_backend_responds(timeout_seconds: int = 3) -> bool:
    return False


def enable_tkinterdnd(root) -> object | None:
    return None


def gui_mode():
    """Interface catalogue sombre sans connexion ni images."""
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        from tkinter import filedialog, messagebox, ttk

        from . import _facade

        class App:
            def __init__(self, root):
                self.root = root
                self.font = "Roboto" if "Roboto" in tkfont.families() else "Segoe UI"
                self.session = requests.Session()
                self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
                self.preferences = _facade.load_preferences()
                self.default_sources = [source.copy() for source in get_default_sources()]
                self.source_enabled = dict(self.preferences.get("source_enabled", {}))
                self.source_order = list(self.preferences.get("source_order", []))
                self.source_policies = dict(self.preferences.get("source_policies", {}))
                self.provider_stats = dict(self.preferences.get("provider_stats", {}))
                self.rom_folder = tk.StringVar(value=self.preferences.get("rom_folder", ""))
                self.output_root_by_dat_var = tk.BooleanVar(value=bool(self.preferences.get("output_root_by_dat", False)))
                self.clean_torrentzip_var = tk.BooleanVar(value=bool(self.preferences.get("clean_torrentzip", False)))
                self.move_to_tosort_var = tk.BooleanVar(value=bool(self.preferences.get("move_to_tosort", False)))
                self.prefer_1fichier_var = tk.BooleanVar(value=bool(self.preferences.get("prefer_1fichier", False)))
                self.parallel_var = tk.IntVar(value=max(1, int(self.preferences.get("parallel_downloads", DEFAULT_PARALLEL_DOWNLOADS) or DEFAULT_PARALLEL_DOWNLOADS)))
                self.progress_var = tk.DoubleVar(value=0)
                self.status_var = tk.StringVar(value="Pret")
                self.system_query_var = tk.StringVar()
                self.game_query_var = tk.StringVar()
                self.history_query_var = tk.StringVar()
                self.family_filter = "all"
                self.letter_filter = "all"
                self.current_page = "home"
                self.current_system_id = ""
                self.running = False
                self.systems_tree = None
                self.games_tree = None
                self.history_tree = None
                self.log_text = None

                self.root.title(f"ROM Downloader {APP_VERSION}")
                self.root.geometry("1180x780")
                self.root.minsize(1040, 680)
                self.root.configure(bg=UI_COLOR_BG)
                self.root.columnconfigure(0, weight=1)
                self.root.rowconfigure(1, weight=1)
                self.configure_style()
                self.build_shell()
                self.show_page("home")

            def configure_style(self):
                self.style = ttk.Style(self.root)
                try:
                    self.style.theme_use("clam")
                except Exception:
                    pass
                self.style.configure("Catalog.Treeview", background=UI_COLOR_CARD_BG, foreground=UI_COLOR_TEXT_MAIN, fieldbackground=UI_COLOR_CARD_BG, bordercolor=UI_COLOR_CARD_BORDER, rowheight=30, font=(self.font, 10))
                self.style.configure("Catalog.Treeview.Heading", background=UI_COLOR_INPUT_BG, foreground=UI_COLOR_TEXT_MAIN, bordercolor=UI_COLOR_CARD_BORDER, font=(self.font, 10, "bold"))
                self.style.map("Catalog.Treeview", background=[("selected", UI_COLOR_ACCENT)])
                self.style.configure("Catalog.Horizontal.TProgressbar", troughcolor=UI_COLOR_INPUT_BG, background=UI_COLOR_ACCENT, bordercolor=UI_COLOR_CARD_BORDER, lightcolor=UI_COLOR_ACCENT, darkcolor=UI_COLOR_ACCENT)

            def persist_preferences(self):
                self.preferences.update({
                    "rom_folder": self.rom_folder.get().strip(),
                    "output_root_by_dat": bool(self.output_root_by_dat_var.get()),
                    "clean_torrentzip": bool(self.clean_torrentzip_var.get()),
                    "move_to_tosort": bool(self.move_to_tosort_var.get()),
                    "prefer_1fichier": bool(self.prefer_1fichier_var.get()),
                    "parallel_downloads": max(1, int(self.parallel_var.get() or 1)),
                    "source_enabled": self.source_enabled,
                    "source_order": self.source_order,
                    "source_policies": self.source_policies,
                    "provider_stats": self.provider_stats,
                })
                _facade.save_preferences(self.preferences)

            def build_shell(self):
                header = tk.Frame(self.root, bg="#242529", height=62, highlightbackground="#151515", highlightthickness=1)
                header.grid(row=0, column=0, sticky="ew")
                header.columnconfigure(1, weight=1)
                title = tk.Label(header, text=f"ROM Downloader {APP_VERSION}", bg="#242529", fg=UI_COLOR_TEXT_MAIN, font=(self.font, 15, "bold"))
                title.grid(row=0, column=0, padx=(18, 28), pady=14, sticky="w")
                nav = tk.Frame(header, bg="#242529")
                nav.grid(row=0, column=1, sticky="e", padx=18)
                self.nav_buttons = {}
                for page, label in [
                    ("home", "Accueil"),
                    ("systems", "Systemes"),
                    ("games", "Jeux"),
                    ("downloads", "Telechargements"),
                    ("history", "Historique"),
                    ("sources", "Sources"),
                ]:
                    btn = self.button(nav, label, lambda page=page: self.show_page(page), width=15)
                    btn.pack(side="left", padx=4)
                    self.nav_buttons[page] = btn

                self.content = tk.Frame(self.root, bg=UI_COLOR_BG)
                self.content.grid(row=1, column=0, sticky="nsew")
                self.content.columnconfigure(0, weight=1)
                self.content.rowconfigure(0, weight=1)

                footer = tk.Frame(self.root, bg=UI_COLOR_CARD_BG, highlightbackground=UI_COLOR_CARD_BORDER, highlightthickness=1)
                footer.grid(row=2, column=0, sticky="ew")
                footer.columnconfigure(0, weight=1)
                ttk.Progressbar(footer, variable=self.progress_var, maximum=100, style="Catalog.Horizontal.TProgressbar").grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 4))
                tk.Label(footer, textvariable=self.status_var, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, anchor="w", font=(self.font, 10)).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))

            def clear_content(self):
                for child in self.content.winfo_children():
                    child.destroy()

            def button(self, parent, text, command, kind="ghost", width=12):
                palette = {
                    "accent": (UI_COLOR_ACCENT, UI_COLOR_ACCENT_HOVER),
                    "danger": (UI_COLOR_ERROR, "#c0392b"),
                    "ghost": (UI_COLOR_GHOST, UI_COLOR_GHOST_HOVER),
                    "success": (UI_COLOR_SUCCESS, "#27ae60"),
                }
                bg, active = palette.get(kind, palette["ghost"])
                return tk.Button(parent, text=text, command=command, bg=bg, fg=UI_COLOR_TEXT_MAIN, activebackground=active, activeforeground=UI_COLOR_TEXT_MAIN, relief="flat", bd=0, padx=12, pady=8, width=width, font=(self.font, 10, "bold"), cursor="hand2")

            def entry(self, parent, var):
                return tk.Entry(parent, textvariable=var, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief="flat", bd=0, highlightthickness=1, highlightbackground=UI_COLOR_INPUT_BORDER, highlightcolor=UI_COLOR_ACCENT, font=(self.font, 11))

            def check(self, parent, text, var):
                return tk.Checkbutton(parent, text=text, variable=var, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, activebackground=UI_COLOR_BG, activeforeground=UI_COLOR_TEXT_MAIN, selectcolor=UI_COLOR_INPUT_BG, font=(self.font, 10))

            def page_frame(self):
                frame = tk.Frame(self.content, bg=UI_COLOR_BG)
                frame.grid(row=0, column=0, sticky="nsew", padx=36, pady=30)
                frame.columnconfigure(0, weight=1)
                frame.rowconfigure(2, weight=1)
                return frame

            def show_page(self, page):
                self.current_page = page
                self.clear_content()
                for key, btn in self.nav_buttons.items():
                    btn.configure(bg=UI_COLOR_ACCENT if key == page else UI_COLOR_GHOST)
                {
                    "home": self.build_home_page,
                    "systems": self.build_systems_page,
                    "games": self.build_games_page,
                    "downloads": self.build_downloads_page,
                    "history": self.build_history_page,
                    "sources": self.build_sources_page,
                }[page]()

            def build_home_page(self):
                frame = self.page_frame()
                systems = list_catalog_systems()
                history = list_download_history(limit=8)
                tk.Label(frame, text="Accueil", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                stats = tk.Frame(frame, bg=UI_COLOR_BG)
                stats.grid(row=1, column=0, sticky="ew", pady=(24, 16))
                for index, (label, value) in enumerate([
                    ("Systemes indexes", len(systems)),
                    ("Jeux indexes", sum(int(item.get("game_count", 0) or 0) for item in systems)),
                    ("Historique", len(list_download_history(limit=5000))),
                ]):
                    card = tk.Frame(stats, bg=UI_COLOR_CARD_BG, highlightbackground=UI_COLOR_CARD_BORDER, highlightthickness=1)
                    card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 14, 0), ipadx=18, ipady=16)
                    stats.columnconfigure(index, weight=1)
                    tk.Label(card, text=str(value), bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).pack(anchor="w")
                    tk.Label(card, text=label, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 10)).pack(anchor="w", pady=(4, 0))

                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=2, column=0, sticky="nw")
                self.button(actions, "Indexer / rafraichir", self.start_catalog_index, kind="accent", width=20).pack(side="left", padx=(0, 10))
                self.button(actions, "Parcourir les systemes", lambda: self.show_page("systems"), width=20).pack(side="left")

                recent = tk.Frame(frame, bg=UI_COLOR_BG)
                recent.grid(row=3, column=0, sticky="ew", pady=(28, 0))
                tk.Label(recent, text="Derniers telechargements", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 15, "bold")).pack(anchor="w")
                for item in history:
                    line = f"{item.get('date', '')} - {item.get('system_name', '')} - {item.get('game_name', '')} [{item.get('status', '')}]"
                    tk.Label(recent, text=line, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_SUB, anchor="w", font=(self.font, 10)).pack(fill="x", pady=3)

            def build_systems_page(self):
                frame = self.page_frame()
                top = tk.Frame(frame, bg=UI_COLOR_BG)
                top.grid(row=0, column=0, sticky="ew")
                top.columnconfigure(1, weight=1)
                tk.Label(top, text="Systemes", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                search = self.entry(top, self.system_query_var)
                search.grid(row=0, column=1, sticky="ew", padx=16, ipady=7)
                self.button(top, "Rechercher", self.refresh_systems, kind="accent", width=12).grid(row=0, column=2)

                filters = tk.Frame(frame, bg=UI_COLOR_BG)
                filters.grid(row=1, column=0, sticky="ew", pady=(18, 12))
                self.button(filters, "Tous", lambda: self.set_family_filter("all"), width=12).pack(side="left", padx=(0, 8))
                for section in list_catalog_sections():
                    width = max(12, min(22, len(section) + 2))
                    self.button(filters, section, lambda value=section: self.set_family_filter(value), width=width).pack(side="left", padx=(0, 8))

                self.systems_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("games", "size", "dat"), show="tree headings")
                self.systems_tree.heading("#0", text="Systeme")
                self.systems_tree.heading("games", text="Jeux")
                self.systems_tree.heading("size", text="Taille estimee")
                self.systems_tree.heading("dat", text="DAT")
                self.systems_tree.column("#0", width=310, anchor="w")
                self.systems_tree.column("games", width=80, anchor="e")
                self.systems_tree.column("size", width=130, anchor="e")
                self.systems_tree.column("dat", width=600, anchor="w")
                self.systems_tree.grid(row=2, column=0, sticky="nsew")
                self.systems_tree.bind("<Double-1>", lambda _event: self.open_selected_system())
                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
                self.button(actions, "Ouvrir", self.open_selected_system, kind="accent", width=14).pack(side="left", padx=(0, 10))
                self.button(actions, "Rafraichir l'index", self.start_catalog_index, width=18).pack(side="left")
                self.refresh_systems()

            def set_family_filter(self, value):
                self.family_filter = value
                self.refresh_systems()

            def refresh_systems(self):
                if not self.systems_tree:
                    return
                self.systems_tree.delete(*self.systems_tree.get_children())
                systems = list_catalog_systems({"query": self.system_query_var.get(), "section": self.family_filter})
                for item in systems:
                    self.systems_tree.insert("", "end", iid=item["system_id"], text=item["system_name"], values=(item["game_count"], format_bytes(item["total_size"]), item["dat_label"]))
                self.status_var.set(f"{len(systems)} systeme(s) affiche(s)")

            def open_selected_system(self):
                if not self.systems_tree:
                    return
                selection = self.systems_tree.selection()
                if not selection:
                    return
                self.current_system_id = selection[0]
                self.show_page("games")

            def build_games_page(self):
                frame = self.page_frame()
                system = get_catalog_system(self.current_system_id) if self.current_system_id else None
                title = system["system_name"] if system else "Jeux"
                top = tk.Frame(frame, bg=UI_COLOR_BG)
                top.grid(row=0, column=0, sticky="ew")
                top.columnconfigure(1, weight=1)
                tk.Label(top, text=title, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                self.entry(top, self.game_query_var).grid(row=0, column=1, sticky="ew", padx=16, ipady=7)
                self.button(top, "Filtrer", self.refresh_games, kind="accent", width=12).grid(row=0, column=2)

                letters = tk.Frame(frame, bg=UI_COLOR_BG)
                letters.grid(row=1, column=0, sticky="ew", pady=(18, 12))
                for value in ["all", "#"] + list("abcdefghijklmnopqrstuvwxyz"):
                    text = "Tous" if value == "all" else value.upper()
                    self.button(letters, text, lambda value=value: self.set_letter_filter(value), width=4).pack(side="left", padx=(0, 4))

                self.games_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("rom", "size", "providers"), show="tree headings")
                self.games_tree.heading("#0", text="Jeu")
                self.games_tree.heading("rom", text="ROM")
                self.games_tree.heading("size", text="Taille")
                self.games_tree.heading("providers", text="Providers")
                self.games_tree.column("#0", width=360, anchor="w")
                self.games_tree.column("rom", width=320, anchor="w")
                self.games_tree.column("size", width=100, anchor="e")
                self.games_tree.column("providers", width=90, anchor="e")
                self.games_tree.grid(row=2, column=0, sticky="nsew")

                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
                self.button(actions, "Telecharger le jeu", self.start_selected_game_download, kind="accent", width=18).pack(side="left", padx=(0, 10))
                self.button(actions, "Telecharger le systeme", self.start_system_download, kind="success", width=22).pack(side="left", padx=(0, 10))
                self.button(actions, "Retour systemes", lambda: self.show_page("systems"), width=16).pack(side="left")
                self.refresh_games()

            def set_letter_filter(self, value):
                self.letter_filter = value
                self.refresh_games()

            def refresh_games(self):
                if not self.games_tree:
                    return
                self.games_tree.delete(*self.games_tree.get_children())
                if not self.current_system_id:
                    self.status_var.set("Selectionne un systeme")
                    return
                games = list_catalog_games(self.current_system_id, self.game_query_var.get(), self.letter_filter)
                for game in games:
                    self.games_tree.insert("", "end", iid=game["game_id"], text=game["game_name"], values=(game["primary_rom"], format_bytes(game["size"]), len(game.get("providers", []))))
                self.status_var.set(f"{len(games)} jeu(x) affiche(s)")

            def build_downloads_page(self):
                frame = self.page_frame()
                tk.Label(frame, text="Telechargements", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                settings = tk.Frame(frame, bg=UI_COLOR_BG)
                settings.grid(row=1, column=0, sticky="ew", pady=(22, 16))
                settings.columnconfigure(1, weight=1)
                tk.Label(settings, text="Dossier de sortie", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 11, "bold")).grid(row=0, column=0, sticky="w")
                self.entry(settings, self.rom_folder).grid(row=0, column=1, sticky="ew", padx=12, ipady=7)
                self.button(settings, "Parcourir", self.browse_output, width=12).grid(row=0, column=2)
                self.check(settings, "Sous-dossier nomme comme le DAT", self.output_root_by_dat_var).grid(row=1, column=1, sticky="w", pady=8)
                self.check(settings, "Recompresser en ZIP TorrentZip apres validation MD5", self.clean_torrentzip_var).grid(row=2, column=1, sticky="w")
                self.check(settings, "Deplacer les fichiers hors DAT vers ToSort", self.move_to_tosort_var).grid(row=3, column=1, sticky="w")
                self.check(settings, "Privilegier les sources 1fichier configurees", self.prefer_1fichier_var).grid(row=4, column=1, sticky="w")
                tk.Label(settings, text="Parallele", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN).grid(row=5, column=0, sticky="w", pady=(8, 0))
                tk.Spinbox(settings, from_=1, to=12, textvariable=self.parallel_var, width=5, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, buttonbackground=UI_COLOR_GHOST, relief="flat").grid(row=5, column=1, sticky="w", pady=(8, 0))
                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=2, column=0, sticky="ew")
                self.button(actions, "Arreter", self.stop, kind="danger", width=12).pack(side="left")
                self.log_text = tk.Text(frame, height=16, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief="flat", wrap="word", font=(self.font, 9))
                self.log_text.grid(row=3, column=0, sticky="nsew", pady=(18, 0))

            def build_history_page(self):
                frame = self.page_frame()
                top = tk.Frame(frame, bg=UI_COLOR_BG)
                top.grid(row=0, column=0, sticky="ew")
                top.columnconfigure(1, weight=1)
                tk.Label(top, text="Historique", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                self.entry(top, self.history_query_var).grid(row=0, column=1, sticky="ew", padx=16, ipady=7)
                self.button(top, "Filtrer", self.refresh_history, kind="accent", width=12).grid(row=0, column=2)
                self.history_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("system", "provider", "status", "size", "date", "path"), show="tree headings")
                self.history_tree.heading("#0", text="Jeu")
                for col, label in [("system", "Systeme"), ("provider", "Provider"), ("status", "Statut"), ("size", "Taille"), ("date", "Date"), ("path", "Fichier")]:
                    self.history_tree.heading(col, text=label)
                self.history_tree.column("#0", width=300)
                self.history_tree.column("system", width=180)
                self.history_tree.column("provider", width=130)
                self.history_tree.column("status", width=90)
                self.history_tree.column("size", width=90, anchor="e")
                self.history_tree.column("date", width=145)
                self.history_tree.column("path", width=360)
                self.history_tree.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
                self.refresh_history()

            def refresh_history(self):
                if not self.history_tree:
                    return
                self.history_tree.delete(*self.history_tree.get_children())
                rows = list_download_history({"query": self.history_query_var.get()}, limit=500)
                for index, item in enumerate(rows):
                    self.history_tree.insert("", "end", iid=str(index), text=item.get("game_name", ""), values=(item.get("system_name", ""), item.get("provider", ""), item.get("status", ""), format_bytes(item.get("size", 0)), item.get("date", ""), item.get("file_path", "")))
                self.status_var.set(f"{len(rows)} entree(s) d'historique")

            def build_sources_page(self):
                frame = self.page_frame()
                frame.columnconfigure(0, weight=1)
                tk.Label(frame, text="Sources", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                self.sources_list = tk.Listbox(frame, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, selectbackground=UI_COLOR_ACCENT, relief="flat", font=(self.font, 10), height=18)
                self.sources_list.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
                for label, command in [
                    ("Activer/desactiver", self.toggle_source),
                    ("Monter", lambda: self.move_source(-1)),
                    ("Descendre", lambda: self.move_source(1)),
                    ("Cles API", self.open_api_settings),
                    ("Sauver", self.persist_preferences),
                ]:
                    self.button(actions, label, command, kind="accent" if label == "Sauver" else "ghost", width=16).pack(side="left", padx=(0, 8))
                self.refresh_sources_list()

            def ordered_source_names(self):
                names = self.source_order or [source["name"] for source in self.default_sources]
                known = {source["name"] for source in self.default_sources}
                for source in self.default_sources:
                    if source["name"] not in names:
                        names.append(source["name"])
                return [name for name in names if name in known]

            def refresh_sources_list(self):
                self.sources_list.delete(0, "end")
                known = {source["name"]: source for source in self.default_sources}
                for name in self.ordered_source_names():
                    source = known[name]
                    active = self.source_enabled.get(name, source.get("enabled", True))
                    stats = self.provider_stats.get(name, {})
                    speed = format_bytes(stats.get("average_speed", 0)) + "/s" if stats.get("average_speed") else ""
                    policy = source_policy_summary(self.source_policies.get(name, {}))
                    suffix = " | ".join(part for part in [policy, speed] if part)
                    self.sources_list.insert("end", f"{'[x]' if active else '[ ]'} {name} ({source.get('type', '')}) {suffix}")

            def selected_source_name(self):
                selection = self.sources_list.curselection()
                if not selection:
                    return ""
                return self.ordered_source_names()[selection[0]]

            def toggle_source(self):
                name = self.selected_source_name()
                if not name:
                    return
                known = {source["name"]: source for source in self.default_sources}
                current = self.source_enabled.get(name, known[name].get("enabled", True))
                self.source_enabled[name] = not current
                self.refresh_sources_list()
                self.persist_preferences()

            def move_source(self, delta):
                selection = self.sources_list.curselection()
                if not selection:
                    return
                names = self.ordered_source_names()
                index = selection[0]
                new_index = max(0, min(index + delta, len(names) - 1))
                if index == new_index:
                    return
                names[index], names[new_index] = names[new_index], names[index]
                self.source_order = names
                self.refresh_sources_list()
                self.sources_list.selection_set(new_index)
                self.persist_preferences()

            def browse_output(self):
                folder = filedialog.askdirectory(title="Selectionner le dossier de sortie")
                if folder:
                    self.rom_folder.set(folder)
                    self.persist_preferences()

            def selected_sources(self, dat_profile=None):
                known = {source["name"]: source for source in self.default_sources}
                sources = []
                for name in self.ordered_source_names():
                    item = known[name].copy()
                    item["enabled"] = bool(self.source_enabled.get(name, item.get("enabled", True)))
                    policy = self.source_policies.get(name, {})
                    timeout = optional_positive_int(policy.get("timeout_seconds"), minimum=3, maximum=1800)
                    quota = optional_positive_int(policy.get("quota_per_run"), minimum=1, maximum=100000)
                    if timeout is not None:
                        item["timeout_seconds"] = timeout
                    if quota is not None:
                        item["quota_per_run"] = quota
                    if policy.get("delay_seconds") is not None:
                        try:
                            item["delay_seconds"] = max(0.0, min(float(policy.get("delay_seconds")), 60.0))
                        except (TypeError, ValueError):
                            pass
                    sources.append(item)
                sources = apply_source_policies(sources, self.source_policies)
                sources = prepare_sources_for_profile(sources, dat_profile, prefer_1fichier=bool(self.prefer_1fichier_var.get()))
                return prioritize_sources(sources, self.provider_stats)

            def output_folder_for_system(self, system):
                root = self.rom_folder.get().strip()
                if not root:
                    raise ValueError("Veuillez selectionner un dossier de sortie.")
                folder = resolve_dat_output_folder(system["dat_path"], root, self.output_root_by_dat_var.get())
                os.makedirs(folder, exist_ok=True)
                return folder

            def start_catalog_index(self):
                if self.running:
                    return
                self.running = True
                self.status_var.set("Indexation du catalogue...")
                threading.Thread(target=self.run_catalog_index, daemon=True).start()

            def run_catalog_index(self):
                try:
                    result = build_catalog_index(force=True)
                    self._ui(lambda: self.status_var.set(f"Index catalogue: {result['systems']} systeme(s), {result['games']} jeu(x)"))
                    self._ui(lambda: self.show_page(self.current_page))
                except Exception as exc:
                    self._ui(lambda msg=str(exc): self.status_var.set(f"Erreur index: {msg}"))
                finally:
                    self.running = False

            def start_selected_game_download(self):
                if not self.games_tree or not self.current_system_id:
                    return
                selection = self.games_tree.selection()
                if not selection:
                    return
                game_id = selection[0]
                games = list_catalog_games(self.current_system_id)
                game = next((item for item in games if item["game_id"] == game_id), None)
                if game:
                    self.start_download_job([game])

            def start_system_download(self):
                if not self.current_system_id:
                    return
                self.start_download_job(None)

            def start_download_job(self, selected_games):
                if self.running:
                    return
                system = get_catalog_system(self.current_system_id)
                if not system:
                    self.status_var.set("Aucun systeme selectionne")
                    return
                try:
                    self.output_folder_for_system(system)
                except Exception as exc:
                    messagebox.showerror("Erreur", str(exc))
                    return
                self.persist_preferences()
                self.running = True
                self.progress_var.set(0)
                self.show_page("downloads")
                threading.Thread(target=self.run_download_job, args=(system, selected_games), daemon=True).start()

            def run_download_job(self, system, selected_games):
                started = time.time()
                try:
                    dat_profile = finalize_dat_profile(detect_dat_profile(system["dat_path"]))
                    system_name = dat_profile.get("system_name") or system["system_name"]
                    output_folder = self.output_folder_for_system(system)
                    sources = self.selected_sources(dat_profile)
                    dat_games = parse_dat_file(system["dat_path"])
                    local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(output_folder, dat_games)
                    missing_games = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
                    catalog_games = {game["game_name"]: game for game in list_catalog_games(system["system_id"])}
                    for game in missing_games:
                        catalog_game = catalog_games.get(game.get("game_name", ""))
                        if catalog_game:
                            game["game_id"] = catalog_game.get("game_id", "")
                            game["system_id"] = system["system_id"]
                    if selected_games is not None:
                        wanted = {game["game_name"] for game in selected_games}
                        missing_games = [game for game in missing_games if game.get("game_name") in wanted]
                    self.log(f"DAT detecte: {describe_dat_profile(dat_profile)}")
                    self.log(f"Jeux manquants: {len(missing_games)}")
                    if not missing_games:
                        self.status_var.set("Aucun jeu manquant")
                        return
                    result = download_missing_games_sequentially(
                        missing_games,
                        sources,
                        self.session,
                        system_name,
                        dat_profile,
                        output_folder,
                        "",
                        False,
                        None,
                        lambda value: self._ui(lambda v=value: self.progress_var.set(v)),
                        self.log,
                        lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                        is_running=lambda: self.running,
                        parallel_downloads=max(1, int(self.parallel_var.get() or 1)),
                        system_id=system["system_id"],
                    )
                    self.update_provider_stats(result)
                    if self.move_to_tosort_var.get():
                        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, output_folder)
                        if files_to_move:
                            moved, failed = move_files_to_tosort(files_to_move, output_folder, os.path.join(output_folder, "ToSort"), False)
                            self.log(f"ToSort: {moved} deplace(s), {failed} echec(s)")
                    torrentzip_summary = {"repacked": 0, "skipped": 0, "failed": 0, "deleted": 0}
                    if self.clean_torrentzip_var.get():
                        torrentzip_summary = repack_verified_archives_to_torrentzip(dat_games, output_folder, False, self.log, lambda message: self._ui(lambda msg=message: self.status_var.set(msg)), is_running=lambda: self.running)
                    report_path = write_download_report(output_folder, {
                        "dat_file": system["dat_path"],
                        "system_name": system_name,
                        "dat_profile": describe_dat_profile(dat_profile),
                        "output_folder": output_folder,
                        "source_url": "",
                        "active_sources": [source["name"] for source in sources if source.get("enabled", True)],
                        "total_dat_games": len(dat_games),
                        "missing_before": len(missing_games),
                        "resolved_items": result.get("resolved_items", []),
                        "downloaded_items": result.get("downloaded_items", []),
                        "failed_items": result.get("failed_items", []),
                        "skipped_items": result.get("skipped_items", []),
                        "not_available": result.get("not_available", []),
                        "tosort_moved": 0,
                        "tosort_failed": 0,
                        "torrentzip_repacked": torrentzip_summary.get("repacked", 0),
                        "torrentzip_skipped": torrentzip_summary.get("skipped", 0),
                        "torrentzip_deleted": torrentzip_summary.get("deleted", 0),
                        "torrentzip_failed": torrentzip_summary.get("failed", 0),
                    })
                    self.log(f"Rapport: {report_path}")
                    self._ui(lambda: self.status_var.set(f"Termine - {result.get('downloaded', 0)} telecharge(s), {result.get('failed', 0)} echec(s), {result.get('skipped', 0)} ignore(s)"))
                except Exception as exc:
                    self.log(f"ERREUR: {exc}")
                    self._ui(lambda msg=str(exc): self.status_var.set(f"Erreur: {msg}"))
                finally:
                    self.running = False
                    self.persist_preferences()

            def update_provider_stats(self, result):
                metrics = build_pipeline_summary(result or {}).get("provider_metrics", {})
                if metrics:
                    self.provider_stats = merge_provider_metrics(self.provider_stats, metrics)
                    self.persist_preferences()

            def record_history_from_result(self, system, result, started):
                elapsed = max(0.001, time.time() - started)
                for status_key, status in [("downloaded_items", "completed"), ("skipped_items", "skipped"), ("failed_items", "failed"), ("not_available", "not_found")]:
                    for item in result.get(status_key, []) or []:
                        path = item.get("downloaded_path", "")
                        size = os.path.getsize(path) if path and os.path.exists(path) else 0
                        attempts = item.get("provider_attempts") or []
                        provider = (attempts[-1].get("source") if attempts else item.get("source", ""))
                        duration = sum(float(attempt.get("duration_seconds", 0) or 0) for attempt in attempts) or elapsed
                        record_download_history({
                            "game_name": item.get("game_name", ""),
                            "system_name": system.get("system_name", ""),
                            "dat_path": system.get("dat_path", ""),
                            "provider": provider,
                            "status": status,
                            "size": size,
                            "duration_seconds": duration,
                            "average_speed": size / duration if size and duration else 0,
                            "file_path": path,
                            "error": str(item.get("error", "")),
                        })

            def stop(self):
                self.running = False
                self.status_var.set("Arret demande...")

            def log(self, message):
                self._ui(lambda msg=message: self.append_log(msg))

            def append_log(self, message):
                if self.log_text is None:
                    return
                self.log_text.configure(state="normal")
                self.log_text.insert("end", str(message) + "\n")
                self.log_text.see("end")

            def open_api_settings(self):
                window = tk.Toplevel(self.root)
                window.title("Cles API locales")
                window.configure(bg=UI_COLOR_BG)
                window.geometry("560x240")
                window.transient(self.root)
                window.columnconfigure(1, weight=1)
                keys = load_api_keys()
                fields = [
                    ("1fichier", "onefichier", keys.get("1fichier", "")),
                    ("AllDebrid", "alldebrid", keys.get("alldebrid", "")),
                    ("RealDebrid", "realdebrid", keys.get("realdebrid", "")),
                    ("archive.org compte", "archive_username", keys.get("archive_username", "")),
                    ("archive.org mot de passe", "archive_password", keys.get("archive_password", "")),
                ]
                vars_by_key = {}
                for row, (label, key, value) in enumerate(fields):
                    tk.Label(window, text=label, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN).grid(row=row, column=0, sticky="w", padx=14, pady=7)
                    var = tk.StringVar(value=value)
                    vars_by_key[key] = var
                    tk.Entry(window, textvariable=var, show="*", bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief="flat").grid(row=row, column=1, sticky="ew", padx=(8, 14), pady=7, ipady=5)

                def save_keys():
                    save_api_keys({
                        "1fichier": vars_by_key["onefichier"].get().strip(),
                        "alldebrid": vars_by_key["alldebrid"].get().strip(),
                        "realdebrid": vars_by_key["realdebrid"].get().strip(),
                        "archive_username": vars_by_key["archive_username"].get().strip(),
                        "archive_password": vars_by_key["archive_password"].get().strip(),
                    })
                    window.destroy()

                self.button(window, "Sauver", save_keys, kind="accent", width=12).grid(row=len(fields), column=1, sticky="e", padx=14, pady=12)

            def _ui(self, callback):
                if threading.current_thread() is threading.main_thread():
                    callback()
                else:
                    self.root.after(0, callback)

        root = tk.Tk()
        app = App(root)
        root.protocol("WM_DELETE_WINDOW", root.quit)
        root.mainloop()
        root.destroy()
    except Exception as e:
        print(f"Erreur GUI: {e}")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Erreur GUI", str(e))
            root.destroy()
        except Exception:
            pass


__all__ = [
    "detect_system_name",
    "tkinterdnd_backend_responds",
    "enable_tkinterdnd",
    "gui_mode",
]
