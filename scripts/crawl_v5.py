import requests
from bs4 import BeautifulSoup
import json
import time
from pathlib import Path

OUT_FILE = Path("/home/ubuntu/turkmen_dataset_build/raw/turkmenportal/news.jsonl")
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

def get_links(p):
    url = f"https://turkmenportal.com/tm/news?page={p}"
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            if '/tm/news/' in a['href'] and len(a['href'].split('/')) > 3:
                if a['href'] not in links:
                    links.append(a['href'])
        return links
    except: return []

def get_content(path):
    url = f"https://turkmenportal.com{path}"
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.find('h1').text.strip() if soup.find('h1') else ""
        content = soup.find('div', class_='common-text-style')
        text = content.get_text(separator=' ', strip=True) if content else ""
        return {"url": url, "title": title, "text": text}
    except: return None

def main():
    count = 0
    with open(OUT_FILE, "a", encoding="utf-8") as f:
        for p in range(1, 11):
            print(f"Page {p}")
            links = get_links(p)
            for l in links:
                data = get_content(l)
                if data and data['text']:
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
                    f.flush()
                    count += 1
                time.sleep(0.1)
    print(f"Done: {count} articles")

if __name__ == "__main__":
    main()
