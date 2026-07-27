import requests
from bs4 import BeautifulSoup
import json
import time
from pathlib import Path

OUT_FILE = Path("/home/ubuntu/turkmen_dataset_build/raw/turkmenportal/news.jsonl")
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

headers = {"User-Agent": "Mozilla/5.0"}
session = requests.Session()
session.headers.update(headers)

def get_links(p):
    try:
        r = session.get(f"https://turkmenportal.com/tm/news?page={p}", timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        return list(set([a['href'] for a in soup.find_all('a', href=True) if '/tm/news/' in a['href'] and len(a['href'].split('/')) > 3]))
    except: return []

def main():
    count = 0
    f = open(OUT_FILE, "w", encoding="utf-8")
    try:
        for p in range(1, 6):
            print(f"Page {p}")
            links = get_links(p)
            for l in links:
                try:
                    r = session.get(f"https://turkmenportal.com{l}", timeout=10)
                    soup = BeautifulSoup(r.text, 'html.parser')
                    title = soup.find('h1').text.strip() if soup.find('h1') else ""
                    content = soup.find('div', class_='common-text-style')
                    text = content.get_text(separator=' ', strip=True) if content else ""
                    if text:
                        f.write(json.dumps({"url": l, "title": title, "text": text}, ensure_ascii=False) + "\n")
                        f.flush()
                        count += 1
                        print(f"  [{count}] {title[:40]}...")
                except: pass
                time.sleep(0.2)
    finally:
        f.close()
    print(f"Total: {count}")

if __name__ == "__main__":
    main()
