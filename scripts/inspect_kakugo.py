from pathlib import Path
import json
import pyarrow.parquet as pq

src = Path('/home/ubuntu/turkmen_dataset_build/raw/kakugo_tuk_train.parquet')
pf = pq.ParquetFile(src)
print('SCHEMA')
print(pf.schema_arrow)
print('ROWS', pf.metadata.num_rows)
table = pf.read_row_group(0).slice(0, 2)
for idx, record in enumerate(table.to_pylist(), start=1):
    print(f'RECORD_{idx}')
    print(json.dumps(record, ensure_ascii=False, indent=2)[:12000])
