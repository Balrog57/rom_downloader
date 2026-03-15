import os
import requests
import zipfile
import io
import re

REDUMP_DOWNLOADS_URL = "http://redump.org/downloads/"
OUTPUT_DIR = os.path.join("dat.exemple", "redump")

def get_redump_dat_links():
    """
    Parses the Redump downloads page to find all individual DAT links.
    """
    import subprocess
    print(f"Fetching Redump downloads from {REDUMP_DOWNLOADS_URL}...")
    try:
        print("  Running curl...")
        cmd = [
            "curl", "-s", "-L",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            REDUMP_DOWNLOADS_URL
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  Curl failed with code {result.returncode}")
            return []
        html = result.stdout
        print("  HTML received via curl.")
    except Exception as e:
        print(f"Error fetching Redump page: {e}")
        return []

    # Regex to find links like /datfile/arch/, /datfile/chihiro/, etc.
    # Pattern: <a href="/datfile/([^/]+)/">([^<]+)</a>
    dat_pattern = re.compile(r'<a href="/datfile/([^/]+)/">([^<]+)</a>')
    matches = dat_pattern.findall(html)
    
    links = []
    for slug, name in matches:
        links.append({
            "name": name.strip(),
            "url": f"http://redump.org/datfile/{slug}/"
        })
    
    return links

def download_and_extract_redump(dat_info):
    name = dat_info['name']
    url = dat_info['url']
    
    print(f"Processing {name}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    try:
        # Step 1: Visit the datfile page to find the actual ZIP link
        # Actually, Redump often redirects or has the link directly.
        # Let's try to find the .zip link in the page.
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        
        # Find ZIP link: /datfile/chihiro/Sega%20-%20Chihiro%20(20231215%20182312).zip
        zip_pattern = re.compile(r'href="(/datfile/[^/]+/[^"]+\.zip)"')
        zip_match = zip_pattern.search(response.text)
        
        if not zip_match:
            print(f"  [!] No ZIP file found for {name}")
            return False
            
        zip_url = "http://redump.org" + zip_match.group(1)
        print(f"  Downloading ZIP from {zip_url}...")
        
        zip_response = requests.get(zip_url, headers=headers, timeout=60)
        zip_response.raise_for_status()
        
        # Step 2: Extract DAT from ZIP
        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as z:
            # Find the .dat file inside the zip
            dat_files = [f for f in z.namelist() if f.lower().endswith('.dat')]
            if not dat_files:
                print(f"  [!] No .dat file found inside the ZIP for {name}")
                return False
                
            for dat_file in dat_files:
                # Extract to output dir
                z.extract(dat_file, OUTPUT_DIR)
                print(f"  [+] Extracted {dat_file} to {OUTPUT_DIR}")
                
        return True
        
    except Exception as e:
        print(f"  [!] Error processing {name}: {e}")
        return False

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    links = get_redump_dat_links()
    print(f"Found {len(links)} systems.")
    
    success_count = 0
    for dat_info in links:
        if download_and_extract_redump(dat_info):
            success_count += 1
            
    print(f"\nFinished! Successfully processed {success_count}/{len(links)} systems.")

if __name__ == "__main__":
    main()
