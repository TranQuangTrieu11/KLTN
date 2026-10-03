"""Fetch missing Tiki images/reviews by exact retailer ID; cache evidence locally."""
import json
import time
import threading
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen


class ProductEnrichment:
    def __init__(self, engine):
        self.engine = engine
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.pending = set()
        self.lock = threading.Lock()
        with engine.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS product_enrichment(product TEXT PRIMARY KEY, data TEXT, fetched REAL)')

    def cached(self, product_id):
        with self.engine.connect() as db:
            row = db.execute('SELECT data,fetched FROM product_enrichment WHERE product=?', (product_id,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else ({}, 0)

    def apply(self, row):
        result = dict(row)
        data, fetched = self.cached(row['product_id'])
        if data.get('image_url') and not result.get('image_url'):
            result['image_url'] = data['image_url']
            result['image_source'] = data.get('source_url')
        if data.get('reviews'):
            result['external_reviews'] = data['reviews']
        if fetched:
            result['enriched_at'] = fetched
        return result

    def queue(self, product_id):
        if not product_id.startswith(('tiki_', 'amazon_')):
            return
        _, fetched = self.cached(product_id)
        with self.lock:
            if time.time()-fetched < 86400 or product_id in self.pending:
                return
            self.pending.add(product_id)
        self.pool.submit(self.fetch, product_id)

    def pending_for(self, product_id):
        with self.lock:
            return product_id in self.pending

    def fetch(self, product_id):
        data = {}
        retailer_id = product_id.removeprefix('tiki_')
        try:
            if product_id.startswith('amazon_'):
                asin = product_id.removeprefix('amazon_')
                if not (len(asin) == 10 and asin.isalnum()):
                    return
                source = 'https://www.amazon.com/dp/'+asin
                class Images(HTMLParser):
                    image = None
                    def handle_starttag(self, tag, attrs):
                        attrs = dict(attrs)
                        if tag == 'img' and attrs.get('id') in {'landingImage', 'imgBlkFront'}:
                            self.image = attrs.get('data-old-hires') or attrs.get('src')
                request = Request(source, headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(request, timeout=6) as response:
                    page = response.read(3_000_000).decode('utf-8', 'replace')
                    if asin not in response.url:
                        raise ValueError('Product redirect mismatch')
                parser = Images()
                parser.feed(page)
                if parser.image and parser.image.startswith('https://'):
                    data.update(image_url=parser.image, source_url=source)
                else:
                    data['unavailable'] = True
                return
            if not retailer_id.isdigit():
                return
            source = 'https://tiki.vn/api/v2/products/'+retailer_id
            def read(url):
                request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
                with urlopen(request, timeout=6) as response:
                    return json.loads(response.read(3_000_000))
            product = read(source)
            if str(product.get('id')) != retailer_id:
                raise ValueError('Retailer product ID mismatch')
            image = product.get('thumbnail_url')
            if isinstance(image, str) and image.startswith('https://'):
                data.update(image_url=image, source_url=source)
            try:
                reviews = read('https://tiki.vn/api/v2/reviews?product_id='+retailer_id+'&limit=5&page=1')
                data['reviews'] = [{'review_id': 'tiki_live_'+str(r['id']), 'rating': r.get('rating'), 'title': r.get('title'), 'text': str(r.get('content') or '')[:1200], 'source': 'tiki', 'source_url': 'https://tiki.vn/api/v2/reviews?product_id='+retailer_id} for r in reviews.get('data', []) if r.get('id') and r.get('content')]
            except Exception:
                data['reviews_unavailable'] = True
        except Exception:
            data['unavailable'] = True
        finally:
            with self.engine.connect() as db:
                previous = db.execute('SELECT data FROM product_enrichment WHERE product=?', (product_id,)).fetchone()
                if previous:
                    current = json.loads(previous[0])
                    current.update(data)
                    data = current
                db.execute('INSERT OR REPLACE INTO product_enrichment VALUES (?,?,?)', (product_id, json.dumps(data, ensure_ascii=False), time.time()))
            with self.lock:
                self.pending.discard(product_id)
