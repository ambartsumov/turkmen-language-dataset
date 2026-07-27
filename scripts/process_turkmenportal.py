import json
import hashlib
from pathlib import Path
import zstandard as zstd
import io
import fasttext
import numpy as np

# Compatibility for fasttext with numpy 2
_original_array = np.array
def _compat_array(obj, *args, **kwargs):
    if kwargs.get('copy') is False: kwargs['copy'] = None
    return _original_array(obj, *args, **kwargs)
np.array = _compat_array

ROOT = Path('/home/ubuntu/turkmen_dataset_build')
RAW_FILE = ROOT / 'raw/turkmenportal/final_news.jsonl'
OUT_DIR = ROOT / 'processed/monolingual'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / 'turkmenportal_news.jsonl.zst'

LANGID_MODEL = fasttext.load_model(str(ROOT / 'raw/lid.176.ftz'))

def is_turkmen(text):
    if len(text) < 50: return False
    labels, _ = LANGID_MODEL.predict(text.replace('\n', ' ')[:1000], k=1)
    return labels[0] == '__label__tk'

def main():
    seen_hashes = set()
    count = 0
    
    cctx = zstd.ZstdCompressor(level=10)
    with open(OUT_FILE, 'wb') as f_out:
        with cctx.stream_writer(f_out) as writer:
            text_writer = io.TextIOWrapper(writer, encoding='utf-8')
            
            with open(RAW_FILE, 'r', encoding='utf-8') as f_in:
                for line in f_in:
                    data = json.loads(line)
                    text = data['text']
                    
                    # Дедупликация по хэшу текста
                    h = hashlib.sha256(text.encode('utf-8')).hexdigest()
                    if h in seen_hashes: continue
                    seen_hashes.add(h)
                    
                    # Проверка языка
                    if is_turkmen(text):
                        record = {
                            "id": f"tp_{h[:12]}",
                            "url": data.get('url'),
                            "title": data.get('title'),
                            "text": text
                        }
                        text_writer.write(json.dumps(record, ensure_ascii=False) + '\n')
                        count += 1
            
            text_writer.flush()
            
    print(f"Processed {count} unique Turkmen articles from Turkmenportal.")

if __name__ == "__main__":
    main()
