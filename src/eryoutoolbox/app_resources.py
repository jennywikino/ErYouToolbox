"""Read-only application resources, independent of cwd and writable userdata."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, unquote

FORMAT = 'eryoutoolbox-resources-v1'
MANIFEST = 'RESOURCE_MANIFEST.json'
CONFIGS = ('config/games.json',)
BRANDING = ('assets/branding/MiaomiaoEryouxiang_icon.ico', 'assets/branding/MiaomiaoEryouxiang_icon.png')


def development_root():
    return Path(__file__).resolve().parents[2]


def resource_root():
    return Path(sys._MEIPASS).resolve() if getattr(sys, 'frozen', False) else development_root()


def executable_root():
    return Path(sys.executable).resolve().parent


class _References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        value = values.get('src') if tag == 'script' else values.get('href') if tag == 'link' else None
        if value:
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc:
                raise ValueError(f'Production HTML requires an external resource: {value}')
            self.paths.append(unquote(parsed.path).lstrip('/'))


def inventory(root):
    root = Path(root).resolve()
    required = [*CONFIGS, *BRANDING, 'frontend/dist/index.html']
    for name in required:
        if not (root/name).is_file():
            raise ValueError(f'Missing application resource: {root/name}')
    games = json.loads((root/CONFIGS[0]).read_text(encoding='utf-8'))
    ids = [g.get('game_id') for g in games.get('games', [])]
    if not ids or any(type(i) is not int or i <= 0 for i in ids) or len(ids) != len(set(ids)):
        raise ValueError(f'Invalid games configuration: {root/CONFIGS[0]}')
    references = _References()
    references.feed((root/'frontend/dist/index.html').read_text(encoding='utf-8'))
    if not references.paths or not any(p.endswith('.js') for p in references.paths):
        raise ValueError(f'No production JavaScript entry: {root / "frontend/dist/index.html"}')
    for name in references.paths:
        path = (root/'frontend/dist'/name).resolve()
        if not path.is_relative_to(root/'frontend/dist/assets') or not path.is_file():
            raise ValueError(f'Missing or unsafe frontend asset: {path}')
    paths = [root/name for name in (*CONFIGS, *BRANDING)] + sorted((root/'frontend/dist').rglob('*'))
    files = {}
    for path in paths:
        if path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError(f'Unsafe application resource: {path}')
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'format': FORMAT, 'files':files}


def verify_resources(root, *, require_manifest=False):
    root = Path(root).resolve()
    actual = inventory(root)
    path = root/MANIFEST
    if require_manifest or path.exists():
        if not path.is_file():
            raise ValueError(f'Missing resource manifest: {path}')
        expected = json.loads(path.read_text(encoding='utf-8'))
        if expected.get('format') != FORMAT or not isinstance(expected.get('files'),dict):
            raise ValueError(f'Invalid resource manifest: {path}')
        if expected != actual:
            changed = sorted(k for k in set(expected['files']) | set(actual['files']) if expected['files'].get(k) != actual['files'].get(k))
            raise ValueError(f'Resource integrity mismatch under {root}: {changed}')
    return actual
