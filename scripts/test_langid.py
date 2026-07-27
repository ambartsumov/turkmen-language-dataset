from collections import Counter
import io
import json
from pathlib import Path

import numpy as np

# fasttext-wheel 0.9.2 calls np.array(..., copy=False), which NumPy 2 rejects
# for a Python list. Replace only that unsupported request with copy=None.
_original_array = np.array
def _compat_array(obj, *args, **kwargs):
    if kwargs.get('copy') is False:
        kwargs['copy'] = None
    return _original_array(obj, *args, **kwargs)
np.array = _compat_array

import fasttext
import zstandard as zstd

ROOT = Path('/home/ubuntu/turkmen_dataset_build')
model = fasttext.load_model(str(ROOT / 'raw' / 'lid.176.ftz'))

examples = {
    'turkmen': 'Himiýa tebigat ylymlarynyň iň wajyp we giň ugurlarynyň biridir. Maddalar we olaryň aýratynlyklary öwrenilýär.',
    'kazakh_latin': 'NUR-SULTAN. QazAqparat – 2025 jyldan bastap elimiz tolyqqandy latyn álipbıine kóshedi.',
    'english': 'This is a short English sentence used only to test language identification.',
}
for label, text in examples.items():
    labels, probabilities = model.predict(text.replace('\n', ' '), k=3)
    print(label, list(zip(labels, probabilities)))

counts = Counter()
source = ROOT / 'raw' / 'hplt_tuk_cleaned_1.jsonl.zst'
dctx = zstd.ZstdDecompressor()
with source.open('rb') as raw, dctx.stream_reader(raw) as reader, io.TextIOWrapper(reader, encoding='utf-8', errors='replace') as inp:
    for idx, line in enumerate(inp, 1):
        text = json.loads(line).get('text', '').replace('\n', ' ')
        label = model.predict(text[:3000], k=1)[0][0]
        counts[label] += 1
        if idx >= 1000:
            break
print('first_1000_hplt_labels', counts.most_common())
