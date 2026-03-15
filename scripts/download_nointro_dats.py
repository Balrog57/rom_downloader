import os
import requests
import re
import zipfile
import io
import time
from bs4 import BeautifulSoup

# Configuration
DATOMATIC_BASE_URL = "https://datomatic.no-intro.org/"
DATOMATIC_DOWNLOAD_URL = f"{DATOMATIC_BASE_URL}index.php?page=download&op=dat"
OUTPUT_DIR = os.path.join("dat.exemple", "no-intro")

# User Agents to avoid simple bot detection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1"
}

import subprocess

def get_html_with_curl(url):
    """
    Use curl to fetch HTML since requests is often blocked by Datomatic.
    """
    cmd = [
        "curl", "-s", "-L",
        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            return result.stdout
    except Exception as e:
        print(f"Curl error: {e}")
    return None

def get_systems(session):
    """
    Fetch the list of systems and their IDs from the dropdown.
    """
    print(f"Fetching systems list from {DATOMATIC_DOWNLOAD_URL}...")
    html = get_html_with_curl(DATOMATIC_DOWNLOAD_URL)
    if not html:
        print("Error fetching Datomatic page via curl.")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    select_s = soup.find('select', {'name': 's'})
    if not select_s:
        # Check for throttling in the raw html
        if "throttled" in html.lower():
            print("Access is currently throttled. Please wait a few minutes.")
        return []

    systems = []
    for option in select_s.find_all('option'):
        val = option.get('value')
        text = option.text.strip()
        if val and text:
            systems.append({"id": val, "name": text})
    
    return systems

def filter_systems(systems):
    """
    Filter systems based on user criteria:
    - From Acorn to Zeebo
    - Exclude Source Codes, Unofficial, Non-Redump, Non-Game
    """
    filtered = []
    
    # Sort alphabetically by name to correctly identify range
    systems.sort(key=lambda x: x['name'].lower())
    
    # Find index of Acorn
    # The first system starting with Acorn is usually "Acorn - Archimedes"
    # The last system starting with Zeebo is usually "Zeebo - Zeebo"
    
    start_found = False
    
    for s in systems:
        name = s['name'].lower()
        
        # Check if we should start
        if "acorn" in name:
            start_found = True
        
        if not start_found:
            continue
            
        # Exclusions
        keywords = ["source code", "unofficial", "non-redump", "not redumped", "non-game", "not games", "non-intro"]
        if any(keyword in name for keyword in keywords):
            print(f"  Skipping excluded system: {s['name']}")
            continue

        filtered.append(s)
        
        # Check if we should stop
        if "zeebo" in name:
            break
            
    return filtered

def download_nointro_dat(session, system):
    sys_id = system['id']
    sys_name = system['name']
    
    print(f"Processing {sys_name} (ID: {sys_id})...")
    
    try:
        # Step 1: Submit 'Prepare' form
        # We need to simulate the POST request sent when clicking 'Prepare'
        # The form on Standard DAT usually has many parameters. 
        # We'll use defaults similar to what's in the browser.
        
        url = f"{DATOMATIC_DOWNLOAD_URL}&s={sys_id}"
        
        # Prepare data for POST
        # Based on a typical Datomatic form:
        # s: sys_id
        # op: 'dat'
        # prepare: 'Prepare'
        # Many other fields like 'release_1', 'release_2', 'bio', etc.
        
        # We'll first GET the page to handle any session values or CSRF if needed (though Datomatic is usually simple)
        prep_page = session.get(url, timeout=30)
        prep_soup = BeautifulSoup(prep_page.text, 'html.parser')
        
        form_data = {
            "s": sys_id,
            "prepare": "Prepare"
        }
        
        # Add all hidden fields and checkboxes that are checked by default
        for inp in prep_soup.find_all('input'):
            if inp.get('type') == 'hidden' or (inp.get('type') in ['checkbox', 'radio'] and inp.get('checked')):
                form_data[inp.get('name')] = inp.get('value', 'on')
        
        # Send POST to 'Prepare'
        # Note: Datomatic redirects to the manager page after this
        response = session.post(DATOMATIC_DOWNLOAD_URL, data=form_data, timeout=60, allow_redirects=True)
        response.raise_for_status()
        
        # Step 2: Find 'Download!!' link in the manager page
        # The URL usually looks like index.php?page=manager&download=[TICKET_ID]
        
        # Search for the download link in the response text
        # Pattern: index.php?page=manager&s=[ID]&download=[TICKET_ID]
        download_match = re.search(r'index\.php\?page=manager&[^"]*download=\d+', response.text)
        if not download_match:
            # Maybe we are already on the manager page and it says 'Download!!'
            soup_manager = BeautifulSoup(response.text, 'html.parser')
            dl_link = None
            for a in soup_manager.find_all('a'):
                if "download" in a.get('href', '').lower() and "!!" in a.text:
                    dl_link = a.get('href')
                    break
            
            if not dl_link:
                print(f"  [!] Could not find download link for {sys_name}")
                if "throttled" in response.text.lower():
                    print("      Access Throttled. Waiting 60 seconds...")
                    time.sleep(60)
                return False
        else:
            dl_link = download_match.group(0)
            
        if dl_link and not dl_link.startswith('http'):
            dl_link = DATOMATIC_BASE_URL + dl_link
            
        print(f"  Fetching ZIP from {dl_link}...")
        
        # Sometimes there's a small delay before the ticket is ready
        time.sleep(2)
        
        zip_response = session.get(dl_link, timeout=120)
        zip_response.raise_for_status()
        
        # The response should be a ZIP file
        if zip_response.headers.get('Content-Type') != 'application/zip' and b'PK\x03\x04' not in zip_response.content[:4]:
            print(f"  [!] Received non-ZIP content for {sys_name}. Check if site redirected or blocked.")
            return False

        # Step 3: Extract and Save
        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as z:
            dat_files = [f for f in z.namelist() if f.lower().endswith('.dat')]
            if not dat_files:
                print(f"  [!] No DAT file in ZIP for {sys_name}")
                return False
                
            for dat_file in dat_files:
                # Sanitize filename if needed
                z.extract(dat_file, OUTPUT_DIR)
                print(f"  [+] Extracted {dat_file} to {OUTPUT_DIR}")
        
        # Sleep to avoid aggressive throttling
        time.sleep(5)
        return True
        
    except Exception as e:
        print(f"  [!] Error processing {sys_name}: {e}")
        return False

def get_session():
    # We still need a session for the POST/Download flow
    session = requests.Session()
    # Mocking browser headers more extensively
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    return session

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    session = get_session()
    
    all_systems = get_systems(session)
    if not all_systems:
        print("Terminating due to empty systems list.")
        return
        
    targets = filter_systems(all_systems)
    print(f"Ready to download {len(targets)} DATs.")
    
    success_count = 0
    for system in targets:
        if download_nointro_dat(session, system):
            success_count += 1
        else:
            # If we get throttled, we might want to stop or wait longer
            print("  Pausing for 30 seconds to be safe...")
            time.sleep(30)
            
    print(f"\nFinished! Successfully processed {success_count}/{len(targets)} systems.")

if __name__ == "__main__":
    main()
