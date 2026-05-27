"""API et interface web locale pour le catalogue et les telechargements."""
from __future__ import annotations

import json
import os
import time
import html
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .catalog import list_catalog_systems, list_catalog_games, get_catalog_system
from .scanner import analyze_dat_folder, scan_local_roms, find_missing_games
from .dat_parser import parse_dat_file
from .dat_profile import detect_dat_profile, finalize_dat_profile
from .pipeline import resume_existing_download
from .local_database import (
    database_status,
    dashboard_stats,
    list_download_jobs,
    list_download_history,
    list_provider_metrics,
    build_source_health_summary,
    get_download_job_detail,
    list_validated_providers,
    list_provider_candidates,
    pause_download_job,
    resume_download_job,
    cancel_download_job,
    retry_failed_queue_items,
    create_download_job,
    get_job_config,
)
from .mapping_status import build_mapping_status
from .diagnostics import provider_healthcheck
from .sources import get_default_sources, resolve_system_mapping
from .downloads import recover_orphaned_parts
from .env import PREFERENCES_FILE
from ..network.cache import clear_listing_cache_file, clear_resolution_cache_file
from ..network.utils import load_json_file, save_json_file
from ..version import APP_VERSION

_WEB_THREADS: dict[str, threading.Thread] = {}


def _load_preferences() -> dict:
    return load_json_file(PREFERENCES_FILE, {})


def _save_preferences(preferences: dict) -> bool:
    return save_json_file(PREFERENCES_FILE, preferences or {})


def _clear_caches_for_source(source: str) -> dict:
    from . import _facade
    return _facade.clear_caches_for_source(source)

_WEB_CSS = """
body{font-family:Segoe UI,sans-serif;background:#151515;color:#fff;margin:0;padding:20px}
h1,h2{color:#ff6699}
table{width:100%;border-collapse:collapse;margin:10px 0}
th{background:#1e1e1e;color:#ff6699;padding:8px;text-align:left;border-bottom:2px solid #444}
td{padding:6px 8px;border-bottom:1px solid #333}
tr:hover{background:#1e1e1e}
a{color:#ff6699;text-decoration:none}
a:hover{text-decoration:underline}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px}
.badge-ok{background:#2ecc71;color:#000}
.badge-fail{background:#e74c3c;color:#fff}
.badge-pause{background:#aaaaaa;color:#000}
.nav{background:#242529;padding:10px 20px;margin:-20px -20px 20px;display:flex;gap:15px}
.nav a{color:#fff;font-weight:bold}
.card{background:#1e1e1e;border:1px solid #444;border-radius:6px;padding:15px;margin:10px;display:inline-block;min-width:150px}
.card .value{font-size:28px;font-weight:bold;color:#ff6699}
.card .label{font-size:11px;color:#aaa}
input,button{background:#202020;color:#fff;border:1px solid #444;border-radius:4px;padding:7px;margin:3px}
select{background:#202020;color:#fff;border:1px solid #444;border-radius:4px;padding:7px;margin:3px}
button{cursor:pointer;background:#ff6699;color:#111;font-weight:bold}
button.secondary{background:#333;color:#fff}
.panel{background:#1e1e1e;border:1px solid #444;border-radius:6px;padding:12px;margin:12px 0}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
pre{background:#101010;border:1px solid #333;padding:10px;overflow:auto;max-height:260px}
"""

_WEB_HEAD = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>ROM Downloader {APP_VERSION} - Web</title>
<style>{_WEB_CSS}</style>
<script>
async function apiPost(path, data) {{
  const r = await fetch(path, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(data||{{}})}});
  const j = await r.json();
  const out = document.getElementById('api-result');
  if (out) out.textContent = JSON.stringify(j, null, 2);
  return j;
}}
function formData(run) {{
  return {{
    dat_path: document.getElementById('dat_path')?.value || '',
    rom_folder: document.getElementById('rom_folder')?.value || '',
    output_folder: document.getElementById('output_folder')?.value || document.getElementById('rom_folder')?.value || '',
    candidate_limit: document.getElementById('candidate_limit')?.value || 0,
    parallel_downloads: Number(document.getElementById('parallel')?.value || 1),
    output_mode: document.getElementById('output_mode')?.value || 'flat',
    archive_mode: document.getElementById('archive_mode')?.value || 'none',
    frontend: document.getElementById('frontend')?.value || '',
    include_tosort: true,
    run: !!run
  }};
}}
async function analyzeForm() {{ return apiPost('/api/analyze', formData(false)); }}
async function createJob(run) {{ return apiPost('/api/job/create', formData(run)); }}
async function jobAction(path, job_id, extra) {{ return apiPost(path, Object.assign({{job_id}}, extra || {{}})); }}
async function retryError(job_id, error_code) {{ return jobAction('/api/job/retry', job_id, {{error_code}}); }}
async function retryRetryable(job_id) {{ return jobAction('/api/job/retry', job_id, {{retryable_only:true}}); }}
async function cleanupJobParts(job_id) {{ return jobAction('/api/job/cleanup-parts', job_id); }}
async function clearCaches(source) {{ return apiPost('/api/cache/clear', source ? {{source}} : {{}}); }}
async function testSources() {{ return apiPost('/api/source/test', {{}}); }}
setInterval(() => {{
  const table = document.getElementById('jobs-table');
  if (table) fetch('/jobs').then(r=>r.text()).then(t=>{{ const d=document.createElement('div'); d.innerHTML=t; const n=d.querySelector('#jobs-table'); if(n) table.innerHTML=n.innerHTML; }});
}}, 5000);
</script></head>
<body>
<div class="nav">
<a href="/">Accueil</a>
<a href="/systems">Systemes</a>
<a href="/jobs">Jobs</a>
<a href="/history">Historique</a>
<a href="/sources">Sources</a>
<a href="/api/status">API status</a>
</div>
"""

_WEB_FOOT = "</body></html>"


class _WebHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _ok(self, content_type="text/html; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()

    def _json(self, data):
        self._ok("application/json; charset=utf-8")
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def _html(self, body: str):
        self._ok()
        self.wfile.write((_WEB_HEAD + body + _WEB_FOOT).encode("utf-8"))

    def _error(self, code: int, msg: str):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode("utf-8"))

    def _query(self):
        parsed = urlparse(self.path)
        return parse_qs(parsed.query)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path.startswith("/api/"):
            return self._handle_api(path)
        return self._handle_page(path)

    def _handle_api(self, path):
        if path == "/api/status":
            return self._json(database_status())
        if path == "/api/dashboard":
            return self._json(dashboard_stats())
        if path == "/api/systems":
            systems = list_catalog_systems()
            return self._json(systems)
        if path == "/api/system":
            sid = self._query().get("id", [None])[0]
            if not sid:
                return self._error(400, "missing id")
            return self._json(get_catalog_system(sid) or {})
        if path == "/api/games":
            sid = self._query().get("sid", [None])[0]
            q = self._query().get("q", [""])[0]
            letter = self._query().get("letter", ["all"])[0]
            if not sid:
                return self._error(400, "missing sid")
            return self._json(list_catalog_games(sid, q, letter))
        if path == "/api/jobs":
            status = self._query().get("status", ["all"])[0]
            limit = int(self._query().get("limit", ["50"])[0])
            return self._json(list_download_jobs(status=status, limit=limit))
        if path == "/api/job":
            from .local_database import run_download_job
            job_id = self._query().get("id", [None])[0]
            if not job_id:
                return self._error(400, "missing id")
            return self._json(run_download_job(job_id))
        if path == "/api/job/status":
            job_id = self._query().get("id", [None])[0]
            if not job_id:
                return self._error(400, "missing id")
            config = get_job_config(job_id) or {}
            if config:
                config["job_id"] = job_id
            return self._json(config)
        if path == "/api/job/detail":
            job_id = self._query().get("id", [None])[0]
            if not job_id:
                return self._error(400, "missing id")
            detail = get_download_job_detail(job_id)
            if not detail:
                return self._error(404, "job introuvable")
            return self._json(detail)
        if path == "/api/history":
            limit = int(self._query().get("limit", ["200"])[0])
            q = self._query().get("q", [""])[0]
            status = self._query().get("status", ["all"])[0]
            error_code = self._query().get("error_code", [""])[0]
            retryable_raw = self._query().get("retryable", [""])[0].strip().lower()
            retryable = None
            if retryable_raw in {"1", "true", "yes", "oui"}:
                retryable = True
            elif retryable_raw in {"0", "false", "no", "non"}:
                retryable = False
            return self._json(list_download_history({
                "query": q,
                "status": status,
                "error_code": error_code,
                "retryable": retryable,
            }, limit=limit))
        if path == "/api/metrics":
            return self._json(list_provider_metrics())
        if path == "/api/source/health":
            return self._json(build_source_health_summary(get_default_sources()))
        if path == "/api/providers":
            game_id = self._query().get("game_id", [""])[0]
            if not game_id:
                return self._error(400, "missing game_id")
            return self._json(list_validated_providers(game_id))
        if path == "/api/candidates":
            game_id = self._query().get("game_id", [""])[0]
            if not game_id:
                return self._error(400, "missing game_id")
            status = self._query().get("status", ["all"])[0]
            return self._json(list_provider_candidates(game_id, status=status))
        if path == "/api/sources":
            return self._json(get_default_sources())
        if path == "/api/mapping":
            return self._json(build_mapping_status())
        return self._error(404, "unknown API endpoint")

    def do_POST(self):
        if not self._same_origin_request():
            return self._error(403, "origine refusee")
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/job/pause":
            return self._job_action(pause_download_job)
        if path == "/api/job/resume":
            return self._job_action(resume_download_job)
        if path == "/api/job/cancel":
            return self._job_action(cancel_download_job)
        if path == "/api/job/retry":
            return self._api_job_retry()
        if path == "/api/job/cleanup-parts":
            return self._api_job_cleanup_parts()
        if path == "/api/analyze":
            return self._api_analyze()
        if path == "/api/job/create":
            return self._api_job_create()
        if path == "/api/job/run":
            return self._api_job_run()
        if path == "/api/source/test":
            return self._json({"results": provider_healthcheck()})
        if path == "/api/source/policy":
            return self._api_source_policy()
        if path == "/api/cache/clear":
            return self._api_cache_clear()
        return self._error(404, "unknown API endpoint")

    def _same_origin_request(self) -> bool:
        """Bloque les POST cross-origin pour eviter les actions CSRF sur l'UI locale."""
        host = (self.headers.get("Host") or "").strip().lower()
        for header in ("Origin", "Referer"):
            value = (self.headers.get(header) or "").strip()
            if not value:
                continue
            parsed = urlparse(value)
            if parsed.netloc and parsed.netloc.lower() != host:
                return False
        return True

    def _job_action(self, action, count=False):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        job_id = body.get("job_id", "")
        if not job_id:
            return self._error(400, "missing job_id")
        result = action(job_id)
        if count:
            return self._json({"retried": result})
        return self._json({"ok": result})

    def _api_job_retry(self):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        job_id = body.get("job_id", "")
        if not job_id:
            return self._error(400, "missing job_id")
        retried = retry_failed_queue_items(
            job_id,
            error_code=body.get("error_code", "") or "",
            retryable_only=bool(body.get("retryable_only", False)),
        )
        return self._json({"retried": retried})

    def _api_job_cleanup_parts(self):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        job_id = body.get("job_id", "")
        if not job_id:
            return self._error(400, "missing job_id")
        config = get_job_config(job_id) or {}
        output_folder = config.get("output_folder", "")
        if not output_folder:
            return self._error(404, "job introuvable")
        removed = recover_orphaned_parts(output_folder)
        return self._json({"ok": True, "removed": len(removed), "files": removed[:50]})

    def _json_body(self, max_length: int = 65536):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return (400, "taille de requete invalide")
        if length > max_length:
            return (413, "requete trop volumineuse")
        try:
            return json.loads(self.rfile.read(length)) if length else {}
        except json.JSONDecodeError:
            return (400, "json invalide")

    def _api_analyze(self):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        dat_path = body.get("dat_path", "")
        rom_folder = body.get("rom_folder", "")
        if not dat_path or not rom_folder:
            return self._error(400, "dat_path et rom_folder requis")
        return self._json(analyze_dat_folder(
            dat_path,
            rom_folder,
            include_tosort=bool(body.get("include_tosort", False)),
            candidate_limit=body.get("candidate_limit", 0),
        ))

    def _missing_games_for_job(self, dat_path: str, rom_folder: str) -> tuple[list, str]:
        dat_games = parse_dat_file(dat_path)
        profile = finalize_dat_profile(detect_dat_profile(dat_path))
        local_roms, local_roms_normalized, local_game_names, signature_index = scan_local_roms(rom_folder, dat_games)
        missing = find_missing_games(dat_games, local_roms, local_roms_normalized, local_game_names, signature_index)
        return missing, ""

    def _api_job_create(self):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        dat_path = body.get("dat_path", "")
        rom_folder = body.get("rom_folder", "")
        output_folder = body.get("output_folder") or rom_folder
        if not dat_path or not rom_folder:
            return self._error(400, "dat_path et rom_folder requis")
        missing, system_id = self._missing_games_for_job(dat_path, rom_folder)
        settings = {
            "dat_path": dat_path,
            "rom_folder": rom_folder,
            "parallel_downloads": int(body.get("parallel_downloads") or 1),
            "report_formats": body.get("report_formats") or "txt,json,csv,html",
            "output_mode": body.get("output_mode") or "flat",
            "archive_mode": body.get("archive_mode") or "none",
            "frontend": body.get("frontend") or None,
            "dry_run": bool(body.get("dry_run", False)),
        }
        job_id = create_download_job(system_id, missing, output_folder, settings=settings)
        if body.get("run"):
            self._start_job_thread(job_id)
        return self._json({"job_id": job_id, "queued": len(missing), "running": bool(body.get("run"))})

    def _start_job_thread(self, job_id: str):
        if job_id in _WEB_THREADS and _WEB_THREADS[job_id].is_alive():
            return
        config = get_job_config(job_id) or {}
        settings = config.get("settings") or {}
        dat_path = settings.get("dat_path", "")
        rom_folder = settings.get("rom_folder") or config.get("output_folder", "")
        parallel = int(settings.get("parallel_downloads") or 1)

        def _run():
            if dat_path and rom_folder:
                resume_existing_download(
                    job_id,
                    dat_path,
                    rom_folder,
                    parallel_downloads=parallel,
                    output_mode=settings.get("output_mode") or "flat",
                    archive_mode=settings.get("archive_mode") or "none",
                    frontend=settings.get("frontend") or None,
                    report_formats=settings.get("report_formats", "txt"),
                )

        thread = threading.Thread(target=_run, name=f"romdl-web-job-{job_id[:8]}", daemon=True)
        _WEB_THREADS[job_id] = thread
        thread.start()

    def _api_job_run(self):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        job_id = body.get("job_id", "")
        if not job_id:
            return self._error(400, "missing job_id")
        self._start_job_thread(job_id)
        return self._json({"ok": True, "job_id": job_id})

    def _api_source_policy(self):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        source = body.get("source", "")
        if not source:
            return self._error(400, "source requise")
        prefs = _load_preferences()
        policies = dict(prefs.get("source_policies", {}))
        current = dict(policies.get(source, {}))
        for key in ("enabled", "timeout", "delay_seconds", "quota_per_run", "user_agent", "cookies"):
            if key in body:
                current[key] = body[key]
        policies[source] = current
        prefs["source_policies"] = policies
        _save_preferences(prefs)
        return self._json({"ok": True, "source": source, "policy": current})

    def _api_cache_clear(self):
        body = self._json_body()
        if isinstance(body, tuple):
            return self._error(body[0], body[1])
        source = body.get("source", "")
        if source:
            return self._json({"ok": True, "removed": _clear_caches_for_source(source)})
        clear_resolution_cache_file()
        clear_listing_cache_file()
        return self._json({"ok": True, "removed": "all"})

    def _handle_page(self, path):
        if path == "/":
            stats = dashboard_stats()
            jobs = stats.get("jobs", {})
            active = jobs.get("active", 0)
            paused = jobs.get("paused", 0)
            failed = jobs.get("failed", 0)
            completed = jobs.get("completed", 0)
            self._html(f"""
<h1>ROM Downloader {APP_VERSION}</h1>
<div>
<div class="card"><div class="value">{stats['systems']}</div><div class="label">Systemes</div></div>
<div class="card"><div class="value">{stats['games']}</div><div class="label">Jeux</div></div>
<div class="card"><div class="value">{stats['verified']}</div><div class="label">Verifies</div></div>
<div class="card"><div class="value">{stats['valid_providers']}</div><div class="label">Providers valides</div></div>
<div class="card"><div class="value">{stats['attempts_24h']}</div><div class="label">Tentatives 24h</div></div>
<div class="card"><div class="value">{format_bytes_for_web(stats['average_speed'])}/s</div><div class="label">Vitesse moyenne</div></div>
</div>
<h2>Jobs</h2>
<span class="badge badge-ok">Actifs: {active}</span>
<span class="badge badge-pause">Pause: {paused}</span>
<span class="badge badge-fail">Echoues: {failed}</span>
<span class="badge badge-ok">Termines: {completed}</span>
<div class="panel">
<h2>Analyse / job</h2>
<div class="row">
<input id="dat_path" size="52" placeholder="Chemin DAT">
<input id="rom_folder" size="42" placeholder="Dossier ROMs">
<input id="output_folder" size="42" placeholder="Dossier sortie optionnel">
<input id="candidate_limit" type="number" min="0" value="0" title="Candidates">
<input id="parallel" type="number" min="1" max="12" value="2" title="Parallele">
<select id="output_mode" title="Mode de sortie">
<option value="flat">Flat</option>
<option value="verified">Verified</option>
<option value="tosort">ToSort</option>
<option value="dat-structure">Structure DAT</option>
</select>
<select id="archive_mode" title="Mode archive">
<option value="none">Archive: aucune</option>
<option value="zip">ZIP</option>
<option value="torrentzip">TorrentZip</option>
</select>
<select id="frontend" title="Frontend">
<option value="">Frontend: aucun</option>
<option value="batocera">Batocera</option>
<option value="retrobat">RetroBat</option>
<option value="es-de">ES-DE</option>
<option value="launchbox">LaunchBox</option>
</select>
</div>
<button onclick="analyzeForm()">Analyser</button>
<button class="secondary" onclick="createJob(false)">Creer job</button>
<button onclick="createJob(true)">Creer et lancer</button>
<pre id="api-result"></pre>
</div>
""")
        elif path == "/systems":
            systems = list_catalog_systems()
            rows = ""
            for item in systems[:200]:
                sid = html.escape(str(item.get('system_id', '')), quote=True)
                system_label = html.escape(str(item.get('system_name', '')))
                section = html.escape(str(item.get('dat_section', '')))
                rows += f"<tr><td><a href=\"/games?sid={sid}\">{system_label}</a></td><td>{section}</td><td>{item.get('game_count',0)}</td></tr>"
            self._html(f"<h1>Systemes ({len(systems)})</h1><table><tr><th>Systeme</th><th>Section</th><th>Jeux</th></tr>{rows}</table>")
        elif path == "/games":
            sid = self._query().get("sid", [None])[0]
            if not sid:
                return self._html("<h1>Jeux</h1><p>Selectionnez un systeme</p>")
            sys_info = get_catalog_system(sid) or {}
            games = list_catalog_games(sid, limit=200)
            rows = ""
            for g in games:
                game_name = html.escape(str(g.get('game_name', '')))
                primary_rom = html.escape(str(g.get('primary_rom', '')))
                rows += f"<tr><td>{game_name}</td><td>{primary_rom}</td><td>{format_bytes_for_web(g.get('size',0))}</td><td>{len(g.get('providers',[]))}</td></tr>"
            title = html.escape(str(sys_info.get('system_name', sid)))
            self._html(f"<h1>{title}</h1><table><tr><th>Jeu</th><th>ROM</th><th>Taille</th><th>Providers</th></tr>{rows}</table>")
        elif path == "/jobs":
            jobs = list_download_jobs(status="all", limit=100)
            rows = ""
            for job in jobs:
                q = job.get("queue", {})
                queue_txt = ", ".join(f"{k}={v}" for k, v in sorted(q.items()))
                job_short = html.escape(str(job.get('job_id', ''))[:8])
                status = html.escape(str(job.get('status', '')))
                output = html.escape(str(job.get('output_folder', '')))
                queue_html = html.escape(queue_txt)
                job_id = html.escape(str(job.get('job_id', '')), quote=True)
                detail_link = f"<a href=\"/job?id={job_id}\">{job_short}</a>"
                actions = (
                    f"<button onclick=\"jobAction('/api/job/run','{job_id}')\">Run</button>"
                    f"<button class=\"secondary\" onclick=\"jobAction('/api/job/pause','{job_id}')\">Pause</button>"
                    f"<button class=\"secondary\" onclick=\"jobAction('/api/job/resume','{job_id}')\">Resume</button>"
                    f"<button class=\"secondary\" onclick=\"jobAction('/api/job/retry','{job_id}')\">Retry</button>"
                    f"<button class=\"secondary\" onclick=\"jobAction('/api/job/cancel','{job_id}')\">Cancel</button>"
                )
                rows += f"<tr><td>{detail_link}</td><td>{status}</td><td>{job['completed']}/{job['total']}</td><td>{output}</td><td>{queue_html}</td><td>{actions}</td></tr>"
            self._html(f"<h1>Jobs</h1><table id=\"jobs-table\"><tr><th>ID</th><th>Statut</th><th>Progression</th><th>Dossier</th><th>File</th><th>Actions</th></tr>{rows}</table><pre id=\"api-result\"></pre>")
        elif path == "/job":
            job_id_raw = self._query().get("id", [""])[0]
            detail = get_download_job_detail(job_id_raw)
            if not detail:
                return self._html("<h1>Job</h1><p>Job introuvable</p>")
            job = detail.get("job", {})
            job_id = html.escape(str(job.get("job_id", "")), quote=True)
            queue_txt = ", ".join(f"{k}={v}" for k, v in sorted((detail.get("queue") or {}).items())) or "vide"
            errors_txt = ", ".join(f"{k}={v}" for k, v in sorted((detail.get("errors") or {}).items())) or "aucune"
            parts = detail.get("parts") or {}
            summary = detail.get("summary") or {}
            item_rows = ""
            for item in detail.get("items", [])[:100]:
                item_rows += (
                    "<tr>"
                    f"<td>{html.escape(str(item.get('status', '')))}</td>"
                    f"<td>{html.escape(str(item.get('game_name', '')))}</td>"
                    f"<td>{html.escape(str(item.get('priority', 0)))}</td>"
                    f"<td>{html.escape(str(item.get('attempt_count', 0)))}</td>"
                    f"<td>{html.escape(str(item.get('locked_by', '') or ''))}</td>"
                    "</tr>"
                )
            attempt_rows = ""
            for attempt in detail.get("attempts", [])[:100]:
                attempt_rows += (
                    "<tr>"
                    f"<td>{html.escape(str(attempt.get('status', '')))}</td>"
                    f"<td>{html.escape(str(attempt.get('game_name', '')))}</td>"
                    f"<td>{html.escape(str(attempt.get('provider', '')))}</td>"
                    f"<td>{html.escape(str(attempt.get('error_code', '') or '-'))}</td>"
                    f"<td>{html.escape(str(attempt.get('detail', '') or ''))}</td>"
                    "</tr>"
                )
            actions = (
                f"<button onclick=\"jobAction('/api/job/run','{job_id}')\">Run</button>"
                f"<button class=\"secondary\" onclick=\"jobAction('/api/job/pause','{job_id}')\">Pause</button>"
                f"<button class=\"secondary\" onclick=\"jobAction('/api/job/resume','{job_id}')\">Resume</button>"
                f"<button class=\"secondary\" onclick=\"jobAction('/api/job/retry','{job_id}')\">Retry</button>"
                f"<button class=\"secondary\" onclick=\"retryRetryable('{job_id}')\">Retry retryable</button>"
                f"<button class=\"secondary\" onclick=\"cleanupJobParts('{job_id}')\">Nettoyer .part</button>"
                f"<button class=\"secondary\" onclick=\"jobAction('/api/job/cancel','{job_id}')\">Cancel</button>"
            )
            error_actions = ""
            for error_code in sorted((detail.get("errors") or {}).keys()):
                code = html.escape(str(error_code), quote=True)
                error_actions += f"<button class=\"secondary\" onclick=\"retryError('{job_id}','{code}')\">Retry {code}</button>"
            self._html(
                f"<h1>Job {html.escape(str(job.get('job_id', ''))[:8])}</h1>"
                f"<p>Statut: {html.escape(str(job.get('status', '')))} - Progression: {job.get('completed', 0)}/{job.get('total', 0)}</p>"
                f"<p>Dossier: {html.escape(str(job.get('output_folder', '')))}</p>"
                f"<p>File: {html.escape(queue_txt)}<br>Erreurs: {html.escape(errors_txt)}"
                f"<br>Fragments .part: {parts.get('count', 0)} ({format_bytes_for_web(parts.get('bytes', 0))})"
                f"<br>Retryable recents: {summary.get('retryable_recent', 0)}"
                f"<br>Derniere mise a jour: {int(summary.get('seconds_since_update') or 0)}s</p>"
                f"<div class=\"row\">{actions}{error_actions}</div><pre id=\"api-result\"></pre>"
                "<h2>Items</h2><table><tr><th>Statut</th><th>Jeu</th><th>Priorite</th><th>Essais</th><th>Lock</th></tr>"
                f"{item_rows}</table>"
                "<h2>Tentatives recentes</h2><table><tr><th>Statut</th><th>Jeu</th><th>Provider</th><th>Erreur</th><th>Detail</th></tr>"
                f"{attempt_rows}</table>"
            )
        elif path == "/history":
            rows_items = list_download_history(limit=200)
            rows = ""
            for item in rows_items:
                date = html.escape(str(item.get('date', '')))
                game_name = html.escape(str(item.get('game_name', '')))
                provider = html.escape(str(item.get('provider', '')))
                status = html.escape(str(item.get('status', '')))
                rows += f"<tr><td>{date}</td><td>{game_name}</td><td>{provider}</td><td>{status}</td></tr>"
            self._html(
                "<h1>Historique</h1>"
                "<div class=\"row\">"
                "<a class=\"badge badge-fail\" href=\"/api/history?status=failed&limit=500\">Export echecs JSON</a>"
                "<a class=\"badge badge-ok\" href=\"/api/history?status=failed&retryable=1&limit=500\">Export retryable JSON</a>"
                "</div>"
                f"<table><tr><th>Date</th><th>Jeu</th><th>Provider</th><th>Statut</th></tr>{rows}</table>"
            )
        elif path == "/sources":
            health_rows = build_source_health_summary(get_default_sources())
            rows = ""
            for src in health_rows[:50]:
                name = src.get("provider", "")
                successes = src.get("success_count", 0)
                failures = src.get("failure_count", 0)
                speed = format_bytes_for_web(src.get("average_speed", 0)) + "/s" if src.get("average_speed") else ""
                status = html.escape(str(src.get("status", "")))
                score = f"{float(src.get('score') or 0):.2f}"
                coverage = int(src.get("coverage") or 0)
                candidates = int(src.get("active_candidates") or 0)
                last_error = html.escape(str(src.get("last_error_code") or ""))
                reasons = html.escape(", ".join(src.get("score_reasons") or []))
                action = html.escape(str(src.get("recommended_action") or ""))
                js_name = html.escape(json.dumps(str(name)), quote=True)
                rows += (
                    f"<tr><td>{html.escape(str(name))}</td><td>{html.escape(str(src.get('type','')))}</td>"
                    f"<td>{status}</td><td>{score}</td><td>{coverage}</td><td>{candidates}</td>"
                    f"<td>{successes}</td><td>{failures}</td><td>{speed}</td>"
                    f"<td>{last_error}</td><td>{reasons}</td><td>{action}</td>"
                    f"<td><button onclick=\"clearCaches({js_name})\">Cache</button></td></tr>"
                )
            self._html(
                "<h1>Sources</h1><button onclick=\"testSources()\">Tester maintenant</button>"
                "<button class=\"secondary\" onclick=\"clearCaches('')\">Vider caches</button>"
                "<table><tr><th>Provider</th><th>Type</th><th>Statut</th><th>Score</th><th>Couverture</th>"
                "<th>Candidats</th><th>Succes</th><th>Echecs</th><th>Vitesse</th>"
                "<th>Derniere erreur</th><th>Raisons</th><th>Action</th><th>Cache</th></tr>"
                f"{rows}</table><pre id=\"api-result\"></pre>"
            )
        else:
            self._html("<h1>404</h1><p>Page non trouvee</p>")


def format_bytes_for_web(val):
    if not val:
        return "0 B"
    val = float(val)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TB"


def run_web_ui(host: str = "127.0.0.1", port: int = 8888, open_browser: bool = True):
    """Lance l'interface web locale."""
    server = ThreadingHTTPServer((host, port), _WebHandler)
    url = f"http://{host}:{port}"
    print(f"Web UI: {url}")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArret du serveur web")
        server.shutdown()
