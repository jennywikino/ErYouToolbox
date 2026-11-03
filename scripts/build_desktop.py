"""Build an allowlisted Windows portable candidate using an isolated environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.5.0-rc1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packaging-python', type=Path, default=Path(os.environ['LOCALAPPDATA'])/'ErYouToolbox/packaging-venv/Scripts/python.exe')
    parser.add_argument('--output', type=Path, default=ROOT/'dist'/('desktop-'+VERSION))
    args = parser.parse_args()
    platform_info = json.loads(subprocess.check_output([str(args.packaging_python), '-c',
        "import json,platform,struct; print(json.dumps({'system':platform.system(),'machine':platform.machine(),'bits':struct.calcsize('P')*8}))"],text=True))
    if platform_info != {'system':'Windows','machine':'AMD64','bits':64}:
        parser.error('Packaging requires a Windows AMD64 64-bit Python environment')
    if not (ROOT/'frontend/dist/index.html').is_file():
        parser.error('Run the production frontend build first')
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/'dist').resolve()) or output == (ROOT/'dist').resolve():
        parser.error('Build output must be a new directory inside project dist')
    if output.exists():
        parser.error('Output exists; preserve it before choosing a fresh build destination')
    output.mkdir(parents=True)
    git_sha = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty = bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    command = [str(args.packaging_python), '-m','PyInstaller','--noconfirm','--onedir','--windowed',
               '--name','ErYouToolbox','--distpath',str(output),'--workpath',str(ROOT/'logs/desktop-build/work'),
               '--specpath',str(ROOT/'logs/desktop-build'), '--paths',str(ROOT/'src'),'--paths',str(ROOT/'scripts'),
               '--collect-all','webview','--collect-all','pythonnet','--collect-all','clr_loader',
               '--hidden-import','history_sync','--hidden-import','eryoutoolbox.author_updates',
               '--add-data',f'{ROOT / "frontend/dist"};frontend/dist',
               '--add-data',f'{ROOT / "config/games.json"};config',
               '--add-data',f'{ROOT / "config/content_ratings.json"};config',str(ROOT/'scripts/desktop_app.py')]
    subprocess.run(command,cwd=ROOT,check=True)
    package = output/'ErYouToolbox'
    versions = json.loads(subprocess.check_output([str(args.packaging_python),'-c',
        "import importlib.metadata as m,json,platform; print(json.dumps({'python':platform.python_version(),**{n:m.version(n) for n in ['pywebview','pythonnet','pyinstaller','httpx']}}))"],text=True))
    manifest={'version':VERSION,'source_commit':git_sha,'working_tree_dirty':dirty,'platform':platform_info,'dependencies':versions}
    (package/'BUILD_INFO.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (package/'README.txt').write_text(
        'ErYouToolbox '+VERSION+' Windows x64 portable candidate\n'
        'Extract the whole folder, then double-click ErYouToolbox.exe. Requires Microsoft Edge WebView2 Evergreen Runtime.\n'
        'First launch creates an EMPTY library in userdata next to the EXE. No personal database is included.\n'
        'Keep userdata when updating. Close the app and pause all writers before backup or moving drives.\n'
        'Do not copy an active development database here. Existing personal data migration is not automatic.\n'
        'Background scheduled tasks are NOT supported. Checks run only while the client is open.\n'
        'Automatic mode starts OFF. Python, Node and Vite are not required to run the EXE.\n'
        'Logs: userdata/logs/desktop.log. Unsigned candidate; clean-machine acceptance is still required.\n',encoding='utf-8')
    forbidden={'userdata','data','logs','node_modules','.git','__pycache__'}
    for path in package.rglob('*'):
        relative=path.relative_to(package)
        if any(p in forbidden for p in relative.parts) or path.suffix.lower() in ('.db','.sqlite','.env','.har'):
            raise RuntimeError(f'Forbidden package entry: {relative}')
    archive=output/f'ErYouToolbox-{VERSION}-win-x64.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(package.rglob('*')):
            if path.is_file():zipped.write(path,Path('ErYouToolbox')/path.relative_to(package))
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'sha256':digest,**manifest},indent=2))


if __name__=='__main__':main()
