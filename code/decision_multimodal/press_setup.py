"""Acquire cap geometry, then keep this native episode for its task controller."""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
from camera_view import acquire
from rgb_cuboid import ray
from rgb_plane import fit_horizontal_texture
from rgb_circle import fit_cap
from robodojo_episode import save


def run(ep):
    table=fit_horizontal_texture(ep.public)
    save(ep.folder/'table_geometry.json',table)
    if not table.get('usable'):
        save(ep.folder/'program_result.json',dict(program_finished=False,stop_reason='Current table texture model unavailable'))
        return
    camera=ep.public['calibration']['cam_high']
    origin,direction=ray(camera,[244,267])
    point=origin+direction*((table['plane_z_m']+.010-origin[2])/direction[2])
    if not acquire(ep,point,'left','first_red_cap'):
        save(ep.folder/'program_result.json',dict(program_finished=False,stop_reason='Active first-cap camera acquisition incomplete'))
        return
    fits={}
    for label,pixel,color in [('red_1',[244,267],'red'),('red_9',[320,267],'red'),('blue',[396,267],'blue')]:
        fits[label]=fit_cap(ep.public,pixel,color,table['plane_z_m'])
    save(ep.folder/'button_geometry.json',dict(table=table,caps=fits,step=ep.tick,
        source='Current RGB and public calibration only; digit identities1/9 from saved Pro image plan'))
    print(json.dumps(dict(event='current_button_geometry_ready',step=ep.tick,output=str(ep.folder))),flush=True)
    # The outer experiment agent can inspect these actual observations and
    # compile a revised fixed task controller without resetting this episode.
    request=json.loads(sys.stdin.readline())
    if request.get('op')=='finish':
        return
    if request.get('op')!='run_controller':
        raise ValueError('Expected explicit fixed task controller or finish')
    path=Path(request['controller']).resolve()
    spec=importlib.util.spec_from_file_location('current_button_task',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.run(ep)
