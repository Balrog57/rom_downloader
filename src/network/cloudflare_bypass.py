import os
import time
from urllib.parse import urljoin

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


def _launch_browser(headless=True):
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=headless,
        args=_get_browser_args(),
    )
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
