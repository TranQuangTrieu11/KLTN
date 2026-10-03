"""Import exact-ASIN product images from the original public metadata Parquet.

Only requested columns/row groups are fetched via HTTP ranges; CSV stays intact.
Requires pyarrow. Run: python import_amazon_images.py ASIN [ASIN ...]
"""
import io
import json
import sys
import time
import csv
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor


class RangeFile(io.RawIOBase):
    def __init__(self, url, size):
        super().__init__()
        self.url, self.size, self.pos = url, size, 0
        self.cache = {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos+offset if whence == 1 else self.size+offset
        return self.pos

    def read(self, size=-1):
        size = min(self.size-self.pos, size if size >= 0 else self.size-self.pos)
        if size <= 0:
            return b''
        key = self.pos, size
        self.prime(*key)
        data = self.cache[key]
        self.pos += len(data)
        return data

    def prime(self, offset, size):
        key = offset, size
        if key not in self.cache:
            req = Request(self.url, headers={'Range': f'bytes={offset}-{offset+size-1}'})
            with urlopen(req, timeout=25) as response:
                if response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    raise RuntimeError('Source did not honor the byte range; refusing a full download')
                data = response.read(size+1)
                if len(data) != size:
                    raise RuntimeError('Incorrect source byte range length')
                self.cache[key] = data


def main(asins):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    import agent_server as server
    if '--all' in asins:
        with server.PRODUCTS_CSV.open(encoding='utf-8-sig', newline='') as handle:
            asins = [row['product_id'] for row in csv.DictReader(handle) if row.get('source') == 'amazon']
    wanted = {asin.removeprefix('amazon_') for asin in asins if len(asin.removeprefix('amazon_')) == 10 and asin.removeprefix('amazon_').isalnum()}
    requested = len(wanted)
    with server.EXTENSIONS.connect() as db:
        existing = db.execute("SELECT product FROM product_enrichment WHERE product LIKE 'amazon_%' AND json_extract(data,'$.image_url') IS NOT NULL").fetchall()
    wanted.difference_update(pid.removeprefix('amazon_') for pid, in existing)
    skipped = requested-len(wanted)
    if not wanted:
        print(json.dumps({'requested_count': requested, 'already_available': skipped, 'imported_count': 0, 'not_found_count': 0}), flush=True)
        return
    if not wanted:
        raise ValueError('Supply at least one valid ASIN')
    root = 'https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/'
    with urlopen('https://huggingface.co/api/datasets/McAuley-Lab/Amazon-Reviews-2023/tree/main/raw_meta_Electronics', timeout=20) as response:
        files = json.load(response)
    found = []
    for info in files:
        if not info['path'].endswith('.parquet'):
            continue
        print('Scanning ASIN column:', info['path'], flush=True)
        with RangeFile(root+info['path'], info['size']) as handle:
            parquet = pq.ParquetFile(handle)
            def prefetch(groups, prefixes):
                ranges = []
                for group in groups:
                    meta = parquet.metadata.row_group(group)
                    for index in range(meta.num_columns):
                        col = meta.column(index)
                        if any(col.path_in_schema == prefix or col.path_in_schema.startswith(prefix+'.') for prefix in prefixes):
                            start = min(col.data_page_offset, col.dictionary_page_offset) if col.dictionary_page_offset is not None else col.data_page_offset
                            ranges.append((start, col.total_compressed_size))
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(lambda span: handle.prime(*span), ranges))
            prefetch(range(parquet.num_row_groups), ['parent_asin'])
            matched = []
            for group in range(parquet.num_row_groups):
                ids = parquet.read_row_group(group, columns=['parent_asin'])['parent_asin']
                mask = pc.is_in(ids, value_set=pa.array(sorted(wanted)))
                if not pc.any(mask).as_py():
                    continue
                matched.append((group, mask))
            prefetch([group for group, _ in matched], ['images.hi_res', 'images.large'])
            for group, mask in matched:
                rows = parquet.read_row_group(group, columns=['parent_asin', 'images.hi_res', 'images.large']).filter(mask).to_pylist()
                with server.EXTENSIONS.connect() as db:
                    for row in rows:
                        asin = row['parent_asin']
                        images = row.get('images') or []
                        if isinstance(images, dict):
                            image = next((value for key in ('hi_res', 'large', 'thumb') for value in (images.get(key) if isinstance(images.get(key), list) else [images.get(key)]) if isinstance(value, str) and value.startswith('https://')), None)
                        else:
                            image = next((img.get('hi_res') or img.get('large') or img.get('thumb') for img in images if isinstance(img, dict) and (img.get('hi_res') or img.get('large') or img.get('thumb'))), None)
                        if not isinstance(image, str) or not image.startswith('https://'):
                            continue
                        pid = 'amazon_'+asin
                        old = db.execute('SELECT data FROM product_enrichment WHERE product=?', (pid,)).fetchone()
                        data = json.loads(old[0]) if old else {}
                        data.update(image_url=image, source_url=root+info['path'], image_kind='product_photo')
                        data.pop('unavailable', None)
                        db.execute('INSERT OR REPLACE INTO product_enrichment VALUES (?,?,?)', (pid, json.dumps(data), time.time()))
                        wanted.discard(asin)
                        found.append(pid)
                        if requested <= 10 or len(found) % 5000 == 0:
                            print('Imported images:', len(found), pid, flush=True)
                if not wanted:
                    break
        if not wanted:
            break
    print(json.dumps({'requested_count': requested, 'already_available': skipped, 'imported_count': len(found), 'not_found_count': len(wanted), 'not_found_sample': sorted(wanted)[:10]}), flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
