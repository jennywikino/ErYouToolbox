import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from eryoutoolbox.character_library import CharacterLibrary,OFFICIAL
from eryoutoolbox.jasm_names import update,parse_names,FOLDERS


class JasmTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.library=CharacterLibrary(self.root)
        self.payload={folder:[{'InternalName':'Others','DisplayName':'其他'},
                             {'InternalName':'Hero','DisplayName':'测试角色'}] for folder in FOLDERS.values()}
        self.payload['Genshin']=[{'InternalName':'Hu Tao','DisplayName':'胡桃'},{'InternalName':'Furina','DisplayName':'芙宁娜'}]
        self.payload['WuWa']=[{'InternalName':'Suoming','DisplayName':'锁冥','Image':'never-download.png'}]
        self.manifest={'version':'2026.10.30','commit':'a'*40,'files':[
            {'path':f'{f}/Languages/zh-cn/characters.json','size':2,'hash':'a'*16} for f in FOLDERS.values()]}
        self.calls=[]
    def tearDown(self):self.tmp.cleanup()
    def fetch(self,url,**kwargs):
        self.calls.append(url)
        if url.endswith('manifest.json'):return copy.deepcopy(self.manifest)
        self.assertIn('/'+'a'*40+'/',url)
        self.assertEqual(kwargs,{'expected_size':2})
        folder=url.split('/')[-4]
        return copy.deepcopy(self.payload[folder])
    def preview(self):
        with patch('eryoutoolbox.jasm_names.update',side_effect=lambda meta:update(meta,fetch=self.fetch)):
            return self.library.command({'action':'jasm'})
    def commit(self,p):return self.library.command({'action':'confirm','token':p['token']})
    def test_five_files_only_no_images_and_official_protection(self):
        names,meta=update(fetch=self.fetch)
        self.assertEqual(len(self.calls),6)
        self.assertTrue(all(u.endswith('.json') and '/Images/' not in u for u in self.calls))
        self.assertEqual(names['20357']['锁暝'],OFFICIAL['锁暝'])
        self.assertNotIn('锁冥',names['20357'])
        self.assertEqual(names['8552']['胡桃'],['Hu Tao'])
        self.assertEqual(names['8552']['芙宁娜'],['Furina'])
        self.assertNotIn('23012',names)
        self.assertEqual(meta['version'],'2026.10.30')
    def test_preview_persistence_and_one_request_version_cache(self):
        p=self.preview();self.assertFalse(self.library.path.exists());self.commit(p)
        saved=CharacterLibrary(self.root).status()
        self.assertEqual(saved['external_meta']['version'],'2026.10.30')
        self.assertEqual(saved['external_counts']['8552'],2)
        self.calls.clear();before=self.library.path.read_bytes()
        self.assertEqual(self.preview()['status'],'unchanged')
        self.assertEqual(len(self.calls),1);self.assertEqual(self.library.path.read_bytes(),before)
    def test_all_layer_priorities_and_restore(self):
        self.commit(self.preview())
        def command(body):self.commit(self.library.command(body))
        command({'action':'import','document':{'format':1,'games':{'8552':{'胡桃':['Imported']}}}})
        self.assertEqual(self.library.effective()[8552]['胡桃'],['Imported'])
        command({'action':'edit','game':8552,'name':'胡桃','aliases':['Personal']})
        self.assertEqual(self.library.effective()[8552]['胡桃'],['Personal'])
        backups=self.library.status()['backups']
        chosen=next(b for b in backups if json.loads((self.library.directory/b).read_text())['external_meta'])
        command({'action':'reset'})
        self.assertIsNone(self.library.status()['external_meta'])
        command({'action':'restore','backup':chosen})
        self.assertEqual(self.library.status()['external_meta']['version'],'2026.10.30')
    def test_failed_file_or_changed_version_keeps_cache(self):
        self.commit(self.preview());before=self.library.path.read_bytes()
        self.manifest['version']='2026.10.31';self.payload['Endfield']=[{}]
        with self.assertRaises(ValueError):self.preview()
        self.assertEqual(before,self.library.path.read_bytes())
        self.assertEqual(self.library.status()['external_meta']['version'],'2026.10.30')
    def test_downgrade_and_manifest_missing_rejected(self):
        _,previous=update(fetch=self.fetch)
        self.manifest['version']='2026.10.29'
        with self.assertRaises(ValueError):update(previous,fetch=self.fetch)
        self.manifest['files'].pop()
        with self.assertRaises(ValueError):update(fetch=self.fetch)
    def test_old_format_read_is_non_destructive(self):
        self.library.directory.mkdir(parents=True)
        old={'format':1,'imported':{'8552':{'测试':['Test']}},'personal':{}}
        self.library.path.write_text(json.dumps(old),encoding='utf-8');before=self.library.path.read_bytes()
        self.assertEqual(self.library.effective()[8552]['测试'],['Test'])
        self.assertEqual(before,self.library.path.read_bytes())
        self.assertEqual(self.library.read()['format'],2)
    def test_bad_format_empty_duplicate_and_control_names(self):
        for rows in [{},[],[{}],[{'InternalName':'X','DisplayName':'<script>'}],
                     [{'InternalName':'A','DisplayName':'同名'},{'InternalName':'B','DisplayName':'同名'}]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):parse_names(rows,'8552')
    def test_atomic_failure_retains_old_external_and_personal(self):
        self.commit(self.preview());before=self.library.path.read_bytes()
        p=self.library.command({'action':'edit','game':8552,'name':'测试','aliases':['Test']})
        with patch('eryoutoolbox.character_library.os.replace',side_effect=OSError('occupied')):
            with self.assertRaises(OSError):self.commit(p)
        self.assertEqual(before,self.library.path.read_bytes())


if __name__=='__main__':unittest.main()
