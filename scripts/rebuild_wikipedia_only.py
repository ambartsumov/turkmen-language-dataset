from pathlib import Path
import json
import sys

ROOT = Path('/home/ubuntu/turkmen_dataset_build')
sys.path.insert(0, str(ROOT / 'scripts'))
import build_turkmen_dataset as builder

report = builder.process_wikipedia()
manifest_path = ROOT / 'processed' / 'manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
for idx, source in enumerate(manifest['sources']):
    if source['name'] == 'tkwiki':
        manifest['sources'][idx] = report
        break
manifest['totals'] = {
    'records_kept': sum(item['records_kept'] for item in manifest['sources']),
    'characters_kept': sum(item['characters_kept'] for item in manifest['sources']),
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
