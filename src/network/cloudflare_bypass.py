import os
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


_BROWSER_POOL = None
_MAX_BROWSERS = 1


def _get_browser_args():
    return [
        '--disable-blink-features=AutomationControlled',
        '--disable-web-security',
        '--disable-features=IsolateOrigins,site-per-process',
        '--disable-dev-shm-usage',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-accelerated-2d-canvas',
        '--disable-gpu',
        '--window-size=1920,1080',
    ]


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, '').strip().lower()
    if not value:
        return default
    return value in {'1', 'true', 'yes', 'oui', 'on'}


def _browser_channel() -> str | None:
    value = os.environ.get('LOLROMS_BROWSER_CHANNEL', '').strip()
    if value:
        return None if value.lower() in {'none', 'bundled', 'chromium'} else value
    return 'msedge' if os.name == 'nt' else None


def _launch_browser(headless=True):
    pw = sync_playwright().start()
    launch_kwargs = {
        'headless': headless,
        'args': _get_browser_args(),
    }
    channel = _browser_channel()
    if channel:
        launch_kwargs['channel'] = channel
    try:
        browser = pw.chromium.launch(**launch_kwargs)
    except Exception:
        launch_kwargs.pop('channel', None)
        browser = pw.chromium.launch(**launch_kwargs)
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        locale='fr-FR',
        viewport={'width': 1920, 'height': 1080},
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        window.chrome = { runtime: {} };
    """)
    return pw, browser, context


def _persistent_profile_dir() -> str:
    configured = os.environ.get('LOLROMS_BROWSER_PROFILE', '').strip()
    if configured:
        return str(Path(configured).expanduser())
    return str(Path(tempfile.gettempdir()) / 'rom_downloader_lolroms_browser_profile')


def _native_browser_profile_dir() -> Path:
    configured = os.environ.get('LOLROMS_NATIVE_BROWSER_PROFILE', '').strip()
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / 'rom_downloader_lolroms_native_profile'


def _find_edge_executable() -> str:
    configured = os.environ.get('LOLROMS_EDGE_PATH', '').strip()
    candidates = [
        configured,
        shutil.which('msedge') or '',
        shutil.which('microsoft-edge') or '',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ''


def _write_chromium_download_preferences(profile_dir: Path, download_dir: Path):
    default_dir = profile_dir / 'Default'
    default_dir.mkdir(parents=True, exist_ok=True)
    preferences_path = default_dir / 'Preferences'
    preferences = {}
    if preferences_path.exists():
        try:
            preferences = json.loads(preferences_path.read_text(encoding='utf-8'))
        except Exception:
            preferences = {}
    preferences.setdefault('download', {})
    preferences['download'].update({
        'default_directory': str(download_dir),
        'directory_upgrade': True,
        'prompt_for_download': False,
    })
    preferences.setdefault('safebrowsing', {})
    preferences['safebrowsing']['enabled'] = True
    preferences_path.write_text(json.dumps(preferences), encoding='utf-8')


def _matching_downloaded_file(download_dir: Path, target_name: str, started_at: float) -> Path | None:
    expected = download_dir / target_name
    if expected.exists() and expected.stat().st_size > 0:
        return expected

    stem = Path(target_name).stem
    suffix = Path(target_name).suffix.lower()
    candidates = []
    for path in download_dir.glob(f"{stem}*{suffix}"):
        try:
            if path.stat().st_mtime + 1 < started_at or path.stat().st_size <= 0:
                continue
            if path.with_name(path.name + '.crdownload').exists():
                continue
            candidates.append(path)
        except OSError:
            continue
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _download_in_progress(download_dir: Path, target_name: str) -> bool:
    stem = Path(target_name).stem
    return any(download_dir.glob(f"{stem}*.crdownload"))


def cloudflare_native_edge_download_file(url: str, dest_path: str, timeout_ms: int = 300000,
                                         progress_callback=None) -> tuple[bool, dict]:
    """Ouvre Edge sans automatisation pour laisser Cloudflare valider une vraie session."""
    edge = _find_edge_executable()
    if not edge:
        print("  Edge introuvable: impossible d'ouvrir le fallback natif LoLROMs.")
        return False, {}

    download_dir = Path(dest_path).parent
    download_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = _native_browser_profile_dir()
    _write_chromium_download_preferences(profile_dir, download_dir)

    target_name = unquote(urlsplit(url).path.rsplit('/', 1)[-1]) or Path(dest_path).name
    started_at = time.time()
    args = [
        edge,
        f'--user-data-dir={profile_dir}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-popup-blocking',
        url,
    ]
    print("  LoLROMs: ouverture Edge natif pour passer Cloudflare et telecharger le fichier...")
    print("  La commande reprendra automatiquement des que le .7z apparait dans le dossier cible.")
    proc = None
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + (timeout_ms / 1000)
        last_progress = 0.0
        while time.monotonic() < deadline:
            downloaded = _matching_downloaded_file(download_dir, target_name, started_at)
            if downloaded:
                final_path = Path(dest_path).with_name(downloaded.name)
                if downloaded.resolve() != final_path.resolve():
                    os.replace(downloaded, final_path)
                if progress_callback:
                    progress_callback(100.0)
                try:
                    proc.terminate()
                except Exception:
                    pass
                return True, {}

            if progress_callback and _download_in_progress(download_dir, target_name):
                last_progress = min(95.0, last_progress + 1.0)
                progress_callback(last_progress)
            time.sleep(2)
        print("  LoLROMs: delai depasse en attente du fichier Edge natif.")
        return False, {}
    except Exception as e:
        print(f"  Edge natif LoLROMs echoue: {e}")
        return False, {}


def _page_looks_like_cloudflare_challenge(page) -> bool:
    try:
        title = (page.title() or '').lower()
        current_url = (page.url or '').lower()
        if '__cf_chl' in current_url:
            return True
        if any(marker in title for marker in ('just a moment', 'un instant', 'cloudflare')):
            return True
        html = (page.content() or '').lower()
        return any(marker in html for marker in (
            'cf-mitigated',
            'challenge-platform',
            'checking your browser',
            'un instant',
            'just a moment',
            'cloudflare',
        ))
    except Exception:
        return False


def _save_playwright_download(download, dest_path: str) -> Path:
    suggested = download.suggested_filename or Path(dest_path).name
    final_path = Path(dest_path).with_name(suggested)
    part_path = final_path.with_suffix(final_path.suffix + '.part')
    download.save_as(str(part_path))
    os.replace(part_path, final_path)
    return final_path


def _click_lolroms_download_link(page, href: str, target_name: str, timeout_ms: int):
    links = page.locator('a[href$=".7z"]').filter(has_text=target_name)
    if links.count() > 0:
        links.first.click(timeout=min(timeout_ms, 30000), no_wait_after=True)
        return
    page.evaluate(
        """href => {
            const a = document.createElement('a');
            a.href = href;
            a.rel = 'noopener';
            document.body.appendChild(a);
            a.click();
            a.remove();
        }""",
        href,
    )


def cloudflare_bypass_fetch(url: str, timeout_ms: int = 60000, headless: bool = True) -> str:
    """Ouvre une URL derriere Cloudflare avec Playwright headless et retourne le HTML final."""
    pw = None
    browser = None
    try:
        pw, browser, context = _launch_browser(headless=headless)
        page = context.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
        # Attendre la fin du challenge Cloudflare (turnstile / IUAM)
        for _ in range(60):
            title = page.title()
            if 'Just a moment' not in title and 'Cloudflare' not in title:
                break
            if page.query_selector('input[name="cf-turnstile-response"]'):
                time.sleep(2)
                continue
            time.sleep(1)
        else:
            # dernier recours : attendre networkidle
            page.wait_for_load_state('networkidle', timeout=timeout_ms)
        html = page.content()
        return html
    except PlaywrightTimeout:
        return ''
    except Exception:
        return ''
    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()


def cloudflare_bypass_fetch_with_cookies(url: str, timeout_ms: int = 60000, headless: bool = True) -> tuple[str, dict]:
    """Retourne (html, cookies_dict) pour reutiliser la session dans requests/cloudscraper."""
    pw = None
    browser = None
    try:
        pw, browser, context = _launch_browser(headless=headless)
        page = context.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
        for _ in range(60):
            title = page.title()
            if 'Just a moment' not in title and 'Cloudflare' not in title:
                break
            time.sleep(1)
        else:
            page.wait_for_load_state('networkidle', timeout=timeout_ms)
        html = page.content()
        cookies = {}
        for c in context.cookies():
            cookies[c['name']] = c['value']
        return html, cookies
    except PlaywrightTimeout:
        return '', {}
    except Exception:
        return '', {}
    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()


def cloudflare_browser_download_file(url: str, dest_path: str, timeout_ms: int = 180000,
                                     headless: bool | None = None,
                                     progress_callback=None) -> tuple[bool, dict]:
    """Telecharge via un vrai contexte navigateur quand Cloudflare bloque le fichier.

    Le mode visible est volontairement le defaut pour les downloads LoLROMs: la challenge
    Cloudflare actuelle des .7z ne se resout pas de facon fiable en headless.
    """
    if headless is None:
        headless = _env_flag('LOLROMS_BROWSER_HEADLESS', False)
    if not headless and os.environ.get('LOLROMS_BROWSER_MODE', 'native').strip().lower() != 'playwright':
        return cloudflare_native_edge_download_file(url, dest_path, timeout_ms, progress_callback)

    pw = None
    context = None
    try:
        if progress_callback:
            progress_callback(0.0)
        pw = sync_playwright().start()
        launch_kwargs = {
            'headless': headless,
            'args': _get_browser_args(),
            'accept_downloads': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'locale': 'fr-FR',
            'viewport': {'width': 1920, 'height': 1080},
        }
        channel = _browser_channel()
        if channel:
            launch_kwargs['channel'] = channel
        try:
            context = pw.chromium.launch_persistent_context(_persistent_profile_dir(), **launch_kwargs)
        except Exception:
            launch_kwargs.pop('channel', None)
            context = pw.chromium.launch_persistent_context(_persistent_profile_dir(), **launch_kwargs)

        page = context.new_page()
        directory_url = url.rsplit('/', 1)[0] + '/' if '/' in url else urljoin(url, '/')
        target_name = unquote(urlsplit(url).path.rsplit('/', 1)[-1])
        page.goto(directory_url, wait_until='domcontentloaded', timeout=timeout_ms)

        href = page.evaluate(
            """target => {
                const links = Array.from(document.querySelectorAll('a[href]'));
                const found = links.find(a => {
                    try {
                        return decodeURIComponent(new URL(a.href, document.baseURI).pathname.split('/').pop()) === target;
                    } catch (_) {
                        return false;
                    }
                });
                return found ? found.href : '';
            }""",
            target_name,
        )
        if not href:
            href = url

        print(
            "  LoLROMs: ouverture du navigateur pour valider Cloudflare..."
            if not headless else
            "  LoLROMs: tentative de telechargement via navigateur headless..."
        )
        if not headless:
            print("  Si Cloudflare affiche une verification, validez-la dans la fenetre du navigateur.")

        downloads = []
        page.on('download', lambda download: downloads.append(download))
        attempts = max(1, int(os.environ.get('LOLROMS_BROWSER_DOWNLOAD_ATTEMPTS', '3') or '3'))
        cookies = {}
        for attempt in range(1, attempts + 1):
            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    _click_lolroms_download_link(page, href, target_name, timeout_ms)
                download = download_info.value
                _save_playwright_download(download, dest_path)
                if progress_callback:
                    progress_callback(100.0)
                cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                return True, cookies
            except PlaywrightTimeout:
                if downloads:
                    _save_playwright_download(downloads[-1], dest_path)
                    if progress_callback:
                        progress_callback(100.0)
                    cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                    return True, cookies

                cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                if not _page_looks_like_cloudflare_challenge(page):
                    if attempt < attempts:
                        page.goto(directory_url, wait_until='domcontentloaded', timeout=timeout_ms)
                        continue
                    return False, cookies

                if headless:
                    return False, cookies

                print("  LoLROMs: Cloudflare attend une validation; nouvelle tentative apres validation...")
                wait_until = time.monotonic() + (timeout_ms / 1000)
                while time.monotonic() < wait_until and _page_looks_like_cloudflare_challenge(page):
                    page.wait_for_timeout(3000)
                    if downloads:
                        _save_playwright_download(downloads[-1], dest_path)
                        if progress_callback:
                            progress_callback(100.0)
                        cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                        return True, cookies
                cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                if attempt < attempts:
                    try:
                        page.goto(directory_url, wait_until='domcontentloaded', timeout=timeout_ms)
                    except Exception:
                        pass

        return False, cookies
    except PlaywrightTimeout:
        return False, {}
    except Exception as e:
        print(f"  Telechargement navigateur LoLROMs echoue: {e}")
        return False, {}
    finally:
        if context:
            context.close()
        if pw:
            pw.stop()


def lolroms_list_directories(base_url: str = 'https://lolroms.com', headless: bool = True) -> list[str]:
    """Scrape la page d'accueil de LoLROMs avec le bypass et retourne la liste des dossiers."""
    html = cloudflare_bypass_fetch(base_url, timeout_ms=90000, headless=headless)
    if not html:
        return []
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    dirs = []
    # nouveau format LoLROMs
    for li in soup.find_all('li', class_='folder-item'):
        a = li.find('a')
        if a:
            dirs.append(a.get_text(strip=True))
    # fallback ancien format
    if not dirs:
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.endswith('/'):
                text = a.get_text(strip=True)
                if text and text not in {'RSS', 'Donate', 'Main', '../', '/'}:
                    dirs.append(text)
    return sorted(set(dirs))


def lolroms_list_files(directory_url: str, headless: bool = True) -> dict[str, str]:
    """Scrape un repertoire LoLROMs et retourne {nom_fichier: url}."""
    html = cloudflare_bypass_fetch(directory_url, timeout_ms=90000, headless=headless)
    if not html:
        return {}
    from bs4 import BeautifulSoup
    import html as html_module
    from urllib.parse import unquote
    soup = BeautifulSoup(html, 'html.parser')
    files = {}
    subdirs = []
    for li in soup.find_all('li', class_='file-item'):
        a = li.find('a', href=True)
        if a:
            href = html_module.unescape(a['href']).strip()
            text = html_module.unescape(a.get_text(strip=True))
            if href and not href.endswith('/'):
                full = urljoin(directory_url.rstrip('/') + '/', href)
                files[text] = full
    for li in soup.find_all('li', class_='folder-item'):
        a = li.find('a', href=True)
        if a:
            href = html_module.unescape(a['href']).strip()
            text = html_module.unescape(a.get_text(strip=True))
            if href.endswith('/'):
                subdirs.append(text)
    # fallback ancien parsing
    if not files and not subdirs:
        for a in soup.find_all('a', href=True):
            href = html_module.unescape(a['href']).strip()
            text = html_module.unescape(a.get_text(strip=True))
            if not href or text in {'RSS', 'Donate', 'Main', '../'}:
                continue
            if href.endswith('/'):
                subdirs.append(text)
            else:
                full = urljoin(directory_url.rstrip('/') + '/', href)
                files[text] = full
    return files, subdirs
