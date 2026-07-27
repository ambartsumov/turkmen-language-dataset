import requests
from bs4 import BeautifulSoup
import json

url = "https://turkmenportal.com/tm/news"
try:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    print(f"Status: {r.status_code}")
    soup = BeautifulSoup(r.text, 'html.parser')
    links = [a['href'] for a in soup.find_all('a', href=True) if '/tm/news/' in a['href']]
    print(f"Links found: {len(links)}")
    
    with open("/home/ubuntu/turkmen_dataset_build/raw/turkmenportal/simple.jsonl", "w", encoding="utf-8") as f:
        for l in links[:5]:
            print(f"Fetching {l}")
            ar = requests.get(f"https://turkmenportal.com{l}", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            asoup = BeautifulSoup(ar.text, 'html.parser')
            title = asoup.find('h1').text.strip() if asoup.find('h1') else "No Title"
            f.write(json.dumps({"url": l, "title": title}, ensure_ascii=False) + "\n")
            print(f"  Saved: {title}")
except Exception as e:
    print(f"Error: {e}")
