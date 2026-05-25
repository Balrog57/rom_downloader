import os
import queue
import threading
import time
from pathlib import Path

import requests

from ..network.metrics import prioritize_sources
from ..network.circuits import SourceCircuitBreaker
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
from .config_profiles import CONFIG_PROFILE_LABELS, config_profile_settings
from .dat_parser import parse_dat_file
from .dat_profile import (
    describe_dat_profile,
    detect_dat_profile,
    finalize_dat_profile,
    prepare_sources_for_profile,
    resolve_dat_output_folder,
)
from .local_database import dashboard_stats, load_circuit_states, save_circuit_states
from .download_history import list_download_history, record_download_history
from .download_orchestrator import download_missing_games_sequentially
from .download_single import download_single_game, auto_extract_and_repack
from .env import *
from .reports import write_download_report, write_download_reports
from .scanner import (
    build_analysis_summary,
    estimate_games_size,
    find_missing_games,
    find_roms_not_in_dat,
    move_files_to_tosort,
    scan_local_roms,
)
from .local_database import dashboard_stats, system_coverage_data
from .sources import (
    apply_source_policies,
    get_default_sources,
    optional_positive_int,
    source_order_key,
    source_policy_summary,
    resolve_system_mapping,
)

_FAMILY_FILTERS = [
    ("Tous", "all"),
    ("No-Intro", "no-intro"),
    ("Redump", "redump"),
    ("Retool", "retool"),
    ("Arcade", "arcade"),
    ("Console", "console"),
    ("Portable", "portable"),
    ("Computer", "computer"),
    ("Port", "port"),
    ("Pinball", "pinball"),
    ("Custom", "custom"),
    ("Non-Redump", "non-redump"),
    ("Source Code", "source-code"),
]

_COVERAGE_BADGES = [
    ("OK", UI_COLOR_SUCCESS),
    ("PARTIEL", UI_COLOR_TEXT_SUB),
    ("A MAPPER", UI_COLOR_ERROR),
    ("LOCAL", UI_COLOR_ACCENT),
]
from .torrentzip import repack_verified_archives_to_torrentzip


def _resolve_per_system_stats(provider_stats: dict, provider_name: str, system_name: str) -> dict:
    """Extrait les metriques per-systeme (cle composite 'provider::systeme') si disponibles."""
    key = f"{provider_name}::{system_name}"
    return provider_stats.get(key, {})


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
                self.download_job_id = ""
                self.circuit_breaker = SourceCircuitBreaker()
                saved_states = load_circuit_states()
                for source_name, state in saved_states.items():
                    if state.get("failures", 0) >= self.circuit_breaker.threshold:
                        for _ in range(state["failures"]):
                            self.circuit_breaker.record_failure(source_name)
                    for etype, edata in state.get("by_type", {}).items():
                        for _ in range(edata.get("failures", 0)):
                            self.circuit_breaker.record_failure(source_name, etype)
                self._schedule_circuit_persist()
                self.download_queue: queue.Queue = queue.Queue()
                self.download_results: list = []
                self.downloads_tab = tk.StringVar(value="queue")
                self.rom_folder = tk.StringVar(value=self.preferences.get("rom_folder", ""))
                self.output_root_by_dat_var = tk.BooleanVar(value=bool(self.preferences.get("output_root_by_dat", False)))
                self.auto_extract_var = tk.BooleanVar(value=bool(self.preferences.get("auto_extract", True)))
                self.clean_torrentzip_var = tk.BooleanVar(value=bool(self.preferences.get("clean_torrentzip", True)))
                self.move_to_tosort_var = tk.BooleanVar(value=bool(self.preferences.get("move_to_tosort", False)))
                self.prefer_1fichier_var = tk.BooleanVar(value=bool(self.preferences.get("prefer_1fichier", False)))
                self.audit_only_var = tk.BooleanVar(value=bool(self.preferences.get("audit_only", False)))
                self.parallel_var = tk.IntVar(value=max(1, int(self.preferences.get("parallel_downloads", DEFAULT_PARALLEL_DOWNLOADS) or DEFAULT_PARALLEL_DOWNLOADS)))
                self.profile_var = tk.StringVar(value=str(self.preferences.get("profile", "")))
                self.progress_var = tk.DoubleVar(value=0)
                self.status_var = tk.StringVar(value="Pret")
                self.system_query_var = tk.StringVar()
                self.game_query_var = tk.StringVar()
                self.history_query_var = tk.StringVar()
                self.family_filter = "all"
                self.letter_filter = "all"
                self.games_filter = "all"
                self.current_page = "home"
                self.current_system_id = ""
                self.dat_games = {}
                self.dat_profile = {}
                self.missing_games = []
                self.local_signature_index = {}
                self.running = False
                self.download_worker_running = False
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
                self.root.after(1000, self._startup_cleanup)

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
                    "auto_extract": bool(self.auto_extract_var.get()),
                    "move_to_tosort": bool(self.move_to_tosort_var.get()),
                    "prefer_1fichier": bool(self.prefer_1fichier_var.get()),
                    "audit_only": bool(self.audit_only_var.get()),
                    "parallel_downloads": max(1, int(self.parallel_var.get() or 1)),
                    "profile": self.profile_var.get(),
                    "source_enabled": self.source_enabled,
                    "source_order": self.source_order,
                    "source_policies": self.source_policies,
                    "provider_stats": self.provider_stats,
                })
                _facade.save_preferences(self.preferences)

            def _apply_profile(self, event=None):
                settings = config_profile_settings(self.profile_var.get())
                if not settings:
                    return
                self.audit_only_var.set(bool(settings.get("dry_run", False)))
                self.parallel_var.set(max(1, int(settings.get("parallel", self.parallel_var.get()) or 1)))
                self.clean_torrentzip_var.set(bool(settings.get("clean_torrentzip", False)))
                self.move_to_tosort_var.set(bool(settings.get("tosort", False)))
                self.prefer_1fichier_var.set(bool(settings.get("prefer_1fichier", False)))
                self.persist_preferences()

            def _schedule_circuit_persist(self):
                def _persist():
                    try:
                        save_circuit_states(self.circuit_breaker)
                    except Exception:
                        pass
                    self.root.after(300000, _persist)
                self.root.after(300000, _persist)

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
                    ("dat", "Charger DAT"),
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
                    "dat": self.build_dat_page,
                    "systems": self.build_systems_page,
                    "games": self.build_games_page,
                    "downloads": self.build_downloads_page,
                    "history": self.build_history_page,
                    "sources": self.build_sources_page,
                }[page]()
                if page == "downloads" and (self.running or self.download_worker_running):
                    self._auto_refresh_downloads()

            def build_home_page(self):
                frame = self.page_frame()
                stats = dashboard_stats()
                tk.Label(frame, text="Accueil", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                cards = tk.Frame(frame, bg=UI_COLOR_BG)
                cards.grid(row=1, column=0, sticky="ew", pady=(20, 10))
                card_data = [
                    ("Systemes indexes", stats["systems"]),
                    ("Jeux indexes", stats["games"]),
                    ("Jeux verifies localement", stats["verified"]),
                    ("Providers valides", stats["valid_providers"]),
                    ("Tentatives 24h", stats["attempts_24h"]),
                    ("Vitesse moyenne globale", f"{format_bytes(stats['average_speed'])}/s" if stats["average_speed"] else "—"),
                ]
                for index, (label, value) in enumerate(card_data):
                    col = index % 3
                    row = index // 3
                    card = tk.Frame(cards, bg=UI_COLOR_CARD_BG, highlightbackground=UI_COLOR_CARD_BORDER, highlightthickness=1)
                    card.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 10, 0), pady=(0, 10), ipadx=14, ipady=12)
                    cards.columnconfigure(col, weight=1)
                    tk.Label(card, text=str(value), bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 20, "bold")).pack(anchor="w")
                    tk.Label(card, text=label, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 9)).pack(anchor="w", pady=(3, 0))

                jobs = stats.get("jobs", {})
                statuses = tk.Frame(frame, bg=UI_COLOR_BG)
                statuses.grid(row=2, column=0, sticky="ew", pady=(10, 14))
                for idx, (suffix, label, color) in enumerate([
                    ("active", "Actifs", UI_COLOR_ACCENT),
                    ("paused", "En pause", UI_COLOR_TEXT_SUB),
                    ("failed", "Echoues", UI_COLOR_ERROR),
                    ("completed", "Termines", UI_COLOR_SUCCESS),
                ]):
                    badge = tk.Frame(statuses, bg=UI_COLOR_CARD_BG, highlightbackground=color, highlightthickness=2)
                    badge.pack(side="left", padx=(0, 10), ipadx=10, ipady=6)
                    tk.Label(badge, text=str(jobs.get(suffix, 0)), bg=UI_COLOR_CARD_BG, fg=color, font=(self.font, 16, "bold")).pack(side="left")
                    tk.Label(badge, text=f" {label}", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 9)).pack(side="left", padx=(4, 0))

                blocked = stats.get("blocked_sources", [])
                if blocked:
                    alert = tk.Frame(frame, bg=UI_COLOR_CARD_BG, highlightbackground=UI_COLOR_ERROR, highlightthickness=1)
                    alert.grid(row=3, column=0, sticky="ew", pady=(0, 14), ipadx=12, ipady=10)
                    tk.Label(alert, text=f"Sources bloquees (circuit breaker): {', '.join(blocked)}", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_ERROR, font=(self.font, 10, "bold")).pack(anchor="w")

                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=4, column=0, sticky="nw")
                self.button(actions, "Indexer / rafraichir", self.start_catalog_index, kind="accent", width=20).pack(side="left", padx=(0, 10))
                self.button(actions, "Parcourir les systemes", lambda: self.show_page("systems"), width=20).pack(side="left")

                history = list_download_history(limit=8)
                recent = tk.Frame(frame, bg=UI_COLOR_BG)
                recent.grid(row=5, column=0, sticky="ew", pady=(20, 0))
                tk.Label(recent, text="Derniers telechargements", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 15, "bold")).pack(anchor="w")
                for item in history:
                    line = f"{item.get('date', '')} - {item.get('system_name', '')} - {item.get('game_name', '')} [{item.get('status', '')}]"
                    tk.Label(recent, text=line, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_SUB, anchor="w", font=(self.font, 10)).pack(fill="x", pady=3)

            def build_dat_page(self):
                frame = self.page_frame()
                tk.Label(frame, text="Charger un DAT", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")

                dat_info = tk.Frame(frame, bg=UI_COLOR_CARD_BG, highlightbackground=UI_COLOR_CARD_BORDER, highlightthickness=1)
                dat_info.grid(row=1, column=0, sticky="ew", pady=(18, 0), ipadx=14, ipady=12)
                dat_info.columnconfigure(1, weight=1)

                self.dat_path_var = tk.StringVar(value=self.preferences.get("last_dat_path", ""))
                tk.Label(dat_info, text="Fichier DAT", bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 11, "bold")).grid(row=0, column=0, sticky="w", padx=(10, 8))
                self.entry(dat_info, self.dat_path_var).grid(row=0, column=1, sticky="ew", padx=(0, 8), ipady=7)
                self.button(dat_info, "Parcourir", self.browse_dat_file, width=12).grid(row=0, column=2, padx=(0, 10))

                self.dat_label = tk.StringVar(value="Aucun DAT charge")
                tk.Label(dat_info, textvariable=self.dat_label, bg=UI_COLOR_CARD_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 10)).grid(row=1, column=0, columnspan=3, sticky="w", padx=(10, 10), pady=(8, 0))

                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=2, column=0, sticky="ew", pady=(18, 0))
                self.button(actions, "Charger le DAT", self.load_dat_file, kind="accent", width=20).pack(side="left", padx=(0, 10))
                self.button(actions, "Scanner le dossier", self.scan_rom_folder, width=20).pack(side="left", padx=(0, 10))

                self.dat_results_var = tk.StringVar(value="")
                tk.Label(frame, textvariable=self.dat_results_var, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 10)).grid(row=3, column=0, sticky="w", pady=(10, 0))

                if self.dat_games and self.dat_profile:
                    profile_desc = describe_dat_profile(self.dat_profile) if self.dat_profile else "Inconnu"
                    total = len(self.dat_games)
                    missing = len(self.missing_games) if self.missing_games else "?"
                    self.dat_results_var.set(f"DAT: {profile_desc} | {total} jeux | {missing} manquants")

            def browse_dat_file(self):
                from tkinter import filedialog
                path = filedialog.askopenfilename(title="Selectionner un fichier DAT", filetypes=[("DAT files", "*.dat *.xml"), ("All files", "*.*")])
                if path:
                    self.dat_path_var.set(path)
                    self.preferences["last_dat_path"] = path
                    self.persist_preferences()

            def load_dat_file(self):
                dat_path = self.dat_path_var.get().strip()
                if not dat_path or not os.path.isfile(dat_path):
                    self.dat_label.set("Fichier DAT introuvable")
                    return
                self.dat_games = parse_dat_file(dat_path)
                self.dat_profile = finalize_dat_profile(detect_dat_profile(dat_path))
                profile_desc = describe_dat_profile(self.dat_profile) if self.dat_profile else "Inconnu"
                total = len(self.dat_games)
                self.dat_label.set(f"DAT charge: {profile_desc} - {total} jeux")
                self.missing_games = []
                self.dat_results_var.set(f"DAT: {profile_desc} | {total} jeux | Cliquez sur 'Scanner le dossier' pour detecter les manquants")

            def scan_rom_folder(self):
                rom_folder = self.rom_folder.get().strip()
                if not rom_folder:
                    self.dat_results_var.set("Erreur: Selectionnez un dossier de sortie dans les Telechargements d'abord")
                    self.show_page("downloads")
                    return
                if not self.dat_games:
                    self.dat_results_var.set("Erreur: Chargez un DAT d'abord")
                    return
                self.running = True
                self.dat_results_var.set("Scan en cours...")
                threading.Thread(target=self.run_scan_rom_folder, args=(rom_folder,), daemon=True).start()

            def run_scan_rom_folder(self, rom_folder):
                try:
                    output_folder = rom_folder
                    if self.output_root_by_dat_var.get() and self.dat_profile:
                        output_folder = resolve_dat_output_folder(self.dat_profile.get('dat_path', ''), rom_folder, True)
                        os.makedirs(output_folder, exist_ok=True)
                    local_roms, local_roms_normalized, local_game_names, self.local_signature_index = scan_local_roms(output_folder, self.dat_games)
                    self.missing_games = find_missing_games(self.dat_games, local_roms, local_roms_normalized, local_game_names, self.local_signature_index)
                    total = len(self.dat_games)
                    present = total - len(self.missing_games)
                    missing_size, _missing_unknown = estimate_games_size(self.missing_games)
                    profile_desc = describe_dat_profile(self.dat_profile) if self.dat_profile else "Inconnu"
                    msg = f"DAT: {profile_desc} | {total} jeux, {present} presents, {len(self.missing_games)} manquants | {format_bytes(missing_size)} a auditer"
                    self._ui(lambda m=msg: self.dat_results_var.set(m))
                    self._ui(lambda: self.show_page("games"))
                except Exception as exc:
                    self._ui(lambda m=str(exc): self.dat_results_var.set(f"Erreur: {m}"))
                finally:
                    self.running = False

            def build_systems_page(self):
                frame = self.page_frame()
                top = tk.Frame(frame, bg=UI_COLOR_BG)
                top.grid(row=0, column=0, sticky="ew")
                top.columnconfigure(1, weight=1)
                tk.Label(top, text="Systemes", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                search = self.entry(top, self.system_query_var)
                search.grid(row=0, column=1, sticky="ew", padx=16, ipady=7)
                search.bind("<Return>", lambda _event: self.refresh_systems())
                self.button(top, "Rechercher", self.refresh_systems, kind="accent", width=12).grid(row=0, column=2)

                filters = tk.Frame(frame, bg=UI_COLOR_BG)
                filters.grid(row=1, column=0, sticky="ew", pady=(18, 12))
                sections = list_catalog_sections()
                filter_items = [("Tous", "all")] + [(s.replace("-", " ").title(), s) for s in sections]
                for label, value in filter_items:
                    w = max(12, min(22, len(label) + 2))
                    self.button(filters, label, lambda v=value: self.set_family_filter(v), width=w).pack(side="left", padx=(0, 5))

                self.systems_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("coverage", "section", "games", "size", "date"), show="tree headings")
                self.systems_tree.heading("#0", text="Systeme")
                self.systems_tree.heading("coverage", text="Couverture")
                self.systems_tree.heading("section", text="Section DAT")
                self.systems_tree.heading("games", text="Jeux")
                self.systems_tree.heading("size", text="Taille")
                self.systems_tree.heading("date", text="Date DAT")
                self.systems_tree.column("#0", width=280, anchor="w")
                self.systems_tree.column("coverage", width=120, anchor="center")
                self.systems_tree.column("section", width=140, anchor="w")
                self.systems_tree.column("games", width=70, anchor="e")
                self.systems_tree.column("size", width=110, anchor="e")
                self.systems_tree.column("date", width=100, anchor="w")
                self.systems_tree.grid(row=2, column=0, sticky="nsew")
                self.systems_tree.bind("<Double-1>", lambda _event: self.open_selected_system())
                self.systems_tree.bind("<ButtonRelease-1>", lambda e: self._on_systems_sort(e) if e.x < 0 or self.systems_tree.identify_region(e.x, e.y) == "heading" else None)
                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
                self.button(actions, "Ouvrir", self.open_selected_system, kind="accent", width=14).pack(side="left", padx=(0, 10))
                self.button(actions, "Rafraichir l'index", self.start_catalog_index, width=18).pack(side="left")
                self.refresh_systems()

            def _on_systems_sort(self, event):
                region = self.systems_tree.identify_region(event.x, event.y)
                if region != "heading":
                    return
                col = self.systems_tree.identify_column(event.x)
                items = [(self.systems_tree.set(item, col), item) for item in self.systems_tree.get_children("")]
                col_key = {1: "system_name", 2: "games", 3: "size", 4: "date"}.get(int(col.replace("#", "")), "system_name")
                self._systems_sort_reverse = not getattr(self, "_systems_sort_reverse", True)
                if col_key == "size":
                    items.sort(key=lambda x: self._parse_size(x[0]), reverse=self._systems_sort_reverse)
                elif col_key == "games":
                    items.sort(key=lambda x: int(x[0] or 0), reverse=self._systems_sort_reverse)
                else:
                    items.sort(reverse=self._systems_sort_reverse)
                for idx, (_, item) in enumerate(items):
                    self.systems_tree.move(item, "", idx)

            def _parse_size(self, val: str) -> int:
                val = (val or "").strip().lower()
                if val.endswith("tb"):
                    return int(float(val[:-2]) * 1024 * 1024 * 1024 * 1024)
                if val.endswith("gb"):
                    return int(float(val[:-2]) * 1024 * 1024 * 1024)
                if val.endswith("mb"):
                    return int(float(val[:-2]) * 1024 * 1024)
                if val.endswith("kb"):
                    return int(float(val[:-2]) * 1024)
                try:
                    return int(float(val))
                except ValueError:
                    return 0

            def _coverage_badge(self, item):
                if item.get("verified_local", 0) >= item.get("game_count", 1):
                    return "LOCAL"
                if item.get("successes", 0) >= 1:
                    return "OK"
                if item.get("candidates", 0) >= 1:
                    return "PARTIEL"
                return "A MAPPER"

            def refresh_systems(self):
                if not self.systems_tree:
                    return
                self.systems_tree.delete(*self.systems_tree.get_children())
                systems = system_coverage_data()
                query = self.system_query_var.get().strip().lower()
                family = (self.family_filter or "all").lower()
                for item in systems:
                    if query and query not in f"{item['system_name']} {item['dat_section']}".lower():
                        continue
                    if family != "all" and family not in item["dat_section"].lower():
                        continue
                    badge = self._coverage_badge(item)
                    badge_color = dict(_COVERAGE_BADGES).get(badge, UI_COLOR_TEXT_SUB)
                    self.systems_tree.insert("", "end", iid=item["system_id"], text=item["system_name"], values=(badge, item["dat_section"], item["game_count"], format_bytes(item["total_size"]), item["dat_date"]), tags=(f"badge_{badge}",))
                for badge, _color in _COVERAGE_BADGES:
                    try:
                        self.systems_tree.tag_configure(f"badge_{badge}", foreground=_color)
                    except Exception:
                        pass
                self.status_var.set(f"{len(self.systems_tree.get_children())} systeme(s) affiche(s)")

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
                using_dat = bool(self.dat_games and self.missing_games is not None)
                if using_dat:
                    system_name = (self.dat_profile or {}).get('system_name', '') or 'Systeme inconnu'
                    title = f"{system_name} ({len(self.missing_games)} manquants / {len(self.dat_games)} total)"
                else:
                    system = get_catalog_system(self.current_system_id) if self.current_system_id else None
                    title = system["system_name"] if system else "Jeux"
                top = tk.Frame(frame, bg=UI_COLOR_BG)
                top.grid(row=0, column=0, sticky="ew")
                top.columnconfigure(1, weight=1)
                tk.Label(top, text=title, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                game_search = self.entry(top, self.game_query_var)
                game_search.grid(row=0, column=1, sticky="ew", padx=16, ipady=7)
                game_search.bind("<Return>", lambda _event: self.refresh_games())
                self.button(top, "Filtrer", self.refresh_games, kind="accent", width=12).grid(row=0, column=2)

                letters = tk.Frame(frame, bg=UI_COLOR_BG)
                letters.grid(row=1, column=0, sticky="ew", pady=(18, 12))
                for value in ["all", "#"] + list("abcdefghijklmnopqrstuvwxyz"):
                    text = "Tous" if value == "all" else value.upper()
                    self.button(letters, text, lambda value=value: self.set_letter_filter(value), width=4).pack(side="left", padx=(0, 4))

                filters_row = tk.Frame(frame, bg=UI_COLOR_BG)
                filters_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
                self.games_filter_var = tk.StringVar(value="missing" if using_dat else "all")
                for label, value in [("Tous", "all"), ("Manquants", "missing"), ("Presents", "present"), ("Providers valides", "valid"), ("Sans provider", "noprovider"), ("Erreur hash", "hash_error"), ("Erreur reseau", "network_error")]:
                    self.button(filters_row, label, lambda v=value: self.set_games_filter(v), width=14).pack(side="left", padx=(0, 5))

                if using_dat:
                    self.games_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("rom", "size", "status"), show="tree headings")
                    self.games_tree.heading("#0", text="Jeu")
                    for col, label, width, anchor in [("rom", "ROM", 280, "w"), ("size", "Taille", 90, "e"), ("status", "Statut", 200, "w")]:
                        self.games_tree.heading(col, text=label)
                        self.games_tree.column(col, width=width, anchor=anchor)
                    self.games_tree.column("#0", width=420, anchor="w")
                    self.games_tree.grid(row=3, column=0, sticky="nsew")
                    self.games_tree.bind("<Double-1>", lambda _event: self.start_selected_game_download())
                    self.games_tree.bind("<<TreeviewSelect>>", lambda _event: self._on_games_select())
                else:
                    self.games_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("rom", "size", "valid", "candidates", "local", "error"), show="tree headings")
                    self.games_tree.heading("#0", text="Jeu")
                    for col, label, width, anchor in [("rom", "ROM", 280, "w"), ("size", "Taille", 90, "e"), ("valid", "Valides", 70, "e"), ("candidates", "Candidats", 80, "e"), ("local", "Statut local", 110, "w"), ("error", "Derniere erreur", 200, "w")]:
                        self.games_tree.heading(col, text=label)
                        self.games_tree.column(col, width=width, anchor=anchor)
                    self.games_tree.column("#0", width=300, anchor="w")
                    self.games_tree.grid(row=3, column=0, sticky="nsew")
                    self.games_tree.bind("<Double-1>", lambda _event: self.start_selected_game_download())
                    self.games_tree.bind("<<TreeviewSelect>>", lambda _event: self._on_games_select())

                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
                self.button(actions, "Telecharger ce jeu", self.start_selected_game_download, kind="accent", width=18).pack(side="left", padx=(0, 10))
                self.button(actions, "Ajouter a la file", self.enqueue_selected_game, width=16).pack(side="left", padx=(0, 10))
                if using_dat:
                    self.button(actions, "Telecharger tous les manquants", self.start_all_missing_download, kind="success", width=24).pack(side="left", padx=(0, 10))
                    self.button(actions, "Ajouter tous a la file", self.enqueue_all_missing, width=18).pack(side="left", padx=(0, 10))
                else:
                    self.button(actions, "Telecharger le systeme", self.start_system_download, kind="success", width=22).pack(side="left", padx=(0, 10))
                self.button(actions, "Retour", lambda: self.show_page("dat" if using_dat else "systems"), width=10).pack(side="left")
                self.refresh_games()

            def set_letter_filter(self, value):
                self.letter_filter = value
                self.refresh_games()

            def set_games_filter(self, value):
                self.games_filter_var.set(value)
                self.refresh_games()

            def set_family_filter(self, value):
                self.family_filter = value
                self.refresh_systems()

            def _on_games_select(self):
                selection = self.games_tree.selection() if self.games_tree else []
                if selection:
                    game_name = self.games_tree.item(selection[0], "text")
                    self.status_var.set(f"Selectionne: {game_name}")
                else:
                    self.refresh_games()

            def refresh_games(self):
                if not self.games_tree:
                    return
                self.games_tree.delete(*self.games_tree.get_children())
                using_dat = bool(self.dat_games and self.missing_games is not None)
                if using_dat:
                    self._refresh_dat_games()
                    return
                if not self.current_system_id:
                    self.status_var.set("Selectionne un systeme ou charge un DAT")
                    return
                games = list_catalog_games(self.current_system_id, self.game_query_var.get(), self.letter_filter)
                game_ids = [g["game_id"] for g in games]
                errors = {} if not game_ids else self._game_error_summary(game_ids)
                game_filter = self.games_filter_var.get()
                for game in games:
                    gid = game["game_id"]
                    valid_count = len(game.get("providers", []))
                    candidates_count = game.get("candidate_count", 0)
                    err = errors.get(gid, {})
                    local_status = "Present" if err.get("valid") else ("Invalide" if err.get("invalid") else "Absent")
                    last_error = err.get("detail", "")
                    if game_filter == "missing" and local_status == "Present":
                        continue
                    if game_filter == "present" and local_status != "Present":
                        continue
                    if game_filter == "valid" and valid_count == 0:
                        continue
                    if game_filter == "noprovider" and (valid_count > 0 or candidates_count > 0):
                        continue
                    if game_filter == "hash_error" and "checksum" not in last_error.lower():
                        continue
                    if game_filter == "network_error" and ("network" not in last_error.lower() and "timeout" not in last_error.lower() and "cloudflare" not in last_error.lower() and "quota" not in last_error.lower()):
                        continue
                    self.games_tree.insert("", "end", iid=gid, text=game["game_name"], values=(game["primary_rom"], format_bytes(game["size"]), valid_count, candidates_count, local_status, last_error))
                self.status_var.set(f"{len(self.games_tree.get_children())} jeu(x) affiche(s)")

            def _refresh_dat_games(self):
                if not self.dat_games:
                    self.status_var.set("Aucun DAT charge")
                    return
                query = self.game_query_var.get().strip().lower()
                game_filter = self.games_filter_var.get()
                missing_names = {g.get('game_name', '') for g in self.missing_games} if self.missing_games else set()
                letter = self.letter_filter
                idx = 0
                for game_name, game_info in self.dat_games.items():
                    primary_rom = (game_info.get('roms') or [{}])[0].get('name', '') if game_info.get('roms') else game_name
                    game_size = sum(int(r.get('size', 0) or 0) for r in (game_info.get('roms') or []))
                    is_missing = game_name in missing_names
                    if query and query not in game_name.lower() and query not in primary_rom.lower():
                        continue
                    if letter != "all":
                        if letter == "#":
                            if game_name[0:1].isalpha():
                                continue
                        else:
                            if not game_name.lower().startswith(letter):
                                continue
                    if game_filter == "missing" and not is_missing:
                        continue
                    if game_filter == "present" and is_missing:
                        continue
                    status_text = "Manquant" if is_missing else "Present"
                    iid = f"dat_{idx}"
                    self.games_tree.insert("", "end", iid=iid, text=game_name, values=(primary_rom, format_bytes(game_size), status_text))
                    idx += 1
                self.status_var.set(f"{idx} jeu(x) affiche(s) — {len(missing_names)} manquants")

            def _game_error_summary(self, game_ids: list[str]) -> dict:
                from .local_database import open_local_database as _opendb
                if not game_ids:
                    return {}
                result = {}
                with _opendb() as conn:
                    placeholders = ",".join("?" * len(game_ids))
                    rows = conn.execute(
                        f"""
                        SELECT game_id, status, error_code, detail
                        FROM (
                            SELECT game_id, status, error_code, detail,
                                   ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY created_at DESC) AS rn
                            FROM download_attempts
                            WHERE game_id IN ({placeholders})
                        )
                        WHERE rn = 1
                        """,
                        game_ids,
                    ).fetchall()
                    for row in rows:
                        result[row["game_id"]] = {
                            "status": row["status"],
                            "detail": row.get("detail", "") or row.get("error_code", ""),
                            "valid": row["status"] in ("downloaded", "completed"),
                        }
                return result

            def enqueue_selected_game(self):
                using_dat = bool(self.dat_games and self.missing_games is not None)
                if using_dat:
                    selection = self.games_tree.selection()
                    if not selection:
                        messagebox.showinfo("Info", "Selectionnez un jeu dans la liste")
                        return
                    item_id = selection[0]
                    game_name = self.games_tree.item(item_id, "text")
                    game_info = self.dat_games.get(game_name)
                    if not game_info:
                        return
                    missing_names = {g.get('game_name', '') for g in self.missing_games}
                    if game_name not in missing_names:
                        messagebox.showinfo("Info", f"{game_name} est deja present")
                        return
                    self.download_queue.put(game_info.copy())
                    messagebox.showinfo("File", f"{game_name} ajoute a la file de telechargement")
                    return
                if not self.games_tree or not self.current_system_id:
                    return
                selection = self.games_tree.selection()
                if not selection:
                    messagebox.showinfo("Info", "Selectionnez un jeu dans la liste")
                    return
                game_id = selection[0]
                games = list_catalog_games(self.current_system_id)
                game = next((item for item in games if item["game_id"] == game_id), None)
                if game:
                    system = get_catalog_system(self.current_system_id)
                    if not system:
                        return
                    from .local_database import create_download_job, list_download_jobs
                    try:
                        folder = self.output_folder_for_system(system)
                    except Exception:
                        messagebox.showerror("Erreur", "Veuillez configurer un dossier de sortie")
                        return
                    existing = list_download_jobs(status="running", limit=100)
                    existing += list_download_jobs(status="pending", limit=100)
                    for job in existing:
                        queue = job.get("queue", {})
                        if queue.get("pending") or queue.get("running"):
                            from .local_database import update_download_queue_item, list_download_queue_items
                            items = list_download_queue_items({"job_id": job["job_id"]})
                            if any(item["game_id"] == game_id for item in items):
                                messagebox.showinfo("Info", "Ce jeu est deja dans la file")
                                return
                    job_id = create_download_job(system["system_id"], [game], folder)
                    messagebox.showinfo("File", f"Ajoute a la file (job {job_id[:8]})")

            def enqueue_all_missing(self):
                if not self.dat_games or self.missing_games is None:
                    messagebox.showinfo("Info", "Chargez un DAT d'abord")
                    return
                count = len(self.missing_games)
                for game in self.missing_games:
                    self.download_queue.put(game.copy())
                messagebox.showinfo("File", f"{count} jeu(x) ajoute(s) a la file de telechargement")
                if not self.download_worker_running:
                    self.start_download_worker()

            def start_all_missing_download(self):
                if not self.dat_games or self.missing_games is None:
                    messagebox.showinfo("Info", "Chargez un DAT d'abord")
                    return
                rom_folder = self.rom_folder.get().strip()
                if not rom_folder:
                    messagebox.showerror("Erreur", "Selectionnez un dossier de sortie")
                    return
                self.persist_preferences()
                self.running = True
                self.progress_var.set(0)
                self.show_page("downloads")
                threading.Thread(target=self.run_all_missing_download, daemon=True).start()

            def run_all_missing_download(self):
                try:
                    audit_only = bool(self.audit_only_var.get())
                    dat_profile = self.dat_profile
                    system_name = dat_profile.get("system_name") if dat_profile else ""
                    output_folder = self.rom_folder.get().strip()
                    if self.output_root_by_dat_var.get() and dat_profile:
                        output_folder = resolve_dat_output_folder(dat_profile.get('dat_path', ''), self.rom_folder.get().strip(), True)
                    os.makedirs(output_folder, exist_ok=True)
                    sources = self.selected_sources(dat_profile, system_name=system_name)
                    result = download_missing_games_sequentially(
                        self.missing_games,
                        sources,
                        self.session,
                        system_name,
                        dat_profile,
                        output_folder,
                        "",
                        audit_only,
                        None,
                        lambda value: self._ui(lambda v=value: self.progress_var.set(v)),
                        self.log,
                        lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                        is_running=lambda: self.running,
                        parallel_downloads=max(1, int(self.parallel_var.get() or 1)),
                        circuit_breaker=self.circuit_breaker,
                    )
                    self.update_provider_stats(result)
                    if self.clean_torrentzip_var.get() and not audit_only:
                        torrentzip_summary = repack_verified_archives_to_torrentzip(
                            self.dat_games, output_folder, False, self.log,
                            lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                            is_running=lambda: self.running,
                        )
                        self.log(f"TorrentZip: {torrentzip_summary.get('repacked', 0)} repack(s)")
                    if self.move_to_tosort_var.get() and not audit_only:
                        local_roms, local_roms_normalized, local_game_names, sig_idx = scan_local_roms(output_folder, self.dat_games)
                        files_to_move = find_roms_not_in_dat(self.dat_games, local_roms, local_roms_normalized, output_folder)
                        if files_to_move:
                            moved, failed = move_files_to_tosort(files_to_move, output_folder, os.path.join(output_folder, "ToSort"), False)
                            self.log(f"ToSort: {moved} deplace(s)")
                    total_size, total_unknown = estimate_games_size(self.dat_games)
                    missing_size, missing_unknown = estimate_games_size(self.missing_games)
                    report_paths = write_download_reports(output_folder, {
                        "dat_file": dat_profile.get("dat_path", "") if dat_profile else "",
                        "system_name": system_name,
                        "dat_profile": describe_dat_profile(dat_profile),
                        "output_folder": output_folder,
                        "dry_run": audit_only,
                        "active_sources": [source["name"] for source in sources if source.get("enabled", True)],
                        "total_dat_games": len(self.dat_games),
                        "present_before": max(0, len(self.dat_games) - len(self.missing_games)),
                        "missing_before": len(self.missing_games),
                        "total_size": total_size,
                        "total_unknown_sizes": total_unknown,
                        "missing_size": missing_size,
                        "missing_unknown_sizes": missing_unknown,
                        "resolved_items": result.get("resolved_items", []),
                        "downloaded_items": result.get("downloaded_items", []),
                        "failed_items": result.get("failed_items", []),
                        "skipped_items": result.get("skipped_items", []),
                        "not_available": result.get("not_available", []),
                    }, formats=("txt", "json", "csv", "html"))
                    report_txt = report_paths.get("txt", "")
                    self.log(f"Rapport{' audit' if audit_only else ''}: {report_txt}")
                    if audit_only:
                        self._ui(lambda path=report_txt: self.status_var.set(f"Audit termine - rapport: {path}"))
                    else:
                        self._ui(lambda: self.status_var.set(f"Termine - {result.get('downloaded', 0)} telecharge(s), {result.get('failed', 0)} echec(s)"))
                except Exception as exc:
                    self.log(f"ERREUR: {exc}")
                    self._ui(lambda msg=str(exc): self.status_var.set(f"Erreur: {msg}"))
                finally:
                    self.running = False
                    self.persist_preferences()

            def start_download_worker(self):
                if self.download_worker_running:
                    return
                self.download_worker_running = True
                threading.Thread(target=self._download_worker_loop, daemon=True).start()

            def _download_worker_loop(self):
                while self.download_worker_running:
                    try:
                        game_info = self.download_queue.get(timeout=1)
                    except queue.Empty:
                        self.download_worker_running = False
                        return
                    if not self.dat_games or not self.dat_profile:
                        self.download_queue.task_done()
                        continue
                    rom_folder = self.rom_folder.get().strip()
                    if not rom_folder:
                        self.log("Erreur: dossier de sortie non configure")
                        self.download_queue.task_done()
                        continue
                    dat_profile = self.dat_profile
                    system_name = dat_profile.get("system_name", "") if dat_profile else ""
                    output_folder = rom_folder
                    try:
                        if self.output_root_by_dat_var.get() and dat_profile:
                            output_folder = resolve_dat_output_folder(dat_profile.get('dat_path', ''), rom_folder, True)
                        os.makedirs(output_folder, exist_ok=True)
                    except Exception:
                        pass
                    sources = self.selected_sources(dat_profile, system_name=system_name)
                    if self.audit_only_var.get():
                        self._ui(lambda: self.status_var.set(f"Audit: {game_info.get('game_name', '?')}"))
                        try:
                            result = download_missing_games_sequentially(
                                [game_info],
                                sources,
                                self.session,
                                system_name,
                                dat_profile,
                                output_folder,
                                "",
                                True,
                                None,
                                None,
                                self.log,
                                lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                                is_running=lambda: self.running,
                                parallel_downloads=1,
                                circuit_breaker=self.circuit_breaker,
                            )
                            self.download_results.append(result)
                            self.log(f"AUDIT: {game_info.get('game_name', '?')}")
                        except Exception as exc:
                            self.log(f"ERREUR AUDIT: {game_info.get('game_name', '?')}: {exc}")
                        self.download_queue.task_done()
                        continue
                    self._ui(lambda: self.status_var.set(f"Telechargement: {game_info.get('game_name', '?')}"))
                    try:
                        result = download_single_game(
                            game_info=game_info,
                            sources=sources,
                            session=self.session,
                            system_name=system_name,
                            dat_profile=dat_profile,
                            output_folder=output_folder,
                            dat_games=self.dat_games,
                            clean_torrentzip=bool(self.clean_torrentzip_var.get()),
                            log_func=self.log,
                            is_running=lambda: self.running,
                            circuit_breaker=self.circuit_breaker,
                            parallel_downloads=max(1, int(self.parallel_var.get() or 1)),
                            system_id=game_info.get('system_id', ''),
                            game_id=game_info.get('game_id', ''),
                        )
                        status = result.get('status', 'failed')
                        game_name = game_info.get('game_name', '?')
                        if status == 'downloaded':
                            self.log(f"OK: {game_name}")
                        else:
                            self.log(f"ECHEC: {game_name} ({status})")
                        self.download_results.append(result)
                    except Exception as exc:
                        self.log(f"ERREUR: {game_info.get('game_name', '?')}: {exc}")
                    self.download_queue.task_done()
                self.download_worker_running = False

            def build_downloads_page(self):
                frame = self.page_frame()
                tk.Label(frame, text="Telechargements", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                settings = tk.Frame(frame, bg=UI_COLOR_BG)
                settings.grid(row=1, column=0, sticky="ew", pady=(16, 10))
                settings.columnconfigure(1, weight=1)
                tk.Label(settings, text="Dossier de sortie", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 11, "bold")).grid(row=0, column=0, sticky="w")
                self.entry(settings, self.rom_folder).grid(row=0, column=1, sticky="ew", padx=12, ipady=7)
                self.button(settings, "Parcourir", self.browse_output, width=12).grid(row=0, column=2)
                self.check(settings, "Sous-dossier nomme comme le DAT", self.output_root_by_dat_var).grid(row=1, column=1, sticky="w", pady=6)
                tk.Label(settings, text="Profil DAT", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 10)).grid(row=2, column=0, sticky="w", pady=(6, 0))
                self.profile_combo = ttk.Combobox(settings, textvariable=self.profile_var,
                    values=["", *CONFIG_PROFILE_LABELS],
                    state="readonly", width=20, font=(self.font, 10))
                self.profile_combo.grid(row=2, column=1, sticky="w", pady=(6, 0))
                self.profile_combo.bind("<<ComboboxSelected>>", self._apply_profile)
                self.check(settings, "Extraire + TorrentZip automatiquement", self.auto_extract_var).grid(row=3, column=1, sticky="w")
                self.check(settings, "Recompresser en ZIP TorrentZip (apres telechargement complet)", self.clean_torrentzip_var).grid(row=4, column=1, sticky="w")
                self.check(settings, "Deplacer les fichiers hors DAT vers ToSort", self.move_to_tosort_var).grid(row=5, column=1, sticky="w")
                self.check(settings, "Privilegier les sources 1fichier configurees", self.prefer_1fichier_var).grid(row=6, column=1, sticky="w")
                self.check(settings, "Audit uniquement (dry-run, aucun fichier ROM ecrit)", self.audit_only_var).grid(row=7, column=1, sticky="w")
                tk.Label(settings, text="Parallele", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN).grid(row=8, column=0, sticky="w", pady=(6, 0))
                tk.Spinbox(settings, from_=1, to=12, textvariable=self.parallel_var, width=5, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, buttonbackground=UI_COLOR_GHOST, relief="flat").grid(row=8, column=1, sticky="w", pady=(6, 0))

                tabs = tk.Frame(frame, bg=UI_COLOR_BG)
                tabs.grid(row=2, column=0, sticky="ew", pady=(12, 0))
                for label, value in [("File", "queue"), ("Erreurs", "errors"), ("Historique", "history")]:
                    self.button(tabs, label, lambda v=value: self._set_downloads_tab(v), width=14).pack(side="left", padx=(0, 6))
                self.downloads_tab.set("queue")

                self.downloads_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("action", "detail"), show="tree headings")
                self.downloads_tree.heading("#0", text="Job")
                self.downloads_tree.heading("action", text="Action")
                self.downloads_tree.heading("detail", text="Detail")
                self.downloads_tree.column("#0", width=200)
                self.downloads_tree.column("action", width=120)
                self.downloads_tree.column("detail", width=500)
                self.downloads_tree.grid(row=3, column=0, sticky="nsew", pady=(10, 0))

                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=4, column=0, sticky="ew", pady=(12, 0))
                self.button(actions, "Pause", lambda: self._job_action("pause"), width=12).pack(side="left", padx=(0, 6))
                self.button(actions, "Reprise", lambda: self._job_action("resume"), width=12).pack(side="left", padx=(0, 6))
                self.button(actions, "Annuler", lambda: self._job_action("cancel"), width=12).pack(side="left", padx=(0, 6))
                self.button(actions, "Reessayer echecs", lambda: self._job_action("retry"), width=16).pack(side="left", padx=(0, 6))
                self.button(actions, "Reessayer tout", self._retry_all_incomplete, width=16).pack(side="left", padx=(0, 6))
                self.button(actions, "Nettoyer .part", self._cleanup_orphan_parts, width=16).pack(side="left", padx=(0, 6))
                self.button(actions, "Arreter", self.stop, kind="danger", width=12).pack(side="left", padx=(20, 6))

                self.log_text = tk.Text(frame, height=10, bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN, relief="flat", wrap="word", font=(self.font, 9))
                self.log_text.grid(row=5, column=0, sticky="nsew", pady=(0, 0))

            def _set_downloads_tab(self, tab):
                self.downloads_tab.set(tab)
                self._refresh_downloads_tree()

            def _refresh_downloads_tree(self):
                if not hasattr(self, "downloads_tree") or not self.downloads_tree:
                    return
                self.downloads_tree.delete(*self.downloads_tree.get_children())
                from .local_database import list_download_jobs
                tab = self.downloads_tab.get()
                if tab == "queue":
                    jobs = list_download_jobs(status="all", limit=50)
                    for job in jobs:
                        queue = job.get("queue", {})
                        detail = f"{job['completed']}/{job['total']} - {job['output_folder']}"
                        action = ""
                        st = job["status"]
                        if st == "running":
                            action = "Actif"
                        elif st == "paused":
                            action = "Pause"
                        elif st in ("completed", "finished"):
                            action = "Termine"
                        elif st == "failed":
                            action = "Echoue"
                        elif st in ("cancelled", "stopped"):
                            action = "Annule"
                        q_detail = ", ".join(f"{k}={v}" for k, v in sorted(queue.items()))
                        full_detail = f"{detail} [{q_detail}]" if q_detail else detail
                        self.downloads_tree.insert("", "end", iid=job["job_id"], text=f"{job['job_id'][:8]} [{st}]", values=(action, full_detail))
                elif tab == "errors":
                    from .local_database import open_local_database as _opendb
                    with _opendb() as conn:
                        rows = conn.execute(
                            "SELECT job_id, provider, game_name, error_code, detail, created_at "
                            "FROM download_attempts WHERE status NOT IN ('downloaded', 'completed', 'skipped', 'dry_run') "
                            "ORDER BY created_at DESC LIMIT 200"
                        ).fetchall()
                        for row in rows:
                            self.downloads_tree.insert("", "end", text=row["game_name"], values=(row["provider"] or "", f"{row['error_code']}: {row.get('detail', '')[:200]}"))
                else:
                    from .download_history import list_download_history
                    rows = list_download_history(limit=200)
                    for item in rows:
                        self.downloads_tree.insert("", "end", text=item.get("game_name", ""), values=(item.get("provider", ""), f"{item.get('date', '')} - {item.get('status', '')}"))

            def _job_action(self, action):
                selection = self.downloads_tree.selection() if hasattr(self, "downloads_tree") and self.downloads_tree else []
                if not selection:
                    messagebox.showinfo("Info", "Selectionnez un job")
                    return
                job_id = selection[0]
                from .local_database import pause_download_job as _pause, resume_download_job as _resume, cancel_download_job as _cancel, retry_failed_queue_items as _retry
                ok = False
                if action == "pause":
                    ok = _pause(job_id)
                elif action == "resume":
                    ok = _resume(job_id)
                elif action == "cancel":
                    ok = _cancel(job_id)
                elif action == "retry":
                    count = _retry(job_id)
                    if count:
                        messagebox.showinfo("Info", f"{count} item(s) remis en file")
                    else:
                        messagebox.showinfo("Info", "Aucun item a reessayer")
                    ok = True
                if action != "retry":
                    verb = {"pause": "Pause", "resume": "Reprise", "cancel": "Annulation"}
                    messagebox.showinfo("Info", f"{verb.get(action, action)} {'OK' if ok else 'ECHEC'}")
                self._refresh_downloads_tree()

            def _retry_all_incomplete(self):
                from .local_database import list_download_jobs, retry_failed_queue_items as _retry
                jobs = list_download_jobs(status="all", limit=100)
                total = 0
                for job in jobs:
                    if job["status"] in ("failed", "stopped", "cancelled"):
                        count = _retry(job["job_id"])
                        total += count
                if total:
                    messagebox.showinfo("Info", f"{total} item(s) remis en file dans tous les jobs")
                else:
                    messagebox.showinfo("Info", "Aucun job a reprendre")
                self._refresh_downloads_tree()

            def _cleanup_orphan_parts(self):
                import glob as _glob
                output = self.rom_folder.get().strip()
                if not output or not os.path.isdir(output):
                    messagebox.showinfo("Info", "Dossier ROMs non configure ou introuvable")
                    return
                parts = _glob.glob(os.path.join(output, "**", "*.part"), recursive=True)
                removed = 0
                for p in parts:
                    try:
                        os.remove(p)
                        removed += 1
                    except Exception:
                        pass
                messagebox.showinfo("Nettoyage", f"{removed} fichier(s) .part supprime(s)")

            def _startup_cleanup(self):
                from .local_database import cleanup_stale_locks
                try:
                    result = cleanup_stale_locks()
                    if result.get("unlocked_items", 0) or result.get("stopped_jobs", 0):
                        self.log(f"Nettoyage au demarrage: {result['unlocked_items']} verrou(s) libere(s), {result['stopped_jobs']} job(s) stoppes")
                except Exception:
                    pass

            def build_history_page(self):
                frame = self.page_frame()
                top = tk.Frame(frame, bg=UI_COLOR_BG)
                top.grid(row=0, column=0, sticky="ew")
                top.columnconfigure(1, weight=1)
                tk.Label(top, text="Historique", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")
                history_search = self.entry(top, self.history_query_var)
                history_search.grid(row=0, column=1, sticky="ew", padx=16, ipady=7)
                history_search.bind("<Return>", lambda _event: self.refresh_history())
                self.button(top, "Filtrer", self.refresh_history, kind="accent", width=12).grid(row=0, column=2)

                self.history_tree = ttk.Treeview(frame, style="Catalog.Treeview", columns=("date", "system", "provider", "status"), show="tree headings")
                self.history_tree.heading("#0", text="Jeu")
                for col, label, width, anchor in [
                    ("date", "Date", 160, "w"),
                    ("system", "Systeme", 220, "w"),
                    ("provider", "Provider", 120, "w"),
                    ("status", "Statut", 100, "w"),
                ]:
                    self.history_tree.heading(col, text=label)
                    self.history_tree.column(col, width=width, anchor=anchor)
                self.history_tree.column("#0", width=320, anchor="w")
                self.history_tree.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
                self.refresh_history()

            def refresh_history(self):
                if not self.history_tree:
                    return
                self.history_tree.delete(*self.history_tree.get_children())
                query = self.history_query_var.get().strip().lower()
                shown = 0
                for item in list_download_history(limit=500):
                    haystack = " ".join(str(item.get(key, "")) for key in ("game_name", "system_name", "provider", "status", "date")).lower()
                    if query and query not in haystack:
                        continue
                    self.history_tree.insert(
                        "",
                        "end",
                        text=item.get("game_name", ""),
                        values=(item.get("date", ""), item.get("system_name", ""), item.get("provider", ""), item.get("status", "")),
                    )
                    shown += 1
                self.status_var.set(f"{shown} entree(s) d'historique affichee(s)")

            def build_sources_page(self):
                frame = self.page_frame()
                frame.columnconfigure(0, weight=1)
                tk.Label(frame, text="Sources", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 24, "bold")).grid(row=0, column=0, sticky="w")

                filter_frame = tk.Frame(frame, bg=UI_COLOR_BG)
                filter_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
                tk.Label(filter_frame, text="Systeme:", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 10)).pack(side="left", padx=(0, 6))
                self.source_system_var = tk.StringVar(value="Tous")
                self.source_system_combo = ttk.Combobox(filter_frame, textvariable=self.source_system_var,
                                                        values=["Tous"], state="readonly", width=40, font=(self.font, 10))
                self.source_system_combo.pack(side="left")
                self.source_system_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_sources_list())
                self._populate_source_system_filter()

                self.sources_tree = ttk.Treeview(frame, style="Catalog.Treeview",
                                                  columns=("type", "etat", "coverage", "success_rate", "success", "failures", "speed", "quota", "delay", "timeout", "last_ok", "last_fail"),
                                                  show="tree headings")
                for col, label, width in [
                    ("#0", "Provider", 180), ("type", "Type", 100), ("etat", "Etat", 70),
                    ("coverage", "Couverture", 90), ("success_rate", "Taux", 55),
                    ("success", "Succes", 60), ("failures", "Echecs", 60),
                    ("speed", "Vitesse", 80), ("quota", "Quota", 60), ("delay", "Delai", 60),
                    ("timeout", "Timeout", 70), ("last_ok", "Dernier OK", 130), ("last_fail", "Dernier echec", 130)
                ]:
                    self.sources_tree.heading(col, text=label)
                    if col == "#0":
                        self.sources_tree.column("#0", width=width, anchor="w")
                    else:
                        self.sources_tree.column(col, width=width, anchor="e" if col in ("priority", "success", "failures", "quota", "delay", "success_rate", "coverage") else "w")
                self.sources_tree.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
                self.sources_tree.bind("<Double-1>", self._edit_source_policy)
                actions = tk.Frame(frame, bg=UI_COLOR_BG)
                actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
                for label, command, kind in [
                    ("Activer/desactiver", self.toggle_source, "ghost"),
                    ("Monter", lambda: self.move_source(-1), "ghost"),
                    ("Descendre", lambda: self.move_source(1), "ghost"),
                    ("Editer politiques", self._edit_source_policy, "ghost"),
                    ("Cles API", self.open_api_settings, "ghost"),
                    ("Tester connexion", self._test_provider_connection, "ghost"),
                    ("Vider cache", self._clear_source_cache, "ghost"),
                ]:
                    self.button(actions, label, command, kind=kind, width=14).pack(side="left", padx=(0, 4))
                self.button(actions, "Sauver", self.persist_preferences, kind="accent", width=12).pack(side="left", padx=(6, 4))
                self._cloudflare_status_label = tk.Label(frame, text="", bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_SUB, font=(self.font, 10))
                self._cloudflare_status_label.grid(row=4, column=0, sticky="w", pady=(10, 0))
                self.refresh_sources_list()

            def _populate_source_system_filter(self):
                systems = ["Tous"]
                try:
                    catalog = list_catalog_systems()
                    systems.extend([s["system_name"] for s in catalog[:100]])
                except Exception:
                    pass
                self.source_system_combo["values"] = systems

            def _edit_source_policy(self, event=None):
                name = self.selected_source_name()
                if not name:
                    return
                known = {source["name"]: source for source in self.default_sources}
                source = known.get(name)
                if not source:
                    return
                policy = self.source_policies.get(name, {})
                dialog = tk.Toplevel(self.root)
                dialog.title(f"Politiques: {name}")
                dialog.configure(bg=UI_COLOR_BG)
                dialog.resizable(False, False)

                entries = {}
                row = 0
                for key, label, default_val, validator in [
                    ("timeout_seconds", "Timeout (s, 3-1800)", source.get("timeout_seconds", 120), lambda v: 3 <= int(v) <= 1800),
                    ("quota_per_run", "Quota par run (1-100000)", source.get("quota_per_run", "-"), lambda v: v == "-" or 1 <= int(v) <= 100000),
                    ("delay_seconds", "Delai (s, 0-60)", source.get("delay_seconds", "0"), lambda v: 0 <= float(v) <= 60),
                    ("user_agent", "User-Agent (vide = defaut)", source.get("user_agent", ""), lambda v: len(v) <= 512),
                    ("cookies", "Cookies (key=val;key2=val2)", source.get("cookies", ""), lambda v: len(v) <= 2048),
                ]:
                    tk.Label(dialog, text=label, bg=UI_COLOR_BG, fg=UI_COLOR_TEXT_MAIN, font=(self.font, 10)).grid(row=row, column=0, sticky="w", padx=12, pady=6)
                    current = policy.get(key, default_val)
                    var = tk.StringVar(value=str(current) if current is not None else "")
                    entry = tk.Entry(dialog, textvariable=var, width=28 if key in ("user_agent", "cookies") else 12, font=(self.font, 10),
                                    bg=UI_COLOR_INPUT_BG, fg=UI_COLOR_TEXT_MAIN, insertbackground=UI_COLOR_TEXT_MAIN,
                                    relief="flat")
                    entry.grid(row=row, column=1, padx=12, pady=6)
                    entries[key] = (var, validator)
                    row += 1

                def save_policy():
                    new_policy = {}
                    for key, (var, validator) in entries.items():
                        val = var.get().strip()
                        if not val:
                            continue
                        try:
                            if not validator(val):
                                messagebox.showwarning("Valeur invalide", f"La valeur de {key} est hors limites.", parent=dialog)
                                return
                        except (TypeError, ValueError):
                            messagebox.showwarning("Valeur invalide", f"La valeur de {key} n'est pas un nombre.", parent=dialog)
                            return
                        if key in ("timeout_seconds", "quota_per_run"):
                            new_policy[key] = int(val)
                        elif key in ("delay_seconds",):
                            new_policy[key] = float(val)
                        else:
                            new_policy[key] = val
                    self.source_policies[name] = new_policy
                    self.refresh_sources_list()
                    self.persist_preferences()
                    dialog.destroy()

                btn_frame = tk.Frame(dialog, bg=UI_COLOR_BG)
                btn_frame.grid(row=row, column=0, columnspan=2, pady=(12, 12))
                self.button(btn_frame, "Appliquer", save_policy, kind="accent", width=12).pack(side="left", padx=6)
                self.button(btn_frame, "Annuler", dialog.destroy, kind="ghost", width=12).pack(side="left", padx=6)

            def _clear_source_cache(self):
                name = self.selected_source_name()
                if not name:
                    return
                from . import _facade
                removed = _facade.clear_caches_for_source(name)
                messagebox.showinfo("Cache vide",
                    f"Cache {name}: {removed.get('resolution', 0)} resolution, {removed.get('listing', 0)} listing supprime(s).")

            def refresh_sources_list(self):
                if not hasattr(self, "sources_tree") or not self.sources_tree:
                    return
                self.sources_tree.delete(*self.sources_tree.get_children())
                from .local_database import list_provider_metrics, list_provider_system_metrics
                from .sources import SYSTEM_MAPPINGS, resolve_system_mapping
                system_filter = self.source_system_var.get().strip()
                show_system = system_filter and system_filter != "Tous"
                metrics = list_provider_metrics()
                known = {source["name"]: source for source in self.default_sources}
                if show_system:
                    sys_metrics = list_provider_system_metrics(system_filter)
                else:
                    sys_metrics = {}
                for name in self.ordered_source_names():
                    source = known[name]
                    active = self.source_enabled.get(name, source.get("enabled", True))
                    m = self.provider_stats.get(name, {})
                    if show_system:
                        composite = f"{name}::{system_filter}"
                        if composite in sys_metrics:
                            m = sys_metrics[composite]
                    success_val = m.get("downloaded", 0)
                    failure_val = m.get("failed", 0)
                    attempts = m.get("attempts", 0)
                    success_rate = (success_val / attempts * 100) if attempts > 0 else 0
                    avg_speed = format_bytes(m.get("average_speed", 0)) + "/s" if m.get("average_speed") else ""
                    last_ok = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["last_success_at"])) if m.get("last_success_at") else ""
                    last_fail = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["last_failure_at"])) if m.get("last_failure_at") else ""
                    policy = self.source_policies.get(name, {})
                    quota_val = policy.get("quota_per_run", "") or source.get("quota_per_run", "")
                    delay_val = policy.get("delay_seconds") if policy.get("delay_seconds") is not None else source.get("delay_seconds", "")
                    timeout_val = policy.get("timeout_seconds", "") or source.get("timeout_seconds", "")
                    if show_system:
                        coverage = 1
                    else:
                        source_type = source.get("type", "")
                        if source_type in ("archive_org", "minerva"):
                            coverage = "large"
                        else:
                            count = sum(1 for mapping in SYSTEM_MAPPINGS.values() if mapping.get(source_type))
                            coverage = count if count > 0 else ""
                    cb_open = self.circuit_breaker.is_open(name)
                    cf_open = self.circuit_breaker.is_open(name, error_type="cloudflare_challenge")
                    if cf_open:
                        etat = "CF"
                    elif cb_open:
                        etat = "Bloque"
                    elif success_val > 0:
                        etat = "OK"
                    else:
                        etat = "?"
                    prefix = "[x]" if active else "[ ]"
                    self.sources_tree.insert("", "end", iid=name, text=f"{prefix} {name}",
                        values=(source.get("type", ""), etat, coverage, f"{success_rate:.0f}%" if attempts > 0 else "",
                                success_val, failure_val,
                                avg_speed, quota_val, delay_val, timeout_val, last_ok, last_fail))
                self.refresh_cloudflare_status()

            def _test_provider_connection(self):
                name = self.selected_source_name()
                if not name:
                    return
                threading.Thread(target=self._run_provider_test, args=(name,), daemon=True).start()

            def _run_provider_test(self, name):
                from .diagnostics import provider_healthcheck
                known = {source["name"]: source for source in self.default_sources}
                source = known.get(name)
                if not source:
                    return
                result = provider_healthcheck([source], timeout=8)
                if result:
                    r = result[0]
                    msg = f"{r['name']}: {r['status']} ({r.get('elapsed_ms', 0)} ms)\n{r.get('detail', '')}"
                else:
                    msg = f"{name}: impossible de tester"
                self._ui(lambda m=msg: messagebox.showinfo("Test connexion", m))

            def _diagnose_cloudflare(self):
                name = self.selected_source_name()
                if not name:
                    return
                cf_status = "Challenge" if self.circuit_breaker.is_open(name, error_type="cloudflare_challenge") else ("Bloque" if self.circuit_breaker.is_open(name) else "OK")
                self._cloudflare_status_label.config(text=f"Statut Cloudflare {name}: {cf_status}")

            def refresh_cloudflare_status(self):
                if not hasattr(self, "_cloudflare_status_label"):
                    return
                cf_blocked = []
                for name in self.ordered_source_names():
                    if self.circuit_breaker.is_open(name, error_type="cloudflare_challenge"):
                        cf_blocked.append(name)
                self._cloudflare_status_label.config(
                    text="Sources bloquees Cloudflare: " + (", ".join(cf_blocked) if cf_blocked else "Aucune"),
                    fg=UI_COLOR_ERROR if cf_blocked else UI_COLOR_TEXT_SUB,
                )

            def selected_source_name(self):
                if hasattr(self, "sources_tree") and self.sources_tree:
                    selection = self.sources_tree.selection()
                    if selection:
                        return selection[0]
                return ""

            def ordered_source_names(self):
                names = self.source_order or [source["name"] for source in self.default_sources]
                known = {source["name"] for source in self.default_sources}
                for source in self.default_sources:
                    if source["name"] not in names:
                        names.append(source["name"])
                return [name for name in names if name in known]

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
                if not hasattr(self, "sources_tree") or not self.sources_tree:
                    return
                selection = self.sources_tree.selection()
                if not selection:
                    return
                names = self.ordered_source_names()
                index = next((i for i, n in enumerate(names) if n == selection[0]), -1)
                if index < 0:
                    return
                new_index = max(0, min(index + delta, len(names) - 1))
                if index == new_index:
                    return
                names[index], names[new_index] = names[new_index], names[index]
                self.source_order = names
                self.refresh_sources_list()
                self.sources_tree.selection_set(selection[0])
                self.persist_preferences()

            def browse_output(self):
                folder = filedialog.askdirectory(title="Selectionner le dossier de sortie")
                if folder:
                    self.rom_folder.set(folder)
                    self.persist_preferences()

            def selected_sources(self, dat_profile=None, system_name: str = ""):
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
                    item["order"] = optional_positive_int(policy.get("order"), minimum=1, maximum=999)
                    if policy.get("delay_seconds") is not None:
                        try:
                            item["delay_seconds"] = max(0.0, min(float(policy.get("delay_seconds")), 60.0))
                        except (TypeError, ValueError):
                            pass
                    sources.append(item)
                sources = apply_source_policies(sources, self.source_policies)
                sources = prepare_sources_for_profile(sources, dat_profile, prefer_1fichier=bool(self.prefer_1fichier_var.get()))
                return prioritize_sources(sources, self.provider_stats, system_name=system_name)

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
                using_dat = bool(self.dat_games and self.missing_games is not None)
                if using_dat:
                    selection = self.games_tree.selection()
                    if not selection:
                        messagebox.showinfo("Info", "Selectionnez un jeu dans la liste")
                        return
                    item_id = selection[0]
                    game_name = self.games_tree.item(item_id, "text")
                    game_info = self.dat_games.get(game_name)
                    if not game_info:
                        return
                    rom_folder = self.rom_folder.get().strip()
                    if not rom_folder:
                        messagebox.showerror("Erreur", "Selectionnez un dossier de sortie dans l'onglet Telechargements")
                        return
                    self.persist_preferences()
                    self.running = True
                    self.progress_var.set(0)
                    self.show_page("downloads")
                    threading.Thread(target=self._run_single_dat_game, args=(game_info,), daemon=True).start()
                    return
                if not self.games_tree or not self.current_system_id:
                    return
                selection = self.games_tree.selection()
                if not selection:
                    messagebox.showinfo("Info", "Selectionnez un jeu dans la liste")
                    return
                game_id = selection[0]
                games = list_catalog_games(self.current_system_id)
                game = next((item for item in games if item["game_id"] == game_id), None)
                if game:
                    self.start_download_job([game])

            def _run_single_dat_game(self, game_info):
                try:
                    rom_folder = self.rom_folder.get().strip()
                    dat_profile = self.dat_profile
                    system_name = dat_profile.get("system_name", "") if dat_profile else ""
                    output_folder = rom_folder
                    if self.output_root_by_dat_var.get() and dat_profile:
                        output_folder = resolve_dat_output_folder(dat_profile.get('dat_path', ''), rom_folder, True)
                    os.makedirs(output_folder, exist_ok=True)
                    sources = self.selected_sources(dat_profile, system_name=system_name)
                    if self.audit_only_var.get():
                        self._ui(lambda: self.status_var.set(f"Audit: {game_info.get('game_name', '?')}"))
                        result = download_missing_games_sequentially(
                            [game_info],
                            sources,
                            self.session,
                            system_name,
                            dat_profile,
                            output_folder,
                            "",
                            True,
                            None,
                            lambda value: self._ui(lambda v=value: self.progress_var.set(v)),
                            self.log,
                            lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                            is_running=lambda: self.running,
                            parallel_downloads=1,
                            circuit_breaker=self.circuit_breaker,
                            system_id=game_info.get('system_id', ''),
                        )
                        total_size, total_unknown = estimate_games_size(self.dat_games)
                        missing_size, missing_unknown = estimate_games_size([game_info])
                        report_paths = write_download_reports(output_folder, {
                            "dat_file": dat_profile.get("dat_path", "") if dat_profile else "",
                            "system_name": system_name,
                            "dat_profile": describe_dat_profile(dat_profile),
                            "output_folder": output_folder,
                            "dry_run": True,
                            "active_sources": [source["name"] for source in sources if source.get("enabled", True)],
                            "total_dat_games": len(self.dat_games),
                            "present_before": max(0, len(self.dat_games) - 1),
                            "missing_before": 1,
                            "total_size": total_size,
                            "total_unknown_sizes": total_unknown,
                            "missing_size": missing_size,
                            "missing_unknown_sizes": missing_unknown,
                            "resolved_items": result.get("resolved_items", []),
                            "downloaded_items": result.get("downloaded_items", []),
                            "failed_items": result.get("failed_items", []),
                            "skipped_items": result.get("skipped_items", []),
                            "not_available": result.get("not_available", []),
                        }, formats=("txt", "json", "csv", "html"))
                        report_txt = report_paths.get("txt", "")
                        self.log(f"Rapport audit: {report_txt}")
                        self._ui(lambda path=report_txt: self.status_var.set(f"Audit termine - rapport: {path}"))
                        return
                    self._ui(lambda: self.status_var.set(f"Telechargement: {game_info.get('game_name', '?')}"))
                    result = download_single_game(
                        game_info=game_info,
                        sources=sources,
                        session=self.session,
                        system_name=system_name,
                        dat_profile=dat_profile,
                        output_folder=output_folder,
                        dat_games=self.dat_games,
                        clean_torrentzip=bool(self.auto_extract_var.get() or self.clean_torrentzip_var.get()),
                        progress_callback=lambda v: self._ui(lambda val=v: self.progress_var.set(val)),
                        log_func=self.log,
                        is_running=lambda: self.running,
                        circuit_breaker=self.circuit_breaker,
                    )
                    status = result.get('status', 'failed')
                    game_name = game_info.get('game_name', '?')
                    if status == 'downloaded':
                        self.log(f"Telecharge: {game_name}")
                    elif status == 'skipped':
                        self.log(f"Deja present: {game_name}")
                    else:
                        self.log(f"Echec: {game_name} ({status})")
                    self._ui(lambda: self.status_var.set(f"{status}: {game_name}"))
                except Exception as exc:
                    self.log(f"ERREUR: {exc}")
                    self._ui(lambda msg=str(exc): self.status_var.set(f"Erreur: {msg}"))
                finally:
                    self.running = False
                    self.persist_preferences()

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
                    audit_only = bool(self.audit_only_var.get())
                    dat_profile = finalize_dat_profile(detect_dat_profile(system["dat_path"]))
                    system_name = dat_profile.get("system_name") or system["system_name"]
                    output_folder = self.output_folder_for_system(system)
                    sources = self.selected_sources(dat_profile, system_name=system_name)
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
                    if audit_only:
                        self.log("Mode audit uniquement: aucun fichier ROM ne sera ecrit")
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
                        audit_only,
                        None,
                        lambda value: self._ui(lambda v=value: self.progress_var.set(v)),
                        self.log,
                        lambda message: self._ui(lambda msg=message: self.status_var.set(msg)),
                        is_running=lambda: self.running,
                        parallel_downloads=max(1, int(self.parallel_var.get() or 1)),
                        system_id=system["system_id"],
                    )
                    self.update_provider_stats(result)
                    if self.move_to_tosort_var.get() and not audit_only:
                        files_to_move = find_roms_not_in_dat(dat_games, local_roms, local_roms_normalized, output_folder)
                        if files_to_move:
                            moved, failed = move_files_to_tosort(files_to_move, output_folder, os.path.join(output_folder, "ToSort"), False)
                            self.log(f"ToSort: {moved} deplace(s), {failed} echec(s)")
                    torrentzip_summary = {"repacked": 0, "skipped": 0, "failed": 0, "deleted": 0}
                    if self.clean_torrentzip_var.get() and not audit_only:
                        torrentzip_summary = repack_verified_archives_to_torrentzip(dat_games, output_folder, False, self.log, lambda message: self._ui(lambda msg=message: self.status_var.set(msg)), is_running=lambda: self.running)
                    total_size, total_unknown = estimate_games_size(dat_games)
                    missing_size, missing_unknown = estimate_games_size(missing_games)
                    report_paths = write_download_reports(output_folder, {
                        "dat_file": system["dat_path"],
                        "system_name": system_name,
                        "dat_profile": describe_dat_profile(dat_profile),
                        "output_folder": output_folder,
                        "source_url": "",
                        "dry_run": audit_only,
                        "active_sources": [source["name"] for source in sources if source.get("enabled", True)],
                        "total_dat_games": len(dat_games),
                        "present_before": max(0, len(dat_games) - len(missing_games)),
                        "missing_before": len(missing_games),
                        "total_size": total_size,
                        "total_unknown_sizes": total_unknown,
                        "missing_size": missing_size,
                        "missing_unknown_sizes": missing_unknown,
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
                    }, formats=("txt", "json", "csv", "html"))
                    report_txt = report_paths.get("txt", "")
                    self.log(f"Rapport{' audit' if audit_only else ''}: {report_txt}")
                    if audit_only:
                        self._ui(lambda path=report_txt: self.status_var.set(f"Audit termine - rapport: {path}"))
                    else:
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
                window.geometry("560x280")
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

            def _auto_refresh_downloads(self):
                if self.current_page == "downloads" and hasattr(self, "downloads_tree") and self.downloads_tree:
                    try:
                        self._refresh_downloads_tree()
                    except Exception:
                        pass
                if self.running or self.download_worker_running:
                    self.root.after(2000, self._auto_refresh_downloads)

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
