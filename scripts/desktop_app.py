"""Portable desktop host. Never opens the development database."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing as close_resource
from http.server import ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from eryoutoolbox.app_resources import resource_root, executable_root, development_root, verify_resources

RESOURCES = resource_root()
from eryoutoolbox.database import initialize_database, SCHEMA_VERSION
from react_api import ReadOnlyAPI, make_handler
from backfill_content_ratings import instance_lock

VERSION = '0.5.0-rc3'


class DesktopAPI(ReadOnlyAPI):
    """Do not expose a confirmable preview until its worker releases the shared lock."""
    desktop = True

    def get(self, target):
        status, result = super().get(target)
        if urlsplit(target).path == '/api/sync' and status == 200 and self.web_sync.worker_active:
            if result.get('status') == 'waiting':
                result = {**result, 'status':'checking'}
            elif result.get('status') in ('success','partial'):
                result = {**result, 'status':'importing'}
        return status, result


def portable_root():
    return (executable_root() if getattr(sys, 'frozen', False)
            else development_root() / 'dist' / 'desktop-development')


def prepare_data(home, resources=RESOURCES):
    """Only a missing, explicitly named portable userdata directory can be initialized."""
    root = Path(home).resolve() / 'userdata'
    if root.is_symlink() or root.is_junction():
        raise ValueError('userdata must not be a link or junction')
    root.mkdir(parents=True, exist_ok=True)
    # Test write access before creating a database. No fallback directory.
    probe = root / ('.write-test-' + secrets.token_hex(8))
    with probe.open('xb') as stream:
        stream.write(b'1')
    probe.unlink()
    db = root / 'data/eryoutoolbox.db'
    marker = root / 'portable.json'
    if db.exists():
        if not marker.is_file():
            raise ValueError('Existing database has no portable identity. Do not copy a production database here.')
        identity = json.loads(marker.read_text(encoding='utf-8'))
        if identity.get('format') != 'eryoutoolbox-portable-v1':
            raise ValueError('Unknown portable userdata format')
        with close_resource(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as connection:
            if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise ValueError('Database requires an explicit, backed-up migration; automatic migration is disabled')
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Portable database integrity check failed')
    elif marker.exists() or any(root.iterdir()):
        raise ValueError('Incomplete userdata exists but database is missing. Restore it explicitly; no replacement database created.')
    else:
        # Creation is staged so interrupted initialization is not mistaken for an existing library.
        staged = root / 'initializing.db'
        initialize_database(staged)
        (root / 'data').mkdir()
        staged.replace(db)
        marker.write_text(json.dumps({'format':'eryoutoolbox-portable-v1', 'created_version':VERSION}), encoding='utf-8')
    config = root / 'config'
    config.mkdir(exist_ok=True)
    for name in ('games.json',):
        target = config / name
        if not target.exists():
            with target.open('xb') as stream:
                stream.write((resources / 'config' / name).read_bytes())
    identity_path = config / 'project_identity.json'
    if not identity_path.exists():
        with identity_path.open('x', encoding='utf-8') as stream:
            json.dump({'project_id':str(uuid.uuid4()), 'name':'ErYouToolbox portable'}, stream)
    return root, db


def desktop_handler(api, port, static, closing):
    base = make_handler(api, port)
    static = Path(static).resolve()
    class Handler(base):
        def log_message(self, fmt, *args):
            logging.info(fmt, *args)

        def do_POST(self):
            with self.server.lifecycle_lock:
                self._post()

        def _post(self):
            if closing.is_set():
                self.send_error(503, 'Desktop is closing')
                return
            # Desktop has a single exact origin, never the development Vite origin.
            if self.headers.get('Origin') != f'http://127.0.0.1:{port}':
                self.send_error(403)
                return
            if self.path == '/api/sync' and api.web_sync.worker_active:
                raw = b'{"error":"Previous sync worker is still finishing; retry after it completes."}'
                self.send_response(409)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            super().do_POST()

        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}':
                self.send_error(403)
                return
            path = unquote(urlsplit(self.path).path)
            if path.startswith('/api/'):
                return super().do_GET()
            # Serve only dist/index.html and dist/assets; never the project or userdata.
            if path == '/':
                target = static / 'index.html'
            elif path.startswith('/assets/') and '\\' not in path:
                target = (static / path.lstrip('/')).resolve()
                if not target.is_relative_to(static / 'assets'):
                    self.send_error(404)
                    return
            else:
                self.send_error(404)
                return
            if not target.is_file():
                self.send_error(404)
                return
            raw = target.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-cache' if target.name == 'index.html' else 'public, max-age=31536000, immutable')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(raw)
    return Handler


def create_server(root, database, static=RESOURCES/'frontend/dist', *, resources=RESOURCES):
    if not (Path(static)/'index.html').is_file():
        raise ValueError('Missing production frontend. Build frontend before packaging.')
    api = DesktopAPI(database, runtime_root=root, resources_root=resources)
    closing = threading.Event()
    # Binding port zero atomically reserves a free loopback port; no check/bind race.
    server = ThreadingHTTPServer(('127.0.0.1', 0), None)
    server.lifecycle_lock = threading.RLock()
    server.RequestHandlerClass = desktop_handler(api, server.server_port, static, closing)
    return server, api, closing


def webview2_available():
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in (winreg.KEY_READ | winreg.KEY_WOW64_32KEY, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\EdgeUpdate\Clients', 0, access) as clients:
                    for index in range(winreg.QueryInfoKey(clients)[0]):
                        with winreg.OpenKey(clients, winreg.EnumKey(clients,index)) as key:
                            try:
                                name=winreg.QueryValueEx(key,'name')[0]
                                version=winreg.QueryValueEx(key,'pv')[0]
                                if 'WebView2' in name and version and version != '0.0.0.0':
                                    return True
                            except OSError:
                                pass
            except OSError:
                pass
    return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-seconds', type=int, default=0, help='Isolated UI smoke test: close idle window after N seconds')
    args=parser.parse_args()
    server=None
    try:
        if os.name != 'nt':
            raise RuntimeError('This candidate supports Windows x64 only')
        if not webview2_available():
            raise RuntimeError('Microsoft Edge WebView2 Runtime is required. Install Evergreen Runtime from https://developer.microsoft.com/microsoft-edge/webview2/ . No download was performed.')
        verify_resources(RESOURCES, require_manifest=bool(getattr(sys, 'frozen', False)))
        home=portable_root()
        # The lock is owned by this process and follows the portable directory.
        home.mkdir(parents=True,exist_ok=True)
        with ExitStack() as stack:
            stack.enter_context(instance_lock(home/'.desktop.lock'))
            root,database=prepare_data(home)
            (root/'logs').mkdir(exist_ok=True)
            logging.basicConfig(filename=root/'logs/desktop.log',level=logging.INFO,encoding='utf-8')
            server,api,closing=create_server(root,database)
            thread=threading.Thread(target=server.serve_forever,name='desktop-http',daemon=True)
            thread.start()
            import webview
            webview.settings['ALLOW_DOWNLOADS'] = False
            webview.settings['ALLOW_FILE_URLS'] = False
            webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
            url=f'http://127.0.0.1:{server.server_port}/'
            logging.info('Desktop %s ready: %s database=%s',VERSION,url,database)
            window=webview.create_window('二游工具盒 ErYouToolbox',url,width=1440,height=960,min_size=(960,640))
            def attach_cache():
                # Only Microsoft's DiskCache kind, never AllProfile/DOM storage.
                # No filesystem deletion of an active browser profile.
                def clear_disk_cache():
                    from System import Action
                    from Microsoft.Web.WebView2.Core import CoreWebView2BrowsingDataKinds
                    done=threading.Event();errors=[]
                    def invoke():
                        try:
                            task=window.native.browser.webview.CoreWebView2.Profile.ClearBrowsingDataAsync(CoreWebView2BrowsingDataKinds.DiskCache)
                            def finished():
                                try:task.GetAwaiter().GetResult()
                                except Exception as exc:errors.append(str(exc))
                                finally:done.set()
                            task.GetAwaiter().OnCompleted(Action(finished))
                        except Exception as exc:errors.append(str(exc));done.set()
                    window.native.BeginInvoke(Action(invoke))
                    if not done.wait(15):raise RuntimeError('WebView2 cache clearing timed out; no folder was forcibly deleted')
                    if errors:raise RuntimeError('; '.join(errors))
                api.cache.webview_clear=clear_disk_cache
            window.events.loaded += attach_cache
            def before_close():
                # Reject new writes, then wait for known workers without interrupting transactions.
                with server.lifecycle_lock:
                    closing.set()
                    try:
                        if api.web_sync.worker_active or api.auto_sync.running.locked() or api.history_sync.running.locked():
                            raise RuntimeError('A sync is running')
                        with instance_lock(root/'logs/content_ratings/instance.lock'):
                            pass
                    except RuntimeError:
                        closing.clear()
                        window.create_confirmation_dialog('任务尚未结束','同步任务仍在运行，请等待完成或在同步详情中停止后关闭。')
                        return False
                return True
            window.events.closing += before_close
            def smoke():
                try:
                    if not window.events.loaded.wait(30):
                        raise RuntimeError('WebView document did not load')
                    time.sleep(max(1,args.smoke_seconds))
                    from urllib.request import urlopen
                    with urlopen(url+'api/games', timeout=5) as response:
                        games=json.load(response)
                    report={'version':VERSION,'url':url,'games':len(games['games']),
                            'content_ratings':'retired',
                            'resources':str(RESOURCES),'userdata':str(root),
                            'page':window.evaluate_js("({title:document.title,text:document.body.innerText,root:!!document.querySelector('#root')})")}
                    (root/'logs/desktop-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                except Exception:
                    logging.exception('Desktop smoke failed')
                finally:
                    window.destroy()
            try:
                # Portable browser storage is explicitly scoped. The native API
                # clears DiskCache only; pywebview must not recursively remove it.
                browser_storage=root/'cache/webview'
                from eryoutoolbox.cache_management import safe_child
                safe_child(root,browser_storage)
                webview.start(smoke if args.smoke_seconds else None,gui='edgechromium',private_mode=False,storage_path=str(browser_storage))
            finally:
                closing.set()
                api.web_sync.cancel.set()
                while api.web_sync.worker_active or api.auto_sync.running.locked() or api.history_sync.running.locked():
                    time.sleep(0.2)
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                server=None
        return 0
    except Exception as exc:
        logging.exception('Desktop startup or shutdown failed')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,str(exc),'ErYouToolbox could not start',0x10)
        return 1
    finally:
        if server is not None:
            server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
