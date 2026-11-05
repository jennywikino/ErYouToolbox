"""Only JASM's known language JSON format; no images or repository archives."""
import hashlib
import json
import re
from datetime import datetime, timezone

from .character_library import fetch_json, validate, OFFICIAL

SOURCE = 'https://github.com/Moonholder/JASM-GameAssets'
RAW = 'https://raw.githubusercontent.com/Moonholder/JASM-GameAssets'
FOLDERS = {'8552': 'Genshin', '18366': 'Honkai', '19567': 'ZZZ', '20357': 'WuWa', '21842': 'Endfield'}


def parse_names(rows, gid):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError('JASM角色数组异常')
    names = {}
    for row in rows:
        if not isinstance(row, dict):raise ValueError('JASM角色项必须为对象')
        english, chinese = row.get('InternalName'), row.get('DisplayName')
        if not isinstance(english, str) or not isinstance(chinese, str):raise ValueError('JASM缺少中英文名称')
        english,chinese=english.strip(),chinese.strip()
        if english in ('Others', 'Weapons', 'Gliders'):continue
        if gid == '20357' and english.casefold() == 'suoming':
            chinese, aliases = '锁暝', OFFICIAL['锁暝']
        else:aliases = [english]
        if chinese in names and names[chinese] != aliases:raise ValueError('JASM存在冲突的同名角色')
        names[chinese] = aliases
    if not names:raise ValueError('JASM无有效角色名称，不覆盖旧缓存')
    validate({'format': 1, 'games': {gid: names}})
    return names


def update(previous=None, fetch=fetch_json):
    manifest = fetch(RAW + '/main/manifest.json')
    if not isinstance(manifest, dict):raise ValueError('JASM manifest格式异常')
    version, revision = manifest.get('version'), manifest.get('commit')
    if not isinstance(version, str) or not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}', version):raise ValueError('JASM版本格式异常')
    datetime.strptime(version, '%Y.%m.%d')
    if not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{40}', revision):raise ValueError('JASM commit异常')
    entries=manifest.get('files')
    if not isinstance(entries,list) or len(entries)>5000:raise ValueError('JASM文件清单异常')
    selected={}
    for folder in FOLDERS.values():
        path=f'{folder}/Languages/zh-cn/characters.json'
        matches=[f for f in entries if isinstance(f,dict) and f.get('path')==path]
        if len(matches)!=1:raise ValueError(f'JASM manifest缺失或重复路径: {path}')
        item=matches[0]
        if type(item.get('size')) is not int or not 0<item['size']<=512*1024 or not isinstance(item.get('hash'),str) or not re.fullmatch('[a-f0-9]{16,64}',item['hash']):raise ValueError('JASM文件元数据异常')
        selected[path]={'hash':item['hash'],'size':item['size']}
    if previous and version<previous['version']:raise ValueError('拒绝较旧的JASM版本')
    if previous and previous['version']==version and previous['revision']==revision and previous['files']==selected:
        return None  # One manifest request, no repeated language downloads or saves.
    games, digests = {}, {}
    for gid,folder in FOLDERS.items():
        path=f'{folder}/Languages/zh-cn/characters.json'
        rows=fetch(f'{RAW}/{revision}/{path}',expected_size=selected[path]['size'])
        games[gid]=parse_names(rows,gid)
        # This is a local canonical-JSON hash, not the upstream 16-digit hash algorithm.
        digests[path]=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return games,{'source':SOURCE,'version':version,'revision':revision,'files':selected,'sha256':digests,
                  'synced_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
