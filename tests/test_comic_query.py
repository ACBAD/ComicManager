"""Run with: python -m unittest discover -s tests -p 'test_comic_*.py' -v"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from comics import Comic, ComicManager
from tags import SpecificTagHitomi, SpecificTagNHentai, TagGroup
import utils


SCHEMA = (Path(__file__).resolve().parents[1] / 'comic.sql').read_text()
STORED_UPDATED_AT = '2026-09-06T01:02:03.456Z'


class ComicQueryTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.db_path = Path(directory) / 'comics.db'
        self.conn = self.enterContext(closing(sqlite3.connect(self.db_path)))
        self.conn.executescript(SCHEMA)
        self.manager = ComicManager(self.conn)
        self.enterContext(patch.object(app_module, 'COMIC_DB_PATH', self.db_path))
        self.enterContext(patch.object(utils, 'auth_config', utils.UserConfig(users={
            'test-reader': utils.UserInfo(username='reader', abilities=[]),
        })))
        # 不运行 DMB lifespan；使用实际的每请求连接依赖，所有数据都在临时库中。
        self.client = TestClient(app_module.app, cookies={'auth_token': 'test-reader'})
        self.addCleanup(self.client.close)
        manager = self.manager.tag_manager
        glasses = manager.create_generic_tag('眼镜', TagGroup.Tag)
        cat = manager.create_generic_tag('猫', TagGroup.Tag)
        namesake = manager.create_generic_tag('眼镜', TagGroup.Character)
        unused = manager.create_generic_tag('未使用', TagGroup.Tag)
        self.tag_ids = {
            key: manager.query_generic_tag_ids(tag.tag_group, tag.name)[0][0]
            for key, tag in (('glasses', glasses), ('cat', cat), ('namesake', namesake), ('unused', unused))
        }
        female = SpecificTagHitomi(origin_name='glasses', group='tags', tag_sex='female')
        male = SpecificTagHitomi(origin_name='glasses', group='tags', tag_sex='male')
        cross_site = SpecificTagNHentai(origin_name='glasses', group=TagGroup.Tag)
        cat_tag = SpecificTagHitomi(origin_name='cat', group='tags')
        namesake_tag = SpecificTagHitomi(origin_name='眼镜', group='characters')
        for specific, generic in (
            (female, glasses), (male, glasses), (cross_site, glasses),
            (cat_tag, cat), (namesake_tag, namesake),
        ):
            manager.create_specific_tag(specific, generic)
        self.first_tags = [female, male, cat_tag]
        for comic in (
            Comic(id=91, title='100%_完成\\版', authors=['A%_\\uthor'], comic_tags=[]),
            Comic(id=7, title='月光 Moon', authors=['Alice', 'Alicia', '乙'],
                  comic_tags=self.first_tags, series_name='月光', volume_number=2),
            Comic(id=42, title='moon', authors=['alice'], comic_tags=[namesake_tag]),
            Comic(id=11, title='月光 Moon II', authors=['Alice'], comic_tags=[cross_site]),
            Comic(id=23, title='Moonlight', authors=['Alicia'], comic_tags=[cat_tag]),
            Comic(id=55, title='別册 月光', authors=['乙'], comic_tags=[]),
            Comic(id=99, title='  留白  ', authors=[' Alice '], comic_tags=[]),
            Comic(id=101, title='Alice', authors=[], comic_tags=[]),
        ):
            self.manager.add_comic(comic)
        with self.conn:
            self.conn.execute('UPDATE comics SET updated_at = ?', (STORED_UPDATED_AT,))

    def assert_query(self, payload, expected_ids, total=None):
        response = self.client.post('/api/comics/query', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([comic['id'] for comic in response.json()], expected_ids)
        self.assertEqual(response.headers['X-Total-Count'], str(len(expected_ids) if total is None else total))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        return response

    def test_empty_filters_match_listing_and_empty_library(self):
        listing = self.client.get('/api/comics')
        for payload in ({}, {'generic_tag_ids': []}, {'generic_tag_ids': [], 'tag_match': 'any'},
                        {'title': None, 'author_name': None}):
            with self.subTest(payload=payload):
                response = self.assert_query(payload, [7, 11, 23, 42, 55, 91, 99, 101])
                self.assertEqual(response.json(), listing.json())
        with self.conn:
            self.conn.execute('DELETE FROM comics')
        self.assert_query({}, [])
        self.assert_query({'order': 'DESC'}, [])

    def test_id_order_applies_before_pagination_and_listing_stays_ascending(self):
        ascending = [7, 11, 23, 42, 55, 91, 99, 101]
        self.assert_query({'order': 'ASC'}, ascending)
        descending = list(reversed(ascending))
        self.assert_query({'order': 'DESC'}, descending)
        for offset in (0, 3, 6, 9):
            with self.subTest(offset=offset):
                self.assert_query({'order': 'DESC', 'limit': 3, 'offset': offset},
                                  descending[offset:offset + 3], total=8)
        listing = self.client.get('/api/comics?limit=3&offset=3')
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual([comic['id'] for comic in listing.json()], ascending[3:6])
        self.assertEqual(listing.headers['X-Total-Count'], '8')

    def test_title_matches_are_literal_and_case_sensitive(self):
        for payload, expected in (
            ({'title': '月光'}, [7, 11, 55]),
            ({'title': '月光', 'title_match': 'prefix'}, [7, 11]),
            ({'title': '月光 Moon', 'title_match': 'exact'}, [7]),
            ({'title': 'Moon'}, [7, 11, 23]),
            ({'title': 'moon'}, [42]),
            ({'title': 'missing'}, []),
            ({'title': '  留白  ', 'title_match': 'exact'}, [99]),
            ({'title': '留白', 'title_match': 'exact'}, []),
            ({'title': '%_'}, [91]),
            ({'title': '\\'}, [91]),
            ({'title': '100%_', 'title_match': 'prefix'}, [91]),
            ({'title': '100%_完成\\版', 'title_match': 'exact'}, [91]),
        ):
            with self.subTest(payload=payload):
                self.assert_query(payload, expected)

    def test_author_matches_use_authors_not_titles(self):
        for payload, expected in (
            ({'author_name': 'Alice'}, [7, 11]),
            ({'author_name': 'Ali', 'author_match': 'prefix'}, [7, 11, 23]),
            ({'author_name': 'lic', 'author_match': 'contains'}, [7, 11, 23, 42, 99]),
            ({'author_name': 'alice'}, [42]),
            ({'author_name': '乙'}, [7, 55]),
            ({'author_name': ' Alice '}, [99]),
            ({'author_name': 'missing'}, []),
            ({'author_name': 'A%_\\uthor'}, [91]),
            ({'author_name': 'A%_', 'author_match': 'prefix'}, [91]),
            ({'author_name': '%_', 'author_match': 'contains'}, [91]),
        ):
            with self.subTest(payload=payload):
                self.assert_query(payload, expected)

    def test_generic_tag_matches_all_source_variants_without_duplicates(self):
        for name, expected in (('glasses', [7, 11]), ('cat', [7, 23]), ('namesake', [42]), ('unused', [])):
            with self.subTest(name=name):
                self.assert_query({'generic_tag_ids': [self.tag_ids[name]]}, expected)

    def test_multiple_tags_all_any_and_repeated_ids(self):
        glasses, cat = self.tag_ids['glasses'], self.tag_ids['cat']
        self.assert_query({'generic_tag_ids': [glasses, cat]}, [7])
        self.assert_query({'generic_tag_ids': [glasses, cat, glasses]}, [7])
        self.assert_query({'generic_tag_ids': [glasses, cat, glasses], 'tag_match': 'any'}, [7, 11, 23])

    def test_unknown_generic_tag_is_an_unmatched_condition(self):
        glasses = self.tag_ids['glasses']
        self.assert_query({'generic_tag_ids': [2**63 - 1]}, [])
        self.assert_query({'generic_tag_ids': [glasses, 999999]}, [])
        self.assert_query({'generic_tag_ids': [glasses, 999999], 'tag_match': 'any'}, [7, 11])

    def test_all_filter_categories_are_combined_with_and(self):
        for payload, expected in (
            ({'title': 'Moon', 'author_name': 'Alice'}, [7, 11]),
            ({'title': 'Moon', 'generic_tag_ids': [self.tag_ids['cat']]}, [7, 23]),
            ({'author_name': '乙', 'generic_tag_ids': [self.tag_ids['glasses']]}, [7]),
            ({'title': '月光', 'author_name': 'Alice', 'generic_tag_ids': [self.tag_ids['cat']]}, [7]),
            ({'title': 'Moon', 'author_name': 'alice', 'generic_tag_ids': [self.tag_ids['glasses']]}, []),
            ({'title': 'Moon', 'author_name': 'Alice', 'generic_tag_ids': list(self.tag_ids.values()),
              'tag_match': 'any'}, [7, 11]),
        ):
            with self.subTest(payload=payload):
                self.assert_query(payload, expected)

    def test_filter_pagination_counts_comics_not_matching_relations(self):
        filters = {'author_name': 'Ali', 'author_match': 'prefix',
                   'generic_tag_ids': [self.tag_ids['glasses'], self.tag_ids['cat']], 'tag_match': 'any'}
        for offset, expected in ((0, [7]), (1, [11]), (2, [23]), (3, []), (99, []), (2**63 - 1, [])):
            with self.subTest(offset=offset):
                self.assert_query({**filters, 'limit': 1, 'offset': offset}, expected, total=3)
        for offset, expected in ((0, [23]), (1, [11]), (2, [7]), (3, [])):
            with self.subTest(order='DESC', offset=offset):
                self.assert_query({**filters, 'title': 'Moon', 'order': 'DESC',
                                   'limit': 1, 'offset': offset}, expected, total=3)

    def test_default_and_maximum_page_sizes(self):
        with self.conn:
            self.conn.executemany('INSERT INTO comics (id, title) VALUES (?, ?)',
                                  [(number, '分页测试') for number in range(201, 304)])
        self.assert_query({'title': '分页测试'}, list(range(201, 251)), total=103)
        self.assert_query({'title': '分页测试', 'limit': 100}, list(range(201, 301)), total=103)
        self.assert_query({'title': '分页测试', 'limit': 100, 'offset': 100}, [301, 302, 303], total=103)
        self.assert_query({'title': '分页测试', 'order': 'DESC', 'limit': 100},
                          list(range(303, 203, -1)), total=103)
        self.assert_query({'title': '分页测试', 'order': 'DESC', 'limit': 100, 'offset': 100},
                          [203, 202, 201], total=103)

    def test_returns_complete_raw_model_without_dmb_or_database_writes(self):
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        with patch.object(app_module.DMBClient, 'fetch_comic_info') as fetch_source:
            response = self.assert_query({'title': '月光', 'author_name': 'Alice',
                                          'generic_tag_ids': [self.tag_ids['cat']], 'order': 'DESC'}, [7])
        self.assertEqual(response.json(), [{
            'id': 7, 'title': '月光 Moon', 'authors': ['Alice', 'Alicia', '乙'],
            'comic_tags': [tag.model_dump(mode='json') for tag in self.first_tags],
            'series_name': '月光', 'volume_number': 2, 'updated_at': STORED_UPDATED_AT,
        }])
        fetch_source.assert_not_called()
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).digest(), before)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_search_text_cannot_change_sql(self):
        for field in ('title', 'author_name'):
            for match in ('exact', 'prefix', 'contains'):
                with self.subTest(field=field, match=match):
                    match_field = 'title_match' if field == 'title' else 'author_match'
                    self.assert_query({field: "' OR 1=1 --", match_field: match}, [])
        self.assert_query({'author_name': 'Alice'}, [7, 11])

    def test_invalid_request_returns_standard_validation_error(self):
        for payload in (
            [], {'extra': True}, {'generic_tag_ids': [0]}, {'generic_tag_ids': [-1]},
            {'generic_tag_ids': [2**63]}, {'generic_tag_ids': ['invalid']}, {'generic_tag_ids': [1.5]},
            {'generic_tag_ids': [1] * 101}, {'generic_tag_ids': '1'}, {'generic_tag_ids': None},
            {'tag_match': 'none'}, {'title_match': 'regex'}, {'author_match': 'regex'},
            {'order': 'desc'}, {'order': ''}, {'order': None}, {'order': 1}, {'order': ['DESC']},
            {'order': 'DESC; DROP TABLE comics; --'},
            {'title': ''}, {'title': '  \n'}, {'title': 123}, {'author_name': ''}, {'author_name': '\t'},
            {'limit': 0}, {'limit': 101}, {'limit': 1.5}, {'offset': -1}, {'offset': 0.5}, {'offset': 2**63},
        ):
            with self.subTest(payload=payload):
                response = self.client.post('/api/comics/query', json=payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()['error']['code'], 'INVALID_REQUEST')
        response = self.client.post('/api/comics/query')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'INVALID_REQUEST')

    def test_manager_rejects_invalid_order_before_running_sql(self):
        for order in ('desc', '', None, 'DESC; DROP TABLE comics; --'):
            with self.subTest(order=order):
                with self.assertRaises(ValueError):
                    self.manager.query_comics(order=order)
        self.assert_query({'order': 'DESC', 'limit': 1}, [101], total=8)

    def test_requires_login_but_no_creation_permission(self):
        self.assert_query({'author_name': 'Alice'}, [7, 11])
        self.client.cookies.clear()
        for headers in ({}, {'Cookie': 'auth_token=unknown'}):
            with self.subTest(headers=headers):
                response = self.client.post('/api/comics/query', json={}, headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()['error']['code'], 'AUTHENTICATION_REQUIRED')

    def test_concurrent_requests_keep_filters_and_connections_independent(self):
        cases = [({'title': 'Moon'}, [7, 11, 23]), ({'author_name': '乙'}, [7, 55]),
                 ({'title': 'Moon', 'order': 'DESC'}, [23, 11, 7]),
                 ({'generic_tag_ids': [self.tag_ids['cat']]}, [7, 23]), ({'title': 'missing'}, [])]
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(
                lambda case: self.client.post('/api/comics/query', json=case[0]), cases * 3,
            ))
        for response, (_, expected) in zip(responses, cases * 3):
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([comic['id'] for comic in response.json()], expected)
            self.assertEqual(response.headers['X-Total-Count'], str(len(expected)))

    def test_count_rows_and_relations_share_snapshot_when_filter_membership_changes(self):
        self.conn.execute('PRAGMA journal_mode = WAL')
        with closing(sqlite3.connect(self.db_path)) as writer:
            writer.execute('PRAGMA foreign_keys = ON')
            writes = []

            def update_between_count_and_rows(sql):
                if sql.startswith('SELECT c.id, c.title') and not writes:
                    ComicManager(writer).add_comic(
                        Comic(id=7, title='已更新', authors=['其他作者'], comic_tags=[]), allow_override=True,
                    )
                    writes.append(7)

            self.conn.set_trace_callback(update_between_count_and_rows)
            try:
                result, total = self.manager.query_comics(
                    author_name='Alice', title='月光', generic_tag_ids=[self.tag_ids['glasses']],
                )
            finally:
                self.conn.set_trace_callback(None)
            self.assertEqual(writes, [7])
            self.assertEqual(total, 2)
            self.assertEqual([comic.id for comic in result], [7, 11])
            self.assertEqual(result[0].title, '月光 Moon')
            self.assertEqual(result[0].authors, ['Alice', 'Alicia', '乙'])
            self.assertEqual(result[0].comic_tags, self.first_tags)
            self.assertEqual(result[0].updated_at, STORED_UPDATED_AT)
            self.assertFalse(self.conn.in_transaction)
        self.assert_query({'author_name': 'Alice'}, [11])


if __name__ == '__main__':
    unittest.main()
