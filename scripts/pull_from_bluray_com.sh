#!/usr/bin/env bash

# Exit immediately if any command fails
set -eo pipefail

echo "Starting Dolby Vision 4K Blu-ray title scraper..."

python3 -u - << 'EOF'
import urllib.request as ur
import re
import time

titles = set()
p = 1
consecutive_errors = 0
last_titles_count = 0
no_growth_pages = 0

print("Connecting to Blu-ray.com...", flush=True)

while True:
    try:
        url = f"https://www.blu-ray.com/movies/search.php?action=search&ultrahd=1&dolbyvision=1&page={p}"
        req = ur.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Cookie': 'country=us'
        })
        with ur.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            slugs = re.findall(r'href="https://www\.blu-ray\.com/movies/([^/"]+-4K-Blu-ray)/\d+/"', html)
            if not slugs:
                if "No index" in html or "robots" in html:
                    print(f"Page {p} returned block message! Retrying in 5 seconds...", flush=True)
                    time.sleep(5)
                    consecutive_errors += 1
                    if consecutive_errors > 5:
                        print("Too many blocks. Stopping.", flush=True)
                        break
                    continue
                else:
                    print(f"No more slugs found on page {p}. Stopping.", flush=True)
                    break

            consecutive_errors = 0
            for s in slugs:
                title = s.replace("-4K-Blu-ray", "").replace("-", " ")
                titles.add(title)
            print(f"Page {p} scraped. Total unique titles: {len(titles)}", flush=True)

            # Check for growth
            if len(titles) == last_titles_count:
                no_growth_pages += 1
            else:
                no_growth_pages = 0
                last_titles_count = len(titles)

            if no_growth_pages >= 3:
                print("Titles count has not increased for 3 pages. Done scraping.", flush=True)
                break

            p += 1
            time.sleep(0.3)
    except Exception as e:
        print(f"Error on page {p}: {e}. Retrying in 5 seconds...", flush=True)
        time.sleep(5)
        consecutive_errors += 1
        if consecutive_errors > 5:
            print("Too many consecutive errors. Stopping.", flush=True)
            break

# Write to file
output_file = "gemini_dv_bluray_com.txt"
with open(output_file, "w") as f:
    f.write("\n".join(sorted(titles)))
print(f"Done! Saved {len(titles)} titles to {output_file}", flush=True)
EOF
