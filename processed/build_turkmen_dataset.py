#!/usr/bin/env python3
"""Build a provenance-preserving, text-only Turkmen training dataset.

This script consumes only the source files listed in docs/source_review.md.
It keeps source-specific outputs separate because their licenses differ.
"""
from __future__ import annotations

import bz2
import csv
import hashlib
import html
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np

# fasttext-wheel 0.9.2 uses np.array(..., copy=False), which NumPy 2 rejects
# for Python lists. This compatibility shim changes only that unsupported call.
_original_array = np.array
def _compat_array(obj: Any, *args: Any, **kwargs: Any) -> Any:
    if kwargs.get('copy') is False:
        kwargs['copy'] = None
    return _original_array(obj, *args, **kwargs)
np.array = _compat_array

import fasttext
import pyarrow.parquet as pq
import zstandard as zstd

ROOT = Path('/home/ubuntu/turkmen_dataset_build')
RAW = ROOT / 'raw'
OUT = ROOT / 'processed'
OUT.mkdir(parents=True, exist_ok=True)
LANGID_MODEL = fasttext.load_model(str(RAW / 'lid.176.ftz'))

# The sources already label their records as Turkmen.  This filter only rejects
# clearly non-Turkmen fragments (mostly unremoved English/Cyrillic boilerplate).
CYRILLIC_RE = re.compile(r'[\u0400-\u04FF]')
URL_RE = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
THINK_RE = re.compile(r'<think>.*?</think>', re.IGNORECASE | re.DOTALL)
COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
REF_RE = re.compile(r'<ref(?:\s[^>]*)?>.*?</ref\s*>|<ref(?:\s[^>]*)?/>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r'<[^>]+>')
MD_LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]+\)')
WIKI_LINK_RE = re.compile(r'\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]')
WIKI_TABLE_RE = re.compile(r'\{\|.*?\|\}', re.DOTALL)
MAGIC_WORD_RE = re.compile(r'__[A-Z_]+__')
MULTISPACE_RE = re.compile(r'[ \t]+')
MULTINEWLINE_RE = re.compile(r'\n{3,}')
TOKEN_RE = re.compile(r"[A-Za-zÄÖÜÝŞŽÇÑäöüňşžçñ]+")
ENGLISH_MARKERS = {
    'the', 'and', 'with', 'that', 'this', 'from', 'into', 'your', 'their',
    'what', 'when', 'where', 'which', 'have', 'will', 'would', 'should',
    'about', 'please', 'answer', 'response', 'instruction', 'write', 'text',
}
TURKMEN_MARKERS = {
    'we', 'we', 'we-de', 'üçin', 'bolup', 'bolan', 'bilen', 'ýaly', 'diýip',
    'hem', 'bir', 'bu', 'şeýle', 'ýok', 'bar', 'hakynda', 'bolýar', 'edýär',
}

SOURCE_INFO = {
    'hplt_tuk_cleaned': {
        'source_url': 'https://data.hplt-project.org/two/cleaned/tuk_Latn/1.jsonl.zst',
        'license': 'CC0 for data packaging; see HPLT terms for source-text caveats',
        'kind': 'monolingual_web_documents',
    },
    'tkwiki': {
        'source_url': 'https://dumps.wikimedia.org/tkwiki/latest/tkwiki-latest-pages-articles.xml.bz2',
        'license': 'CC BY-SA 4.0 and GFDL',
        'kind': 'encyclopedic_articles',
    },
    'tatoeba_tuk': {
        'source_url': 'https://downloads.tatoeba.org/exports/per_language/tuk/tuk_sentences.tsv.bz2',
        'license': 'CC BY 2.0 FR; some records are CC0 (check upstream per-record metadata)',
        'kind': 'sentences',
    },
    'turkmenspeech_transcripts': {
        'source_url': 'https://huggingface.co/datasets/mamed0v/TurkmenSpeech',
        'license': 'CC BY-NC 4.0',
        'kind': 'speech_transcripts',
    },
    'alpaca_turkmen': {
        'source_url': 'https://huggingface.co/datasets/mamed0v/alpaca-turkmen',
        'license': 'CC BY-SA 4.0',
        'kind': 'synthetic_or_translated_instruction_pairs',
    },
    'kakugo_tuk': {
        'source_url': 'https://huggingface.co/datasets/ptrdvn/kakugo-tuk',
        'license': 'Apache-2.0',
        'kind': 'synthetic_or_translated_conversations',
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def clean_text(value: Any) -> str:
    """Normalize a textual field without translating or inventing content."""
    if not isinstance(value, str):
        return ''
    text = html.unescape(value)
    text = THINK_RE.sub(' ', text)
    text = URL_RE.sub(' ', text)
    text = COMMENT_RE.sub(' ', text)
    text = MD_LINK_RE.sub(r'\1', text)
    text = text.replace('\r', '\n').replace('\u00a0', ' ')
    text = re.sub(r'[`*_]{1,3}', '', text)
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', text)
    text = MULTISPACE_RE.sub(' ', text)
    text = MULTINEWLINE_RE.sub('\n\n', text)
    return text.strip(' \n\t-–—|')


def is_fasttext_turkmen(text: str) -> bool:
    """Return True only when fastText's independent classifier predicts Turkmen."""
    candidate = MULTISPACE_RE.sub(' ', text.replace('\n', ' ')).strip()[:6000]
    if len(candidate) < 20:
        return False
    labels, _ = LANGID_MODEL.predict(candidate, k=1)
    return bool(labels) and labels[0] == '__label__tk'


def is_usable_turkmen(text: str) -> bool:
    """Conservative text sanity check, not a replacement for language ID."""
    if len(text) < 12:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 6:
        return False
    if sum(bool(CYRILLIC_RE.match(ch)) for ch in letters) / len(letters) > 0.20:
        return False
    tokens = [x.lower() for x in TOKEN_RE.findall(text)]
    if len(tokens) < 2:
        return False
    english_hits = sum(token in ENGLISH_MARKERS for token in tokens)
    turkmen_hits = sum(token in TURKMEN_MARKERS for token in tokens)
    special_chars = sum(ch in 'äöüňşžçýÄÖÜÝŞŽÇÑñ' for ch in text)
    # A clearly English segment with no Turkmen signals is not retained.
    if english_hits >= 4 and english_hits > turkmen_hits * 2 and special_chars == 0:
        return False
    # For sufficiently long material, require an independent language-ID signal.
    if len(text) >= 160 and not is_fasttext_turkmen(text):
        return False
    return True


def strip_wiki_markup(text: str) -> str:
    text = COMMENT_RE.sub(' ', text)
    text = REF_RE.sub(' ', text)
    text = WIKI_TABLE_RE.sub(' ', text)
    text = MAGIC_WORD_RE.sub(' ', text)
    # Repeatedly remove innermost templates; bounded to avoid pathological input.
    for _ in range(12):
        new_text = re.sub(r'\{\{[^{}]*\}\}', ' ', text, flags=re.DOTALL)
        if new_text == text:
            break
        text = new_text

    def replace_link(match: re.Match[str]) -> str:
        return match.group(2) or match.group(1) or match.group(3) or ''

    text = WIKI_LINK_RE.sub(replace_link, text)
    # Tolerate malformed/nested links and common image-option remnants.
    text = text.replace('[[', ' ').replace(']]', ' ')
    text = re.sub(r'(?i)\bthumb\|(?:right|left|center|none|\d+px)\|?', ' ', text)
    text = re.sub(r'(?i)\b(?:file|image|faýl|surat):[^|\n]+\|?', ' ', text)
    text = re.sub(r'\[https?://[^\s\]]+(?:\s+([^\]]+))?\]', lambda m: m.group(1) or ' ', text)
    text = TAG_RE.sub(' ', text)
    text = re.sub(r"'{2,}", '', text)
    text = re.sub(r'(?m)^\s*[=]{2,}.*?[=]{2,}\s*$', ' ', text)
    text = re.sub(r'(?m)^\s*[*#;:]\s*', '', text)
    return clean_text(text)


class ZstdJsonlWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.raw = path.open('wb')
        self.compressed = zstd.ZstdCompressor(level=10, threads=-1).stream_writer(self.raw)
        self.text = io.TextIOWrapper(self.compressed, encoding='utf-8')
        self.count = 0
        self.characters = 0

    def write(self, obj: dict[str, Any], char_count: int) -> None:
        self.text.write(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n')
        self.count += 1
        self.characters += char_count

    def close(self) -> None:
        self.text.close()


def progress(name: str, seen: int) -> None:
    if seen and seen % 100_000 == 0:
        print(f'[{name}] processed {seen:,}', file=sys.stderr, flush=True)


def process_hplt() -> dict[str, Any]:
    name = 'hplt_tuk_cleaned'
    src = RAW / 'hplt_tuk_cleaned_1.jsonl.zst'
    writer = ZstdJsonlWriter(OUT / 'monolingual' / f'{name}.jsonl.zst')
    seen = 0
    dropped = Counter()
    dctx = zstd.ZstdDecompressor()
    with src.open('rb') as raw, dctx.stream_reader(raw) as reader, io.TextIOWrapper(reader, encoding='utf-8', errors='replace') as inp:
        for line in inp:
            seen += 1
            progress(name, seen)
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                dropped['invalid_json'] += 1
                continue
            langs = item.get('lang') or []
            if langs and 'tuk_Latn' not in langs:
                dropped['wrong_language_label'] += 1
                continue
            text = item.get('text', '')
            pii = item.get('pii', [])
            if isinstance(pii, list):
                for span in reversed(pii):
                    if isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span):
                        start, end = max(0, span[0]), max(0, span[1])
                        text = text[:start] + ' [REDACTED] ' + text[end:]
            text = clean_text(text)
            if not is_usable_turkmen(text):
                dropped['language_or_quality_filter'] += 1
                continue
            # HPLT is web-mined; require fastText agreement even for short documents.
            if not is_fasttext_turkmen(text):
                dropped['fasttext_not_turkmen'] += 1
                continue
            record_id = str(item.get('id') or hashlib.sha1(text.encode('utf-8')).hexdigest())
            writer.write({'id': record_id, 'text': text}, len(text))
    writer.close()
    return report(name, src, writer, seen, dropped)


def process_wikipedia() -> dict[str, Any]:
    name = 'tkwiki'
    src = RAW / 'tkwiki_latest_pages_articles.xml.bz2'
    writer = ZstdJsonlWriter(OUT / 'monolingual' / f'{name}_articles.jsonl.zst')
    seen = 0
    dropped = Counter()
    with bz2.open(src, 'rb') as f:
        for _, elem in ET.iterparse(f, events=('end',)):
            if not elem.tag.endswith('page'):
                continue
            seen += 1
            title = ''
            namespace = ''
            wikitext = ''
            for child in elem:
                if child.tag.endswith('title'):
                    title = child.text or ''
                elif child.tag.endswith('ns'):
                    namespace = child.text or ''
                elif child.tag.endswith('revision'):
                    for rev_child in child:
                        if rev_child.tag.endswith('text'):
                            wikitext = rev_child.text or ''
                            break
            if namespace != '0':
                dropped['non_article_namespace'] += 1
            else:
                text = strip_wiki_markup(wikitext)
                if not is_usable_turkmen(text):
                    dropped['language_or_quality_filter'] += 1
                else:
                    page_id = hashlib.sha1((title + '\n' + text).encode('utf-8')).hexdigest()
                    writer.write({'id': page_id, 'text': text}, len(text))
            elem.clear()
    writer.close()
    return report(name, src, writer, seen, dropped)


def process_tatoeba() -> dict[str, Any]:
    name = 'tatoeba_tuk'
    src = RAW / 'tatoeba_tuk_sentences.tsv.bz2'
    writer = ZstdJsonlWriter(OUT / 'monolingual' / f'{name}_sentences.jsonl.zst')
    seen = 0
    dropped = Counter()
    seen_texts: set[str] = set()
    with bz2.open(src, 'rt', encoding='utf-8', errors='replace') as f:
        for line in f:
            seen += 1
            fields = line.rstrip('\n').split('\t', 2)
            if len(fields) != 3:
                dropped['malformed_row'] += 1
                continue
            record_id, lang, text = fields
            text = clean_text(text)
            if lang not in {'tuk', 'tk'}:
                dropped['wrong_language_label'] += 1
            elif text in seen_texts:
                dropped['duplicate'] += 1
            elif not is_usable_turkmen(text):
                dropped['language_or_quality_filter'] += 1
            else:
                seen_texts.add(text)
                writer.write({'id': record_id, 'text': text}, len(text))
    writer.close()
    return report(name, src, writer, seen, dropped)


def process_speech_transcripts() -> dict[str, Any]:
    name = 'turkmenspeech_transcripts'
    src = RAW / 'turkmenspeech_metadata.csv'
    writer = ZstdJsonlWriter(OUT / 'monolingual' / f'{name}.jsonl.zst')
    seen = 0
    dropped = Counter()
    seen_texts: set[str] = set()
    with src.open('r', encoding='utf-8', errors='replace', newline='') as f:
        for row in csv.DictReader(f):
            seen += 1
            text = clean_text(row.get('text', ''))
            if (row.get('language') or '').lower() not in {'tk', 'tuk'}:
                dropped['wrong_language_label'] += 1
            elif text in seen_texts:
                dropped['duplicate'] += 1
            elif not is_usable_turkmen(text):
                dropped['language_or_quality_filter'] += 1
            else:
                seen_texts.add(text)
                writer.write({'id': row.get('id', ''), 'text': text}, len(text))
            progress(name, seen)
    writer.close()
    return report(name, src, writer, seen, dropped)


def process_alpaca() -> dict[str, Any]:
    name = 'alpaca_turkmen'
    src = RAW / 'alpaca_turkmen.jsonl'
    writer = ZstdJsonlWriter(OUT / 'dialogues' / f'{name}_instruction_pairs.jsonl.zst')
    seen = 0
    dropped = Counter()
    with src.open('r', encoding='utf-8', errors='replace') as f:
        for line in f:
            seen += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                dropped['invalid_json'] += 1
                continue
            instruction = clean_text(row.get('instruction_tk', ''))
            user_input = clean_text(row.get('input_tk', ''))
            response = clean_text(row.get('output_tk', ''))
            prompt = instruction if not user_input else f'{instruction}\n\n{user_input}'
            if not (is_usable_turkmen(prompt) and is_usable_turkmen(response)):
                dropped['language_or_quality_filter'] += 1
                continue
            record_id = hashlib.sha1((prompt + '\n' + response).encode('utf-8')).hexdigest()
            messages = [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': response}]
            writer.write({'id': record_id, 'messages': messages}, len(prompt) + len(response))
            progress(name, seen)
    writer.close()
    return report(name, src, writer, seen, dropped)


def process_kakugo() -> dict[str, Any]:
    name = 'kakugo_tuk'
    src = RAW / 'kakugo_tuk_train.parquet'
    writer = ZstdJsonlWriter(OUT / 'dialogues' / f'{name}_conversations.jsonl.zst')
    seen = 0
    dropped = Counter()
    pf = pq.ParquetFile(src)
    for batch in pf.iter_batches(batch_size=512):
        for row in batch.to_pylist():
            seen += 1
            messages = []
            for message in row.get('messages') or []:
                if not isinstance(message, dict):
                    continue
                role = str(message.get('role') or '').strip().lower()
                content = clean_text(message.get('content', ''))
                if role not in {'user', 'assistant'}:
                    continue
                if not is_usable_turkmen(content):
                    continue
                messages.append({'role': role, 'content': content})
            roles = {m['role'] for m in messages}
            if len(messages) < 2 or not {'user', 'assistant'}.issubset(roles):
                dropped['invalid_or_non_turkmen_conversation'] += 1
                continue
            serial = '\n'.join(m['role'] + ':' + m['content'] for m in messages)
            record_id = hashlib.sha1(serial.encode('utf-8')).hexdigest()
            writer.write({'id': record_id, 'messages': messages}, sum(len(m['content']) for m in messages))
            progress(name, seen)
    writer.close()
    return report(name, src, writer, seen, dropped)


def report(name: str, src: Path, writer: ZstdJsonlWriter, seen: int, dropped: Counter[str]) -> dict[str, Any]:
    return {
        'name': name,
        'source': SOURCE_INFO[name],
        'source_filename': src.name,
        'source_sha256': sha256(src),
        'source_bytes': src.stat().st_size,
        'processed_file': str(writer.path.relative_to(ROOT)),
        'records_seen': seen,
        'records_kept': writer.count,
        'characters_kept': writer.characters,
        'dropped': dict(sorted(dropped.items())),
    }


def main() -> None:
    jobs = [
        process_hplt,
        process_wikipedia,
        process_tatoeba,
        process_speech_transcripts,
        process_alpaca,
        process_kakugo,
    ]
    reports = []
    for job in jobs:
        print(f'Starting {job.__name__}', file=sys.stderr, flush=True)
        reports.append(job())
    totals = {
        'records_kept': sum(item['records_kept'] for item in reports),
        'characters_kept': sum(item['characters_kept'] for item in reports),
    }
    manifest = {
        'dataset_name': 'turkmen_legal_mixed_sources',
        'build_date_utc': '2026-07-27',
        'content_language': 'Turkmen (Latin script)',
        'output_encoding': 'UTF-8',
        'format': 'JSONL compressed with Zstandard; files remain separated by source and license',
        'language_filter': 'Source language labels plus fastText lid.176; HPLT requires fastText prediction __label__tk for every retained document.',
        'totals': totals,
        'sources': reports,
        'important_limitations': [
            'The archive does not claim to contain 1,000–2,000 books or millions of natural human dialogues.',
            'Kakugo and Alpaca records are synthetic or machine-translated instruction data, not naturally occurring conversations.',
            'TurkmenSpeech transcripts are CC BY-NC 4.0 and cannot be used commercially.',
            'HPLT packages data under CC0 but does not own the underlying web text; consult its terms and applicable law before downstream deployment.',
        ],
    }
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(totals, ensure_ascii=False), file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
