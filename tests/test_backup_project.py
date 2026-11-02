import json
from pathlib import Path, PureWindowsPath
from contextlib import redirect_stdout
import io
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]
from backup_project import create_backup, verify_bundle, default_destination, main
from eryoutoolbox.database import initialize_database


class ProjectBackupTests(unittest.TestCase):
    def test_default_destination_tracks_project_drive(self):
        for drive in ('E', 'F'):
            project = PureWindowsPath(f'{drive}:/codex/Projects/ErYouToolbox')
            self.assertEqual(PureWindowsPath(default_destination(project)), PureWindowsPath(f'{drive}:/ErYouToolboxBackups'))

    def test_cli_default_and_explicit_destination_without_real_backup(self):
        for args, expected in (([], default_destination(ROOT)), (['--destination', 'custom-backups'], Path('custom-backups'))):
            with patch('backup_project.create_backup', return_value={'passed': True}) as create, \
                    patch('backup_project.same_volume', return_value=True), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
                self.assertEqual(create.call_args.args[1], expected)
                self.assertIn('same physical device', output.getvalue())

    def test_cli_verify_does_not_create_default_backup(self):
        with patch('backup_project.verify_bundle', return_value={'passed': True}) as verify, \
                patch('backup_project.create_backup') as create, redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--verify', 'saved-bundle']), 0)
            verify.assert_called_once()
            create.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name)
        self.database = self.root / 'data' / 'eryoutoolbox.db'
        initialize_database(self.database)
        c = sqlite3.connect(self.database)
        c.execute("INSERT INTO mods(source,item_type,item_id,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',42,'now','now')")
        c.execute("INSERT INTO user_states(source,item_type,item_id,note,updated_at) VALUES('gamebanana','Mod',42,'keep','now')")
        c.execute("INSERT INTO mod_events(source,item_type,item_id,event_type,detected_at) VALUES('gamebanana','Mod',42,'first_seen','now')")
        c.execute("INSERT INTO sync_runs(source,started_at,status) VALUES('gamebanana','now','success')")
        c.commit()
        c.close()
        self.checkpoint = self.root / 'logs' / 'content_ratings' / 'checkpoint_all.json'
        self.checkpoint.parent.mkdir(parents=True)
        self.checkpoint.write_text(json.dumps({'format': 'eryoutoolbox-rating-backfill-v1', 'game': None,
            'attempted_ids': [42], 'failures': {'732069': {'reason': 'timeout'}}}), encoding='utf-8')
        self.destination = self.root / 'backup_target'

    def tearDown(self):
        self.temp.cleanup()

    def create(self):
        return create_backup(self.root, self.destination, temp_parent=self.root, writers_paused=True)

    def test_backup_restore_all_tables_schema_and_checkpoint_preserved(self):
        before = self.database.read_bytes()
        checkpoint = self.checkpoint.read_bytes()
        report = self.create()
        self.assertTrue(report['passed'])
        self.assertEqual(report['snapshot']['counts'], {'mods': 1, 'user_states': 1, 'mod_events': 1, 'sync_runs': 1, 'author_subscriptions': 0})
        self.assertEqual(report['snapshot']['user_version'], 3)
        self.assertEqual(report['checkpoints'], 1)
        bundle = Path(report['bundle'])
        self.assertEqual((bundle / 'checkpoints/logs/content_ratings/checkpoint_all.json').read_bytes(), checkpoint)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(self.checkpoint.read_bytes(), checkpoint)
        self.assertFalse(list(self.root.glob('backup_restore_*')))

    def test_repeated_backup_does_not_overwrite_history(self):
        first = Path(self.create()['bundle'])
        before = (first / 'manifest.json').read_bytes()
        second = Path(self.create()['bundle'])
        self.assertNotEqual(first, second)
        self.assertEqual((first / 'manifest.json').read_bytes(), before)

    def test_wal_committed_rows_included_without_changing_journal_mode(self):
        c = sqlite3.connect(self.database)
        self.assertEqual(c.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        c.execute("INSERT INTO mods(source,item_type,item_id,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',43,'now','now')")
        c.commit()
        c.execute("INSERT INTO mods(source,item_type,item_id,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',44,'pending','pending')")
        try:
            report = self.create()
            self.assertEqual(report['snapshot']['counts']['mods'], 2)
            self.assertTrue(c.in_transaction)
            self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        finally:
            c.close()

    def test_corrupt_database_is_not_marked_complete(self):
        self.database.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):
            self.create()
        manifest = json.loads(next(self.destination.glob('*/manifest.json')).read_text())
        self.assertEqual(manifest['status'], 'failed')

    def test_foreign_key_violation_fails(self):
        c = sqlite3.connect(self.database)
        c.execute("INSERT INTO user_states(source,item_type,item_id,updated_at) VALUES('gamebanana','Mod',999,'now')")
        c.commit()
        c.close()
        with self.assertRaisesRegex(ValueError, 'foreign key'):
            self.create()

    def test_tampered_checkpoint_and_database_fail_checksums(self):
        for name in ('database.db', 'checkpoints/logs/content_ratings/checkpoint_all.json'):
            report = self.create()
            bundle = Path(report['bundle'])
            with (bundle / name).open('ab') as stream:
                stream.write(b'X')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                verify_bundle(bundle, temp_parent=self.root)

    def test_checkpoint_change_during_backup_is_detected(self):
        import backup_project
        original = backup_project.sqlite_copy
        def copy_and_modify(*args, **kwargs):
            original(*args, **kwargs)
            self.checkpoint.write_text('{}', encoding='utf-8')
        with patch('backup_project.sqlite_copy', side_effect=copy_and_modify):
            with self.assertRaisesRegex(ValueError, 'Checkpoints changed'):
                self.create()

    def test_missing_database_not_created(self):
        self.database.unlink()
        with self.assertRaises(FileNotFoundError):
            self.create()
        self.assertFalse(self.database.exists())

    def test_same_volume_warning_flag_and_external_destination_supported(self):
        self.assertTrue(self.create()['same_project_volume'])
        with tempfile.TemporaryDirectory(dir=ROOT) as other_directory:
            report = create_backup(self.root, Path(other_directory), temp_parent=self.root, writers_paused=True)
            self.assertTrue(report['passed'])
            self.assertFalse(Path(report['bundle']).is_relative_to(self.root))
        with patch('backup_project.same_volume', return_value=False):
            self.assertFalse(self.create()['same_project_volume'])

    def test_unrecognized_checkpoint_is_not_silently_skipped(self):
        self.checkpoint.write_text('{"format":"private-user-file"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unrecognized checkpoint'):
            self.create()

    def test_manifest_path_traversal_is_rejected(self):
        bundle = Path(self.create()['bundle'])
        manifest_path = bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files'].append({'path': '../outside.json', 'kind': 'checkpoint', 'size': 0, 'sha256': ''})
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Unsafe backup manifest path'):
            verify_bundle(bundle, temp_parent=self.root)


    def state(self,name,value):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value),encoding='utf-8');return p

    def test_new_state_allowlist_and_optional_absence(self):
        values={
          'config/project_identity.json':{'project_id':'e459681a-240f-45d2-b8ce-c0d49572cb98','name':'ErYouToolbox'},
          'logs/author_updates/rotation.json':{'format':'eryoutoolbox-author-check-v1','cursor':7,'failures':{'7':{'pending_ids':[43],'not_before':0}}},
          'logs/author_updates/latest.json':{'format':'eryoutoolbox-author-check-v1','observed_at':'2026-11-02T00:00:00Z','authors':[]},
          'logs/history_sync/state.json':{'format':'eryoutoolbox-history-v1','database':'data/eryoutoolbox.db','games':{}},
          'logs/history_sync/settings.json':{'enabled':True,'paused':True,'max_pages':2},
          'logs/history_sync/cooldown.json':{'not_before':100},
          'logs/preview_repairs/state.json':{'format':'preview-repairs-v1','database':'data/eryoutoolbox.db','items':{'42':{'status':'failed','checked_at':100,'next_check':200}}},
          'logs/preview_repairs/cooldown.json':{'not_before':100},
          'logs/web_sync/task.json':{'format':'eryoutoolbox-web-sync-v1','database':'data/eryoutoolbox.db','task_id':'test','state':{'status':'discarded'},'candidate':None}}
        for name,value in values.items():self.state(name,value)
        for name in ('logs/content_ratings/instance.lock','logs/author_profiles/7.json','logs/ui_smoke/test/profile/cache.json','logs/author_updates/check_old.json','config/private.json'):
            self.state(name,{})
        report=self.create();bundle=Path(report['bundle']);m=json.loads((bundle/'manifest.json').read_text())
        self.assertEqual(report['checkpoints'],10);self.assertEqual(len(m['files']),11)
        self.assertTrue(all((bundle/'checkpoints'/name).exists() for name in values))

    def test_explicit_pause_required(self):
        with self.assertRaisesRegex(ValueError,'Pause ALL'):create_backup(self.root,self.destination)
        self.assertFalse(self.destination.exists())

    def test_invalid_new_format_and_binding(self):
        p=self.state('logs/preview_repairs/state.json',{'format':'future-v2','database':'data/eryoutoolbox.db','items':{}})
        with self.assertRaises(ValueError):self.create()
        p.write_text('{broken')
        with self.assertRaises(ValueError):self.create()
        p.write_text(json.dumps({'format':'preview-repairs-v1','database':'E:/somewhere.db','items':{}}))
        with self.assertRaises(ValueError):self.create()

    def test_json_database_mismatch_blocks_complete(self):
        self.state('logs/web_sync/task.json',{'format':'eryoutoolbox-web-sync-v1','database':'data/eryoutoolbox.db','task_id':'test','state':{'status':'waiting'},'candidate':{'baseline':'wrong','sync_generation':1,'task_id':'test'}})
        with self.assertRaisesRegex(ValueError,'mismatch'):self.create()
        self.assertEqual(json.loads(next(self.destination.glob('*/manifest.json')).read_text())['status'],'failed')

    def test_database_change_after_snapshot_refused(self):
        import backup_project
        original=backup_project.verify_bundle
        def verify(*args,**kwargs):
            value=original(*args,**kwargs);c=sqlite3.connect(self.database);c.execute("UPDATE mods SET title='changed'");c.commit();c.close();return value
        with patch('backup_project.verify_bundle',side_effect=verify):
            with self.assertRaisesRegex(ValueError,'Database changed'):self.create()

    def test_interrupt_manifest_never_complete(self):
        with patch('backup_project.sqlite_copy',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.create()
        self.assertEqual(json.loads(next(self.destination.glob('*/manifest.json')).read_text())['status'],'failed')

    def test_missing_recovery_file_does_not_restore_production(self):
        bundle=Path(self.create()['bundle']);before=self.database.read_bytes()
        (bundle/'checkpoints/logs/content_ratings/checkpoint_all.json').unlink()
        with self.assertRaises(FileNotFoundError):verify_bundle(bundle,temp_parent=self.root)
        self.assertEqual(before,self.database.read_bytes())

    def test_legacy_manifest_verification_compatible(self):
        bundle=Path(self.create()['bundle']);p=bundle/'manifest.json';m=json.loads(p.read_text())
        m.pop('database_digest');m.pop('recovery_inventory');m['snapshot']['counts'].pop('author_subscriptions');p.write_text(json.dumps(m))
        self.assertTrue(verify_bundle(bundle,temp_parent=self.root)['passed'])


if __name__ == '__main__':
    unittest.main()
