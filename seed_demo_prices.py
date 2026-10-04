"""Explicitly seed synthetic Shopee prices for a local demonstration.

Only unpriced products without active price/currency edits are affected.
CSV originals remain unchanged; all edits can be disabled in the admin UI.
"""
import argparse
import csv
import hashlib
import json
import uuid
from pathlib import Path


def seed(engine, rows, normalize):
    from agent_extensions import now
    generated = []
    with engine.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        edited = {r[0] for r in db.execute("SELECT product FROM edits WHERE active=1 AND field IN ('price','currency')")}
        version = db.execute('SELECT COALESCE(MAX(version),0) FROM edits').fetchone()[0]
        recorded = now()
        for row in rows:
            pid = row['product_id']
            if row.get('source') != 'shopee' or row.get('price', '').strip() or pid in edited:
                continue
            name = normalize(row.get('product_name', ''))
            low, high = 29000, 299000
            for words, bounds in [
                (('remote', 'dieu khien'), (29000, 99000)),
                (('cap ', 'cable', 'op lung', 'mieng dan'), (19000, 149000)),
                (('tai nghe', 'headphone'), (79000, 499000)),
                (('the nho', 'microsd', 'usb'), (59000, 299000)),
                (('chuot', 'mouse', 'ban phim'), (79000, 599000)),
                (('loa ', 'speaker'), (149000, 999000)),
            ]:
                if any(word in name for word in words):
                    low, high = bounds
                    break
            number = int(hashlib.sha256(pid.encode()).hexdigest()[:8], 16)
            value = low + (number % ((high-low)//10000+1))*10000
            evidence = 'Dữ liệu giả lập cho demo; tạo bằng seed_demo_prices.py; không phải giá bán Shopee.'
            for field, new_value in (('price', value), ('currency', 'VND')):
                version += 1
                edit_id = str(uuid.uuid4())
                db.execute('INSERT INTO edits VALUES (?,?,?,?,?,?,1,?,?)', (edit_id, pid, field, json.dumps(new_value), 'Giá giả lập phục vụ kiểm thử giao diện và lọc ngân sách', evidence, version, recorded))
                db.execute('INSERT INTO edit_events(edit,action,created) VALUES (?,?,?)', (edit_id, 'seed_demo_price', recorded))
            generated.append({'product_id': pid, 'product_name': row['product_name'], 'price': value, 'currency': 'VND', 'price_kind': 'simulated', 'recorded_at': recorded})
    return generated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Xác nhận nhập giá giả lập')
    args = parser.parse_args()
    if not args.apply:
        parser.error('Cần --apply để nhập giá giả lập cho demo.')
    import agent_server as server
    with server.PRODUCTS_CSV.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    generated = seed(server.EXTENSIONS, rows, server.normalize)
    if generated:
        destination = Path('.runtime/shopee_demo_prices.csv')
        destination.parent.mkdir(exist_ok=True)
        with destination.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(generated[0]))
            writer.writeheader()
            writer.writerows(generated)
    print(json.dumps({'imported_demo_prices': len(generated)}))
