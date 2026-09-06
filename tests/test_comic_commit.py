"""Commit always uses fresh DMB data; all writes are isolated in a temporary database."""

from contextlib import closing
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import httpx

import app as app_module
from comics import ComicManager
from tags import SpecificTagHitomi, TagGroup
import utils


SCHEMA = (Path(__file__).resolve().parents[1] / 'comic.sql').read_text()


class ComicCommitTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.db_path = Path(directory) / 'comics.db'
        self.conn = self.enterContext(closing(sqlite3.connect(self.db_path)))
        self.conn.executescript(SCHEMA)
        self.manager = ComicManager(self.conn)
        self.enterContext(patch.object(app_module, 'COMIC_DB_PATH', self.db_path))
        self.enterContext(patch.object(utils, 'auth_config', utils.UserConfig(users={
            'test-writer': utils.UserInfo(username='writer', abilities=[utils.UserAbilities.CREATE_DOCUMENT]),
            'test-reader': utils.UserInfo(username='reader', abilities=[]),
        })))
        self.document = self.source_document('first', ['glasses'])
        self.source = SimpleNamespace(fetch_comic_info=Mock(side_effect=lambda _: deepcopy(self.document)))
        self.enterContext(patch.dict(app_module.app.dependency_overrides, {
            app_module.get_dmb_client: lambda: self.source,
        }))
        self.client = TestClient(app_module.app, cookies={'auth_token': 'test-writer'})
        self.addCleanup(self.client.close)

    @staticmethod
    def source_document(title, names):
        return {
            'document_id': 7, 'source': 'hitomi', 'source_document_id': 'source-7',
            'source_meta': {
                'title': title,
                'artists': [{'artist': f'{title} author'}],
                'tags': [{'tag': name, 'url': f'/tag/{name}.html'} for name in names],
            },
        }

    def seed_mapping(self, name):
        generic = self.manager.tag_manager.create_generic_tag(name, TagGroup.Tag)
        self.manager.tag_manager.create_specific_tag(
            SpecificTagHitomi(origin_name=name, group='tags', url=f'/tag/{name}.html'), generic,
        )

    def test_preview_is_raw_read_only_comic_without_version_header(self):
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        response = self.client.get('/api/comics/7/preview')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertNotIn('ETag', response.headers)
        self.assertEqual(set(response.json()), {
            'id', 'title', 'authors', 'comic_tags', 'series_name', 'volume_number', 'updated_at',
        })
        self.assertEqual(response.json()['title'], 'first')
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).digest(), before)

    def test_commit_without_preview_or_body_fetches_dmb_and_saves(self):
        self.seed_mapping('glasses')
        response = self.client.post('/api/comics/7/commit')
        self.assertEqual(response.status_code, 201)
        self.source.fetch_comic_info.assert_called_once_with('7')
        self.assertEqual(response.json()['title'], 'first')
        stored = self.manager.get_comic(7)
        self.assertEqual(stored.title, 'first')
        self.assertEqual(stored.authors, ['first author'])
        self.assertEqual([tag.origin_name for tag in stored.comic_tags], ['glasses'])
        self.assertIsNotNone(stored.updated_at)

    def test_commit_uses_latest_title_authors_and_mapped_tags_after_preview(self):
        self.seed_mapping('glasses')
        self.seed_mapping('hat')
        preview = self.client.get('/api/comics/7/preview')
        self.assertEqual(preview.json()['title'], 'first')
        self.document = self.source_document('latest', ['hat'])
        response = self.client.post('/api/comics/7/commit')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.source.fetch_comic_info.call_count, 2)
        self.assertEqual(response.json()['title'], 'latest')
        stored = self.manager.get_comic(7)
        self.assertEqual(stored.title, 'latest')
        self.assertEqual(stored.authors, ['latest author'])
        self.assertEqual([tag.origin_name for tag in stored.comic_tags], ['hat'])

    def test_missing_mapping_in_latest_dmb_data_still_blocks_all_comic_writes(self):
        self.seed_mapping('glasses')
        self.client.get('/api/comics/7/preview')
        self.document = self.source_document('latest', ['glasses', 'hat'])
        response = self.client.post('/api/comics/7/commit')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'UNMAPPED_SPECIFIC_TAGS')
        self.assertEqual(response.json()['error']['details']['specific_tags'][0]['origin_name'], 'hat')
        for table in ['comics', 'comic_tags', 'comic_authors']:
            self.assertEqual(self.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
        self.seed_mapping('hat')
        self.assertEqual(self.client.post('/api/comics/7/commit').status_code, 201)

    def test_client_body_cannot_supply_or_override_comic_data(self):
        self.seed_mapping('glasses')
        response = self.client.post('/api/comics/7/commit', json={
            'title': 'client title', 'authors': ['client'], 'comic_tags': [],
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['title'], 'first')
        self.assertEqual(len(self.manager.get_comic(7).comic_tags), 1)

    def test_existing_comic_requires_explicit_override(self):
        self.seed_mapping('glasses')
        self.seed_mapping('hat')
        self.assertEqual(self.client.post('/api/comics/7/commit').status_code, 201)
        self.document = self.source_document('latest', ['hat'])
        response = self.client.post('/api/comics/7/commit')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'COMIC_ALREADY_EXISTS')
        self.assertEqual(self.manager.get_comic(7).title, 'first')
        self.assertEqual(self.client.post('/api/comics/7/commit?allow_override=true').status_code, 201)
        stored = self.manager.get_comic(7)
        self.assertEqual(stored.title, 'latest')
        self.assertEqual(stored.authors, ['latest author'])
        self.assertEqual([tag.origin_name for tag in stored.comic_tags], ['hat'])
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_source_failure_or_invalid_source_cannot_write_comic(self):
        self.source.fetch_comic_info.side_effect = httpx.ReadTimeout('timeout')
        response = self.client.post('/api/comics/7/commit')
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()['error']['code'], 'SOURCE_SERVICE_TIMEOUT')
        self.source.fetch_comic_info.side_effect = lambda _: {**self.document, 'document_id': 8}
        response = self.client.post('/api/comics/7/commit')
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.manager.get_comic(7))

    def test_commit_still_requires_creation_permission(self):
        self.client.cookies.set('auth_token', 'test-reader')
        response = self.client.post('/api/comics/7/commit')
        self.assertEqual(response.status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/comics/7/commit').status_code, 401)
        self.source.fetch_comic_info.assert_not_called()

    def test_commit_openapi_has_no_request_body(self):
        operation = app_module.app.openapi()['paths']['/api/comics/{comic_id}/commit']['post']
        self.assertNotIn('requestBody', operation)


if __name__ == '__main__':
    unittest.main()
