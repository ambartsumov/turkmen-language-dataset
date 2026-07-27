import requests
from bs4 import BeautifulSoup
import json
import time
from pathlib import Path

OUT_FILE = Path("/home/ubuntu/turkmen_dataset_build/raw/turkmenportal/final_news.jsonl")
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

headers = {"User-Agent": "Mozilla/5.0"}
session = requests.Session()
session.headers.update(headers)

def get_links(p):
    try:
        r = session.get(f"https://turkmenportal.com/tm/news?page={p}", timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        # Собираем только ссылки на конкретные новости, исключая категории
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/tm/news/' in href and '/category/' not in href and len(href.split('/')) > 3:
                if href not in links:
                    links.append(href)
        return links
    except: return []

def get_content(path):
    url = f"https://turkmenportal.com{path}"
    try:
        r = session.get(url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Находим основной текст. В Next.js он часто в этом классе
        content = soup.find('div', class_='common-text-style')
        if not content:
            # План Б: ищем любой блок с большим количеством текста
            blocks = soup.find_all('div')
            content = max(blocks, key=lambda b: len(b.get_text()), default=None)
            
        if content:
            # Очистка текста
            for s in content(['script', 'style', 'nav', 'header', 'footer']):
                s.decompose()
            text = content.get_text(separator=' ', strip=True)
            # Удаляем лишние пробелы
            text = " ".join(text.split())
            if len(text) > 200: # Минимальный порог для статьи
                title = soup.find('h1').text.strip() if soup.find('h1') else ""
                return {"url": url, "title": title, "text": text}
    except: pass
    return None

def main():
    count = 0
    seen_urls = set()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for p in range(1, 21): # Собираем 20 страниц
            print(f"Page {p}")
            links = get_links(p)
            for l in links:
                if l in seen_urls: continue
                seen_urls.add(l)
                
                data = get_content(l)
                if data:
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
                    f.flush()
                    count += 1
                    if count % 10 == 0:
                        print(f"  Collected {count} articles...")
                time.sleep(0.1)
    print(f"Done: {count} articles")

if __name__ == "__main__":
    main()
