import sys,json,tempfile,unittest,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from http.client import HTTPConnection
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.jasm_names import parse_names
from eryoutoolbox.character_library import CharacterLibrary
from eryoutoolbox.character_aliases import alias_groups
from eryoutoolbox.database import initialize_database
from backup_project import create_backup,verify_bundle
from react_api import ReadOnlyAPI,make_handler

class MaintFixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_trim_and_strict_validation(self):
  rows=[{'InternalName':en,'DisplayName':zh+' '} for en,zh in [('Evelyn','伊芙琳'),('Lighter','莱特'),('Trigger','扳机'),('Vivian','薇薇安')]]
  self.assertEqual(len(parse_names(rows,'19567')),4)
  for name in ['   ','<script>','a\nb']:
   with self.assertRaises(ValueError):parse_names([{'InternalName':'Test','DisplayName':name}],'19567')
 def test_preserve_aliases_but_personal_correction_wins(self):
  lib=CharacterLibrary(self.root);state=lib.read()
  state['external']={'8552':{'胡桃':['Hu Tao']},'21842':{'陈千语':['ChenQianyu']}}
  names=lib.effective(state)
  self.assertIn('Hutao',alias_groups('胡桃',8552,names)[0][1])
  self.assertIn('Chen Qianyu',alias_groups('陈千语',21842,names)[0][1])
  state['personal']={'8552':{'胡桃':['Personal']}}
  self.assertEqual(lib.effective(state)[8552]['胡桃'],['Personal'])
 def test_personal_library_backup_and_restore_rehearsal(self):
  initialize_database(self.root/'data/eryoutoolbox.db')
  lib=CharacterLibrary(self.root)
  preview=lib.command({'action':'edit','game':8552,'name':'测试','aliases':['Test']})
  lib.command({'action':'confirm','token':preview['token']})
  before=lib.path.read_bytes()
  result=create_backup(self.root,self.root/'backups',temp_parent=self.root/'restore',writers_paused=True)
  bundle=Path(result['bundle']);manifest=json.loads((bundle/'manifest.json').read_text())
  self.assertIn('data/character_library/library.json',manifest['recovery_inventory']['included'])
  self.assertEqual((bundle/'checkpoints/data/character_library/library.json').read_bytes(),before)
  self.assertTrue(verify_bundle(bundle,temp_parent=self.root/'rehearsal')['passed'])
  self.assertEqual(lib.path.read_bytes(),before)
 def test_history_authorization_is_explicit_and_validated(self):
  db=self.root/'data/eryoutoolbox.db';initialize_database(db)
  api=ReadOnlyAPI(db,runtime_root=self.root)
  self.assertEqual(api.auto_sync.settings()['mode'],'off')
  server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(api,0));port=server.server_port
  server.RequestHandlerClass=make_handler(api,port);thread=threading.Thread(target=server.serve_forever);thread.start()
  c=HTTPConnection('127.0.0.1',port,timeout=5)
  try:
   for mode,expected in [('apply',200),('check',200),('off',200),('bad',400)]:
    c.request('POST','/api/history-sync',json.dumps({'action':'authorize','mode':mode}),{'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json','X-ErYouToolbox':'1'})
    response=c.getresponse();response.read();self.assertEqual(response.status,expected)
    if expected==200:self.assertEqual(api.auto_sync.settings()['mode'],mode)
   self.assertEqual(api.history_sync.run(manual=True)['status'],'disabled')
  finally:c.close();server.shutdown();server.server_close();thread.join()
