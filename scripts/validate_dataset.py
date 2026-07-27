#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import zstandard as zstd

ROOT = Path('/home/ubuntu/turkmen_dataset_build')
PROCESSED = ROOT / 'processed'
manifest = json.loads((PROCESSED / 'manifest.json').read_text(encoding='utf-8'))


def read_records(path: Path):
    dctx = zstd.ZstdDecompressor()
    with path.open('rb') as raw, dctx.stream_reader(raw) as reader:
        import io
        with io.TextIOWrapper(reader, encoding='utf-8') as text:
            for line_no, line in enumerate(text, 1):
                try:
                    yield line_no, json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f'{path}: invalid JSON at line {line_no}: {exc}') from exc


errors = []
summary = []
for source in manifest['sources']:
    path = ROOT / source['processed_file']
    count = 0
    samples = []
    for line_no, record in read_records(path):
        count += 1
        if 'id' not in record:
            errors.append(f'{path}: missing id at line {line_no}')
        if 'text' in record:
            content = record['text']
        elif 'messages' in record:
            content = ' '.join(str(m.get('content', '')) for m in record['messages'])
            roles = {m.get('role') for m in record['messages']}
            if not {'user', 'assistant'}.issubset(roles):
                errors.append(f'{path}: malformed dialogue at line {line_no}')
        else:
            errors.append(f'{path}: no text or messages at line {line_no}')
            content = ''
        if not content.strip():
            errors.append(f'{path}: empty content at line {line_no}')
        if len(samples) < 2:
            samples.append(content[:320].replace('\n', ' '))
    expected = source['records_kept']
    if count != expected:
        errors.append(f'{path}: expected {expected} lines, got {count}')
    summary.append({'file': path.name, 'records': count, 'samples': samples})

report = {'ok': not errors, 'errors': errors, 'summary': summary}
(ROOT / 'docs' / 'validation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
