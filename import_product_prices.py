"""Import sourced catalog prices as audited knowledge edits, never guessed prices.

CSV columns: product_id,price,currency,source_url,recorded_at (ISO 8601).
Run: python import_product_prices.py prices.csv [--check]
"""
import csv
import json
import math
import sys
import uuid
from datetime import datetime
from urllib.parse import urlparse


def import_prices(engine, path, check_only=False):
    valid = []
    seen = set()
    with open(path, encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'product_id', 'price', 'currency', 'source_url', 'recorded_at'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CSV thiếu cột bắt buộc: '+', '.join(sorted(required)))
        for number, row in enumerate(reader, 2):
            pid = row['product_id'].strip()
            engine.product(pid)
            if pid in seen:
                raise ValueError(f'Dòng {number}: mã sản phẩm trùng.')
            seen.add(pid)
            value = float(row['price'])
            currency = row['currency'].strip().upper()
            source = row['source_url'].strip()
            timestamp = datetime.fromisoformat(row['recorded_at'].strip().replace('Z', '+00:00'))
            if not math.isfinite(value) or value <= 0 or currency not in {'VND', 'USD'}:
                raise ValueError(f'Dòng {number}: giá hoặc tiền tệ không hợp lệ.')
            if urlparse(source).scheme not in {'https', 'http'} or not urlparse(source).hostname or timestamp.tzinfo is None:
                raise ValueError(f'Dòng {number}: cần URL nguồn và thời điểm kèm múi giờ.')
            valid.append((pid, value, currency, source, timestamp.isoformat()))
    if not valid:
        raise ValueError('CSV không có dòng giá.')
    from agent_extensions import now
    with engine.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for pid, *_ in valid:
            if db.execute("SELECT 1 FROM edits WHERE product=? AND field IN ('price','currency') AND active=1", (pid,)).fetchone():
                raise ValueError('Có giá/tiền tệ đang chỉnh sửa cho '+pid+'. Hãy xử lý phiên bản đó trước.')
        if not check_only:
            version = db.execute('SELECT COALESCE(MAX(version),0) FROM edits').fetchone()[0]
            for pid, value, currency, source, recorded in valid:
                for field, new_value in (('price', value), ('currency', currency)):
                    version += 1
                    edit_id = str(uuid.uuid4())
                    db.execute('INSERT INTO edits VALUES (?,?,?,?,?,?,1,?,?)', (edit_id, pid, field, json.dumps(new_value), 'Bổ sung giá từ nguồn cung cấp, ghi nhận '+recorded, source, version, now()))
                    db.execute('INSERT INTO edit_events(edit,action,created) VALUES (?,?,?)', (edit_id, 'import_sourced_price', now()))
    return {'products': len(valid), 'check_only': check_only}


if __name__ == '__main__':
    import agent_server as server
    server.load_products()
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python import_product_prices.py prices.csv [--check]')
    print(json.dumps(import_prices(server.EXTENSIONS, sys.argv[1], '--check' in sys.argv)))
