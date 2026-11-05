import json
import http.client
import http.server
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from eryoutoolbox.character_library import CharacterLibrary, OFFICIAL, validate, decode, fetch_json
from eryoutoolbox.character_aliases import alias_groups
from eryoutoolbox.database import initialize_database
from eryoutoolbox.ui_queries import query_mods


class CharacterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = CharacterLibrary(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, **body):
        preview = self.library.command(body)
        self.library.command({'action': 'confirm', 'token': preview['token']})
        return preview

    def test_six_games_official_and_traditional(self):
        self.assertEqual(len(self.library.effective()), 6)
        for term in ['锁暝', '鎖暝', 'Suoming', 'suo ming']:
            self.assertEqual(alias_groups(term, 20357, self.library.effective())[0][0], 20357)
            self.assertEqual(alias_groups(term, 8552, self.library.effective()), [])

    def test_preview_is_readonly_and_confirm_persists(self):
        p = self.library.command({'action': 'edit', 'game': 8552, 'name': '测试', 'aliases': ['Test']})
        self.assertFalse(self.library.path.exists())
        self.assertEqual(len(p['changes']), 1)
        self.library.command({'action': 'confirm', 'token': p['token']})
        self.assertEqual(CharacterLibrary(self.root).effective()[8552]['测试'], ['Test'])
        with self.assertRaises(ValueError):
            self.library.command({'action': 'confirm', 'token': p['token']})

    def test_priority_import_merge_delete_and_reset(self):
        self.commit(action='import', document={'format': 1, 'games': {'8552': {'胡桃': ['Imported']}}})
        self.commit(action='edit', game=8552, name='胡桃', aliases=['Personal'])
        self.commit(action='import', document={'format': 1, 'games': {'8552': {'胡桃': ['Later']}}})
        self.assertEqual(self.library.effective()[8552]['胡桃'], ['Personal'])
        self.commit(action='edit', game=8552, name='胡桃', aliases=None)
        self.assertNotIn('胡桃', self.library.effective()[8552])
        self.commit(action='reset')
        self.assertIn('Hu Tao', self.library.effective()[8552]['胡桃'])

    def test_official_cannot_be_overwritten_by_typo(self):
        for name, aliases in [('锁冥', ['Suoming']), ('锁暝', ['Wrong']), ('锁暝', None)]:
            with self.assertRaises(ValueError):
                self.library.command({'action': 'edit', 'game': 20357, 'name': name, 'aliases': aliases})
        self.commit(action='edit', game=20357, name='锁暝', aliases=OFFICIAL['锁暝'] + ['锁暝角色'])

    def test_backup_restore_and_failed_replace(self):
        self.commit(action='edit', game=8552, name='测试', aliases=['One'])
        self.commit(action='edit', game=8552, name='测试', aliases=['Two'])
        backups = self.library.status()['backups']
        chosen = next(b for b in backups if 'One' in (self.library.directory / b).read_text())
        self.commit(action='restore', backup=chosen)
        self.assertEqual(self.library.effective()[8552]['测试'], ['One'])
        p = self.library.command({'action': 'reset'})
        with patch('eryoutoolbox.character_library.os.replace', side_effect=OSError('occupied')):
            with self.assertRaises(OSError):
                self.library.command({'action': 'confirm', 'token': p['token']})
        self.assertEqual(self.library.effective()[8552]['测试'], ['One'])

    def test_conflicting_and_expired_previews(self):
        p = self.library.command({'action': 'reset'})
        self.commit(action='edit', game=8552, name='测试', aliases=['One'])
        with self.assertRaises(ValueError):
            self.library.command({'action': 'confirm', 'token': p['token']})
        p = self.library.command({'action': 'reset'})
        with patch('eryoutoolbox.character_library.time.monotonic', return_value=10**20):
            with self.assertRaises(ValueError):
                self.library.command({'action': 'confirm', 'token': p['token']})

    def test_format_size_content_duplicate_and_quantity(self):
        invalid = [{}, {'format': 2, 'games': {}}, {'format': 1, 'games': {'999': {}}},
                   {'format': 1, 'games': {'8552': {'x': ['<script>']}}},
                   {'format': 1, 'games': {'8552': {'x': ['a', 'a']}}},
                   {'format': 1, 'games': {'8552': {'x': []}}},
                   {'format': 1, 'games': {'8552': {str(i): ['a'] for i in range(3001)}}}]
        for doc in invalid:
            with self.subTest(doc=str(doc)[:80]), self.assertRaises(ValueError):
                validate(doc)
        with self.assertRaises(ValueError):
            decode(b'x' * (512 * 1024 + 1))
        with self.assertRaises(ValueError):
            decode('{"format":1,"format":1,"games":{}}')

    def test_url_allowlist_without_network(self):
        for url in ['file:///a.json', 'http://raw.githubusercontent.com/a/b/c.json',
                    'https://github.com/a/b/blob/main/a.json', 'https://raw.githubusercontent.com@127.0.0.1/a.json',
                    'https://raw.githubusercontent.com/a/b/main/a.json?x=1',
                    'https://raw.githubusercontent.com/a/b/../a.json']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch_json(url)

    def test_url_fetch_preview_then_confirm(self):
        document = {'format': 1, 'games': {'8552': {'测试': ['Test']}}}
        with patch('eryoutoolbox.character_library.fetch_json', return_value=document) as fetch:
            p = self.library.command({'action': 'url', 'url': 'https://raw.githubusercontent.com/a/b/main/a.json'})
            fetch.assert_called_once()
        self.assertFalse(self.library.path.exists())
        self.library.command({'action': 'confirm', 'token': p['token']})
        self.assertIn('测试', self.library.effective()[8552])

    def test_bounded_fetch_no_redirect_and_http_errors(self):
        from unittest.mock import MagicMock
        url = 'https://raw.githubusercontent.com/a/b/main/names.json'
        response = MagicMock()
        response.iter_bytes.return_value = [b'{"format":1,"games":{}}']
        with patch('eryoutoolbox.character_library.httpx.stream') as stream:
            stream.return_value.__enter__.return_value = response
            self.assertEqual(fetch_json(url)['format'], 1)
            self.assertFalse(stream.call_args.kwargs['follow_redirects'])
            response.iter_bytes.return_value = [b'x' * (512 * 1024 + 1)]
            with self.assertRaises(ValueError):
                fetch_json(url)
            for code in [302, 403, 404, 429, 500]:
                response.raise_for_status.side_effect = httpx.HTTPStatusError('failed', request=httpx.Request('GET', url), response=httpx.Response(code))
                with self.assertRaises(httpx.HTTPStatusError):
                    fetch_json(url)
        with patch('eryoutoolbox.character_library.httpx.stream', side_effect=httpx.ReadTimeout('timeout')):
            with self.assertRaises(httpx.ReadTimeout):
                fetch_json(url)

    def test_backup_failure_does_not_save(self):
        self.commit(action='edit', game=8552, name='测试', aliases=['One'])
        old = self.library.path.read_bytes()
        pending = self.library.command({'action': 'reset'})
        with patch('eryoutoolbox.character_library.os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.library.command({'action': 'confirm', 'token': pending['token']})
        self.assertEqual(old, self.library.path.read_bytes())

    def test_http_origin_preview_confirm_and_live_search(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        from react_api import ReadOnlyAPI, make_handler
        db = self.root / 'test.db'
        initialize_database(db)
        api = ReadOnlyAPI(db, runtime_root=self.root)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), http.server.BaseHTTPRequestHandler)
        port = server.server_port
        server.RequestHandlerClass = make_handler(api, port)
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        before = db.read_bytes()
        def post(body, origin=None):
            headers = {'Content-Type': 'application/json', 'X-ErYouToolbox': '1', 'Origin': origin or f'http://127.0.0.1:{port}'}
            connection.request('POST', '/api/character-library', json.dumps(body), headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, raw
        try:
            body = {'action': 'edit', 'game': 20357, 'name': '验证测试', 'aliases': ['No Local MOD']}
            self.assertEqual(post(body, 'https://example.com')[0], 403)
            status, raw = post(body)
            self.assertEqual(status, 200)
            self.assertFalse(api.character_library.path.exists())
            status, _ = post({'action': 'confirm', 'token': json.loads(raw)['token']})
            self.assertEqual(status, 200)
            from urllib.parse import quote
            status, result = api.get('/api/mods?search=' + quote('验证测试'))
            self.assertEqual(status, 200)
            self.assertTrue(result['search_info']['alias_known'])
            self.assertEqual(result['total_count'], 0)
            with patch('eryoutoolbox.character_library.fetch_json', side_effect=httpx.ReadTimeout('timeout')):
                self.assertEqual(post({'action': 'url', 'url': 'https://raw.githubusercontent.com/a/b/main/a.json'})[0], 503)
            self.assertEqual(db.read_bytes(), before)
            self.assertEqual(len(api.character_library.status()['backups']), 1)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join(5)

    def test_restore_path_and_corruption(self):
        for path in ['../library.json', 'C:/a.json', 'backup-no.json']:
            with self.assertRaises(ValueError):
                self.library.command({'action': 'restore', 'backup': path})
        self.library.directory.mkdir(parents=True)
        self.library.path.write_text('{}')
        with self.assertRaises(ValueError):
            self.library.status()

    def test_search_live_update_empty_meaning_and_database_unchanged(self):
        db = self.root / 'test.db'
        initialize_database(db)
        connection = sqlite3.connect(db)
        with connection:
            connection.execute("INSERT INTO mods(source,item_type,item_id,game_id,title,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',1,20357,'Suoming costume','x','x')")
        connection.close()
        before = db.read_bytes()
        result = query_mods(db, search='锁暝', character_index=self.library.effective())
        self.assertEqual(result['items'][0]['item_id'], 1)
        self.commit(action='edit', game=20357, name='新增名称', aliases=['Missing MOD'])
        result = query_mods(db, search='新增名称', character_index=self.library.effective())
        self.assertTrue(result['search_info']['alias_known'])
        self.assertEqual(result['total_count'], 0)
        self.assertEqual(before, db.read_bytes())


if __name__ == '__main__':
    unittest.main()
