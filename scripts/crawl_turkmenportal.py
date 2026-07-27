import requests
from bs4 import BeautifulSoup
import json
import time
import os
from pathlib import Path
import zstandard as zstd
import io
import re

BASE_URL = "https://turkmenportal.com/tm/news"
ARTICLE_BASE = "https://turkmenportal.com"
OUT_DIR = Path("/home/ubuntu/turkmen_dataset_build/raw/turkmenportal")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Пагинация на сайте работает через GET-параметр page: ?page=N
# На основе анализа, страниц около 2943. 
# Для ускорения в песочнице мы будем собирать данные эффективно.

def get_article_links(page_num):
    url = f"{BASE_URL}?page={page_num}"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        # Ссылки на новости находятся в <a> тегах внутри карточек новостей.
        # Судя по структуре, ссылки имеют формат /tm/news/ID-slug
        links = []
        for a in soup.find_all('a', href=re.compile(r'^/tm/news/\d+')):
            href = a.get('href')
            if href not in links:
                links.append(href)
        return links
    except Exception as e:
        print(f"Error fetching page {page_num}: {e}")
        return []

def parse_article(path):
    url = f"{ARTICLE_BASE}{path}"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Заголовок новости
        title_tag = soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else ""
        
        # Основной текст новости
        # На Turkmenportal текст обычно в div с классом content-text или внутри article
        content_div = soup.find('div', class_='common-text-style') # Из анализа DOM
        if not content_div:
            content_div = soup.find('article')
            
        if content_div:
            # Удаляем скрипты и стили
            for s in content_div(['script', 'style']):
                s.decompose()
            text = content_div.get_text(separator='\n', strip=True)
        else:
            text = ""
            
        return {
            "id": path.split('/')[-1].split('-')[0],
            "url": url,
            "title": title,
            "text": text
        }
    except Exception as e:
        print(f"Error parsing article {url}: {e}")
        return None

def main():
    # Мы не можем скачать все 3000 страниц за один раз в рамках сессии быстро,
    # поэтому соберем первые 50 страниц для демонстрации и оценки объема.
    # В реальной задаче можно запустить в фоне или параллельно.
    
    output_file = OUT_DIR / "turkmenportal_news.jsonl"
    
    count = 0
    with open(output_file, 'wb') as f:
        with open(output_file, "w", encoding="utf-8") as text_writer:
            text_writer = io.TextIOWrapper(writer, encoding='utf-8')
            
            # Собираем ссылки со страниц
            for p in range(1, 21): # Первые 50 страниц
                print(f"Processing page {p}...")
                links = get_article_links(p)
                if not links:
                    break
                
                for link in links:
                    article = parse_article(link)
                    if article and article['text']:
                        text_writer.write(json.dumps(article, ensure_ascii=False) + '\n')
                        count += 1
                
                # Небольшая пауза чтобы не нагружать сервер
                time.sleep(0.5)
            
            text_writer.flush()
    
    print(f"Successfully collected {count} articles from Turkmenportal.")

if __name__ == "__main__":
    main()
