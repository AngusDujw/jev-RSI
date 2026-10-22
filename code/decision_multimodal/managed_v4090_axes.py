"""Compact native campaign; resource-gated concurrency and independent API bridge."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time


def scheduler(path):
    cfg=json.loads(path.read_text());root=path.parent
    queued=list(cfg['cases']);active={};done=[]
    while queued or active:
        for name,(proc,log) in list(active.items()):
            if proc.poll() is not None:
                log.close();done.append(dict(name=name,returncode=proc.returncode));del active[name]
                case=next(c for c in cfg['cases'] if c['name']==name)
                if case.get('experience_snapshot') and (Path(case['output'])/'execution.jsonl').exists():
                    from experience_harness import public_trace_facts
                    facts=public_trace_facts(case['output'])
                    (Path(case['output'])/'public-experience-facts.json').write_text(json.dumps(facts,indent=2)+'\n')
        limit=json.loads((root/'concurrency.json').read_text())['limit']
        free=int(subprocess.check_output(['nvidia-smi','--id=0','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())
        available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))/1024
        while queued and len(active)<limit and free>2500 and available>5000:
            if shutil.disk_usage(root).free<8*1024**3:raise RuntimeError('DataStorage free-space guard')
            case=queued.pop(0);out=Path(case['output']);out.parent.mkdir(parents=True,exist_ok=True)
            if out.exists():raise FileExistsError(out)
            log=(root/(case['name']+'.log')).open('w')
            env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',NUMBA_NUM_THREADS='1',
                TMPDIR=str(root/'cache'),XDG_CACHE_HOME=str(root/'cache'),PYTHONDONTWRITEBYTECODE='1',
                MAGICK_HOME=cfg['runtime_libs']+'/usr',
                LD_LIBRARY_PATH=cfg['runtime_libs']+'/usr/lib/x86_64-linux-gnu'+(':'+os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else ''))
            command=[cfg['python'],'-B',str(Path(cfg['project'])/case.get('entrypoint','code/decision_multimodal/libero_direct_axes.py')),
                '--task',str(case['task']),'--init',str(case['init']),'--gpu','0','--output',case['output'],
                '--plan',case['plan'],'--libero-root',cfg['libero_root'],'--example-bank',cfg['example_bank'],
                '--input-variant',case['variant'],'--grounded','--relation-prompts','--surface-context',
                '--coordinate-questions','--adaptive-steps','--file-transport','--compact']
            if case['variant']!='task_native_frame':command+=['--positive-frame']
            if case.get('record_evidence'):command+=['--record-evidence']
            if case.get('live_surfaces'):command+=['--live-surfaces']
            if case.get('actor_attention'):command+=['--actor-attention']
            if case.get('focused_questions'):command+=['--focused-questions']
            if case.get('relative_step_scale'):command+=['--relative-step-scale']
            if case.get('numeric_xy'):command+=['--numeric-xy']
            if case.get('reference_history'):command+=['--reference-history']
            if case.get('protocol_file'):command+=['--protocol-file',case['protocol_file']]
            if case.get('live_protocol'):command+=['--live-protocol']
            if case.get('scoped_reference_call'):command+=['--scoped-reference-call']
            if case.get('fin_central_samples'):command+=['--fin-central-samples']
            if case.get('held_example_bank'):command+=['--held-example-bank',case['held_example_bank']]
            if case.get('scene_example_bank'):command+=['--scene-example-bank',case['scene_example_bank']]
            if case.get('rotation_effect_hints'):command+=['--rotation-effect-hints']
            if case.get('bound_span_rotation'):command+=['--bound-span-rotation']
            if case.get('literal_line_reasoning'):command+=['--literal-line-reasoning']
            if case.get('sideview_source_fallback'):command+=['--sideview-source-fallback']
            if case.get('multiview_source_samples'):command+=['--multiview-source-samples']
            if case.get('paired_span_selection'):command+=['--paired-span-selection']
            if case.get('span_intent_history'):command+=['--span-intent-history']
            if case.get('posture_task_exit'):command+=['--posture-task-exit']
            if case.get('upper_neck_sample'):command+=['--upper-neck-sample']
            if case.get('candidate_detail_cards'):command+=['--candidate-detail-cards']
            if case.get('span_detail_cards'):command+=['--span-detail-cards']
            if case.get('literal_placement_rotation'):command+=['--literal-placement-rotation']
            if case.get('separate_rotation_call'):command+=['--separate-rotation-call']
            if case.get('visible_shape_features'):command+=['--visible-shape-features']
            if case.get('formal_stage_call'):command+=['--formal-stage-call']
            if case.get('numeric_axis_call'):command+=['--numeric-axis-call']
            if case.get('reference_only'):command+=['--reference-only']
            if case.get('overview_camera'):command+=['--overview-camera',case['overview_camera']]
            if case.get('goal_example'):command+=['--goal-example']
            if case.get('raised_fin_surfaces'):command+=['--raised-fin-surfaces']
            if case.get('part_questions'):command+=['--part-questions']
            if case.get('retain_rotation_examples'):command+=['--retain-rotation-examples']
            if case.get('stage_motion'):command+=['--stage-motion']
            if case.get('receiver_surfaces'):command+=['--receiver-surfaces']
            if case.get('sideview_receiver_samples'):command+=['--sideview-receiver-samples']
            if case.get('pad_outlines'):command+=['--pad-outlines']
            if case.get('visual_near_grasp'):command+=['--visual-near-grasp']
            if case.get('numeric_z'):command+=['--numeric-z']
            if case.get('track_selected'):command+=['--track-selected']
            if case.get('source_motion_test'):command+=['--source-motion-test']
            if case.get('free_placement_posture'):command+=['--free-placement-posture']
            if case.get('robot_self_mask'):command+=['--robot-self-mask']
            command+=['--horizon',str(case.get('horizon',600))]
            if case.get('decisions'):command+=['--decisions',str(case['decisions'])]
            if case.get('wall_seconds'):command+=['--wall-seconds',str(case['wall_seconds'])]
            if case.get('omit_example_kind'):
                command+=['--omit-example-kind',case['omit_example_kind'],'--frozen-source',case['frozen_source']]
            if case.get('experience_snapshot'):
                command+=['--experience-snapshot',case['experience_snapshot'],
                          '--experience-sha256',case['experience_sha256'],
                          '--experience-mode',case['experience_mode'],
                          '--frozen-source',case['frozen_source'],
                          '--frozen-source-sha256',case['frozen_source_sha256']]
            elif case.get('budget_audit'):
                command+=['--frozen-source',case['frozen_source']]
            if case.get('rotation_strategy_file'):
                command+=['--rotation-strategy-file',case['rotation_strategy_file'],
                          '--rotation-strategy-sha256',case['rotation_strategy_sha256']]
            command+=['--execution-steps',str(case.get('execution_steps',4))]
            proc=subprocess.Popen(command,cwd=cfg['project'],env=env,stdout=log,stderr=subprocess.STDOUT)
            active[case['name']]=(proc,log);free-=1500;available-=2000
        status=dict(time=time.time(),active=[dict(name=n,pid=p.pid) for n,(p,_) in active.items()],
            queued=len(queued),finished=done,limit=limit,gpu_free_mib=free,mem_available_mib=available)
        part=root/'status.part';part.write_text(json.dumps(status,indent=2));part.replace(root/'status.json')
        time.sleep(3)


def bridge(path):
    cfg=json.loads(path.read_text());root=path.parent;deadline=time.monotonic()+28800
    while time.monotonic()<deadline:
        cfg=json.loads(path.read_text())
        if cfg.get('api_http2') and cfg.get('api_http_pool'):raise ValueError('Choose one local HTTP mode')
        command=[sys.executable,'-B',str(Path(__file__).with_name('decision_file_bridge.py')),
            '--host',cfg['host'],'--remote-roots',*[c['output'] for c in cfg['cases']],
            '--key-file',str(Path.cwd()/'.private/du-openai-direct.key'),'--output',str(root/'bridge'),
            '--resume','--compact','--workers',str(cfg.get('api_workers',12)),'--seconds',str(max(1,int(deadline-time.monotonic()))),
            '--control-path',cfg.get('control_path','code/runs/v4090-dm-20261019.sock')]
        if cfg.get('api_http2'):command+=['--http2']
        elif cfg.get('api_http_pool'):command+=['--http-pool']
        with (root/'bridge.log').open('a') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode==0:return
        time.sleep(2)
    raise TimeoutError('Campaign bridge wall budget exhausted; results retained')


def main():
    p=argparse.ArgumentParser();p.add_argument('--scheduler',type=Path);p.add_argument('--bridge',type=Path)
    a=p.parse_args()
    if a.scheduler:scheduler(a.scheduler.resolve())
    elif a.bridge:bridge(a.bridge.resolve())
    else:p.error('Choose --scheduler or --bridge')


if __name__=='__main__':main()
