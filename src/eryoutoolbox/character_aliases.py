"""Offline third-party name facts; original literal search is always retained."""
import json
from pathlib import Path

INDEX=json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
ALIASES={int(gid):names for gid,names in INDEX['games'].items()}

def alias_groups(keyword, game_id=None, index=None):
    found=[]
    for gid,names in (ALIASES if index is None else index).items():
        if game_id is not None and game_id!=gid:continue
        terms=[]
        for zh,english in names.items():
            if keyword.casefold() in [x.casefold() for x in [zh,*english]]:
                terms.extend([zh,*english])
        if terms:found.append((gid,list(dict.fromkeys(terms))))
    return found
