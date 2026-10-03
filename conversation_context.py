"""Small, explicit follow-up resolver; only carry filters the shopper supplied."""
import re


PRICE = r'(?:dưới|nhỏ hơn|tối đa|under|max|trên|lớn hơn|ít nhất|từ|from|min)\s*\d+(?:[.,]\d+)?\s*(?:triệu|ngàn|nghìn|ngan|trieu|k|usd|vnd|đồng)?'
CAPACITY = r'\b\d+\s*(?:gb|tb)\b'
BRANDS = ('sony', 'samsung', 'apple', 'sandisk', 'kingston', 'xiaomi', 'anker', 'jbl', 'logitech', 'asus', 'acer', 'dell', 'hp', 'lenovo', 'oppo', 'vivo')

CATEGORIES = ('tai nghe', 'the nho', 'microsd', 'micro sd', 'dien thoai', 'laptop', 'ban hoc', 'may anh', 'giay', 'dep', 'chuot', 'ban phim', 'loa', 'ao', 'quan')


def has_phrase(text, phrase):
    return bool(re.search(r'\b'+re.escape(phrase)+r'\b', text))


def excluded_terms(norm, terms):
    """Recognize explicit exclusions without treating them as positive filters."""
    return {term for term in terms if re.search(
        r'\b(?:khong(?:\s+(?:lay|chon|mua|tim|dung))?|bo|tru|ngoai tru|loai bo)\s+(?:(?:hang|thuong hieu|san|cua)\s+)?'
        + re.escape(term) + r'\b', norm)}


def new_category(message, previous, normalize):
    current, old = normalize(message), normalize(previous)
    if previous and current.startswith(('cho ', 'de ', 'dung cho ', 'dung voi ', 'lap vao ', 'gan vao ')):
        return False
    return any(has_phrase(current, term) and not has_phrase(old, term) for term in CATEGORIES)


def conversation_intent(norm, previous, normalize):
    """Classify references before searching; never search on comparison boilerplate."""
    anchors = ('vua gui', 'vua de xuat', 'vua goi y', 'vua xem', 'o tren', 'danh sach', 'trong so', 'trong cac', 'trong 5', 'trong nam', 'cac mau nay', 'cac san pham nay', 'cai nay', 'cai do', 'nhung cai do')
    anchored = any(t in norm for t in anchors) or bool(positions(norm))
    choice = any(t in norm for t in ('tot nhat', 'phu hop nhat', 'nen chon', 'nen mua', 'chon cai nao', 'dang mua', 'chon giup', 'goi y chon'))
    if choice and (anchored or not new_category(norm, previous, normalize)):
        return 'best'
    if anchored:
        return 'reference'
    if any(t in norm for t in ('review', 'danh gia', 'so sanh', 'uu diem', 'nhuoc diem', 'co tot khong', 'co tot ko', 'gia bao nhieu', 'vi sao', 'tai sao')) and not new_category(norm, previous, normalize):
        return 'reference'
    return 'search'


def rewrite(message, previous, normalize):
    norm = normalize(message)
    followup = bool(re.search(CAPACITY, message, re.I)) or norm in {'tiki', 'shopee', 'shoppe', 'amazon'} or any(norm == b for b in BRANDS) or norm.startswith(('cho ', 'de ', 'dung cho ', 'nhung ', 'uu tien ')) or any(t in norm for t in ('re hon', 'tot hon', 'loc ', 'them nua', 'loai khac', 'con loai', 'ngan sach', 'duoi ', 'tren ', 'toi da', 'chi lay', 'chi tim', 'cua hang', 'hang ', 'con tiki', 'con shopee', 'con shoppe', 'con amazon', 'co loai', 'co ban', 'dung luong', 'khong day', 'co day', 'chong on', 'chong nuoc', 'gaming', 'choi game'))
    # A complete new category starts its own search, even if it mentions a budget.
    if not previous or not followup or new_category(message, previous, normalize):
        return message, False
    query = previous
    if excluded_terms(norm, BRANDS + ('amazon', 'shopee', 'shoppe', 'tiki')):
        return (query+' '+message).strip(), True
    if 'co day' in norm:
        query = re.sub(r'không dây|khong day|wireless|bluetooth', '', query, flags=re.I)
    elif any(t in norm for t in ('khong day', 'wireless', 'bluetooth')):
        query = re.sub(r'có dây|co day|wired', '', query, flags=re.I)
    if re.search(PRICE, message, re.I):
        query = re.sub(PRICE, '', query, flags=re.I)
    if re.search(CAPACITY, message, re.I):
        query = re.sub(CAPACITY, '', query, flags=re.I)
    if any(s in norm for s in ('tiki', 'shopee', 'amazon')):
        query = re.sub(r'\b(?:tiki|shopee|amazon)\b', '', query, flags=re.I)
    if any(re.search(r'\b'+b+r'\b', norm) for b in BRANDS):
        query = re.sub(r'\b(?:'+'|'.join(BRANDS)+r')\b', '', query, flags=re.I)
    return (query+' '+message).strip(), True


def positions(norm):
    indices = [int(n)-1 for n in re.findall(r'(?:số|so|thu|pham|cai|mau)\s*(\d+)\b', norm)]
    match = re.search(r'so sanh\s+(\d+)\s+(?:va|voi)\s+(\d+)\b', norm)
    if match:
        indices += [int(match[1])-1, int(match[2])-1]
    for text, i in (('thu nhat', 0), ('dau tien', 0), ('thu hai', 1), ('thu ba', 2), ('thu tu', 3), ('thu nam', 4)):
        if text in norm:
            indices.append(i)
    return list(dict.fromkeys(indices))
