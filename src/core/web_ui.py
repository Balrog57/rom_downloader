"""API et interface web locale pour le catalogue et les telechargements."""
from __future__ import annotations

import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .catalog import list_catalog_systems, list_catalog_games, get_catalog_system
from .local_database import (
    database_status,
    dashboard_stats,
    list_download_jobs,
    list_download_history,
    list_provider_metrics,
    list_validated_providers,
    list_provider_candidates,
    pause_download_job,
    resume_download_job,
    cancel_download_job,
    retry_failed_queue_items,
)
from .mapping_status import build_mapping_status
from .sources import get_default_sources, resolve_system_mapping
from ..version import APP_VERSION

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
"""

_WEB_HEAD = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>ROM Downloader {APP_VERSION} - Web</title>
<style>{_WEB_CSS}</style></head>
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
        self.send_header("Access-Control-Allow-Origin", "*")
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
        if path == "/api/history":
            limit = int(self._query().get("limit", ["200"])[0])
            q = self._query().get("q", [""])[0]
            return self._json(list_download_history({"query": q}, limit=limit))
        if path == "/api/metrics":
            return self._json(list_provider_metrics())
        if path == "/api/providers":
            return self._json(list_validated_providers())
        if path == "/api/candidates":
            return self._json(list_provider_candidates({}))
        if path == "/api/sources":
            return self._json(get_default_sources())
        if path == "/api/mapping":
            return self._json(build_mapping_status())
        return self._error(404, "unknown API endpoint")

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/job/pause":
            return self._job_action(pause_download_job)
        if path == "/api/job/resume":
            return self._job_action(resume_download_job)
        if path == "/api/job/cancel":
            return self._job_action(cancel_download_job)
        if path == "/api/job/retry":
            return self._job_action(retry_failed_queue_items, count=True)
        return self._error(404, "unknown API endpoint")

    def _job_action(self, action, count=False):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        job_id = body.get("job_id", "")
        if not job_id:
            return self._error(400, "missing job_id")
        result = action(job_id)
        if count:
            return self._json({"retried": result})
        return self._json({"ok": result})

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
""")
        elif path == "/systems":
            systems = list_catalog_systems()
            rows = ""
            for item in systems[:200]:
                rows += f"<tr><td><a href=\"/games?sid={item['system_id']}\">{item['system_name']}</a></td><td>{item.get('dat_section','')}</td><td>{item.get('game_count',0)}</td></tr>"
            self._html(f"<h1>Systemes ({len(systems)})</h1><table><tr><th>Systeme</th><th>Section</th><th>Jeux</th></tr>{rows}</table>")
        elif path == "/games":
            sid = self._query().get("sid", [None])[0]
            if not sid:
                return self._html("<h1>Jeux</h1><p>Selectionnez un systeme</p>")
            sys_info = get_catalog_system(sid) or {}
            games = list_catalog_games(sid, limit=200)
            rows = ""
            for g in games:
                rows += f"<tr><td>{g['game_name']}</td><td>{g.get('primary_rom','')}</td><td>{format_bytes_for_web(g.get('size',0))}</td><td>{len(g.get('providers',[]))}</td></tr>"
            self._html(f"<h1>{sys_info.get('system_name',sid)}</h1><table><tr><th>Jeu</th><th>ROM</th><th>Taille</th><th>Providers</th></tr>{rows}</table>")
        elif path == "/jobs":
            jobs = list_download_jobs(status="all", limit=100)
            rows = ""
            for job in jobs:
                q = job.get("queue", {})
                queue_txt = ", ".join(f"{k}={v}" for k, v in sorted(q.items()))
                rows += f"<tr><td>{job['job_id'][:8]}</td><td>{job['status']}</td><td>{job['completed']}/{job['total']}</td><td>{job['output_folder']}</td><td>{queue_txt}</td></tr>"
            self._html(f"<h1>Jobs</h1><table><tr><th>ID</th><th>Statut</th><th>Progression</th><th>Dossier</th><th>File</th></tr>{rows}</table>")
        elif path == "/history":
            rows_items = list_download_history(limit=200)
            rows = ""
            for item in rows_items:
                rows += f"<tr><td>{item.get('date','')}</td><td>{item.get('game_name','')}</td><td>{item.get('provider','')}</td><td>{item.get('status','')}</td></tr>"
            self._html(f"<h1>Historique</h1><table><tr><th>Date</th><th>Jeu</th><th>Provider</th><th>Statut</th></tr>{rows}</table>")
        elif path == "/sources":
            sources = get_default_sources()
            metrics = list_provider_metrics()
            rows = ""
            for src in sources[:30]:
                name = src.get("name", "")
                m = metrics.get(name, {})
                successes = m.get("downloaded", 0)
                failures = m.get("failed", 0)
                speed = format_bytes_for_web(m.get("average_speed", 0)) + "/s" if m.get("average_speed") else ""
                rows += f"<tr><td>{name}</td><td>{src.get('type','')}</td><td>{successes}</td><td>{failures}</td><td>{speed}</td></tr>"
            self._html(f"<h1>Sources</h1><table><tr><th>Provider</th><th>Type</th><th>Succes</th><th>Echecs</th><th>Vitesse</th></tr>{rows}</table>")
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
    server = HTTPServer((host, port), _WebHandler)
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
