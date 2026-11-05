"""Local SQLite browsing API with restricted author-subscription writes."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
import httpx
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.ui_queries import (  # noqa: E402
    DatabaseReadError, preview_display_decision, query_mod_detail, query_mods,
    readonly_connection, query_discovery_status, query_categories, valid_http_url,
)
from eryoutoolbox.app_resources import resource_root
from eryoutoolbox.subscriptions import status as follow_status, set_follow
from eryoutoolbox.author_updates import preview as preview_authors
from eryoutoolbox.popular import PopularClient, link_local
from eryoutoolbox.read_states import get_state as get_read_state, set_read
from web_sync import WebSync
from eryoutoolbox.authors import author_list,member,fill_one
from auto_sync import AutoSync
from manage_auto_sync import task_status
from eryoutoolbox.source_detail import SourceDetail
from eryoutoolbox.cache_management import CacheManagement
from eryoutoolbox.character_library import CharacterLibrary
POPULAR = PopularClient()

def author_summary(report):
    return {'checked_at':report.get('observed_at'),'status':report.get('status'), 'preview':not bool(report.get('applied')),
            'followed':report.get('followed_count',0),'checked_authors':report.get('checked_authors',0),
            'pending':report.get('pending_count',0)+sum(bool(a.get('errors')) for a in report.get('authors',[])),
            'new':sum(a.get('new_publications',0) for a in report.get('authors',[])),
            'updates':sum(a.get('comparison',{}).get('source_update_events',0) for a in report.get('authors',[]) if not a.get('baseline_pending')),
            'baseline_pending':any(a.get('baseline_pending') for a in report.get('authors',[])),
            'requests':report.get('requests',0)}

def valid_write_origin(headers, port):
    return (headers.get('Host') in {f'127.0.0.1:{port}', f'localhost:{port}'}
            and headers.get('Origin') in {'http://127.0.0.1:5173','http://localhost:5173',f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
            and headers.get('X-ErYouToolbox') == '1'
            and headers.get('Content-Type','').split(';')[0].strip() == 'application/json')


class ReadOnlyAPI:
    def __init__(self, database: Path, games_path: Path | None = None, *, runtime_root: Path | None = None, resources_root: Path | None = None):
        config_root = Path(resources_root) if resources_root is not None else resource_root()
        self.database = database
        self.games = json.loads((games_path or config_root/'config/games.json').read_text(encoding="utf-8"))["games"]
        local_root=runtime_root if runtime_root is not None else (ROOT if database.resolve().is_relative_to(ROOT) else database.parent)
        self.runtime_root = local_root
        self.character_library = CharacterLibrary(local_root)
        self.web_sync = WebSync(database, local_root, self.games)
        self.auto_sync=AutoSync(local_root,database,self.games,state_dir=None if local_root==ROOT else local_root/'logs/auto_sync')
        self.source_detail=SourceDetail()
        self.history_sync=self.auto_sync.history()
        self.cache=CacheManagement(local_root,POPULAR,self.source_detail,
                                   busy=lambda:self.web_sync.worker_active or self.auto_sync.running.locked() or self.history_sync.running.locked())

    @staticmethod
    def number(query, name, default, minimum, maximum):
        value = int(query.get(name, [str(default)])[0])
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return value

    @staticmethod
    def image_policy(item, allow_unknown, show_sensitive=False, show_unknown=False):
        item = dict(item)
        # Old image/rating preferences are ignored. URL validation still applies
        # in the normalizer/query parser and in the rendering components.
        urls = [url for url in item.get("preview_urls", []) if valid_http_url(url)]
        state = "DISPLAY" if urls else "NO_IMAGE" if not item.get("image_count", len(item.get("preview_urls", []))) else "PREFERENCE_HIDDEN"
        item["preview_state"] = state
        item["image_count"] = len(item.get("preview_images", item.get("preview_urls", [])))
        item["preview_urls"] = urls
        if state != "DISPLAY":
            item["preview_images"] = []
        return item

    def get(self, target: str):
        path = urlsplit(target)
        query = parse_qs(path.query, keep_blank_values=True)
        allow_unknown = query.get("show_unrated", ["1"])[0] == "1"
        show_sensitive = query.get('show_sensitive',['0'])[0]=='1'
        show_unknown = query.get('show_unknown_preview',['0'])[0]=='1'
        try:
            if path.path=='/api/character-library':return 200,self.character_library.status()
            if path.path=='/api/cache':return 200,self.cache.status()
            if path.path=='/api/rating-enrichment':
                return 410,{'error':'Content rating enrichment has been retired'}
            if path.path=='/api/categories':
                gid=self.number(query,'game',0,1,2**31-1) if query.get('game',[''])[0] else None
                if gid is not None and gid not in {g['game_id'] for g in self.games}:raise ValueError('Unknown game')
                return 200,query_categories(self.database,gid)
            if path.path in ('/api/authors','/api/author'):
                specific=path.path=='/api/author'
                aid=self.number(query,'author_id',0,1,2**63-1) if specific else None
                source=query.get('source',[''])[0] if specific else None
                result=author_list(self.database,search=query.get('search',[''])[0][:200],limit=self.number(query,'limit',20,1,20),offset=self.number(query,'offset',0,0,1000000),source=source,author_id=aid)
                for author in result['items']:
                    profile=member(self.web_sync.root,author['source'],author['author_id'],fetch=specific)
                    author['avatar_url']=profile.get('avatar_url')
                    author['profile_url']=f"https://gamebanana.com/members/{author['author_id']}" if author['source']=='gamebanana' else None
                if not specific and query.get('fill_avatar',['0'])[0]=='1':
                    fill_one(self.web_sync.root,result['items'])
                return 200,result
            if path.path == '/api/auto-sync':
                result=self.auto_sync.status()
                result['task']=( {'registered':False,'status':'unsupported','note':'Portable desktop: checks run only while the client is open.'}
                                if getattr(self, 'desktop', False) else task_status(self.auto_sync.root,self.auto_sync.directory))
                return 200,result
            if path.path == '/api/history-sync':
                return 200,self.history_sync.status()
            if path.path == '/api/sync':
                return 200,self.web_sync.view()
            if path.path == '/api/read-state':
                return 200,get_read_state(self.database,query.get('source',[''])[0],self.number(query,'item_id',0,1,2**63-1))
            if path.path == '/api/popular':
                gid=self.number(query,'game',0,1,2**31-1)
                game=next((g for g in self.games if g['game_id']==gid),None)
                if game is None:raise ValueError('Unknown game ID; all-games rankings must be requested separately')
                scope=query.get('scope',['history'])[0]
                if scope=='recent':
                    result=POPULAR.recent(game,query.get('sort',['likes'])[0],days=self.number(query,'days',30,7,90),
                        page=self.number(query,'page',1,1,100),limit=self.number(query,'limit',20,1,20),
                        max_pages=self.number(query,'max_pages',2,1,5),refresh=query.get('refresh',['0'])[0]=='1')
                elif scope=='history':
                    result=POPULAR.fetch(game,query.get('sort',['likes'])[0],self.number(query,'page',1,1,100),self.number(query,'limit',20,1,20),query.get('refresh',['0'])[0]=='1')
                else:raise ValueError('Invalid ranking scope')
                result=link_local(self.database,result)
                result['items']=[self.image_policy(i,allow_unknown,show_sensitive,show_unknown) for i in result['items']]
                return 200,result
            if path.path == '/api/author-updates':
                latest=self.runtime_root/'logs/author_updates/latest.json'
                return 200, author_summary(json.loads(latest.read_text(encoding='utf-8'))) if latest.exists() else {'status':'not_checked'}
            if path.path == '/api/subscription':
                source = query.get('source',[''])[0]
                author_id = self.number(query,'author_id',0,1,2**63-1)
                if not source or len(source)>80:
                    raise ValueError('Invalid source')
                return 200, follow_status(self.database, source, author_id)
            if path.path == "/api/content-ratings":
                return 410, {'error':'Content rating filters have been retired'}
            if path.path == "/api/games":
                return 200, {"games": self.games}
            if path.path == "/api/mods":
                limit = self.number(query, "limit", 18, 1, 50)
                offset = self.number(query, "offset", 0, 0, 1_000_000)
                game_id = None
                if query.get("game", [""])[0]:
                    game_id = self.number(query, "game", 0, 1, 2**31 - 1)
                    if game_id not in {game["game_id"] for game in self.games}:
                        raise ValueError("Unknown game ID.")
                codes = None  # Ignore pre-rc3 bookmarked rating filters.
                result = query_mods(
                    self.database, game_id=game_id,
                    character_index=self.character_library.effective(),
                    author_source=query.get('author_source',[None])[0],
                    author_id=self.number(query,'author_id',0,1,2**63-1) if query.get('author_id') else None,
                    exclude_item_id=self.number(query,'exclude_id',0,1,2**63-1) if query.get('exclude_id') else None,
                    search=query.get("search", [""])[0][:200],
                    sort=query.get("sort", ["created"])[0],
                    require_updated=query.get("sort", ["created"])[0] == 'updated' and query.get('feed',[''])[0]=='subscriptions',
                    subscriptions_only=query.get('feed',[''])[0] == 'subscriptions',
                    read_filter=query.get('read',['all'])[0],
                    limit=limit, offset=offset, rating_codes=codes,
                    require_preview=query.get("with_images", ["0"])[0] == "1",
                    category=query.get('category',[None])[0],subcategory=query.get('subcategory',[None])[0],
                )
                # Only enrich the current page with the already saved category text.
                identities = [(item["source"], item["item_type"], item["item_id"])
                              for item in result["items"]]
                if identities:
                    connection = readonly_connection(self.database)
                    try:
                        condition = " OR ".join(
                            "(source=? AND item_type=? AND item_id=?)" for _ in identities)
                        rows = connection.execute(
                            "SELECT source,item_type,item_id,category,subcategory FROM mods WHERE " + condition,
                            [value for identity in identities for value in identity],
                        ).fetchall()
                        categories = {(row["source"], row["item_type"], row["item_id"]): row
                                      for row in rows}
                        for item, identity in zip(result["items"], identities):
                            row = categories.get(identity)
                            item["category"] = row["category"] if row else None
                            item["subcategory"] = row["subcategory"] if row else None
                    finally:
                        connection.close()
                result["items"] = [self.image_policy(item, allow_unknown,show_sensitive,show_unknown) for item in result["items"]]
                return 200, {**result, "limit": limit, "offset": offset,
                             "discovery": query_discovery_status(self.database, game_id)}
            if path.path == "/api/mod":
                item_id = self.number(query, "item_id", 0, 1, 2**63 - 1)
                source = query.get("source", [""])[0]
                item_type = query.get("item_type", [""])[0]
                if not source or not item_type:
                    raise ValueError("source and item_type are required.")
                item = query_mod_detail(self.database, source=source,
                                       item_type=item_type, item_id=item_id)
                if item is not None and query.get('source_refresh',['0'])[0]=='1':
                    if source!='gamebanana' or item_type!='Mod':raise ValueError('Unsupported source detail')
                    game=next((g for g in self.games if g['game_id']==item['game_id']),None)
                    if not game:raise ValueError('Unsupported game')
                    fresh=self.source_detail.fetch(item_id,game)
                    # On-demand display only. Never replace saved images or user state.
                    for field in ('metrics','files','file_count','description','created_at','updated_at'):
                        if fresh.get(field) is not None:item[field]=fresh[field]
                    item['source_display_refreshed']=True
                if item is None:
                    if source=='gamebanana' and item_type=='Mod' and query.get('remote_game'):
                        gid=self.number(query,'remote_game',0,1,2**31-1)
                        game=next((g for g in self.games if g['game_id']==gid),None)
                        if game is None:raise ValueError('Unknown source game')
                        item=self.source_detail.fetch(item_id,game)
                        return 200,self.image_policy(item,allow_unknown,show_sensitive,show_unknown)
                    return 404, {"error": "The MOD is not in the local database."}
                return 200, self.image_policy(item, allow_unknown,show_sensitive,show_unknown)
            return 404, {"error": "Unknown endpoint."}
        except (ValueError, TypeError) as exc:
            return 400, {"error": str(exc)}
        except (DatabaseReadError, sqlite3.Error) as exc:
            return 503, {"error": f"SQLite read failed: {exc}"}
        except (RuntimeError, httpx.HTTPError) as exc:
            return 502, {'error':str(exc)}


def make_handler(api: ReadOnlyAPI, port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path not in ('/api/character-library','/api/cache','/api/subscription','/api/author-updates','/api/read-state','/api/sync','/api/auto-sync','/api/auto-sync/run','/api/auto-sync/startup','/api/auto-sync/refresh','/api/history-sync','/api/rating-enrichment') or not valid_write_origin(self.headers,port) or self.headers.get('Transfer-Encoding'):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0<length<=(600*1024 if self.path=='/api/character-library' else 2048):
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(length))
                if self.path=='/api/character-library':result=api.character_library.command(body)
                elif self.path=='/api/cache':result=api.cache.command(body)
                elif self.path == '/api/rating-enrichment':
                    raise ValueError('Content rating enrichment has been retired')
                elif self.path == '/api/auto-sync':
                    result=api.auto_sync.configure(body)
                elif self.path == '/api/history-sync':
                    history=api.history_sync
                    if isinstance(body,dict) and set(body)=={'action','mode'} and body['action']=='authorize':
                        if body['mode'] not in ('off','check','apply'):raise ValueError('Invalid history authorization')
                        api.auto_sync.configure({**api.auto_sync.settings(),'mode':body['mode']})
                        result=history.status()
                    elif body=={'action':'continue'}:
                        if api.web_sync.worker_active or api.auto_sync.running.locked():raise ValueError('Another sync task is active')
                        if (history.status().get('last_run') or {}).get('status')=='checking':raise ValueError('Historical scan already running')
                        history.configure({**history.settings(),'enabled':True,'paused':False,'max_pages':2})
                        result=history.launch(manual=True)
                    elif body=={'action':'stop'}:result=history.configure({**history.settings(),'paused':True})
                    elif body=={'action':'run'}:result=history.launch(manual=True)
                    elif isinstance(body,dict) and set(body)=={'action','settings'} and body['action']=='configure':result=history.configure(body['settings'])
                    else:raise ValueError('Invalid historical scan action')
                elif self.path=='/api/auto-sync/refresh':
                    if not isinstance(body,dict) or set(body)-{'game'}:raise ValueError('Invalid refresh request')
                    result=api.auto_sync.browser_launch(game=body.get('game'))
                elif self.path in ('/api/auto-sync/run','/api/auto-sync/startup'):
                    if body=={'action':'stop'}:
                        result=api.auto_sync.stop()
                        raw=json.dumps(result).encode('utf-8');self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
                    if body!={}:raise ValueError('Invalid automatic run request')
                    result=(api.auto_sync.browser_launch(startup=True) if self.path.endswith('/startup')
                            else api.auto_sync.launch())
                elif self.path == '/api/sync':
                    if not isinstance(body,dict):raise ValueError('Invalid request')
                    result=api.web_sync.start(body)
                elif self.path == '/api/read-state':
                    if not isinstance(body,dict) or set(body)!={'source','item_id','is_read'}:raise ValueError('Invalid read-state request')
                    result=set_read(api.database,body['source'],body['item_id'],body['is_read'])
                elif self.path == '/api/author-updates':
                    if body != {}:raise ValueError('Author check only supports dry-run')
                    report,_=preview_authors(api.database,api.runtime_root)
                    result=author_summary(report)
                elif not isinstance(body,dict) or set(body) != {'source','author_id','followed'}:
                    raise ValueError('Invalid subscription request')
                else:
                    result = set_follow(api.database,body['source'],body['author_id'],body['followed'])
                status = 200
            except (ValueError,TypeError) as exc:
                status,result=400,{'error':str(exc)}
            except (RuntimeError,sqlite3.Error,OSError,httpx.HTTPError) as exc:
                status,result=503,{'error':str(exc)}
            raw=json.dumps(result).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self.send_error(403)
                return
            status, result = api.get(self.path)
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    database = ROOT / "data" / "eryoutoolbox.db"
    if not database.is_file():
        parser.error(f"Existing database required: {database}")
    try:
        api = ReadOnlyAPI(database)
        with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(api, args.port)) as server:
            print(f"Read-only API: http://127.0.0.1:{args.port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"API could not start: {exc}\n")


if __name__ == "__main__":
    main()

