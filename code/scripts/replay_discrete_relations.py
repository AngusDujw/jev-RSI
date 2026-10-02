"""Temporary model-only test: identical observed errors, three representations."""
import copy,json,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2];run=root/'code/runs/jev-discrete-stack_bowls-04'
q=sorted(run.glob('decision-*/request.json'))[-1]
cfg=json.loads((run/'protocol.json').read_text());sys.path.insert(0,cfg['existing_root']+'/controller/src')
from realman_jev.api import API
out=run.parent/(run.name+'-relations-replay');out.mkdir(exist_ok=False)
api=API(json.loads(Path(cfg['api_config']).read_text())['jev'],lambda e:print(json.dumps(e),flush=True),'jev')
original=json.loads(q.read_text());base=original['state'];variants=[]
for name in ['original_relations','explicit_relations','numeric_same_errors']:
 s=copy.deepcopy(base)
 if name=='explicit_relations':
  for axes in s['relations'].values():
   for axis,v in axes.items():v['target_minus_current_grasp_mm']=v.pop('signed_distance_mm')
 if name=='numeric_same_errors':
  s['geometry']={}
  for a,axes in s.pop('relations').items():
   current=s['robot'][a]['grasp'];errors=[axes[x]['signed_distance_mm']/1000 for x in 'xyz']
   s['geometry'][a]=dict(current_grasp_xyz_m=current,target_minus_grasp_m=errors,target_xyz_m=[c+e for c,e in zip(current,errors)])
 questions={k:v for k,v in original['questions'].items() if k.endswith(('_x','_y','_z'))}
 if name!='original_relations':
  for k,v in questions.items():v['instructions']='Choose sign for '+k+'. Error means target minus CURRENT grasp, in world axes. Positive error means positive motion, negative means negative motion. Relation errors are millimetres, dead_zone_m is metres; convert units. Hold inside dead zone.'
 payload=dict(model=api.cfg['model'],state=s,questions=questions);variants.append((name,payload))
try:
 for name,payload in variants:
  (out/(name+'-request.json')).write_text(json.dumps(payload,indent=2))
  answer=api.post('/systemone',payload);(out/(name+'-response.json')).write_text(json.dumps(answer,indent=2));print(name,answer.get('answers'),flush=True)
finally:api.close()
