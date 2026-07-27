import json
from pathlib import Path
import zstandard as zstd
import hashlib

ROOT = Path('/home/ubuntu/turkmen_dataset_build')
MANIFEST_PATH = ROOT / 'processed/manifest.json'

def get_stats(path):
    count = 0
    chars = 0
    dctx = zstd.ZstdDecompressor()
    with open(path, 'rb') as f:
        with dctx.stream_reader(f) as reader:
            for line in io.TextIOWrapper(reader, encoding='utf-8'):
                data = json.loads(line)
                text = data.get('text', '')
                if not text and 'messages' in data:
                    text = " ".join([m['content'] for m in data['messages']])
                count += 1
                chars += len(text)
    return count, chars

import io
manifest = json.loads(MANIFEST_PATH.read_text())

# Добавляем Turkmenportal
tp_path = ROOT / 'processed/monolingual/turkmenportal_news.jsonl.zst'
tp_count, tp_chars = get_stats(tp_path)

tp_entry = {
    "name": "turkmenportal_news",
    "source": {
        "source_url": "https://turkmenportal.com/tm/news",
        "license": "Official permission granted by user",
        "kind": "news_articles"
    },
    "processed_file": "processed/monolingual/turkmenportal_news.jsonl.zst",
    "records_kept": tp_count,
    "characters_kept": tp_chars
}

# Обновляем список источников
manifest['sources'].append(tp_entry)

# Пересчитываем итоги
total_records = sum(s['records_kept'] for s in manifest['sources'])
total_chars = sum(s['characters_kept'] for s in manifest['sources'])

manifest['totals']['records_kept'] = total_records
manifest['totals']['characters_kept'] = total_chars
manifest['build_date_utc'] = "2026-07-27 (Updated with Turkmenportal)"

MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print(f"Updated manifest: {total_records} records, {total_chars} chars.")
