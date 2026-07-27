import requests
from bs4 import BeautifulSoup
import json
import time
from pathlib import Path

OUT_FILE = Path("/home/ubuntu/turkmen_dataset_build/raw/turkmenportal/news.jsonl")
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(headers)

def get_links(p):
    url = f"https://turkmenportal.com/tm/news?page={p}"
    try:
        r = session.get(url, timeout=15)
        print(f"Page {p} status: {r.status_code}")
        soup = BeautifulSoup(r.text, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            if '/tm/news/' in a['href'] and len(a['href'].split('/')) > 3:
                if a['href'] not in links:
                    links.append(a['href'])
        print(f"Found {len(links)} links on page {p}")
        return links
    except Exception as e:
        print(f"Error links p{p}: {e}")
        return []

def get_content(path):
    url = f"https://turkmenportal.com{path}"
    try:
        r = session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.find('h1').text.strip() if soup.find('h1') else ""
        content = soup.find('div', class_='common-text-style')
        text = content.get_text(separator=' ', strip=True) if content else ""
        return {"url": url, "title": title, "text": text}
    except: return None

def main():
    count = 0
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for p in range(1, 3):
            links = get_links(p)
            for l in links:
                data = get_content(l)
                if data and data['text']:
                    print(f"Saving: {data[\"title\"][:30]}..."); f.write(json.dumps(data, ensure_ascii=False) + "\n")
                    f.flush()
                    count += 1
                time.sleep(0.5)
    print(f"Done: {count} articles")

if __name__ == "__main__":
    main()
