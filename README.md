# Turkmen Language Dataset

A text and dialogue corpus in Turkmen (Latin script) for training and evaluating language models. Turkmen is a low-resource language, so the aim here is to collect what is openly available, clean it the same way, and keep every source traceable.

**336,076 records · ~550 M characters · JSONL + Zstandard, one file per source**

## What's inside

| File | Kind | Records |
| --- | --- | ---: |
| `processed/monolingual/hplt_tuk_cleaned.jsonl.zst` | Web documents (HPLT v2.0), fastText-filtered | 150,282 |
| `processed/monolingual/turkmenspeech_transcripts.jsonl.zst` | ASR transcripts (TurkmenSpeech) | 107,235 |
| `processed/monolingual/tkwiki_articles.jsonl.zst` | Turkmen Wikipedia articles, markup stripped | 8,793 |
| `processed/monolingual/tatoeba_tuk_sentences.jsonl.zst` | Tatoeba sentences | 6,870 |
| `processed/monolingual/turkmenportal_news.jsonl.zst` | Turkmenportal news articles | 320 |
| `processed/dialogues/alpaca_turkmen_instruction_pairs.jsonl.zst` | Instruction pairs (machine-translated Alpaca) | 40,699 |
| `processed/dialogues/kakugo_tuk_conversations.jsonl.zst` | Synthetic / translated conversations | 21,877 |

The HPLT file is stored in parts under `processed/monolingual/parts/`. Join them before reading:

```bash
cat processed/monolingual/parts/hplt_tuk_cleaned.jsonl.zst.part_* > processed/monolingual/hplt_tuk_cleaned.jsonl.zst
```

`processed/manifest.json` records, for every source, the original URL, SHA-256 of the downloaded file, records seen/kept and why records were dropped. `processed/README.md` has the per-source notes.

The dialogue files are machine-translated or synthetic. They are useful for instruction tuning, but they are not natural human conversations.

## Format

- Monolingual files: one JSON object per line with a `"text"` field.
- Dialogue files: a `"messages"` array, `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]`.

```python
import json
import zstandard as zstd

with open("processed/monolingual/tkwiki_articles.jsonl.zst", "rb") as f:
    with zstd.ZstdDecompressor().stream_reader(f) as reader:
        for line in reader:
            print(json.loads(line)["text"][:200])
```

## Processing

- Language check with fastText `lid.176`; web documents are kept only if predicted `__label__tk`.
- Wikipedia: wiki markup, templates, tables and non-article namespaces removed.
- News: HTML stripped, deduplicated, language-checked.

## Rebuilding

`processed/build_turkmen_dataset.py` downloads, cleans and filters the sources. `scripts/` holds the crawler, manifest and validation helpers (`validate_dataset.py`, `update_manifest.py`). The validation report is in `docs/validation_report.json`.

## Repository layout

```
processed/   dataset files, manifest, per-source notes, build script
scripts/     crawling, processing and validation scripts
docs/        validation report, source schema notes
```
