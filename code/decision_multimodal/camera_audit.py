"""Compare two public camera-calibration paths without stepping the scene."""
import importlib.util
import json
from pathlib import Path
import numpy as np
from robodojo_episode import save,wait_command
from rgb_plane import fit_horizontal_texture


def run(ep):
    raw=ep.rpc('public_camera_calibration')['cameras']
    propagated=ep.public['calibration']
    report=dict(step=ep.tick,public_render_parent_calibration=raw,client_propagated_calibration=propagated,
        delta_norms={n:float(np.linalg.norm(np.asarray(raw[n]['camera_to_environment'])-np.asarray(propagated[n]['camera_to_environment']))) for n in raw},
        scope='Only public camera calibration and measured robot propagation, never object poses or native results')
    # Independently test the supplied transforms against actual table texture.
    report['raw_texture_check']=fit_horizontal_texture(dict(ep.public,calibration=raw))
    report['propagated_texture_check']=fit_horizontal_texture(ep.public)
    save(ep.folder/f'camera-audit-step{ep.tick}.json',report)
    print(json.dumps(dict(event='public_camera_audit_ready',step=ep.tick,delta_norms=report['delta_norms'])),flush=True)
    request=wait_command(ep)
    if request.get('op')=='finish':
        return
    if request.get('op')!='run_controller':
        raise ValueError('Expected fixed controller path or finish')
    path=Path(request['controller']).resolve()
    spec=importlib.util.spec_from_file_location('after_camera_audit',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.run(ep)
