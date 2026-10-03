"""Persistent sessions, audited tool execution and retrieval-time knowledge edits.

The planner is deterministic. It does not claim to run Qwen, FAISS or BPR.
"""
import json
import math
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from conversation_context import rewrite, positions, PRICE, conversation_intent


def now():
    return datetime.now(timezone.utc).isoformat()


class AgentExtensions:
    FIELDS = {"price", "currency", "product_name", "description", "brand", "average_rating"}

    def __init__(self, backend, path):
        self.backend = backend
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, query TEXT, products TEXT);
                CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, session TEXT, created TEXT, message TEXT, answer TEXT);
                CREATE TABLE IF NOT EXISTS edits (id TEXT PRIMARY KEY, product TEXT, field TEXT, value TEXT, reason TEXT, evidence TEXT, active INTEGER, version INTEGER, created TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS active_edit ON edits(product, field) WHERE active=1;
                CREATE TABLE IF NOT EXISTS edit_events (id INTEGER PRIMARY KEY, edit TEXT, action TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS focus(session TEXT PRIMARY KEY, product TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def edits(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,product,field,value,reason,evidence,active,version,created FROM edits ORDER BY version DESC").fetchall()
        return [dict(zip(("edit_id", "product_id", "field", "new_value", "reason", "evidence", "active", "version", "created_at"), row)) | {"new_value": json.loads(row[3]), "active": bool(row[6])} for row in rows]

    def overlay(self, row, edits=None):
        result = dict(row)
        applied = []
        for edit in self.edits() if edits is None else edits:
            if edit["active"] and edit["product_id"] == row.get("product_id"):
                result[edit["field"]] = str(edit["new_value"])
                applied.append(edit["edit_id"])
        result["_edit_ids"] = applied
        text = " ".join(str(result.get(key) or "") for key in ("product_name", "category", "subcategory", "brand", "description", "source"))
        result["_search"] = self.backend.normalize(text)
        result["_tokens"] = set(self.backend.tokens(text))
        result['_name'] = self.backend.normalize(result.get('product_name', ''))
        return result

    def product(self, product_id):
        row = next((row for row in self.backend.STATE["products"] if row.get("product_id") == product_id), None)
        if row is None:
            raise ValueError("Không tìm thấy mã sản phẩm.")
        return row

    def create_edit(self, payload):
        product_id = payload.get("product_id")
        self.product(product_id)
        field = payload.get("field")
        value = payload.get("new_value")
        if field not in self.FIELDS:
            raise ValueError("Thuộc tính chỉnh sửa không được hỗ trợ.")
        if field in {"price", "average_rating"}:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError("Giá và rating phải là số.")
            if not math.isfinite(value) or value < 0 or (field == "average_rating" and value > 5):
                raise ValueError("Giá phải không âm; rating trong khoảng 0–5.")
        elif not isinstance(value, str) or not value.strip() or len(value) > 10000:
            raise ValueError("Giá trị văn bản không hợp lệ.")
        if field == "currency" and value not in {"USD", "VND"}:
            raise ValueError("Tiền tệ hỗ trợ: USD, VND.")
        reason, evidence = payload.get("reason"), payload.get("evidence")
        if not all(isinstance(v, str) and v.strip() and len(v) <= 4000 for v in (reason, evidence)):
            raise ValueError("Cần lý do và nguồn bằng chứng (hoặc ghi rõ dữ liệu giả lập).")
        edit_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM edits").fetchone()[0]
            db.execute("INSERT INTO edits VALUES (?,?,?,?,?,?,0,?,?)", (edit_id, product_id, field, json.dumps(value), reason, evidence, version, now()))
            db.execute("INSERT INTO edit_events(edit,action,created) VALUES (?,?,?)", (edit_id, "create_draft", now()))
        return next(edit for edit in self.edits() if edit["edit_id"] == edit_id)

    def set_active(self, edit_id, active):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT product,field FROM edits WHERE id=?", (edit_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy bản chỉnh sửa.")
            if active and db.execute("SELECT 1 FROM edits WHERE product=? AND field=? AND active=1 AND id<>?", (*row, edit_id)).fetchone():
                raise ValueError("Xung đột: hãy tắt bản đang hoạt động của thuộc tính này trước.")
            db.execute("UPDATE edits SET active=? WHERE id=?", (int(active), edit_id))
            db.execute("INSERT INTO edit_events(edit,action,created) VALUES (?,?,?)", (edit_id, "activate" if active else "rollback", now()))
        return {"edit_id": edit_id, "active": active}

    def preview(self, edit_id):
        edit = next((e for e in self.edits() if e["edit_id"] == edit_id), None)
        if not edit:
            raise ValueError("Không tìm thấy bản chỉnh sửa.")
        raw = self.product(edit["product_id"])
        current = self.overlay(raw)
        proposed = dict(current)
        proposed[edit["field"]] = edit["new_value"]
        with self.connect() as db:
            events = db.execute("SELECT action,created FROM edit_events WHERE edit=? ORDER BY id", (edit_id,)).fetchall()
        def response(row):
            return f"{row.get('product_name', edit['product_id'])}: {edit['field']} = {row.get(edit['field'])}. Nguồn: product:{edit['product_id']}."
        return {"original": raw.get(edit["field"]), "before": current.get(edit["field"]), "after": proposed.get(edit["field"]), "before_answer": response(current), "after_answer": response(proposed) + f" Bằng chứng: {edit['evidence']}; phiên bản {edit['version']}.", "evidence": edit["evidence"], "events": events}

    def history(self, session):
        with self.connect() as db:
            rows = db.execute("SELECT created,message,answer FROM turns WHERE session=? ORDER BY id DESC LIMIT 50", (session,)).fetchall()
        return [{"created_at": r[0], "user": r[1], "answer": json.loads(r[2])} for r in reversed(rows)]

    def metrics(self):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
            rows = db.execute("SELECT answer FROM turns ORDER BY id DESC LIMIT 500").fetchall()
        answers = [json.loads(r[0]) for r in rows]
        latencies = sorted(a.get("latency_ms", 0) for a in answers)
        return {"total_turns": total, "sample_size": len(answers), "mean_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0, "p95_latency_ms": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else 0, "errors": sum(a.get("type") == "error" for a in answers), "planner": "deterministic_python", "llm_enabled": False, "faiss_enabled": False, "bpr_enabled": False}

    def viewed(self, session, product_id):
        self.product(product_id)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO focus VALUES (?,?)', (session, product_id))

    def similar(self, product_id, query=''):
        seed = self.overlay(self.product(product_id))
        candidates = self.backend.search_products(query or seed.get('product_name', ''), limit=100)
        seed_tokens = set(self.backend.tokens(seed.get('product_name', '')))
        ranked = []
        for p in candidates:
            if p['product_id'] == product_id:
                continue
            name_tokens = set(self.backend.tokens(p.get('name', '')))
            overlap = len(seed_tokens & name_tokens)
            if overlap < min(2, len(seed_tokens)):
                continue
            similarity = overlap / max(1, len(seed_tokens | name_tokens))
            ranked.append((similarity + (0.15 if p.get('category') and p['category'] == seed.get('category') else 0), p))
        ranked.sort(key=lambda item: (item[0], item[1]['score']), reverse=True)
        return [p for _, p in ranked[:5]]

    def chat(self, message, session, product_id=None, action=None):
        started = time.perf_counter()
        trace = []

        def execute(name, function):
            start = time.perf_counter()
            try:
                result = function()
                trace.append({"tool": name, "status": "ok", "latency_ms": round((time.perf_counter()-start)*1000, 2)})
                return result
            except Exception:
                trace.append({"tool": name, "status": "error", "latency_ms": round((time.perf_counter()-start)*1000, 2)})
                raise

        with self.connect() as db:
            saved = db.execute("SELECT query,products FROM sessions WHERE id=?", (session,)).fetchone()
            focused = db.execute('SELECT product FROM focus WHERE session=?', (session,)).fetchone()
        last_query, last_ids = (saved[0], json.loads(saved[1])) if saved else ("", [])
        # Repair sessions where the old planner searched on a follow-up question.
        if last_query and conversation_intent(self.backend.normalize(last_query), '', self.backend.normalize) != 'search':
            with self.connect() as db:
                recent = db.execute('SELECT message,answer FROM turns WHERE session=? ORDER BY id DESC LIMIT 30', (session,)).fetchall()
            for old_message, raw_answer in recent:
                old_answer = json.loads(raw_answer)
                if old_answer.get('products') and conversation_intent(self.backend.normalize(old_message), '', self.backend.normalize) == 'search':
                    last_query = old_message
                    last_ids = [p['product_id'] for p in old_answer['products']]
                    focused = None
                    break
        norm = self.backend.normalize(message)
        numbers = positions(norm)
        similar = action == 'similar' or any(t in norm for t in ('tuong tu', 'giong cai', 'loai khac', 'cai khac'))
        intent = conversation_intent(norm, last_query, self.backend.normalize)
        best = intent == 'best'
        reference = bool(product_id or numbers) or (any(word in norm for word in ('vua xem', 'vua roi', 'chung', 'cac san pham tren', 'cai nay', 'cai do', 'mau nay', 'gia bao nhieu')) or norm in {'review', 'danh gia', 'xem review', 'xem danh gia', 'so sanh', 'so sanh chung'}) and bool(last_ids)
        reference = reference or similar or best or intent == 'reference'
        wants_compare = "so sanh" in norm
        wants_review = "review" in norm or "danh gia" in norm
        query = message
        products = []
        answer = None
        try:
            if norm in {'xin chao', 'chao', 'hello', 'hi'}:
                answer = {'type': 'conversation', 'message': 'Chào bạn! Bạn đang muốn mua gì? Mình sẽ chọn tối đa 5 sản phẩm phù hợp và cùng bạn so sánh.'}
            elif norm in {'cam on', 'cam on ban', 'ok', 'oke', 'duoc roi'}:
                answer = {'type': 'conversation', 'message': 'Bạn cứ hỏi tiếp nhé. Mình có thể xem đánh giá, so sánh hoặc tìm lựa chọn khác cho bạn.'}
            elif not self.backend.STATE["loaded"]:
                answer = {"type": "error", "message": "Kho dữ liệu chưa sẵn sàng."}
            elif reference and not product_id and (not last_ids or any(i < 0 or i >= len(last_ids) for i in numbers)):
                answer = {"type": "clarification", "message": "Phiên này chưa có sản phẩm ở vị trí bạn nhắc tới. Hãy tìm sản phẩm trước."}
            else:
                if reference:
                    ids = [product_id] if product_id else [last_ids[i] for i in numbers] if numbers else [focused[0]] if focused and not best and any(t in norm for t in ('vua xem', 'cai nay', 'cai do', 'mau nay', 'gia bao nhieu', 'vi sao', 'tai sao', 'chon no', 'san pham do')) else last_ids
                    if similar:
                        if len(ids) != 1:
                            answer = {'type': 'clarification', 'message': 'Bạn muốn tìm sản phẩm tương tự mẫu số mấy? Bạn cũng có thể bấm “Sản phẩm tương tự” ngay dưới mẫu đó.'}
                        else:
                            query = last_query if ids[0] in last_ids else self.product(ids[0]).get('product_name', '')
                            products = execute('find_similar_products', lambda: self.similar(ids[0], query))
                    else:
                        if best:
                            rows = [self.backend.format_product(self.overlay(self.product(pid)), 0) for pid in ids]
                            def confidence(p):
                                rating = self.backend.parse_number(p.get('rating'))
                                count = max(0, self.backend.parse_number(p.get('review_count')))
                                return (rating*count+3.5*50)/(count+50) if rating > 0 and count > 0 else 0
                            rows.sort(key=confidence, reverse=True)
                            products = rows[:1]
                            if products:
                                self.viewed(session, products[0]['product_id'])
                        else:
                            products = execute("get_product_details", lambda: [self.backend.format_product(self.overlay(self.product(pid)), 0) for pid in ids[:5]])
                else:
                    query, inherited = rewrite(message, last_query, self.backend.normalize)
                    if inherited and 're hon' in norm and last_ids:
                        target = self.product(focused[0] if focused else last_ids[0])
                        target = self.overlay(target)
                        amount = self.backend.parse_number(target.get('price'))
                        currency = target.get('currency')
                        if amount > 0 and currency in {'USD', 'VND'}:
                            amount = max(0, amount - (0.01 if currency == 'USD' else 1))
                            query = re.sub(PRICE, '', query, flags=re.I) + f' dưới {amount:g} {currency}'
                    clarification = self.backend.needs_clarification(query)
                    if clarification:
                        answer = {"type": "clarification", "message": clarification}
                    else:
                        products = execute("recommend_products", lambda: self.backend.search_products(query, limit=5))
                if answer is None:
                    if not products:
                        answer = {"type": "empty", "message": "Mình chưa tìm được mẫu tương tự đáp ứng điều kiện này. Bạn muốn nới khoảng giá hoặc đổi thương hiệu không?" if similar else "Mình chưa tìm được sản phẩm phù hợp với điều kiện này. Bạn thử đổi khoảng giá hoặc tên sản phẩm nhé."}
                    else:
                        try:
                            reviews = execute("get_product_reviews", lambda: self.backend.find_reviews([p["product_id"] for p in products], 2))
                            review_fallback = False
                        except Exception:
                            reviews = {}
                            review_fallback = True
                        for product in products:
                            product["reviews"] = product.get('external_reviews') or reviews.get(product["product_id"], [])
                            product["citations"] = ["product:" + product["product_id"]] + ["review:" + r["review_id"] for r in product["reviews"] if r.get("review_id")]
                            rating = product.get('rating')
                            count = product.get('review_count')
                            product['recommendation_reason'] = f"Đánh giá {rating}/5 từ {count} lượt." if self.backend.parse_number(rating) > 0 and self.backend.parse_number(count) > 0 else 'Phù hợp với loại sản phẩm bạn đang tìm.'
                            product['review_summary'] = ' '.join(str(r.get('text', ''))[:240] for r in product['reviews']) or 'Chưa có bằng chứng review để tóm tắt.'
                        comparison = execute("compare_products", lambda: [{k: p.get(k) for k in ("product_id", "name", "price", "currency", "rating", "review_count")} for p in products[:5]]) if wants_compare else []
                        execute("grounding_audit", lambda: all(self.product(p["product_id"]) is not None for p in products))
                        intro = f'Mình chọn được {len(products)} sản phẩm phù hợp cho bạn. Bạn có thể hỏi tiếp về giá, đánh giá hoặc so sánh các mẫu này.'
                        if similar:
                            intro = f'Đây là {len(products)} lựa chọn tương tự mẫu bạn vừa chọn, không gồm mẫu cũ.'
                        elif wants_compare:
                            intro = 'Mình đặt các mẫu cạnh nhau để bạn dễ chọn. Hãy xem giá và số lượt đánh giá bên dưới nhé.'
                        elif wants_review:
                            intro = 'Mình tìm các đánh giá của khách đã mua bên dưới. Mẫu nào chưa có đánh giá thì mình ghi rõ, để bạn dễ cân nhắc.'
                        elif best:
                            p = products[0]
                            if self.backend.parse_number(p.get('rating')) > 0 and self.backend.parse_number(p.get('review_count')) > 0:
                                label = self.backend.trim_text(p['name'], 100)
                                intro = f"Trong {len(ids)} mẫu vừa gửi, mình nghiêng về {label}. Mẫu này có điểm {p.get('rating')}/5 từ {p.get('review_count')} lượt đánh giá. Mình cân nhắc cả điểm và số người đánh giá. Giá ghi nhận là {p.get('price') or 'chưa có'} {p.get('currency') or ''}. Lựa chọn này dựa trên thông tin hiện có, mình chưa dùng thử sản phẩm."
                            else:
                                intro = 'Mình chưa có đủ điểm và lượt đánh giá để chọn mẫu tốt nhất một cách đáng tin cậy. Bạn muốn ưu tiên giá hay một đặc tính cụ thể?'
                        elif reference and any(t in norm for t in ('vi sao', 'tai sao')) and len(products) == 1:
                            p = products[0]
                            intro = f"Mình cân nhắc cả điểm {p.get('rating') or 'chưa có'}/5 và {p.get('review_count') or 'chưa có'} lượt đánh giá của mẫu này, cùng các điều kiện bạn đã hỏi trước đó. Nhiều lượt đánh giá giúp có thêm căn cứ hơn một điểm cao chỉ từ vài lượt. Mình chưa kiểm chứng chất lượng bằng việc dùng thử."
                        elif reference and any(t in norm for t in ('gia bao nhieu', 'bao nhieu tien')) and len(products) == 1:
                            p = products[0]
                            intro = f"Giá ghi nhận của mẫu này là {p['price']} {p.get('currency') or ''}. Bạn nên kiểm tra lại giá hiện tại ở nơi bán." if self.backend.parse_number(p.get('price')) > 0 else 'Mẫu này chưa có giá trong nguồn hiện tại. Mình chưa thể xác nhận giá bán hoặc mức phù hợp với ngân sách của bạn.'
                        elif reference:
                            intro = 'Đây là thông tin của mẫu bạn vừa hỏi. Bạn muốn mình xem đánh giá hay tìm lựa chọn khác?'
                        answer = {"type": "comparison" if wants_compare else "reviews" if wants_review else "recommendation", "message": intro, "products": products, "comparison": comparison, "sources": sorted({p["source"] for p in products if p.get("source")}), "grounding": {"mode": "structured_source_projection", "citations": True}}
                        answer['fallback_reason'] = 'review_tool_failed' if review_fallback else None
                        if review_fallback:
                            answer['message'] += ' Đánh giá đang được chuẩn bị; bạn vẫn có thể xem và chọn sản phẩm.'
        except Exception:
            answer = {"type": "error", "message": "Mình chưa lấy được thông tin lúc này. Bạn thử lại nhé; hội thoại vẫn được giữ nguyên."}
        answer.update(session_id=session, tools=[t["tool"] for t in trace], tool_trace=trace, latency_ms=round((time.perf_counter()-started)*1000, 2))
        with self.connect() as db:
            if (products or (not reference and answer['type'] == 'empty')) and answer["type"] != "error":
                saved_ids = last_ids if (reference and not similar) or not products else [p['product_id'] for p in products]
                db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)", (session, last_query if reference and not similar else query, json.dumps(saved_ids)))
            db.execute("INSERT INTO turns(session,created,message,answer) VALUES (?,?,?,?)", (session, now(), message, json.dumps(answer, ensure_ascii=False)))
        return answer
