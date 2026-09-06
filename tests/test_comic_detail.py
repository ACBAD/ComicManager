"""Comic detail reads use the injected temporary database, never the workspace database."""

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
STORED_UPDATED_AT = '2026-09-06T01:02:03.456Z'


class ComicDetailTests(unittest.TestCase):
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
        # 不运行 DMB lifespan；使用实际的每请求数据库连接依赖。
        self.client = TestClient(app_module.app, cookies={'auth_token': 'test-reader'})
        self.addCleanup(self.client.close)
        generic = self.manager.tag_manager.create_generic_tag('眼镜', TagGroup.Tag)
        self.specific_tags = [
            SpecificTagHitomi(origin_name='glasses', group='tags', tag_sex=sex,
                              url=f'/tag/glasses-{sex}.html')
            for sex in ('female', 'male')
        ]
        for tag in self.specific_tags:
            self.manager.tag_manager.create_specific_tag(tag, generic)
        self.manager.add_comic(Comic(
            id=7, title='本地旧标题', authors=['Alice', '乙'], comic_tags=self.specific_tags,
            series_name='系列', volume_number=2,
        ))
        self.manager.add_comic(Comic(id=91, title='空关联', authors=[], comic_tags=[]))
        with self.conn:
            self.conn.execute('UPDATE comics SET updated_at = ?', (STORED_UPDATED_AT,))

    def test_returns_raw_persisted_comic_by_id_without_writes_or_dmb_reads(self):
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        with patch.object(app_module.DMBClient, 'fetch_comic_info') as fetch_source:
            response = self.client.get('/api/comics/7')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.json(), {
            'id': 7, 'title': '本地旧标题', 'authors': ['Alice', '乙'],
            'comic_tags': [tag.model_dump(mode='json') for tag in self.specific_tags],
            'series_name': '系列', 'volume_number': 2, 'updated_at': STORED_UPDATED_AT,
        })
        fetch_source.assert_not_called()
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).digest(), before)

    def test_empty_relations_and_nullable_fields_are_preserved(self):
        response = self.client.get('/api/comics/91')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'id': 91, 'title': '空关联', 'authors': [], 'comic_tags': [],
            'series_name': None, 'volume_number': None, 'updated_at': STORED_UPDATED_AT,
        })

    def test_missing_comic_returns_standard_404_without_source_fallback(self):
        with patch.object(app_module.DMBClient, 'fetch_comic_info') as fetch_source:
            for comic_id in (0, 8, 2**63 - 1):
                with self.subTest(comic_id=comic_id):
                    response = self.client.get(f'/api/comics/{comic_id}')
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json(), {'error': {
                        'code': 'COMIC_NOT_FOUND', 'message': '漫画未入库',
                        'details': {'comic_id': comic_id},
                    }})
        fetch_source.assert_not_called()

    def test_invalid_ids_return_standard_validation_errors(self):
        for comic_id in ('invalid', '1.5', '-1', str(2**63)):
            with self.subTest(comic_id=comic_id):
                response = self.client.get(f'/api/comics/{comic_id}')
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()['error']['code'], 'INVALID_REQUEST')

    def test_requires_login_but_no_creation_permission(self):
        self.assertEqual(self.client.get('/api/comics/7').status_code, 200)
        self.client.cookies.clear()
        for headers in ({}, {'Cookie': 'auth_token=unknown'}):
            with self.subTest(headers=headers):
                response = self.client.get('/api/comics/7', headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()['error']['code'], 'AUTHENTICATION_REQUIRED')

    def test_detail_uses_one_snapshot_during_concurrent_override(self):
        self.conn.execute('PRAGMA journal_mode = WAL')
        before = self.manager.get_comic(7)
        with closing(sqlite3.connect(self.db_path)) as writer:
            writer.execute('PRAGMA foreign_keys = ON')
            original_loader = self.manager._comic_from_row

            def load_after_override(row):
                ComicManager(writer).add_comic(Comic(
                    id=7, title='并发新标题', authors=['新作者'], comic_tags=[],
                ), allow_override=True)
                return original_loader(row)

            with patch.object(self.manager, '_comic_from_row', side_effect=load_after_override):
                result = self.manager.get_comic(7)
            self.assertEqual(result, before)
            self.assertFalse(self.conn.in_transaction)
            self.assertEqual(self.manager.get_comic(7).title, '并发新标题')

    def test_detail_does_not_commit_callers_transaction(self):
        self.conn.execute('INSERT INTO comics (id, title) VALUES (1, ?)', ('尚未提交',))
        self.assertEqual(self.manager.get_comic(1).title, '尚未提交')
        self.assertIsNone(self.manager.get_comic(2))
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertIsNone(self.manager.get_comic(1))


if __name__ == '__main__':
    unittest.main()
