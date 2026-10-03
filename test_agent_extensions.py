import json
import tempfile
import unittest
import uuid
import threading
import http.client
import csv
from pathlib import Path
from unittest.mock import patch

import agent_server as server
from agent_extensions import AgentExtensions
from customer_accounts import Accounts


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=server.ROOT)
        self.engine = AgentExtensions(server, Path(self.temp.name) / 'state.sqlite3')
        self.original = server.EXTENSIONS
        server.EXTENSIONS = self.engine
        self.old_state = dict(server.STATE)
        rows = []
        for pid, price, currency, capacity in [('a', '16.99', 'USD', '64GB'), ('b', '25', 'USD', '64GB'), ('c', '10', 'USD', '32GB'), ('d', '10', 'VND', '64GB')]:
            row = dict(product_id=pid, product_name='microSD memory card '+capacity, price=price, currency=currency, source='amazon', average_rating='4.5', review_count='10')
            row['_search'] = server.normalize(row['product_name'])
            row['_tokens'] = set(server.tokens(row['product_name']))
            rows.append(row)
        server.STATE.update(products=rows, loaded=True, learning_rules={'intents': []})
        self.reviews = patch.object(server, 'find_reviews', return_value={'a': [{'review_id': 'r1', 'text': 'Good', 'rating': '5'}]})
        self.reviews.start()

    def tearDown(self):
        self.reviews.stop()
        server.EXTENSIONS = self.original
        server.STATE.clear()
        server.STATE.update(self.old_state)
        self.temp.cleanup()

    def edit(self, value=15.99):
        return self.engine.create_edit(dict(product_id='a', field='price', new_value=value, reason='Test', evidence='Simulated test'))

    def test_account_ownership_favorites_and_logout(self):
        accounts = Accounts(self.engine)
        login = accounts.authenticate('register', {'email': 'a@example.com', 'password': 'long-password-123'})
        user = accounts.user(login['token'])
        other = accounts.authenticate('register', {'email': 'b@example.com', 'password': 'other-password-123'})
        self.assertTrue(accounts.allowed(login['session_id'], user))
        self.assertFalse(accounts.allowed(login['session_id'], accounts.user(other['token'])))
        self.assertFalse(accounts.allowed(login['session_id'], None))
        accounts.favorite(user, {'product_id': 'a'})
        self.assertEqual(accounts.profile(user)['favorites'][0]['product_id'], 'a')
        self.assertEqual(accounts.profile(accounts.user(other['token']))['favorites'], [])
        accounts.favorite(user, {'product_id': 'a', 'remove': True})
        self.assertEqual(accounts.profile(user)['favorites'], [])
        with self.assertRaises(ValueError):
            accounts.authenticate('login', {'email': 'a@example.com', 'password': 'wrong-password-123'})
        self.assertIn('before_answer', self.engine.preview(self.edit()['edit_id']))

    def test_hard_filters(self):
        products = server.search_products('microSD 64GB dưới 20 USD')
        self.assertEqual([p['product_id'] for p in products], ['a'])

    def test_excluded_brand_and_platform_are_not_positive_filters(self):
        server.STATE['products'][0]['brand'] = 'Kingston'
        self.assertNotIn('a', [p['product_id'] for p in server.search_products('microSD khong lay hang Kingston')])
        self.assertEqual(server.search_products('microSD khong lay san amazon'), [])
        session = str(uuid.uuid4())
        self.engine.chat('microSD 64GB', session)
        reply = self.engine.chat('khong lay hang Kingston', session)
        self.assertNotIn('a', [p['product_id'] for p in reply['products']])
        self.assertNotIn('c', [p['product_id'] for p in reply['products']])

    def test_top_five_similar_excludes_seed(self):
        seed = dict(server.STATE['products'][0])
        for i in range(8):
            row = dict(seed, product_id='extra'+str(i), price=str(17+i))
            server.STATE['products'].append(row)
        session = str(uuid.uuid4())
        answer = self.engine.chat('microSD 64GB', session)
        self.assertEqual(len(answer['products']), 5)
        similar = self.engine.chat('Sản phẩm tương tự', session, product_id='a', action='similar')
        self.assertEqual(len(similar['products']), 5)
        self.assertNotIn('a', [p['product_id'] for p in similar['products']])
        self.assertNotIn('c', [p['product_id'] for p in similar['products']])

    def test_followup_replaces_budget_capacity_and_preserves_order(self):
        session = str(uuid.uuid4())
        self.engine.chat('microSD 64GB dưới 20 USD', session)
        raised = self.engine.chat('Dưới 30 USD', session)
        self.assertEqual({p['product_id'] for p in raised['products']}, {'a', 'b'})
        original_ids = [p['product_id'] for p in raised['products']]
        self.engine.chat('review cái thứ hai', session)
        again = self.engine.chat('review sản phẩm số 2', session)
        self.assertEqual(again['products'][0]['product_id'], original_ids[1])
        reduced = self.engine.chat('còn loại 32GB dưới 20 USD', session)
        self.assertEqual([p['product_id'] for p in reduced['products']], ['c'])

    def test_review_cache_uses_correct_product_ids_and_skips_empty_text(self):
        path = Path(self.temp.name) / 'reviews.csv'
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['product_id', 'review_id', 'review_text', 'rating', 'source'])
            writer.writeheader()
            writer.writerows([{'product_id': 'a', 'review_id': 'r'+str(i), 'review_text': 'Verified review '+str(i), 'rating': 5, 'source': 'amazon'} for i in range(7)])
            writer.writerow({'product_id': 'b', 'review_id': 'empty', 'review_text': ''})
        self.reviews.stop()
        with patch.object(server, 'REVIEWS_CSV', path):
            server.load_review_cache()
            self.assertTrue(server.STATE['reviews_ready'])
            reviews = server.find_reviews(['a', 'b'], 5)
            self.assertEqual(len(reviews['a']), 5)
            self.assertEqual(reviews['b'], [])

    def test_focus_and_comparison_keep_context(self):
        session = str(uuid.uuid4())
        answer = self.engine.chat('microSD 64GB dưới 30 USD', session)
        self.engine.viewed(session, 'b')
        self.assertEqual(self.engine.chat('giá bao nhiêu', session)['products'][0]['product_id'], 'b')
        compared = self.engine.chat('so sánh 1 và 2', session)
        self.assertEqual(len(compared['comparison']), 2)
        self.assertEqual([p['product_id'] for p in compared['products']], [p['product_id'] for p in answer['products']])

    def test_wired_headphones_not_excluded_and_cartoon_mouse_rejected(self):
        server.STATE['learning_rules'] = {'intents': [{'name': 'bluetooth_headphones', 'triggers': ['tai nghe'], 'must_any': ['tai nghe'], 'boost_terms': [], 'exclude_terms': []}]}
        rows = [dict(product_id='wired', product_name='Tai nghe có dây nhét tai 3.5mm', source='shopee', price='', currency='VND'), dict(product_id='bag', product_name='Túi có hình chuột hoạt hình', source='tiki', price='50000', currency='VND')]
        for row in rows:
            row['_search'] = server.normalize(row['product_name']+' '+row['source'])
            row['_tokens'] = set(server.tokens(row['_search']))
        server.STATE['products'] = rows
        self.assertEqual([p['product_id'] for p in server.search_products('tai nghe Shopee')], ['wired'])
        self.assertEqual(server.search_products('tai nghe Bluetooth Shopee'), [])
        self.assertEqual(server.search_products('chuột Tiki'), [])

    def test_users_exact_best_question_stays_inside_previous_five(self):
        session = str(uuid.uuid4())
        for i in range(5):
            row = dict(server.STATE['products'][0], product_id='card'+str(i), average_rating='4.6', review_count=str(1000+i))
            server.STATE['products'].append(row)
        unrelated = dict(product_id='socks', product_name='Combo 5 đôi tất tốt nhất', price='95000', currency='VND', source='tiki', average_rating='5', review_count='90000')
        unrelated['_search'] = server.normalize(unrelated['product_name'])
        unrelated['_tokens'] = set(server.tokens(unrelated['product_name']))
        server.STATE['products'].append(unrelated)
        first = self.engine.chat('Thẻ nhớ microSD 64GB dưới 20 USD', session)
        ids = [p['product_id'] for p in first['products']]
        answer = self.engine.chat('sản phẩm nào tốt nhất trong 5 cái bạn vừa gửi', session)
        self.assertEqual(len(answer['products']), 1)
        self.assertIn(answer['products'][0]['product_id'], ids)
        self.assertNotIn('recommend_products', answer['tools'])
        why = self.engine.chat('vì sao bạn chọn nó', session)
        self.assertEqual(why['products'][0]['product_id'], answer['products'][0]['product_id'])
        second = self.engine.chat('review sản phẩm số 2', session)
        self.assertEqual(second['products'][0]['product_id'], ids[1])

    def test_empty_followup_keeps_new_budget_for_next_turn(self):
        session = str(uuid.uuid4())
        self.engine.chat('microSD 64GB dưới 30 USD', session)
        self.assertEqual(self.engine.chat('dưới 5 USD', session)['type'], 'empty')
        again = self.engine.chat('chỉ lấy Amazon', session)
        self.assertEqual(again['type'], 'empty')

    def test_sourced_price_import_atomic_and_filterable(self):
        from import_product_prices import import_prices
        path = Path(self.temp.name) / 'prices.csv'
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['product_id','price','currency','source_url','recorded_at'])
            writer.writeheader()
            writer.writerow(dict(product_id='a',price=12,currency='USD',source_url='https://example.com/test-price',recorded_at='2026-10-03T12:00:00+07:00'))
        import_prices(self.engine, path, check_only=True)
        self.assertEqual(self.engine.edits(), [])
        import_prices(self.engine, path)
        self.assertEqual(server.search_products('microSD 64GB dưới 13 USD')[0]['product_id'], 'a')
        with self.assertRaises(ValueError):
            import_prices(self.engine, path)
        self.assertEqual(len(self.engine.edits()), 2)

    def test_edit_preview_rollback_and_persistence(self):
        edit = self.edit(30)
        self.assertEqual(self.engine.preview(edit['edit_id'])['after'], 30)
        self.engine.set_active(edit['edit_id'], True)
        self.assertEqual(server.search_products('microSD 64GB dưới 20 USD'), [])
        reopened = AgentExtensions(server, self.engine.path)
        self.assertTrue(reopened.edits()[0]['active'])
        reopened.set_active(edit['edit_id'], False)
        self.assertEqual(server.search_products('microSD 64GB dưới 20 USD')[0]['price'], '16.99')

    def test_conflict_and_invalid_values(self):
        first, second = self.edit(), self.edit(14)
        self.engine.set_active(first['edit_id'], True)
        with self.assertRaises(ValueError):
            self.engine.set_active(second['edit_id'], True)
        with self.assertRaises(ValueError):
            self.edit(float('nan'))

    def test_sessions_and_multiple_tools(self):
        session = str(uuid.uuid4())
        answer = self.engine.chat('microSD 64GB dưới 20 USD và so sánh đánh giá', session)
        self.assertEqual(answer['type'], 'comparison')
        self.assertIn('compare_products', answer['tools'])
        self.assertIn('review:r1', answer['products'][0]['citations'])
        isolated = self.engine.chat('review sản phẩm số 1', str(uuid.uuid4()))
        self.assertEqual(isolated['type'], 'clarification')
        reopened = AgentExtensions(server, self.engine.path)
        self.assertEqual(reopened.chat('review sản phẩm số 1', session)['products'][0]['product_id'], 'a')
        self.assertEqual(len(reopened.history(session)), 2)

    def test_tool_failure_is_logged(self):
        with patch.object(server, 'find_reviews', side_effect=OSError('unavailable')):
            answer = self.engine.chat('microSD 64GB dưới 20 USD', str(uuid.uuid4()))
        self.assertEqual(answer['type'], 'recommendation')
        self.assertTrue(answer['products'])
        self.assertEqual(answer['fallback_reason'], 'review_tool_failed')
        self.assertTrue(any(t['status'] == 'error' for t in answer['tool_trace']))

    def test_http_access_and_session_history(self):
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.AgentHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        client = http.client.HTTPConnection('127.0.0.1', httpd.server_port)
        try:
            client.request('GET', '/agent_state.sqlite3')
            response = client.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            client.request('GET', '/api/admin/edits')
            response = client.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            session = str(uuid.uuid4())
            client.request('POST', '/api/chat', json.dumps({'message': 'microSD 64GB dưới 20 USD', 'session_id': session}), {'Content-Type': 'application/json'})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            answer = json.loads(response.read())
            self.assertEqual(answer['session_id'], session)
            client.request('GET', '/api/history?session_id=' + session)
            self.assertEqual(len(json.loads(client.getresponse().read())['items']), 1)
        finally:
            client.close()
            httpd.shutdown()
            httpd.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
