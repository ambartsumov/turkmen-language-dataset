import requests
from bs4 import BeautifulSoup
import json
import re
import time

OUT_FILE = "/home/ubuntu/turkmen_dataset_build/raw/turkmenportal/news_nextjs.jsonl"

def get_content(path):
    url = f"https://turkmenportal.com{path}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        # Ищем __NEXT_DATA__ или аналогичные скрипты с JSON
        soup = BeautifulSoup(r.text, 'html.parser')
        script = soup.find('script', id='__NEXT_DATA__')
        if script:
            data = json.loads(script.string)
            # Структура может меняться, обычно контент в props.pageProps.post или аналогично
            # Но проще извлечь весь текст из HTML, если он там есть
            # Если JS не отработал, текст может быть в скрытых блоках
            content = soup.find('div', class_='common-text-style')
            if content:
                return {"url": url, "text": content.get_text(separator=' ', strip=True)}
        
        # Если BeautifulSoup не нашел, попробуем грубый regex для текста
        # В Next.js контент часто в JSON, который мы можем найти
        text_match = re.search(r'"content":"(.*?)"', r.text)
        if text_match:
            text = text_match.group(1).encode().decode('unicode_escape')
            text = re.sub('<[^>]*>', '', text) # Удаляем HTML теги
            return {"url": url, "text": text}
            
        # План Б: просто берем все параграфы
        paragraphs = soup.find_all('p')
        if paragraphs:
            text = " ".join([p.get_text() for p in paragraphs])
            if len(text) > 100:
                return {"url": url, "text": text}
                
    except Exception as e:
        print(f"Error {path}: {e}")
    return None

def main():
    r = requests.get("https://turkmenportal.com/tm/news", headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, 'html.parser')
    links = list(set([a['href'] for a in soup.find_all('a', href=True) if '/tm/news/' in a['href'] and len(a['href'].split('/')) > 3]))
    
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for l in links[:20]:
            print(f"Processing {l}")
            data = get_content(l)
            if data:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
                print(f"  Success: {len(data['text'])} chars")
            time.sleep(0.5)

if __name__ == "__main__":
    main()
