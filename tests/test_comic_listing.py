"""Run with: python -m unittest discover -s tests -p 'test_comic_listing.py' -v"""

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
from tags import SpecificTagHitomi, TagGroup
import utils


SCHEMA = (Path(__file__).resolve().parents[1] / 'comic.sql').read_text()
STORED_UPDATED_AT = '2026-09-05T15:30:00.123Z'


class ComicListingTests(unittest.TestCase):
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
        # 不运行 DMB lifespan；请求使用实际数据库依赖，每个请求自行连接临时库。
        self.client = TestClient(app_module.app, cookies={'auth_token': 'test-reader'})
        self.addCleanup(self.client.close)

    def seed_comics(self):
        generic = self.manager.tag_manager.create_generic_tag('眼镜', TagGroup.Tag)
        self.specific_tags = [
            SpecificTagHitomi(
                origin_name='glasses', group='tags', tag_sex=sex,
                url=f'/tag/glasses-{sex}.html',
            )
            for sex in ('female', 'male')
        ]
        for tag in self.specific_tags:
            self.manager.tag_manager.create_specific_tag(tag, generic)
        self.manager.add_comic(Comic(
            id=7, title='本地漫画', authors=['Alice', '乙'], comic_tags=self.specific_tags,
            series_name='系列', volume_number=2,
        ))
        self.manager.add_comic(Comic(id=91, title='末项', authors=[], comic_tags=[]))
        self.manager.add_comic(Comic(id=2, title='首项', authors=[], comic_tags=[]))
        with self.conn:
            self.conn.execute('UPDATE comics SET updated_at = ?', (STORED_UPDATED_AT,))

    def test_empty_library(self):
        response = self.client.get('/api/comics')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertEqual(response.headers['X-Total-Count'], '0')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_returns_raw_stored_comic_without_writes_or_dmb_reads(self):
        self.seed_comics()
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        with patch.object(app_module.DMBClient, 'fetch_comic_info') as fetch_source:
            response = self.client.get('/api/comics?limit=1&offset=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Total-Count'], '3')
        self.assertEqual(response.json(), [{
            'id': 7,
            'title': '本地漫画',
            'authors': ['Alice', '乙'],
            'comic_tags': [
                {
                    'site': 'hitomi', 'origin_name': 'glasses', 'group': 'tags',
                    'tag_sex': sex, 'url': f'/tag/glasses-{sex}.html',
                }
                for sex in ('female', 'male')
            ],
            'series_name': '系列',
            'volume_number': 2,
            'updated_at': STORED_UPDATED_AT,
        }])
        fetch_source.assert_not_called()
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).digest(), before)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_pagination_uses_id_order_and_retains_total_on_empty_page(self):
        self.seed_comics()
        for offset, expected_ids in ((0, [2, 7]), (2, [91]), (3, []), (99, [])):
            with self.subTest(offset=offset):
                response = self.client.get('/api/comics', params={'limit': 2, 'offset': offset})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([comic['id'] for comic in response.json()], expected_ids)
                self.assertEqual(response.headers['X-Total-Count'], '3')
        first = self.client.get('/api/comics?limit=1').json()[0]
        self.assertEqual(first['authors'], [])
        self.assertEqual(first['comic_tags'], [])
        self.assertIsNone(first['series_name'])
        self.assertIsNone(first['volume_number'])

    def test_default_and_maximum_page_sizes(self):
        with self.conn:
            self.conn.executemany(
                'INSERT INTO comics (id, title) VALUES (?, ?)',
                [(number, f'漫画 {number}') for number in range(1, 104)],
            )
        for params, expected_ids in (
            ({}, list(range(1, 51))),
            ({'limit': 100}, list(range(1, 101))),
            ({'limit': 100, 'offset': 100}, [101, 102, 103]),
        ):
            with self.subTest(params=params):
                response = self.client.get('/api/comics', params=params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([comic['id'] for comic in response.json()], expected_ids)
                self.assertEqual(response.headers['X-Total-Count'], '103')

    def test_invalid_pagination_returns_standard_validation_error(self):
        for params in (
            {'limit': 0}, {'limit': -1}, {'limit': 101}, {'limit': 'invalid'},
            {'limit': '1.5'}, {'offset': -1}, {'offset': 'invalid'}, {'offset': '0.5'},
        ):
            with self.subTest(params=params):
                response = self.client.get('/api/comics', params=params)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()['error']['code'], 'INVALID_REQUEST')

    def test_requires_login_but_no_creation_permission(self):
        self.assertEqual(self.client.get('/api/comics').status_code, 200)
        self.client.cookies.clear()
        for headers in ({}, {'Cookie': 'auth_token=unknown'}):
            with self.subTest(headers=headers):
                response = self.client.get('/api/comics', headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()['error']['code'], 'AUTHENTICATION_REQUIRED')

    def test_concurrent_requests_read_independent_connections(self):
        self.seed_comics()
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(
                lambda _: self.client.get('/api/comics?limit=2'), range(12),
            ))
        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertEqual([comic['id'] for comic in response.json()], [2, 7])
            self.assertEqual(response.headers['X-Total-Count'], '3')

    def test_list_uses_one_snapshot_during_concurrent_override(self):
        self.seed_comics()
        self.conn.execute('PRAGMA journal_mode = WAL')
        with closing(sqlite3.connect(self.db_path)) as writer:
            writer.execute('PRAGMA foreign_keys = ON')
            original_loader = self.manager._comic_from_row

            def load_after_override(row):
                if row[0] == 7:
                    ComicManager(writer).add_comic(Comic(
                        id=7, title='已被并发更新', authors=['新作者'], comic_tags=[],
                    ), allow_override=True)
                return original_loader(row)

            with patch.object(self.manager, '_comic_from_row', side_effect=load_after_override):
                result, total = self.manager.list_comics(limit=1, offset=1)
            self.assertEqual(total, 3)
            self.assertEqual(result[0].title, '本地漫画')
            self.assertEqual(result[0].authors, ['Alice', '乙'])
            self.assertEqual(result[0].comic_tags, self.specific_tags)
            self.assertEqual(result[0].updated_at, STORED_UPDATED_AT)
            self.assertFalse(self.conn.in_transaction)
            self.assertEqual(self.manager.get_comic(7).title, '已被并发更新')

    def test_listing_does_not_commit_callers_transaction(self):
        self.conn.execute('INSERT INTO comics (id, title) VALUES (1, ?)', ('尚未提交',))
        result, total = self.manager.list_comics()
        self.assertEqual([comic.id for comic in result], [1])
        self.assertEqual(total, 1)
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertIsNone(self.manager.get_comic(1))


if __name__ == '__main__':
    unittest.main()
