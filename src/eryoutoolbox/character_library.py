"""Bounded, explicitly confirmed name facts; no executable import formats."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
from urllib.parse import urlsplit

import httpx
from .character_aliases import ALIASES

LIMIT = 512 * 1024
GAMES = {str(g) for g in ALIASES}
OFFICIAL = {'锁暝': ['Suoming', '鎖暝', 'Suo Ming']}


def validate(document, personal=False):
    if not isinstance(document, dict) or set(document) - {'format', 'games', 'sources'} or document.get('format') != 1:
        raise ValueError('名称库必须为 format: 1 / games 格式')
    games = document.get('games')
    if not isinstance(games, dict) or set(games) - GAMES:
        raise ValueError('只支持现有六游戏 ID')
    count = 0
    def name(s):
        return isinstance(s, str) and 0 < len(s) <= 80 and s == s.strip() and not any(ord(c) < 32 or c in '<>\x7f' for c in s)
    for gid, entries in games.items():
        if not isinstance(entries, dict):
            raise ValueError('游戏词条必须为对象')
        count += len(entries)
        for key, values in entries.items():
            if not name(key) or (values is None and not personal):
                raise ValueError('无效名称')
            if values is None:
                if gid == '20357' and key == '锁暝':
                    raise ValueError('官方名称不可删除')
                continue
            if not isinstance(values, list) or not 1 <= len(values) <= 16 or not all(name(s) for s in values) or len(set(values)) != len(values):
                raise ValueError('别名须为 1–16 个不重复的短名称')
            if gid == '20357' and (key in ('锁暝', '鎖暝') or any(s.casefold() in ('suoming', 'suo ming') for s in values)):
                if key != '锁暝' or not set(OFFICIAL['锁暝']).issubset(values):
                    raise ValueError('请保留官方名称 锁暝 / Suoming / 鎖暝 / Suo Ming；其他写法只能作为别名')
    if count > 3000 or len(json.dumps(document, ensure_ascii=False).encode()) > LIMIT:
        raise ValueError('名称库超过 3000 条或 512 KiB')
    return copy.deepcopy(games)


def decode(raw):
    if len(raw) > LIMIT:
        raise ValueError('名称库超过 512 KiB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('JSON 含重复键')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def fetch_json(url, *, expected_size=None):
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError('无效 GitHub JSON URL')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'raw.githubusercontent.com'
            or parsed.query or parsed.fragment or not re.fullmatch(r'/[\w.-]+/[\w.-]+/[\w./-]+\.json', parsed.path)
            or '..' in parsed.path):
        raise ValueError('只允许 https://raw.githubusercontent.com/用户/仓库/版本/文件.json，无查询参数或重定向')
    started = time.monotonic()
    with httpx.stream('GET', url, timeout=15, follow_redirects=False, trust_env=False) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() - started > 30:
                raise ValueError('获取名称库超过30秒，请稍后手动重试')
            raw.extend(chunk)
            if len(raw) > LIMIT:
                raise ValueError('远程文件超过 512 KiB')
        if expected_size is not None and len(raw)!=expected_size:
            raise ValueError('JASM文件大小与manifest不符，保留旧缓存')
        return decode(bytes(raw))


class CharacterLibrary:
    def __init__(self, root):
        self.directory = Path(root) / 'data' / 'character_library'
        self.path = self.directory / 'library.json'
        self.lock = threading.RLock()
        self.pending = {}

    @staticmethod
    def normalize(value):
        if isinstance(value,dict) and value.get('format')==1 and set(value)=={'format','imported','personal'}:
            value={**value,'format':2,'external':{},'external_meta':None}
        if not isinstance(value,dict) or set(value)!={'format','imported','personal','external','external_meta'} or value['format']!=2:
            raise ValueError('个人名称库格式损坏，请恢复备份')
        for layer in ('external','imported','personal'):
            validate({'format':1,'games':value[layer]},layer=='personal')
        meta=value['external_meta']
        if meta is not None:
            if (not isinstance(meta,dict) or set(meta)!={'source','version','revision','files','sha256','synced_at'}
                    or meta['source']!='https://github.com/Moonholder/JASM-GameAssets'
                    or not isinstance(meta['version'],str) or not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}',meta['version'])
                    or not isinstance(meta['revision'],str) or not re.fullmatch('[a-f0-9]{40}',meta['revision'])
                    or not isinstance(meta['files'],dict) or not isinstance(meta['sha256'],dict)
                    or not isinstance(meta['synced_at'],str)):
                raise ValueError('JASM缓存元数据损坏')
        return value

    def read(self):
        if self.directory.is_symlink() or self.directory.is_junction() or self.path.is_symlink():
            raise ValueError('名称库目录不可为链接')
        if not self.path.exists():
            return {'format': 2, 'imported': {}, 'personal': {},'external':{},'external_meta':None}
        return self.normalize(decode(self.path.read_bytes()))

    def effective(self, state=None):
        state = self.read() if state is None else state
        result = {str(g): dict(names) for g, names in ALIASES.items()}
        result['20357'].update(OFFICIAL)
        for layer in ('external', 'imported', 'personal'):
            for gid, entries in state[layer].items():
                for key, values in entries.items():
                    if values is None:
                        result[gid].pop(key, None)
                    else:
                        # Higher source wins ordering; valid lower-source search spellings remain.
                        # Personal corrections remain a complete override (including deletions).
                        result[gid][key] = (list(dict.fromkeys([*values,*result[gid].get(key,[])]))
                                            if layer!='personal' else values)
        return {int(g): names for g, names in result.items()}

    @staticmethod
    def fingerprint(state):
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()

    def status(self):
        with self.lock:
            state = self.read()
            return {'format': 1, 'games': self.effective(state), 'state': state,
                    'external_meta':state['external_meta'],'external_counts':{gid:len(rows) for gid,rows in state['external'].items()},
                    'backups': sorted(p.name for p in self.directory.glob('backup-*.json'))[-50:]}

    def command(self, body):
        with self.lock:
            state = self.read()
            if not isinstance(body, dict):
                raise ValueError('无效名称库请求')
            action = body.get('action')
            if action == 'confirm':
                pending = self.pending.pop(body.get('token'), None)
                if not pending or time.monotonic() > pending[0] or self.fingerprint(state) != pending[1]:
                    raise ValueError('预览已过期或名称库改变，请重新预览')
                updated = pending[2]
                if updated != state:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    backup = self.directory / f'backup-{uuid.uuid4().hex}.json'
                    with backup.open('x', encoding='utf-8') as out:
                        json.dump(state, out, ensure_ascii=False)
                        out.flush()
                        os.fsync(out.fileno())
                    temporary = self.directory / f'.{uuid.uuid4().hex}.tmp'
                    try:
                        with temporary.open('x', encoding='utf-8') as out:
                            json.dump(updated, out, ensure_ascii=False)
                            out.flush()
                            os.fsync(out.fileno())
                        os.replace(temporary, self.path)
                    finally:
                        temporary.unlink(missing_ok=True)
                return self.status()
            updated = copy.deepcopy(state)
            if action=='jasm':
                from .jasm_names import update
                fetched=update(state['external_meta'])
                if fetched is None:return {'status':'unchanged','note':'JASM版本未变，无需重复下载角色文件'}
                updated['external'],updated['external_meta']=fetched
            elif action in ('import', 'url'):
                document = fetch_json(body.get('url', '')) if action == 'url' else body.get('document')
                incoming = validate(document)
                for gid, entries in incoming.items():
                    updated['imported'].setdefault(gid, {}).update(entries)
            elif action == 'edit':
                gid, key, aliases = str(body.get('game')), body.get('name'), body.get('aliases')
                validate({'format': 1, 'games': {gid: {key: aliases}}}, True)
                updated['personal'].setdefault(gid, {})[key] = aliases
            elif action == 'reset':
                updated = {'format': 2, 'imported': {}, 'personal': {},'external':{},'external_meta':None}
            elif action == 'restore':
                filename = body.get('backup', '')
                if not isinstance(filename, str) or not re.fullmatch(r'backup-[a-f0-9]{32}\.json', filename):
                    raise ValueError('无效备份名称')
                path = self.directory / filename
                if path.is_symlink():
                    raise ValueError('备份不可为链接')
                updated = decode(path.read_bytes())
            else:
                raise ValueError('无效操作')
            updated=self.normalize(updated)
            if len(json.dumps(updated).encode()) > LIMIT:
                raise ValueError('合并后名称库过大')
            before, after = self.effective(state), self.effective(updated)
            changes = [{'game': gid, 'name': key, 'before': before[gid].get(key), 'after': after[gid].get(key)}
                       for gid in before for key in sorted(before[gid].keys() | after[gid].keys())
                       if before[gid].get(key) != after[gid].get(key)]
            self.pending = {key: p for key, p in self.pending.items() if p[0] > time.monotonic()}
            if len(self.pending) >= 8:
                raise ValueError('待确认预览过多，请稍后重试')
            token = uuid.uuid4().hex
            self.pending[token] = (time.monotonic() + 600, self.fingerprint(state), updated)
            layer_counts = {layer: sum(state[layer].get(gid, {}).get(key) != updated[layer].get(gid, {}).get(key)
                                      for gid in state[layer].keys() | updated[layer].keys()
                                      for key in state[layer].get(gid, {}).keys() | updated[layer].get(gid, {}).keys())
                            for layer in ('external','imported', 'personal')}
            return {'token': token, 'changes': changes, 'layer_counts': layer_counts,'external_meta':updated['external_meta'],
                    'note': '仅修改名称库；个人修正优先；确认前未保存。被个人修正遮盖的导入项不改变当前搜索。'}
