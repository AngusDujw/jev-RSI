"""Build balanced signed-motion examples from independent real recordings."""
import argparse
import hashlib
import json
from pathlib import Path

from libero_held_motion_demo import compose_example


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--recordings',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();records=[]
    for axis in ('rx','ry','rz'):
        pair=[]
        for sign,name in ((1,'positive'),(-1,'negative')):
            directory=args.recordings/(name+'-'+axis)
            r=json.loads((directory/'result.json').read_text())
            if r.get('kind')!='offline_held_motion_example' or r.get('model_calls')!=0 or r.get('native_evaluated') is not False:
                raise ValueError('Expected independent non-policy example recordings')
            measured=r['measured_rotation_world_deg'];i=('rx','ry','rz').index(axis)
            if measured[i]*sign<.75*abs(r['requested_rotation_deg']):raise ValueError('Requested own rotation was not demonstrated')
            if sum(v*v for j,v in enumerate(measured) if j!=i)>25:raise ValueError('Example has a large other-axis rotation')
            if sum(v*v for v in r['measured_translation_mm'])>225:raise ValueError('Example has a large position drift')
            for t in ('before','after'):
                for camera in ('agentview','sideview'):
                    if not (directory/(t+'-'+camera+'-detail.png')).exists():raise ValueError('Actual example view missing')
            pair.append((directory,r))
        records.append((axis,pair))
    positions=[r['prefix_final_own_position_mm'] for _,pair in records for _,r in pair]
    if any(sum((x-y)**2 for x,y in zip(p,positions[0]))>1 for p in positions):
        raise ValueError('Independent examples do not share the same measured own starting position')
    args.output.mkdir(parents=True,exist_ok=False)
    from PIL import Image
    parts=[];provenance=[]
    for axis,pair in records:
        cards=[compose_example(directory,axis,r['sign'],abs(r['requested_rotation_deg'])) for directory,r in pair]
        combined=Image.new('RGB',(2048,1160),'#10222a')
        for i,card in enumerate(cards):combined.paste(card,(0,i*580))
        file=axis+'.png';combined.save(args.output/file)
        sha=hashlib.sha256((args.output/file).read_bytes()).hexdigest()
        measured=[r['measured_rotation_world_deg'] for _,r in pair]
        caption=(f'ARCHIVED actual held-bottle rotation examples about fixed world {axis[-1].upper()}. '
            'Top row is a positive increment; bottom row is an independently reset negative increment. '
            'Within each row the left two panels are BEFORE fixed agentview/sideview; the right two are AFTER. '
            'The gripper retained close and no translation was requested during each rotation. '
            'Measured own world rotation-vector changes in degrees, positive then negative examples: '+json.dumps(measured)+'. '
            'Use the actual bottle and finger changes to understand the motion effect. '
            'These are historical examples, not CURRENT observations, target angles, policy successes or candidate next actions. '
            'Neither holding nor rigid object following is certified by the own motion; inspect the visible object changes.')
        parts.extend([dict(type='input_text',text=caption),dict(type='input_image',file=file,sha256=sha)])
        provenance.extend(dict(directory=str(directory.resolve()),**r) for directory,r in pair)
    task=str(provenance[0]['task'])
    if any(str(r['task'])!=task for r in provenance):raise ValueError('Examples use different tasks')
    (args.output/'bank.json').write_text(json.dumps(dict(tasks={task:parts},source='Balanced actual held-object motion recordings; no evaluator or target error.',recordings=provenance),indent=2)+'\n')
    print(json.dumps(dict(images=3,recordings=6,api_calls=0,bank=str(args.output/'bank.json'))))


if __name__=='__main__':main()
