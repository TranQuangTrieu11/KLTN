import csv
import json
import math
import os
import re
import socket
import threading
import unicodedata
import sys
import uuid
import hmac
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from agent_extensions import AgentExtensions
from customer_accounts import Accounts
from product_enrichment import ProductEnrichment


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "research" / "data"
PRODUCTS_CSV = DATA_DIR / "products.csv"
REVIEWS_CSV = DATA_DIR / "reviews.csv"
HISTORY_JSON = ROOT / "chat_history.json"
LEARNING_RULES_JSON = ROOT / "agent_learning_rules.json"


STATE = {
    "products": [],
    "loaded": False,
    "load_error": None,
    "search_counts": {},
    "learning_rules": {"intents": []},
    "reviews_ready": False,
    "review_error": None,
}


def normalize(text):
    text = (text or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text):
    words = re.findall(r"[a-z0-9]+", normalize(text))
    stop = {
        "toi", "can", "tim", "goi", "y", "san", "pham", "cho", "voi",
        "mot", "vai", "cai", "tren", "duoi", "gia", "co", "la", "va",
        "the", "nao", "nao", "review", "danh", "gia", "tot", "re",
        "mua", "hang", "shop", "san", "ban", "hang",
        "tuong", "tu", "nhat", "nhung", "giup", "minh", "muon", "hay", "khong", "top", "loai", "duoc", "nhu", "hon", "con", "usd", "vnd", "ngan", "trieu", "toi", "da",
        "vua", "gui", "cac", "trong", "cua", "nen", "chon", "nhat", "su", "dung", "de",
    }
    return [word for word in words if len(word) > 1 and word not in stop and not word.isdigit()]


def expand_query_tokens(message):
    norm = normalize(message)
    result = tokens(message)
    expansions = {
        "the nho": ["memory", "card", "microsd", "micro", "sd", "storage", "flash"],
        "micro sd": ["microsd", "memory", "card", "storage"],
        "microsd": ["memory", "card", "storage"],
        "tai nghe": ["headphone", "headphones", "earbuds", "bluetooth", "wireless"],
        "ban hoc": ["desk", "table", "study", "computer"],
        "setup ban": ["desk", "table", "study", "computer", "accessory"],
        "may anh": ["camera", "photo", "photography"],
        "dien thoai": ["phone", "smartphone", "mobile"],
        "laptop": ["notebook", "computer", "pc"],
        "cong nghe": ["technology", "electronics", "tech", "phu", "kien"],
        "do gia dung": ["home", "kitchen", "household", "gia", "dung"],
        "lam dep": ["beauty", "skin", "makeup", "my", "pham"],
        "thoi trang": ["fashion", "ao", "quan", "giay", "tui"],
        "chuot": ["mouse"],
        "ban phim": ["keyboard"],
        "khong day": ["wireless"],
    }
    for phrase, extra_tokens in expansions.items():
        if phrase in norm:
            result.extend(extra_tokens)
    return list(dict.fromkeys(result))


def load_learning_rules():
    if not LEARNING_RULES_JSON.exists():
        return
    try:
        STATE["learning_rules"] = json.loads(LEARNING_RULES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        STATE["learning_rules"] = {"intents": []}


def detect_intents(message):
    norm = normalize(message)
    detected = []
    for intent in STATE.get("learning_rules", {}).get("intents", []):
        triggers = [normalize(term) for term in intent.get("triggers", [])]
        hits = sum(1 for term in triggers if term and term in norm)
        if hits:
            detected.append((intent, hits))
    detected.sort(key=lambda item: item[1], reverse=True)
    return [dict(intent, _require_wireless=any(term in norm for term in ('bluetooth', 'wireless', 'khong day'))) for intent, _hits in detected]


def contains_any_phrase(search_text, phrases):
    return any(normalize(phrase) in search_text for phrase in phrases if phrase)


def intent_adjustment(row, intents):
    if not intents:
        return 0
    search_text = row.get("_search", "")
    total = 0
    for intent in intents:
        name = intent.get("name")
        must_any = intent.get("must_any", [])
        if must_any and not contains_any_phrase(search_text, must_any):
            return None
        if name == "bluetooth_headphones":
            if contains_any_phrase(search_text, ["tui", "cap", "balo", "backpack", "non", "mu ", "ao ", "quan "]):
                return None
            if intent.get('_require_wireless') and not contains_any_phrase(search_text, ["bluetooth", "wireless", "khong day", "true wireless"]):
                return None
        if name == "study_desk_setup":
            if contains_any_phrase(search_text, ["balo", "backpack", "tui", "cap ", "sandal", "dep ", "giay", "manocanh", "dau manocanh", "kinh "]):
                return None
            desk_context = ["desk", "table", "ban hoc", "ban lam viec", "laptop stand", "monitor stand", "keyboard", "mouse", "den hoc", "lamp", "usb fan", "ke laptop"]
            if not contains_any_phrase(search_text, desk_context):
                return None
        if name == "smart_home":
            if contains_any_phrase(search_text, ["giay", "sandal", "tui", "vi ", "balo", "my pham", "son ", "ao ", "quan "]):
                return None
            home_context = ["home", "kitchen", "gia dung", "nha thong minh", "lau nha", "robot", "vacuum", "wifi", "alexa", "plug", "camera", "appliance", "cleaner"]
            if not contains_any_phrase(search_text, home_context):
                return None
        boost_hits = sum(1 for term in intent.get("boost_terms", []) if normalize(term) in search_text)
        exclude_hits = sum(1 for term in intent.get("exclude_terms", []) if normalize(term) in search_text)
        total += 45 + boost_hits * 9 - exclude_hits * 35
        if exclude_hits and not boost_hits:
            total -= 30
    return total


def parse_price_limit(text):
    norm = normalize(text)
    matches = re.findall(r"(?:duoi|nho hon|under|max|toi da)\s*([0-9]+(?:[.,][0-9]+)?)\s*(trieu|ngan|k|usd|vnd)?", norm)
    if not matches:
        return None, None
    value, unit = matches[-1]
    amount = float(value.replace(",", "."))
    if unit in {"trieu"}:
        amount *= 1_000_000
        currency = "VND"
    elif unit in {"ngan", "k"}:
        amount *= 1_000
        currency = "VND"
    elif unit in {"usd", "vnd"}:
        currency = unit.upper()
    else:
        currency = None
    return amount, currency


def parse_price_floor(text):
    norm = normalize(text)
    matches = re.findall(r"(?:tren|lon hon|tu|from|min|it nhat)\s*([0-9]+(?:[.,][0-9]+)?)\s*(trieu|ngan|k|usd|vnd)?", norm)
    if not matches:
        return None, None
    value, unit = matches[-1]
    amount = float(value.replace(",", "."))
    if unit in {"trieu"}:
        amount *= 1_000_000
        currency = "VND"
    elif unit in {"ngan", "k"}:
        amount *= 1_000
        currency = "VND"
    elif unit in {"usd", "vnd"}:
        currency = unit.upper()
    else:
        currency = None
    return amount, currency


def detect_sources(text):
    norm = normalize(text)
    norm = norm.replace('shoppe', 'shopee')
    sources = []
    for source in ("amazon", "shopee", "tiki"):
        if source in norm:
            sources.append(source)
    return sources


def load_products():
    try:
      load_learning_rules()
      with PRODUCTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
          reader = csv.DictReader(handle)
          products = []
          for row in reader:
              search_text = " ".join([
                  row.get("product_name", ""),
                  row.get("category", ""),
                  row.get("subcategory", ""),
                  row.get("brand", ""),
                  row.get("description", ""),
                  row.get("source", ""),
              ])
              row["_search"] = normalize(search_text)
              row['_name'] = normalize(row.get('product_name', ''))
              row["_tokens"] = set(tokens(search_text))
              products.append(row)
          STATE["products"] = products
          STATE["loaded"] = True
    except Exception as exc:
        STATE["load_error"] = str(exc)


def score_product(row, query_tokens, sources, price_limit, price_currency, price_floor=None, floor_currency=None, intents=None):
    intent_score = intent_adjustment(row, intents or [])
    if intent_score is None:
        return 0
    product_tokens = row.get("_tokens") or set()
    overlap = len(set(query_tokens) & product_tokens)
    if query_tokens and overlap == 0:
        joined = " ".join(query_tokens)
        if joined not in row.get("_search", ""):
            return 0
    if len(query_tokens) >= 4 and overlap < 2:
        return 0

    score = overlap * 18 + intent_score
    source = (row.get("source") or "").lower()
    if sources and source in sources:
        score += 35
    elif sources:
        score -= 30

    try:
        rating = float(row.get("average_rating") or 0)
    except ValueError:
        rating = 0
    try:
        review_count = float(row.get("review_count") or 0)
    except ValueError:
        review_count = 0
    try:
        sold_count = float(row.get("sold_count") or 0)
    except ValueError:
        sold_count = 0

    score += rating * 4
    score += min(math.log10(review_count + 1) * 5, 30)
    score += min(math.log10(sold_count + 1) * 3, 18)

    if price_limit is not None:
        try:
            price = float(row.get("price") or 0)
        except ValueError:
            price = 0
        currency = (row.get("currency") or "").upper()
        if price_currency and currency and currency != price_currency:
            score -= 60
        if price > 0 and price <= price_limit and (not price_currency or currency == price_currency):
            score += 22
        elif price > 0 and price > price_limit and (not price_currency or currency == price_currency):
            score -= 45

    if price_floor is not None:
        try:
            price = float(row.get("price") or 0)
        except ValueError:
            price = 0
        currency = (row.get("currency") or "").upper()
        if floor_currency and currency and currency != floor_currency:
            score -= 35
        if price > 0 and price >= price_floor and (not floor_currency or currency == floor_currency):
            score += 18
        elif price > 0 and price < price_floor and (not floor_currency or currency == floor_currency):
            score -= 24

    return score


def search_products(query, limit=5):
    query_tokens = expand_query_tokens(query)
    sources = detect_sources(query)
    price_limit, price_currency = parse_price_limit(query)
    price_floor, floor_currency = parse_price_floor(query)
    intents = detect_intents(query)
    scored = []
    edits = EXTENSIONS.edits()
    edited_ids = {e['product_id'] for e in edits if e['active']}
    capacity = re.search(r'\b(\d+)\s*(gb|tb)\b', normalize(query))
    norm = normalize(query)
    from conversation_context import BRANDS, excluded_terms
    excluded_brands = excluded_terms(norm, BRANDS)
    excluded_sources = excluded_terms(norm.replace('shoppe', 'shopee'), ('amazon', 'shopee', 'tiki'))
    sources = [s for s in sources if s not in excluded_sources]
    brand = next((b for b in BRANDS if b not in excluded_brands and re.search(r'\b'+b+r'\b', norm)), None)
    families = [
        (('tai nghe', 'headphone', 'earbuds', 'earphone', 'headset'), ('tai nghe', 'headphone', 'earbud', 'headset', 'earphone'), ('tui dung', 'bao da', 'earpad', 'ear pad', 'replacement cushion', 'day chuyen', 'day jack', 'adapter', 'headphone cable')),
        (('the nho', 'microsd', 'micro sd'), ('the nho', 'memory card', 'microsd', 'micro sd', 'sd card'), ('card reader', 'dau doc', 'the nho gia')),
        (('chuot', 'mouse'), ('chuot', 'mouse'), ('mouse pad', 'mousepad', 'lot chuot')),
        (('ban phim', 'keyboard'), ('ban phim', 'keyboard'), ('keycap', 'key cap')),
        (('laptop', 'notebook'), ('laptop', 'notebook', 'macbook'), ('balo', 'backpack', 'tui', 'bag', 'stand', 'gia do', 'de tan nhiet', 'charger', 'sac', 'case', 'cover', 'skin', 'screen protector', 'ram ', 'adapter')),
        (('dien thoai', 'smartphone'), ('dien thoai', 'smartphone', 'iphone', 'galaxy', 'phone'), ('op lung', 'bao da', 'case', 'cover', 'screen protector', 'kinh cuong luc', 'charger', 'cap sac', 'gia do', 'holder', 'phone stand')),
        (('may anh', 'camera'), ('may anh', 'camera'), ('camera bag', 'tui', 'camera case', 'lens cap', 'camera mount', 'camera strap', 'day deo', 'tripod', 'chan may')),
    ]
    family = next((item for item in families if any(phrase in norm for phrase in item[0])), None)
    for row in STATE["products"]:
        if row.get('product_id') in edited_ids:
            row = EXTENSIONS.overlay(row, edits)
        if sources and (row.get('source') or '').lower() not in sources:
            continue
        if (row.get('source') or '').lower() in excluded_sources:
            continue
        name = row.get('_name') or normalize(row.get('product_name', ''))
        if any(re.search(r'\b'+b+r'\b', name+' '+normalize(row.get('brand', ''))) for b in excluded_brands):
            continue
        if brand and not re.search(r'\b'+brand+r'\b', name+' '+normalize(row.get('brand', ''))):
            continue
        if family and (not any(t in name for t in family[1]) or any(t in name for t in family[2])):
            continue
        if family and 'chuot' in family[0] and any(t in name for t in ('chuot tui', 'hinh chuot', 'tai chuot', 'chuot hoat hinh')):
            continue
        if any(t in norm for t in ('khong day', 'wireless', 'bluetooth')) and not any(t in name for t in ('khong day', 'wireless', 'bluetooth')):
            continue
        if 'co day' in norm and any(t in name for t in ('khong day', 'wireless', 'bluetooth')):
            continue
        if capacity and not re.search(r'\b' + capacity[1] + r'\s*' + capacity[2] + r'\b', name):
            continue
        price = parse_number(row.get('price'))
        currency = (row.get('currency') or '').upper()
        if price_limit is not None and (price <= 0 or price > price_limit or (price_currency and currency != price_currency)):
            continue
        if price_floor is not None and (price <= 0 or price < price_floor or (floor_currency and currency != floor_currency)):
            continue
        score = score_product(row, query_tokens, sources, price_limit, price_currency, price_floor, floor_currency, intents)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [format_product(row, score) for score, row in scored[:limit]]


def diversify_sources(scored, limit):
    if not scored:
        return []
    best_score = scored[0][0]
    relevance_floor = 12
    quotas = {"amazon": 2, "tiki": 2, "shopee": 2}
    selected = []
    selected_ids = set()
    for source, quota in quotas.items():
        count = 0
        for score, row in scored:
            if score < relevance_floor:
                continue
            if (row.get("source") or "").lower() != source:
                continue
            product_id = row.get("product_id")
            if product_id in selected_ids:
                continue
            selected.append((score, row))
            selected_ids.add(product_id)
            count += 1
            if count >= quota:
                break
    for score, row in scored:
        if len(selected) >= limit:
            break
        if score < relevance_floor and selected:
            continue
        product_id = row.get("product_id")
        if product_id not in selected_ids:
            selected.append((score, row))
            selected_ids.add(product_id)
    selected.sort(key=lambda item: item[0], reverse=True)
    return [format_product(row, score) for score, row in selected[:limit]]


def format_product(row, score):
    enrichment = globals().get('ENRICHMENT')
    if enrichment and EXTENSIONS is enrichment.engine:
        row = enrichment.apply(row)
    return {
        "product_id": row.get("product_id"),
        "name": row.get("product_name"),
        "category": row.get("category"),
        "brand": row.get("brand"),
        "price": row.get("price"),
        "currency": row.get("currency"),
        "rating": row.get("average_rating"),
        "review_count": row.get("review_count"),
        "sold_count": row.get("sold_count"),
        "source": row.get("source"),
        "url": row.get("product_url"),
        "image_url": row.get("image_url"),
        "score": round(score, 2),
        "description": row.get("description"),
        "knowledge_edit_ids": row.get("_edit_ids", []),
        "price_is_historical": True,
        "image_source": row.get('image_source'),
        "external_reviews": row.get('external_reviews', []),
        "enriched_at": row.get('enriched_at'),
    }


def parse_number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def top_reviewed_products(limit=6):
    ranked = sorted(
        STATE["products"],
        key=lambda row: (
            parse_number(row.get("average_rating")) >= 4.5,
            parse_number(row.get("review_count")),
            parse_number(row.get("average_rating")),
        ),
        reverse=True,
    )
    return [format_product(row, parse_number(row.get("review_count"))) for row in ranked[:limit]]


def top_searched_products(limit=6):
    counts = STATE["search_counts"]
    if not counts:
        return top_reviewed_products(limit)

    by_id = {row.get("product_id"): row for row in STATE["products"]}
    ranked_ids = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    products = []
    for product_id, count in ranked_ids:
        row = by_id.get(product_id)
        if row:
            item = format_product(row, count)
            item["search_count"] = count
            products.append(item)
        if len(products) >= limit:
            break
    return products


def load_review_cache():
    """Read CSV once; subsequent requests use SQLite's product primary key."""
    try:
        if not REVIEWS_CSV.exists():
            STATE['reviews_ready'] = True
            return
        signature = f'{REVIEWS_CSV.stat().st_size}:{REVIEWS_CSV.stat().st_mtime_ns}'
        with EXTENSIONS.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS review_samples(product TEXT PRIMARY KEY, items TEXT); CREATE TABLE IF NOT EXISTS cache_meta(key TEXT PRIMARY KEY,value TEXT);')
            saved = db.execute("SELECT value FROM cache_meta WHERE key='reviews'").fetchone()
        if not saved or saved[0] != signature:
            samples = {}
            with REVIEWS_CSV.open('r', encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    pid = row.get('product_id')
                    text = row.get('review_text', '').strip()
                    if not pid or not text:
                        continue
                    bucket = samples.setdefault(pid, [])
                    if len(bucket) < 5:
                        bucket.append({'review_id': row.get('review_id'), 'rating': row.get('rating'), 'title': row.get('review_title'), 'text': trim_text(text, 1200), 'source': row.get('source'), 'verified_purchase': row.get('verified_purchase')})
            with EXTENSIONS.connect() as db:
                db.execute('DELETE FROM review_samples')
                db.executemany('INSERT INTO review_samples VALUES (?,?)', ((pid, json.dumps(items, ensure_ascii=False)) for pid, items in samples.items()))
                db.execute("INSERT OR REPLACE INTO cache_meta VALUES ('reviews',?)", (signature,))
        STATE['reviews_ready'] = True
    except Exception as exc:
        STATE['review_error'] = str(exc)


def find_reviews(product_ids, per_product=2):
    wanted = set(product_ids)
    found = {product_id: [] for product_id in wanted}
    if not wanted:
        return found
    if not STATE.get('reviews_ready'):
        raise RuntimeError('Review đang chuẩn bị, vui lòng thử lại sau ít phút.')
    with EXTENSIONS.connect() as db:
        for pid in wanted:
            row = db.execute('SELECT items FROM review_samples WHERE product=?', (pid,)).fetchone()
            if row:
                found[pid] = json.loads(row[0])[:per_product]
    return found


def trim_text(text, max_len):
    text = " ".join((text or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def needs_clarification(message):
    q_tokens = tokens(message)
    if normalize(message) in {'amazon', 'tiki', 'shopee', 'shoppe', 'san pham', 'may', 'do', 'phu kien'}:
        return 'Bạn muốn tìm loại sản phẩm nào? Cho mình thêm tên hoặc mục đích sử dụng để chọn đúng nhé.'
    if not q_tokens and not detect_sources(message):
        return "Bạn đang muốn mua gì? Cho mình biết loại sản phẩm và khoảng giá nhé."
    if normalize(message) in {"re hon", "tot hon", "san pham khac", "cai khac", "them nua"}:
        return "Bạn muốn rẻ hơn/tốt hơn so với sản phẩm số mấy trong danh sách trước?"
    return None


def build_answer(message):
    if not STATE["loaded"]:
        return {
            "type": "error",
            "message": f"Kho tri thức sản phẩm chưa sẵn sàng: {STATE['load_error'] or 'đang đồng bộ dữ liệu'}",
        }

    clarification = needs_clarification(message)
    if clarification:
        return {
            "type": "clarification",
            "message": clarification,
            "tools": ["intent_check", "ask_follow_up"],
        }

    products = search_products(message)
    if not products:
        return {
            "type": "empty",
            "message": "Mình chưa tìm thấy sản phẩm phù hợp trong kho dữ liệu hiện tại. Bạn thử nêu rõ hơn tên sản phẩm, thương hiệu, mức giá hoặc sàn muốn tìm nhé.",
            "tools": ["product_search"],
        }

    reviews = find_reviews([item["product_id"] for item in products[:4]], per_product=2)
    for item in products:
        item["reviews"] = reviews.get(item["product_id"], [])
        STATE["search_counts"][item["product_id"]] = STATE["search_counts"].get(item["product_id"], 0) + 1

    sources = sorted({item.get("source") for item in products if item.get("source")})
    return {
        "type": "recommendation",
        "message": "Mình đã phân tích nhu cầu, truy xuất các sản phẩm phù hợp, xếp hạng theo độ liên quan, sàn, giá, rating và số lượt đánh giá; sau đó đối chiếu review khách hàng cho từng lựa chọn nổi bật.",
        "tools": ["hiểu nhu cầu", "tìm sản phẩm", "xếp hạng", "đọc review", "trả lời có căn cứ"],
        "sources": sources,
        "products": products,
    }


def append_history(user_message, answer):
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user": user_message,
        "answer_type": answer.get("type"),
        "message": answer.get("message"),
        "product_ids": [item.get("product_id") for item in answer.get("products", [])],
    }
    history = []
    if HISTORY_JSON.exists():
        try:
            history = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    history.append(record)
    HISTORY_JSON.write_text(json.dumps(history[-200:], ensure_ascii=False, indent=2), encoding="utf-8")


EXTENSIONS = AgentExtensions(sys.modules[__name__], ROOT / 'agent_state.sqlite3')
ENRICHMENT = ProductEnrichment(EXTENSIONS)


class AgentHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def admin_allowed(self):
        token = os.environ.get('AGENT_ADMIN_TOKEN', '')
        return bool(token) and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

    def end_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        accounts = Accounts(EXTENSIONS)
        user = accounts.user(self.headers.get('Authorization', '').removeprefix('Bearer '))
        if parsed.path == '/api/account':
            self.end_json(accounts.profile(user) if user else {'error': 'Cần đăng nhập.'}, 200 if user else 401)
            return
        if parsed.path == '/api/product':
            try:
                pid = parse_qs(parsed.query).get('id', [''])[0]
                ENRICHMENT.queue(pid)
                product = format_product(EXTENSIONS.overlay(EXTENSIONS.product(pid)), 0)
                session = parse_qs(parsed.query).get('session_id', [''])[0]
                if session:
                    if not accounts.allowed(session, user):
                        self.end_json({'error': 'Không có quyền truy cập hội thoại.'}, 403)
                        return
                    EXTENSIONS.viewed(session, pid)
                try:
                    product['reviews'] = find_reviews([pid], 5).get(pid, [])
                    product['reviews_pending'] = False
                except RuntimeError:
                    product['reviews'] = []
                    product['reviews_pending'] = True
                if product.get('external_reviews'):
                    product['reviews'] = product['external_reviews']
                    product['reviews_pending'] = False
                product['enrichment_pending'] = ENRICHMENT.pending_for(pid)
                self.end_json(product)
            except ValueError as exc:
                self.end_json({'error': str(exc)}, 404)
            return
        if parsed.path.startswith('/api/admin/'):
            if not self.admin_allowed():
                self.end_json({'error': 'Cần AGENT_ADMIN_TOKEN và Bearer token.'}, 403)
                return
            if parsed.path == '/api/admin/edits':
                self.end_json({'items': EXTENSIONS.edits()})
            elif parsed.path == '/api/admin/metrics':
                self.end_json(EXTENSIONS.metrics())
            elif parsed.path == '/api/admin/products':
                query = parse_qs(parsed.query).get('q', [''])[0]
                self.end_json({'items': search_products(query) if query else [format_product(EXTENSIONS.overlay(r), 0) for r in STATE['products'][:20]]})
            elif parsed.path == '/api/admin/logs':
                with EXTENSIONS.connect() as db:
                    rows = db.execute('SELECT created,message,answer FROM turns ORDER BY id DESC LIMIT 50').fetchall()
                self.end_json({'items': [{'created': r[0], 'message': r[1], 'answer': json.loads(r[2])} for r in rows]})
            else:
                self.end_json({'error': 'not_found'}, 404)
            return
        if parsed.path == "/api/status":
            self.end_json({
                "app_version": "shopping-chat-2026-10-03",
                "loaded": STATE["loaded"],
                "load_error": STATE["load_error"],
                "product_count": len(STATE["products"]),
                "reviews_available": REVIEWS_CSV.exists(),
                "reviews_ready": STATE.get('reviews_ready', False),
            })
            return
        if parsed.path == '/api/search':
            query = parse_qs(parsed.query).get('q', [''])[0]
            if not query.strip():
                self.end_json({'items': [], 'message': 'Nhập tên sản phẩm bạn muốn tìm.'})
            elif not STATE['loaded']:
                self.end_json({'error': 'Danh sách sản phẩm đang chuẩn bị. Thử lại sau ít phút.'}, 503)
            else:
                products = search_products(query, limit=5)
                for p in products:
                    ENRICHMENT.queue(p['product_id'])
                self.end_json({'items': products})
            return
        if parsed.path == "/api/top-products":
            self.end_json({
                "top_searched": top_searched_products(),
                "top_reviewed": top_reviewed_products(),
            })
            return
        if parsed.path == "/api/history":
            session = parse_qs(parsed.query).get('session_id', [''])[0]
            if not accounts.allowed(session, user):
                self.end_json({'error': 'Không có quyền truy cập phiên.'}, 403)
                return
            self.end_json({'items': EXTENSIONS.history(session) if session else []})
            return
        if parsed.path == "/":
            self.path = "/index.html"
        # Only serve public pages; datasets, SQLite state and local files are private.
        if self.path not in {'/index.html', '/admin.html', '/app.css', '/app.js'}:
            self.end_json({'error': 'not_found'}, 404)
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/chat" and not parsed.path.startswith(('/api/admin/', '/api/account/')):
            self.end_json({"error": "not_found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 65536:
                self.end_json({'error': 'Request quá lớn.'}, 413)
                return
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw or "{}")
            if not isinstance(payload, dict):
                raise ValueError('Expected object')
        except (ValueError, UnicodeDecodeError):
            self.end_json({'error': 'JSON không hợp lệ.'}, 400)
            return
        accounts = Accounts(EXTENSIONS)
        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
        user = accounts.user(token)
        if parsed.path.startswith('/api/account/'):
            action = parsed.path.rsplit('/', 1)[1]
            try:
                if action in {'register', 'login'}:
                    result = accounts.authenticate(action, payload)
                elif not user:
                    self.end_json({'error': 'Cần đăng nhập.'}, 401)
                    return
                elif action == 'logout':
                    with EXTENSIONS.connect() as db:
                        db.execute('DELETE FROM logins WHERE token=?', (token,))
                    result = {'ok': True}
                elif action == 'profile':
                    result = accounts.profile(user, payload)
                elif action == 'favorite':
                    result = accounts.favorite(user, payload)
                elif action == 'session':
                    result = {'session_id': accounts.new_session(user)}
                else:
                    raise ValueError('Chức năng không tồn tại.')
                self.end_json(result)
            except ValueError as exc:
                self.end_json({'error': str(exc)}, 400)
            return
        if parsed.path.startswith('/api/admin/'):
            if not self.admin_allowed():
                self.end_json({'error': 'Cần token quản trị.'}, 403)
                return
            try:
                if parsed.path == '/api/admin/edits':
                    result = EXTENSIONS.create_edit(payload)
                elif parsed.path == '/api/admin/preview':
                    result = EXTENSIONS.preview(payload.get('edit_id'))
                elif parsed.path == '/api/admin/activate':
                    result = EXTENSIONS.set_active(payload.get('edit_id'), True)
                elif parsed.path == '/api/admin/rollback':
                    result = EXTENSIONS.set_active(payload.get('edit_id'), False)
                else:
                    self.end_json({'error': 'not_found'}, 404)
                    return
                self.end_json(result)
            except ValueError as exc:
                self.end_json({'error': str(exc)}, 400)
            return
        if not isinstance(payload.get('message', ''), str):
            self.end_json({'error': 'message phải là chuỗi.'}, 400)
            return
        message = (payload.get("message") or "").strip()
        if not message:
            self.end_json({"type": "clarification", "message": "Bạn muốn tìm sản phẩm gì?"})
            return
        session = payload.get('session_id') or str(uuid.uuid4())
        try:
            session = str(uuid.UUID(session))
        except (ValueError, TypeError, AttributeError):
            self.end_json({'error': 'session_id phải là UUID.'}, 400)
            return
        if not accounts.allowed(session, user):
            self.end_json({'error': 'Không có quyền truy cập phiên. Hãy tạo hội thoại mới.'}, 403)
            return
        action = payload.get('action')
        product_id = payload.get('product_id')
        if action not in {None, 'similar'} or (product_id is not None and not isinstance(product_id, str)):
            self.end_json({'error': 'Yêu cầu sản phẩm không hợp lệ.'}, 400)
            return
        answer = EXTENSIONS.chat(message, session, product_id, action)
        for p in answer.get('products', []):
            ENRICHMENT.queue(p['product_id'])
        self.end_json(answer)


if __name__ == "__main__":
    thread = threading.Thread(target=load_products, daemon=True)
    thread.start()
    threading.Thread(target=load_review_cache, daemon=True).start()
    host = os.environ.get("AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENT_PORT", "8781"))
    server = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"AI Agent server: http://{host}:{port}")
    if host == "0.0.0.0":
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
            print(f"LAN test link: http://{lan_ip}:{port}")
        except OSError:
            print("LAN test link: use this computer's IPv4 address with the selected port.")
    print(f"Products: {PRODUCTS_CSV}")
    print(f"Reviews: {REVIEWS_CSV}")
    server.serve_forever()
