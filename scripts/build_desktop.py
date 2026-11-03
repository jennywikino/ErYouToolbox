"""Build an allowlisted Windows portable candidate using an isolated environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from eryoutoolbox.app_resources import inventory, verify_resources, MANIFEST
VERSION = '0.5.0-rc3'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packaging-python', type=Path, default=Path(os.environ['LOCALAPPDATA'])/'ErYouToolbox/packaging-venv/Scripts/python.exe')
    parser.add_argument('--output', type=Path, default=ROOT/'dist'/('desktop-'+VERSION))
    args = parser.parse_args()
    platform_info = json.loads(subprocess.check_output([str(args.packaging_python), '-c',
        "import json,platform,struct; print(json.dumps({'system':platform.system(),'machine':platform.machine(),'bits':struct.calcsize('P')*8}))"],text=True))
    if platform_info != {'system':'Windows','machine':'AMD64','bits':64}:
        parser.error('Packaging requires a Windows AMD64 64-bit Python environment')
    resources = inventory(ROOT)  # Fail before building if JSON or any HTML entry asset is missing.
    if not (ROOT/'assets/branding/windows_version.txt').is_file():
        parser.error('Missing Windows brand version metadata')
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/'dist').resolve()) or output == (ROOT/'dist').resolve():
        parser.error('Build output must be a new directory inside project dist')
    if output.exists():
        parser.error('Output exists; preserve it before choosing a fresh build destination')
    output.mkdir(parents=True)
    build = ROOT/'logs/desktop-build'/output.name
    build.mkdir(parents=True, exist_ok=True)
    resource_manifest = build/MANIFEST
    resource_manifest.write_text(json.dumps(resources,indent=2),encoding='utf-8')
    git_sha = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty = bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    command = [str(args.packaging_python), '-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
               '--name','妙妙二玩箱','--icon',str(ROOT/'assets/branding/MiaomiaoEryouxiang_icon.ico'),'--version-file',str(ROOT/'assets/branding/windows_version.txt'),'--distpath',str(output),'--workpath',str(build/'work'),
               '--specpath',str(build), '--paths',str(ROOT/'src'),'--paths',str(ROOT/'scripts'),
               '--collect-all','webview','--collect-all','pythonnet','--collect-all','clr_loader',
               '--hidden-import','history_sync','--hidden-import','eryoutoolbox.author_updates',
               '--add-data',f'{ROOT / "frontend/dist"};frontend/dist',
               '--add-data',f'{ROOT / "config/games.json"};config',
               '--add-data',f'{ROOT / "assets/branding/MiaomiaoEryouxiang_icon.ico"};assets/branding',
               '--add-data',f'{ROOT / "assets/branding/MiaomiaoEryouxiang_icon.png"};assets/branding',
               str(ROOT/'scripts/desktop_app.py')]
    command[-1:-1] = ['--add-data', f'{resource_manifest};.']
    subprocess.run(command,cwd=ROOT,check=True)
    package = output/'ErYouToolbox'
    (output/'妙妙二玩箱').rename(package)
    # Compare actual PE icon payloads to the supplied ICO, not Explorer's cache.
    icon_check = """import pefile,struct,sys,hashlib,json
from pathlib import Path
raw=Path(sys.argv[2]).read_bytes(); count=struct.unpack_from('<H',raw,4)[0]
expected=[]
for i in range(count):
 size,offset=struct.unpack_from('<II',raw,6+i*16+8); expected.append(hashlib.sha256(raw[offset:offset+size]).hexdigest())
pe=pefile.PE(sys.argv[1]); actual=[]
for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
 if entry.id==3:
  for image in entry.directory.entries:
   for lang in image.directory.entries:
    data=lang.data.struct; actual.append(hashlib.sha256(pe.get_data(data.OffsetToData,data.Size)).hexdigest())
assert sorted(actual)==sorted(expected), 'EXE icon differs from supplied ICO'
print(json.dumps({'embedded_icon_images':len(actual),'icon_matches_supplied':True}))
"""
    brand_check=json.loads(subprocess.check_output([str(args.packaging_python),'-c',icon_check,str(package/'妙妙二玩箱.exe'),str(ROOT/'assets/branding/MiaomiaoEryouxiang_icon.ico')],text=True))
    bundled = verify_resources(package/'_internal',require_manifest=True)
    if bundled != resources:
        raise RuntimeError('Packaged resources differ from pre-build inputs')
    versions = json.loads(subprocess.check_output([str(args.packaging_python),'-c',
        "import importlib.metadata as m,json,platform; print(json.dumps({'python':platform.python_version(),**{n:m.version(n) for n in ['pywebview','pythonnet','pyinstaller','httpx']}}))"],text=True))
    manifest={'version':VERSION,'build_revision':'OB6-E2-F6','display_name':'妙妙二玩箱','executable':'妙妙二玩箱.exe','source_commit':git_sha,'working_tree_dirty':dirty,'platform':platform_info,'dependencies':versions,'resource_manifest':'_internal/'+MANIFEST}
    manifest.update(brand_check)
    (package/'BUILD_INFO.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    # Reproduce actual third-party notices without collecting environment or
    # installation metadata (direct_url, credentials, paths, etc.).
    license_code="import importlib.metadata as m,json; names=['pywebview','pythonnet','PyInstaller','httpx','clr_loader']; print(json.dumps({n:{str(f):m.distribution(n).locate_file(f).read_text(encoding='utf-8') for f in m.distribution(n).files or [] if '.dist-info' in str(f) and any(k in f.name.lower() for k in ['license','copying'])} for n in names}))"
    notices=json.loads(subprocess.check_output([str(args.packaging_python),'-c',license_code],text=True,encoding='utf-8'))
    if any(not value for value in notices.values()):raise RuntimeError('Missing required Python dependency license')
    for name,filename in [('react','LICENSE'),('react-dom','LICENSE'),('vite','LICENSE.md'),('tailwindcss','LICENSE'),('typescript','LICENSE')]:
        notices[name]={filename:(ROOT/'frontend/node_modules'/name/filename).read_text(encoding='utf-8')}
    (package/'THIRD_PARTY_NOTICES.json').write_text(json.dumps(notices,ensure_ascii=False,indent=2),encoding='utf-8')
    (package/'CANDIDATE_NOTES.md').write_bytes((ROOT/'docs/PRERELEASE_0_5_0_RC3.md').read_bytes())
    (package/'README.txt').write_text(
        '妙妙二玩箱 (ErYouToolbox) '+VERSION+' Windows x64 portable candidate\n'
        'Extract the whole folder, then double-click 妙妙二玩箱.exe. Requires Microsoft Edge WebView2 Evergreen Runtime.\n'
        'First launch creates an EMPTY library in userdata next to the EXE. No personal database is included.\n'
        'Keep userdata when updating. Close the app and pause all writers before backup or moving drives.\n'
        'Do not copy an active development database here. Existing personal data migration is not automatic.\n'
        'Background scheduled tasks are NOT supported. Checks run only while the client is open.\n'
        'Automatic mode starts OFF until explicit first-use consent; saved settings are never replaced.\n'
        'While open, the client checks due-time once per minute. Closing it stops future checks.\n'
        'Python, Node and Vite are not required to run the EXE.\n'
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
