"""Resource discovery/integrity tests never read production data."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.app_resources import inventory, verify_resources, resource_root, executable_root, MANIFEST
from desktop_app import DesktopAPI, prepare_data


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'独立 bundle'
        (self.root/'config').mkdir(parents=True)
        for name in ('games.json','content_ratings.json'):
            shutil.copyfile(ROOT/'config'/name,self.root/'config'/name)
        (self.root/'frontend/dist/assets').mkdir(parents=True)
        (self.root/'frontend/dist/index.html').write_text('<script src="/assets/main.js"></script><link href="/assets/main.css">')
        (self.root/'frontend/dist/assets/main.js').write_text('console.log(1)')
        (self.root/'frontend/dist/assets/main.css').write_text('body{}')
        self.manifest=inventory(self.root)
        (self.root/MANIFEST).write_text(json.dumps(self.manifest))

    def tearDown(self):self.tmp.cleanup()

    def test_bundle_and_executable_roots_are_separate(self):
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(self.root),create=True),patch.object(sys,'executable',str(self.root.parent/'程序/ErYouToolbox.exe')):
            self.assertEqual(resource_root(),self.root)
            self.assertEqual(executable_root(),self.root.parent/'程序')
        self.assertEqual(verify_resources(self.root,require_manifest=True),self.manifest)

    def test_each_required_resource_missing_is_fatal(self):
        for name in ('config/games.json','config/content_ratings.json','frontend/dist/index.html','frontend/dist/assets/main.js','frontend/dist/assets/main.css',MANIFEST):
            path=self.root/name
            original=path.read_bytes();path.unlink()
            try:
                with self.assertRaises((ValueError,FileNotFoundError)) as error:verify_resources(self.root,require_manifest=True)
                self.assertIn(str(path),str(error.exception))
            finally:path.write_bytes(original)

    def test_bad_ratings_cannot_silently_become_empty(self):
        path=self.root/'config/content_ratings.json'
        for value in ({'options':[]},{'options':[{'_sAlias':'-'}]}):
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'ratings'):verify_resources(self.root)

    def test_changed_asset_fails_hash_check(self):
        (self.root/'frontend/dist/assets/main.js').write_text('changed')
        with self.assertRaisesRegex(ValueError,'integrity'):verify_resources(self.root,require_manifest=True)

    def test_resource_paths_do_not_depend_on_cwd_or_userdata_config(self):
        home=Path(self.tmp.name)/'portable'
        root,db=prepare_data(home,self.root)
        (root/'config/content_ratings.json').write_text('{"options":[]}')
        old=Path.cwd()
        try:
            os.chdir(Path(self.tmp.name))
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(self.root),create=True):
                api=DesktopAPI(db,runtime_root=root)
                self.assertEqual(len(api.games),6)
                self.assertIn('UNKNOWN',[r['_sAlias'] for r in api.rating_config['options']])
        finally:os.chdir(old)

    def test_resource_folder_move_keeps_manifest_valid(self):
        new=self.root.parent/'更换 目录'
        shutil.copytree(self.root,new)
        self.assertEqual(verify_resources(new,require_manifest=True),self.manifest)

    def test_missing_resources_fail_before_userdata_creation(self):
        import desktop_app
        with patch.object(sys,'argv',['desktop']),patch.object(desktop_app,'RESOURCES',self.root/'missing'),patch.object(desktop_app,'webview2_available',return_value=True),patch.object(desktop_app,'portable_root') as home,patch('ctypes.windll.user32.MessageBoxW'):
            self.assertEqual(desktop_app.main(),1)
            home.assert_not_called()

    def test_abnormal_process_exit_releases_lock_without_deleting_it(self):
        from backfill_content_ratings import instance_lock
        path=self.root/'instance.lock'
        code="import sys,os;sys.path.insert(0,sys.argv[1]);from backfill_content_ratings import instance_lock\nwith instance_lock(__import__('pathlib').Path(sys.argv[2])):print('ready',flush=True);sys.stdin.readline();os._exit(3)"
        child=subprocess.Popen([sys.executable,'-c',code,str(ROOT/'scripts'),str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            with self.assertRaises(RuntimeError):
                with instance_lock(path):pass
            child.stdin.write('exit\n');child.stdin.flush();child.wait(timeout=5)
            self.assertEqual(child.returncode,3)
            with instance_lock(path):pass
            self.assertTrue(path.exists())
        finally:
            if child.poll() is None:child.stdin.close();child.wait(timeout=5)
            if not child.stdin.closed:child.stdin.close()
            child.stdout.close()
