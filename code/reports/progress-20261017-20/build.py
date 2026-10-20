"""Build a self-contained, evidence-backed four-day progress report; no model calls."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'code/runs/2026-10-20-four-day-report/dist'
DM = ROOT / '.worktrees/decision-multimodal-20261016'
ROBO = ROOT / '.worktrees/robodojo-review-site-20261013'
OLD = DM / 'code/runs/2026-10-17-libero-input-site/dist'
OUT.mkdir(parents=True, exist_ok=True)
manifest = []


def record(dest, source):
    manifest.append({'file': str(dest.relative_to(OUT)), 'source': str(source),
                     'bytes': dest.stat().st_size,
                     'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})


def copy(source, target):
    dest = OUT / target
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    record(dest, source.relative_to(ROOT))


for name in ['index.html', 'style.css', 'app.js', 'data.json']:
    copy(HERE / name, name)
data_js = OUT / 'data.js'
data_js.write_text('window.REPORT_DATA=' + (HERE / 'data.json').read_text() + ';\n')
record(data_js, 'data.json [same values, local-file-compatible JavaScript assignment]')
for base, label in [(DM, 'multimodal'), (ROBO, 'robodojo')]:
    for week in ['2026-W42', '2026-W43']:
        copy(base / f'LOGS/{week}.md', f'sources/{label}-{week}.md')
copy(ROOT / 'LOGS/2026-W42.md', 'sources/main-2026-W42.md')
for name in ['LIBERO_MOTION_MM_RESULTS', 'LIBERO_GRIPPER_PAIR_RESULTS',
             'LIBERO_HYBRID_RESULTS', 'LIBERO_ROTATION_RESULTS']:
    copy(DM / f'code/decision_multimodal/{name}.md', f'sources/{name}.md')
copy(DM / 'code/decision_multimodal/CURRENT_AXES_ITERATIONS.md', 'sources/axes-current.md')
copy(ROBO / 'code/runs/server02-policy-comparison-20261018/comparison-final-audit.json',
     'sources/comparison-final-audit.json')
copy(ROOT / 'LOGS/2026-10-17-server2-artifact-cleanup.md', 'sources/storage-cleanup.md')
for name in ['full-agentview.png', 'marker-agentview.png', 'axes-agentview.png']:
    copy(OLD / 'motion-sample' / name, f'assets/{name}')
for task, init in [(1335, 23), (1383, 10), (1458, 11)]:
    src = OLD / f'rotation-evidence/task-{task}-init-{init}'
    for name in ['policy-replay.mp4', 'visual-image-0.png', 'visual-image-2.png',
                 'visual-request.raw.json', 'visual-response.raw.json']:
        copy(src / name, f'assets/rotation-{task}-{name}')
for task in ['stack_blocks', 'classify_objects']:
    for trial in range(1, 6):
        name = f'decisions-{task}-trial{trial}-layout{(trial-1)%2}.mp4'
        copy(ROBO / f'code/runs/server02-policy-comparison-20261018/review-videos/{name}',
             f'assets/{name}')
for route, label in [
    ('iteration-v20-verify-knob-v20-frozen-init14', 'knob-frozen'),
    ('iteration-v28-bottle-sideview-source-fixed-init12', 'bottle-development')]:
    # Read only an existing evidence service. Preserve the exact downloaded GIF;
    # do not trigger inference, simulation, or any control endpoint.
    url = f'http://100.75.107.115:18943/{route}/rollout.gif'
    dest = OUT / f'assets/{label}.gif'
    if not dest.exists():
        with urllib.request.urlopen(url, timeout=30) as response:
            length = int(response.headers.get('Content-Length', '0'))
            if length > 40_000_000:
                raise ValueError('Evidence GIF exceeds bounded download size')
            raw = response.read(40_000_001)
        if len(raw) > 40_000_000 or raw[:6] not in (b'GIF87a', b'GIF89a'):
            raise ValueError('Invalid evidence GIF')
        dest.write_bytes(raw)
    record(dest, url)

# Make the existing historical ten-task viewer portable, keeping it separate
# from current-period results. Rewrite only its existing media URL prefix.
historical = ROOT / 'code/reports/libero-ten-workflows'
for name in ['index.html', 'viewer.js', 'data.js']:
    copy(historical / name, f'history/{name}')
copy(ROOT / 'code/LIBERO_SUCCESS_VIDEOS.md', 'sources/historical-videos.md')
history_html = OUT / 'history/index.html'
html = history_html.read_text().replace('../../LIBERO_SUCCESS_VIDEOS.md', '../sources/historical-videos.md')
html = html.replace('../libero-goal-casebook/index.html', 'https://github.com/AngusDujw/jev-RSI/blob/main/code/reports/libero-goal-casebook/index.html')
html = html.replace('早期双任务详细档案 ↗', '早期双任务网页源码（GitHub）↗')
history_html.write_text(html)
for item in manifest:
    if item['file'] == 'history/index.html':
        item['sha256'] = hashlib.sha256(history_html.read_bytes()).hexdigest()
        item['bytes'] = history_html.stat().st_size
        item['transformation'] = 'Portable source/reference links only'
for path in (historical / 'assets').iterdir():
    if path.is_file():
        copy(path, f'history/assets/{path.name}')
for path in (ROOT / 'code/runs/2026-10-15-libero-ten-success-videos').glob('goal*.mp4'):
    copy(path, f'history/videos/{path.name}')
viewer = OUT / 'history/data.js'
text = viewer.read_text()
text = text.replace('../../runs/2026-10-15-libero-ten-success-videos/', 'videos/')
viewer.write_text(text)
for item in manifest:
    if item['file'] == 'history/data.js':
        item['sha256'] = hashlib.sha256(viewer.read_bytes()).hexdigest()
        item['bytes'] = viewer.stat().st_size
        item['transformation'] = 'Only historical video URL prefix rewritten for portability'
history_js = OUT / 'history/viewer.js'
js = history_js.read_text()
js = js.replace("a.href='../../scripts/'+f;", "a.href='https://github.com/AngusDujw/jev-RSI/blob/'+current.commit+'/code/scripts/'+f;")
js = js.replace("$('source').href=raw==='execution'?'../../runs/'+current.source_run+'/episode/branches.jsonl':d.source+raw+'.json';", "$('source').href='#';$('source').textContent='下载当前记录 JSON（按原值重新排版）';$('source').onclick=e=>{e.preventDefault();$('download').click();};")
history_js.write_text(js)
for item in manifest:
    if item['file'] == 'history/viewer.js':
        item['sha256'] = hashlib.sha256(history_js.read_bytes()).hexdigest()
        item['bytes'] = history_js.stat().st_size
        item['transformation'] = 'Portable source/download links only; original data unchanged'
heads = {}
for label, path in [('main', ROOT), ('multimodal', DM), ('robodojo', ROBO)]:
    heads[label] = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
(OUT / 'manifest.json').write_text(json.dumps({
    'built_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
    'period': ['2026-10-17', '2026-10-20'],
    'source_heads': heads, 'files': manifest,
    'note': 'Read-only report. Worktree EXP IDs overlap; source labels are part of every identity.'
}, ensure_ascii=False, indent=2))
print(json.dumps({'output': str(OUT), 'files': len(manifest),
                  'bytes': sum(x['bytes'] for x in manifest)}, ensure_ascii=False))
