"""Select official layouts/assets without exposing them to the policy worker."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request
from urllib.parse import quote

TASKS=['general_pickup','fold_clothes','press_by_number','match_and_pick_from_conveyor','stack_bowls']


def valid(path,entry):
    if not path.is_file() or path.stat().st_size!=entry['size']: return False
    h=hashlib.sha256() if entry.get('lfs') else hashlib.sha1()
    if not entry.get('lfs'): h.update(f"blob {entry['size']}\0".encode())
    with path.open('rb') as stream:
        for b in iter(lambda:stream.read(1048576),b''): h.update(b)
    return h.hexdigest()==(entry['lfs']['sha256'] if entry.get('lfs') else entry['blobId'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index',type=Path,required=True)
    p.add_argument('--existing-manifest',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--layouts',type=int,default=5)
    p.add_argument('--tasks',choices=TASKS,nargs='+',default=TASKS)
    p.add_argument('--socks-proxy',help='Authorized host:port for curl SOCKS5 remote DNS')
    p.add_argument('--download',action='store_true')
    a=p.parse_args()
    index=json.loads(a.index.read_text())
    entries={x['rfilename']:x for x in index['siblings'] if x['rfilename'].startswith('Assets/')}
    old={x['rfilename']:x for x in json.loads(a.existing_manifest.read_text())['files']}
    revision=index['sha']
    def fetch(name):
        e=entries[name]; path=a.root/name
        if valid(path,e): return path
        if path.exists(): raise FileExistsError(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        url=f'https://huggingface.co/datasets/RoboDojo-Benchmark/RoboDojo/resolve/{revision}/{quote(name)}'
        partial=path.with_name(path.name+'.download')
        for attempt in range(4):
            try:
                if a.socks_proxy:
                    subprocess.run(['curl','--fail','--silent','--show-error','--location',
                        '--connect-timeout','15','--max-time','90','--socks5-hostname',
                        a.socks_proxy,'--output',str(partial),url],check=True)
                else:
                    with urllib.request.urlopen(url,timeout=90) as response,partial.open('wb') as output:
                        while True:
                            b=response.read(1048576)
                            if not b: break
                            output.write(b)
                break
            except (OSError,urllib.error.URLError,subprocess.CalledProcessError):
                if attempt==3: raise
                time.sleep(2**attempt)
        if not valid(partial,e): raise ValueError('Asset checksum mismatch: '+name)
        partial.rename(path)
        return path
    cases=[]
    for task in a.tasks:
        variants=[task,task+'_random'] if task in ('fold_clothes','stack_bowls') else [task]
        for runtime in variants:
            for layout in range(a.layouts):
                name=f'Assets/Eval_Layout/RoboDojo/arx_x5/0/{runtime}_{layout}.json'
                if name not in entries: raise ValueError('Missing official layout: '+name)
                cases.append(dict(task=task,runtime_task=runtime,layout_id=layout,eval_seed=0,layout=name,
                                  split='development' if layout<3 else 'frozen_candidate'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths=list(pool.map(fetch,[c['layout'] for c in cases]))
    exact={c['layout'] for c in cases}
    prefixes={'Assets/Robots/x5/','Assets/Robots/franka/'}
    for c,path in zip(cases,paths):
        c['layout_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        scene=json.loads(path.read_text())
        for kind in {'Rigid','Dynamic','Geometry','Articulation','Garment','Fluid'} & scene.keys():
            for category,objects in scene[kind].items():
                for obj in objects:
                    folder='Clutter' if obj.get('type')=='cluttered' else kind
                    prefixes.add(f"Assets/Object/RoboDojo/{folder}/{category}/{obj['category_idx']:05d}/")
        prefixes.update([f"Assets/Room/{scene['Room']['default']}/",
                         f"Assets/Material/{scene['Ground']['materials']['default']}/"])
        if 'Table' in scene:
            prefixes.add(f"Assets/Material/{scene['Table']['default']}/")
        exact.add('Assets/Background/'+scene['Background']['category_name'])
        for m in re.finditer(r'(?:\$\{?ASSETS_PATH\}?|\$Robo[Dd]ojo_ASSETS|Assets)/([^"\s]+)',json.dumps(scene)):
            name='Assets/'+m[1]
            if name in entries: prefixes.add(str(Path(name).parent)+'/')
            elif any(x.startswith(name.rstrip('/')+'/') for x in entries): prefixes.add(name.rstrip('/')+'/')
            else: raise ValueError('Unresolved scene asset: '+name)
    for prefix in prefixes:
        if not any(x.startswith(prefix) for x in entries): raise ValueError('Missing prefix: '+prefix)
    selected=exact|{x for x in entries if any(x.startswith(p) for p in prefixes) and '/.thumbs/' not in x}
    files=[entries[x] for x in sorted(selected)]
    missing=[e for e in files if old.get(e['rfilename'])!=e and not valid(a.root/e['rfilename'],e)]
    size=sum(e['size'] for e in missing)
    manifest=dict(repository='RoboDojo-Benchmark/RoboDojo',revision=revision,cases=cases,files=files,
        additional_download_bytes=size,missing_files=[e['rfilename'] for e in missing],
        source='official HF data; reused files must be verified on server before launch')
    a.manifest.parent.mkdir(parents=True,exist_ok=True)
    a.manifest.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(cases=len(cases),files=len(files),missing=len(missing),additional_bytes=size)),flush=True)
    if a.download:
        if size>4_500_000_000: raise RuntimeError('Download exceeds 4.5GB preflight cap; approval required')
        with ThreadPoolExecutor(max_workers=4) as pool:
            for i,_ in enumerate(pool.map(fetch,[e['rfilename'] for e in missing]),1):
                if i%20==0 or i==len(missing): print(f'verified {i}/{len(missing)}',flush=True)


if __name__=='__main__': main()
