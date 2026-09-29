"""Structured RGB-D adapters. Every Cartesian sign is chosen by Jev.

Deterministic phase, arm, quaternion, gripper and nonnegative gain rules are
separately logged. No simulator/task implementation imports or online file I/O.
"""
from collections import deque
import re
import time
import numpy as np
from scipy.spatial.transform import Rotation
try:
    from .visual_evidence import VisualEvidence, EvidenceError, plain, tokens
except ImportError:
    from visual_evidence import VisualEvidence, EvidenceError, plain, tokens

ARMS=('left','right'); AXES=('x','y','z')
NUMBERS={w:str(i) for i,w in enumerate(('zero','one','two','three','four','five','six','seven','eight','nine','ten'))}
IGNORE=set('a an the to of on in into from up pick pickup please and then with object objects item items '
           'put place move grasp lift general stack bowl bowls block blocks cloth clothes fold button buttons '
           'press number numbered by match matching conveyor left right arm robot first second third'.split())


def quat_matrix(q):
    q=np.asarray(q,float)
    if q.shape!=(4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q)-1)>.02:
        raise EvidenceError('invalid proprioceptive quaternion')
    return Rotation.from_quat(q[[1,2,3,0]]/np.linalg.norm(q)).as_matrix()


def tool_quaternion(approach,lateral=None):
    x=np.asarray(approach,float); x=x/max(np.linalg.norm(x),1e-12)
    y=np.asarray([0,1,0] if lateral is None else lateral,float); y=y-x*np.dot(x,y)
    if np.linalg.norm(y)<.1: y=np.array([1.,0,0])-x*x[0]
    y=y/np.linalg.norm(y); z=np.cross(x,y)
    q=Rotation.from_matrix(np.column_stack([x,y,z])).as_quat()
    return q[[3,0,1,2]]


def bounded_quaternion(current,target,cap=.20):
    a=Rotation.from_matrix(quat_matrix(current)); b=Rotation.from_matrix(quat_matrix(target))
    rv=(b*a.inv()).as_rotvec(); angle=np.linalg.norm(rv)
    q=(Rotation.from_rotvec(rv*min(1.,cap/max(angle,1e-12)))*a).as_quat()
    return q[[3,0,1,2]],float(angle)


def text_score(record,text):
    return len((tokens(text)-IGNORE)&(tokens(record['label']+' '+record['appearance']+' '+record['text'])-IGNORE))


class Controller:
    def __init__(self,task: str,settings: dict):
        self.settings=dict(settings)
        name=re.sub(r'[^a-z0-9]+','_',str(task).lower()).strip('_')
        families=('general_pickup','fold_clothes','press_by_number','match_and_pick_from_conveyor','stack_bowls','stack_blocks')
        found=[f for f in families if name==f or name.startswith(f+'_') or name.endswith('_'+f)]
        if len(found)!=1: raise ValueError('unsupported task family: '+name)
        self.task=found[0]; self.task_variant=name; self.schema=settings.get('schema_variant','numeric')
        if self.schema not in ('numeric','relational'): raise ValueError('unknown schema_variant')
        step=float(settings.get('max_step_m',.04)); tolerance=float(settings.get('position_tolerance_m',.005))
        if not np.isfinite([step,tolerance]).all() or step<=0 or tolerance<=0: raise ValueError('invalid metric limits')
        self.max_step=min(.04,step); self.tolerance=min(.012,max(.001,tolerance))
        self.vision=VisualEvidence(settings); self.history=deque(maxlen=12)
        self.stage='select'; self.stage_age=0; self.stage_native=0; self.last_native=None; self.last_result=None
        self.jev_calls=0; self.jev_seconds=0.; self.started=time.monotonic(); self.step_index=0; self.remaining=15
        self.plan=None; self.completed=[]; self.stack_members=set(); self.press_index=0; self.sequence=None; self.fold_index=0
        self.recovery_count=0; self.pending=None; self.grasp_evidence=[]; self.release_evidence=[]; self.transitions=[]
        self.last_motion=None; self.stall_count=0; self.stopped=False; self.stop_reason=''
        self.current={}; self.robot={}; self.debug={}; self.instruction=None

    def _transition(self,new,evidence):
        event=dict(from_stage=self.stage,to_stage=new,evidence=plain(evidence),
                   owner='external_deterministic_scaffold',native_step=self.last_native)
        self.transitions.append(event); self.history.append(dict(event='phase_transition',**event))
        self.stage=new; self.stage_age=0; self.stage_native=self.last_native; self.stall_count=0

    def _result(self,arms=None,stop=False,reason='',ticks=4):
        if stop: self.stopped=True; self.stop_reason=reason
        debug=dict(self.debug)
        debug.update(task=self.task,task_variant=self.task_variant,schema_variant=self.schema,stage_age=self.stage_age,
            state_transitions=self.transitions,history=list(self.history),perception_cost=self.vision.last_cost,
            jev_calls=self.jev_calls,jev_seconds=self.jev_seconds,native_success_claimed=False,
            completed_visual_operations=self.completed,stack_members=sorted(self.stack_members),
            permission_boundary='RGB + depth + calibrated cameras + proprioception + public instruction only',
            rotation_gripper_arm_stage_owner='external_deterministic_scaffold',estimates=self.current,
            visual_association_events=self.vision.events,stale_measurements=[k for k,v in self.current.items() if not v['observed']])
        result=plain(dict(stage=self.stage,arms=arms or {},ticks=int(max(1,min(15,ticks,max(1,self.remaining)))),
                          stop=bool(stop),reason=str(reason),debug=debug))
        self.last_result=result
        return result

    def _recover(self,message):
        self.recovery_count+=1
        self.debug['recovery']=dict(reason=message,attempt=self.recovery_count,rule='hold all arms; force RGB relabel next observation')
        if self.recovery_count>2: return self._result(stop=True,reason='unrecoverable observation ambiguity: '+message,ticks=1)
        return self._result(reason='reacquire observations: '+message,ticks=1)

    def _get(self,oid,fresh=False):
        row=self.current.get(oid)
        if row is None or (fresh and not row['observed']): raise EvidenceError('required visible identity missing: '+str(oid))
        if row['uncertainty_m']>.025: raise EvidenceError('surface position uncertainty exceeds 25 mm: '+oid)
        return row

    def _choose(self,rows,text,allow_order=False):
        if not rows: raise EvidenceError('no visible candidates for '+text[:100])
        scored=sorted([(text_score(r,text),r['id'],r) for r in rows],key=lambda x:(-x[0],x[1]))
        if len(scored)==1 or scored[0][0]>scored[1][0]: return scored[0][2]
        if allow_order:
            return sorted(rows,key=lambda r:(-np.linalg.norm(r['high'][:2]-r['low'][:2]),r['id']))[0]
        raise EvidenceError('instruction does not uniquely identify visible candidates')

    def _read_robot(self,obs):
        r=obs['robot']; p=np.asarray(r['eef_positions'],float); q=np.asarray(r['eef_quaternions_wxyz'],float)
        s=np.asarray(r['states'],float); b=np.asarray(obs['gripper_bias_m'],float)
        if p.shape!=(2,3) or q.shape!=(2,4) or s.shape!=(14,) or b.shape!=(2,) or not np.isfinite(np.r_[p.ravel(),s,b]).all():
            raise EvidenceError('invalid robot feedback')
        self.robot={}
        for i,arm in enumerate(ARMS):
            rot=quat_matrix(q[i])
            self.robot[arm]=dict(grasp=p[i]+rot@np.array([b[i],0,0]),quaternion=q[i]/np.linalg.norm(q[i]),
                                 opening=float(s[i*7+6]),joints=s[i*7:i*7+6],link6=p[i])

    def _nearest_arm(self,point):
        return min(ARMS,key=lambda a:np.linalg.norm(self.robot[a]['grasp']-point))

    def _grasp_point(self,row,arm):
        p=row['top'].copy()
        if row['category']=='bowl':
            candidates=row.get('rim_candidates',[])
            if not candidates: raise EvidenceError('no depth-supported bowl rim sample')
            if self.plan and self.plan.get('source')==row['id'] and self.plan.get('rim_direction') is not None:
                # Preserve the selected side of the rim, instead of changing sides as the gripper moves.
                direction=self.plan['rim_direction']
                return np.asarray(max(candidates,key=lambda v:np.dot(v-row['center'],direction))).copy()
            return np.asarray(min(candidates,key=lambda v:np.linalg.norm(v-self.robot[arm]['grasp']))).copy()
        support=self.vision.support_height(p)
        p[2]-=min(.015,max(0.,float(row['high'][2]-row['low'][2])*.35))
        if support is not None: p[2]=max(p[2],support+.006)
        return p

    def _press_sequence(self,instruction,rows):
        text=instruction.lower()
        for word,num in NUMBERS.items(): text=re.sub(r'\b'+word+r'\b',num,text)
        labels=[]
        for r in rows:
            value=NUMBERS.get(r['text'].strip().lower(),r['text'].strip())
            if r['category']=='button' and re.fullmatch(r'\d+',value): labels.append(str(int(value)))
        if re.search(r'\b(?:ascending|descending|numerical order|increasing|decreasing)\b',text):
            if not labels or len(labels)!=len(set(labels)): raise EvidenceError('numeric ordering requires unique visible button labels')
            reverse=bool(re.search(r'\b(?:descending|decreasing)\b',text))
            return sorted(labels,key=int,reverse=reverse)
        if re.search(r'\b(?:times|reverse|smallest|largest)\b',text):
            raise EvidenceError('unsupported count/order wording; explicit sequence required')
        text=re.sub(r'\b\d+\s+(?:numbered\s+)?buttons?\b','buttons',text)
        ordered=re.search(r'(?:order|sequence)\s*(?:is|of|:)?\s*(.*)',text)
        section=ordered.group(1) if ordered and re.search(r'\d',ordered.group(1)) else re.split(r'\b(?:press|push)\b',text,maxsplit=1)[-1]
        values=re.findall(r'(?<![\w.\-])\d+(?![\w.])',section)
        if not values or len(values)>16: raise EvidenceError('no explicit public number sequence or numeric ordering rule')
        return [str(int(n)) for n in values]

    def _select(self):
        rows=[r for r in self.current.values() if r['observed'] and r['uncertainty_m']<=.025]
        instruction=self.instruction
        if self.task=='press_by_number':
            if self.sequence is None: self.sequence=self._press_sequence(instruction,rows)
            number=self.sequence[self.press_index]; buttons=[]
            for r in rows:
                text=NUMBERS.get(r['text'].strip().lower(),r['text'].strip().lower())
                if r['category']=='button' and re.fullmatch(r'\d+',text) and str(int(text))==number: buttons.append(r)
            if len(buttons)!=1: raise EvidenceError('need exactly one visible button with printed number '+number)
            row=buttons[0]; arm=self._nearest_arm(row['center']); normal=row['normal'].copy()
            if np.dot(normal,self.robot[arm]['grasp']-row['center'])<0: normal=-normal
            if row['plane_residual_m']>.008: raise EvidenceError('button face is not sufficiently planar')
            self.plan=dict(source=row['id'],arms=[arm],normal=normal,button_surface=row['center'].copy(),
                button_before=row['center'].copy(),quaternions={arm:tool_quaternion(-normal)},number=number,
                press_displacements=[],rule='public numeric sequence/order + exact visible OCR + measured face normal')
            self._transition('press_approach',dict(printed_number=number,identity=row['id'],surface=row['center'])); return
        if self.task=='fold_clothes':
            self._select_fold(self._choose([r for r in rows if r['category']=='cloth'],instruction)); return
        dest=None
        if self.task in ('stack_bowls','stack_blocks'):
            category='bowl' if self.task=='stack_bowls' else 'object'
            candidates=[r for r in rows if r['category']==category and r['id'] not in self.stack_members]
            if self.plan and self.plan.get('stack_base'):
                base=self._get(self.plan['stack_base'],fresh=True)
            else:
                if len(candidates)<2: raise EvidenceError('stack requires at least two separately visible items')
                marker=re.search(r'(?:on(?:\s+top\s+of)?|onto|over)\s+(.*)',instruction.lower())
                base=self._choose(candidates,marker.group(1),False) if marker else self._choose(candidates,'',True)
                self.stack_members.add(base['id'])
            candidates=[r for r in candidates if r['id'] not in self.stack_members]
            source=self._choose(candidates,instruction,allow_order=True); dest=base
        elif self.task=='match_and_pick_from_conveyor':
            objects=[r for r in rows if r['category'] in ('object','bowl') and r['id'] not in self.completed]
            references=[r for r in rows if r['category']=='reference']
            reference=self._choose(references,instruction) if len(references)>1 else (references[0] if references else None)
            text=instruction if reference is None else reference['label']+' '+reference['appearance']+' '+reference['text']
            source=self._choose(objects,text)
        else:
            split=re.split(r'\b(?:into|onto|inside|in the|on the)\b',instruction,maxsplit=1,flags=re.I)
            candidates=[r for r in rows if r['category'] in ('object','bowl','cloth','container') and r['id'] not in self.completed]
            if len(split)>1 and re.search(r'\b(?:put|place|deposit|drop)\b',instruction,re.I):
                dest=self._choose([r for r in candidates if r['category'] in ('container','bowl')],split[1])
                candidates=[r for r in candidates if r['id']!=dest['id']]
            source=self._choose(candidates,split[0])
        arm=self._nearest_arm(source['top']); grasp=self._grasp_point(source,arm)
        lateral=np.cross([0,0,-1],source['principal_axis'])
        if np.linalg.norm(lateral)<.1: lateral=np.array([0.,1,0])
        self.plan=dict(source=source['id'],destination=None if dest is None else dest['id'],arms=[arm],
            source_initial=source['center'].copy(),initial_grasp=grasp.copy(),
            rim_direction=(grasp-source['center'] if source['category']=='bowl' else None),
            quaternions={arm:tool_quaternion([0,0,-1],lateral)},baseline=None,grasp_verified=False,carry_offset=None,
            stack_base=(dest['id'] if self.task.startswith('stack_') else None),
            rule='language-grounded visual identity; measured surface grasp; nearest current grasp-point arm')
        self.grasp_evidence=[]; self.release_evidence=[]
        self._transition('approach',dict(source=source['id'],destination=self.plan['destination'],grasp=grasp))

    def _select_fold(self,cloth):
        keys=cloth['keypoints']; corners=cloth.get('corners',[]); mode='outline_half_fold'
        if all(k in keys for k in ('left_cuff','right_cuff','left_shoulder','right_shoulder')) and self.fold_index<2 and re.search(r'sleeve',self.instruction,re.I):
            side=('left','right')[self.fold_index]; opposite=('right','left')[self.fold_index]
            src=[keys[side+'_cuff']]; dst=[keys[opposite+'_shoulder']]
            names=[side+'_cuff']; dst_names=[opposite+'_shoulder']; mode='visible_sleeve_fold'
        elif all(k in keys for k in ('left_hem','right_hem','left_shoulder','right_shoulder')):
            src=[keys['left_hem'],keys['right_hem']]; dst=[keys['left_shoulder'],keys['right_shoulder']]
            names=['left_hem','right_hem']; dst_names=['left_shoulder','right_shoulder']; mode='hem_to_shoulders'
        elif len(corners)==4:
            corners=np.asarray(corners); cn=cloth['corner_names']
            if np.linalg.norm(corners[1]-corners[0])>np.linalg.norm(corners[2]-corners[1]): si,di=[0,3],[1,2]
            else: si,di=[0,1],[3,2]
            # Choose the side closer to the two arms. No absolute layout assumption.
            def cost(indices):
                p,q=corners[indices]
                return min(np.linalg.norm(self.robot['left']['grasp']-p)+np.linalg.norm(self.robot['right']['grasp']-q),
                           np.linalg.norm(self.robot['left']['grasp']-q)+np.linalg.norm(self.robot['right']['grasp']-p))
            if cost(di)<cost(si): si,di=di,si
            src=list(corners[si]); dst=list(corners[di]); names=[cn[i] for i in si]; dst_names=[cn[i] for i in di]
        else: raise EvidenceError('fold requires paired visible landmarks or tracked depth-supported outline corners')
        if len(src)==2:
            direct=sum(np.linalg.norm(self.robot[a]['grasp']-p) for a,p in zip(ARMS,src))
            crossed=sum(np.linalg.norm(self.robot[a]['grasp']-p) for a,p in zip(ARMS,reversed(src)))
            arms=list(ARMS if direct<=crossed else reversed(ARMS))
        else: arms=[self._nearest_arm(src[0])]
        spans=[float(np.linalg.norm(a-b)) for a,b in zip(src,dst)]
        if min(spans)<.04 or max(spans)>.8: raise EvidenceError('cloth fold span not supported by measured geometry')
        if any(abs(a[2]-b[2])>.08 for a,b in zip(src,dst)): raise EvidenceError('cloth not approximately on one support')
        self.plan=dict(source=cloth['id'],arms=arms,fold_mode=mode,
            fold_source={a:np.asarray(p).copy() for a,p in zip(arms,src)},fold_destination={a:np.asarray(p).copy() for a,p in zip(arms,dst)},
            source_names=dict(zip(arms,names)),destination_names=dict(zip(arms,dst_names)),landmark_view=cloth['landmark_view'],
            source_initial=cloth['center'].copy(),initial_extent=(cloth['high']-cloth['low']).copy(),baseline=None,grasp_verified=False,
            quaternions={a:tool_quaternion([0,0,-1],np.asarray(dst[i])-src[i]) for i,a in enumerate(arms)},
            fold_height=min(.14,max(.05,max(spans)*.35)),
            rule='visible garment landmark pairing or measured outline half-fold; no cloth dynamics model')
        self.grasp_evidence=[]; self.release_evidence=[]
        self._transition('approach',dict(mode=mode,source_points=src,destination_points=dst,arms=arms))

    def _fold_points(self,row,which,require=False):
        if row['landmark_view']!=self.plan['landmark_view']: raise EvidenceError('cloth landmark camera changed; semantics may reverse')
        stored=self.plan['fold_'+which]; names=self.plan['source_names' if which=='source' else 'destination_names']; result={}
        for arm,p in stored.items():
            name=names[arm]
            if row['observed'] and name in row['keypoints']:
                result[arm]=row['keypoints'][name]
                if which=='destination': stored[arm]=result[arm].copy()
            else:
                if require: raise EvidenceError('required cloth landmark missing: '+name)
                result[arm]=p
                self.debug.setdefault('frozen_visual_targets',[]).append(dict(arm=arm,kind=which,
                    reason='last measured fold geometry, not observed attachment',requires_reacquisition_before_contact=True))
        return result

    def _targets(self):
        plan=self.plan; arms=plan['arms']; source=self._get(plan['source'])
        uncertainty=source['uncertainty_m']+.006*source['age_steps']
        if self.stage.startswith('press_'):
            arm=arms[0]; normal=plan['normal']
            if self.stage=='press_approach':
                if not source['observed']: raise EvidenceError('button must be currently visible for approach')
                plan['button_surface']=source['center'].copy(); plan['button_before']=source['center'].copy()
            gap={'press_approach':.030,'press_contact':.001,'press_stroke':-.006,'press_retract':.035}[self.stage]
            return {arm:plan['button_surface']+gap*normal},uncertainty,0.
        if self.task=='fold_clothes':
            if self.stage in ('approach','contact'):
                src=self._fold_points(source,'source',require=True)
                return {a:p+np.array([0,0,.045 if self.stage=='approach' else 0]) for a,p in src.items()},uncertainty,1.
            if self.stage=='lift': return {a:plan['baseline']['robot'][a]+[0,0,plan['fold_height']] for a in arms},uncertainty,0.
            if self.stage in ('transport','lower'):
                dst=self._fold_points(source,'destination',require=self.stage=='lower')
                return {a:p+[0,0,plan['fold_height'] if self.stage=='transport' else .006] for a,p in dst.items()},uncertainty,0.
            if self.stage=='retreat': return {a:plan['release_robot'][a]+[0,0,.055] for a in arms},uncertainty,1.
        arm=arms[0]
        if self.stage in ('approach','contact'):
            if not source['observed']: raise EvidenceError('source must be visible before contact')
            grasp=self._grasp_point(source,arm)
            if self.task=='match_and_pick_from_conveyor':
                if not source['velocity_observed']: raise EvidenceError('conveyor needs two fresh positions for velocity')
                velocity=source['velocity_m_per_native_step']; horizon=2 if self.stage=='contact' else 4
                lead=velocity*horizon
                if np.linalg.norm(lead)>.025: lead*=.025/np.linalg.norm(lead)
                grasp=grasp+lead
                self.debug['moving_target_prediction']=dict(velocity_m_per_native_step=velocity,horizon_native_steps=horizon,
                    lead_m=lead,observed=False,rule='bounded constant velocity extrapolation from two RGB-D observations')
            return {arm:grasp+np.array([0,0,.055 if self.stage=='approach' else 0])},uncertainty,1.
        if self.stage=='lift': return {arm:plan['baseline']['robot'][arm]+[0,0,.075]},uncertainty,0.
        if self.stage in ('transport','lower'):
            dest=self._get(plan['destination'],fresh=True); uncertainty=max(uncertainty,dest['uncertainty_m'])
            bottom=plan['baseline']['center'][2]-plan['baseline']['low'][2]
            goal=dest['top'].copy(); goal[:2]=dest['center'][:2]
            goal[2]+=bottom+(.060 if self.stage=='transport' else .004)
            if self.task=='general_pickup' and dest['category']=='container' and self.stage=='lower':
                goal[2]-=min(.035,float(dest['high'][2]-dest['low'][2])*.4)
            self.debug['carried_offset_use']=dict(offset_m=plan['carry_offset'],
                provenance='offset measured at visual lift verification',observed_attachment=False,
                limitation='rigid carry approximation; reverified after release')
            return {arm:goal+plan['carry_offset']},uncertainty,0.
        if self.stage=='retreat': return {arm:plan['release_robot'][arm]+[0,0,.060]},uncertainty,1.
        raise EvidenceError('unexpected movement stage '+self.stage)

    @staticmethod
    def _execution_summary(execution):
        if not isinstance(execution,dict): return None
        allowed=('ik_converged','position_error_m','rotation_error_rad','joint_limit_hit','collision',
                 'executed_ticks','tracking_error_m','command_clipped','arms')
        def clean(v,depth=0):
            if depth>3: return None
            if isinstance(v,dict): return {k:clean(x,depth+1) for k,x in v.items() if k in allowed or k in ARMS}
            if isinstance(v,(list,tuple)): return [clean(x,depth+1) for x in v[:14]]
            if isinstance(v,(bool,int,float,type(None))): return v
            return None
        return plain({k:clean(execution[k]) for k in allowed if k in execution})

    def _deadzone(self,uncertainty):
        tolerance=min(self.tolerance,.002) if self.stage in ('press_contact','press_stroke') else self.tolerance
        return max(tolerance,uncertainty)

    def _state(self,targets,uncertainty,opening,obs):
        dz=self._deadzone(uncertainty)
        common=dict(version='jev_structured_rgbd_v1',schema=self.schema,task=self.task,task_variant=self.task_variant,
            instruction=self.instruction,stage=self.stage,stage_owner='external_deterministic_scaffold',
            frame='world_axes_relative_to_env_origin; metres; x/y calibrated, z upward',native_step=self.last_native,
            remaining_steps=self.remaining,robot=self.robot,active_arms=self.plan['arms'],gripper_opening_external=opening,
            phase_rule=self.plan['rule'],history=list(self.history),previous_execution=self._execution_summary(obs.get('previous_execution')),
            constraints=dict(max_delta_norm_m=self.max_step,dead_zone_m=dz,uncertainty_m=uncertainty,
                stale_memory_ttl_controller_steps=self.vision.ttl,translation_sign_owner='Jev only',hold_is_zero=True,
                orientation_gripper_stage_arm_are_external=True,observation_is_not_ground_truth=True),
            visibility={k:{f:v[f] for f in ('observed','age_steps','uncertainty_m','semantic_age','views','source')} for k,v in self.current.items()},
            selected_identities={k:self.plan.get(k) for k in ('source','destination')},
            convergence_limit='cloth deforms and conveyor targets move; no static-goal convergence guarantee')
        if self.schema=='numeric':
            common['geometry']={a:dict(current_grasp_xyz_m=self.robot[a]['grasp'],target_xyz_m=p,
                target_minus_grasp_m=p-self.robot[a]['grasp'],uncertainty_m=uncertainty,
                distance_m=float(np.linalg.norm(p-self.robot[a]['grasp']))) for a,p in targets.items()}
            common['visible_surfaces']={k:{f:v[f] for f in ('category','label','appearance','text','center','low','high','top','normal')}
                                        for k,v in self.current.items()}
        else:
            edges=[]
            for a,p in targets.items():
                for j,axis in enumerate(AXES):
                    e=float(p[j]-self.robot[a]['grasp'][j])
                    relation='overlaps_dead_zone' if abs(e)<=dz else ('target_above_axis_coordinate' if e>0 else 'target_below_axis_coordinate')
                    edges.append(dict(subject='target:'+a,reference='grasp:'+a,axis=axis,relation=relation,
                        signed_separation_interval_m=[e-uncertainty,e+uncertainty],current_coordinate_m=float(self.robot[a]['grasp'][j]),
                        target_coordinate_m=float(p[j]),distance_to_dead_zone_m=max(0.,abs(e)-dz)))
            common['relations']=edges
            common['entities']={k:dict(kind=v['category'],visible_description=v['label']+' '+v['appearance'],printed_text=v['text'],
                visible_bounds_m=[v['low'],v['high']],surface_center_m=v['center'],top_m=v['top'],normal=v['normal']) for k,v in self.current.items()}
        return plain(common)

    def _questions(self,targets):
        result={}
        for a in targets:
            for axis in AXES:
                result[f'{a}_{axis}']=dict(type='choice',instructions=(
                    f'Choose ONLY the sign of the next world-frame {axis} translation for the {a} nominal grasp point '
                    f'in the stated {self.stage} subtask. Use geometry, history, uncertainty and dead zone. '
                    'Hold when separation overlaps the dead zone or evidence is insufficient. '
                    'Do not decide rotation, opening, arm, stage, or success. Positive/negative are world coordinate signs.'),
                    criteria={'negative':f'decrease the grasp point world {axis} coordinate toward the stated target',
                              'hold':f'zero {axis} motion: aligned within dead zone or direction not supported',
                              'positive':f'increase the grasp point world {axis} coordinate toward the stated target'})
        return result

    def _motion_guard(self,commands):
        # Point-level observed clearance guard, not whole-robot collision checking.
        starts={a:self.robot[a]['grasp'] for a in ARMS}
        ends={a:starts[a]+np.asarray(commands.get(a,{}).get('delta_xyz_m',[0,0,0])) for a in ARMS}
        relative=starts['left']-starts['right']; velocity=(ends['left']-ends['right'])-relative
        t=float(np.clip(-np.dot(relative,velocity)/max(np.dot(velocity,velocity),1e-12),0,1))
        if np.linalg.norm(relative+t*velocity)<.055 and np.linalg.norm(ends['left']-ends['right'])<np.linalg.norm(relative):
            return 'predicted nominal grasp-point separation below 55 mm'
        if not self.stage.startswith('press_'):
            for arm in commands:
                z=self.vision.support_height(ends[arm])
                allowance=.003 if self.task=='fold_clothes' else .001
                if z is not None and ends[arm][2]<z-allowance: return 'command would cross observed support surface'
        return None

    def _movement(self,targets,uncertainty,opening,obs,ask_jev):
        self.debug['targets']=targets; dz=self._deadzone(uncertainty); self.debug['dead_zone_m']=dz
        if uncertainty>.025: raise EvidenceError('target uncertainty too large')
        if self.stage in ('contact','lower','press_contact','press_stroke') and uncertainty>.012:
            raise EvidenceError('contact phase requires <=12 mm surface uncertainty')
        orientations={}; angles={}
        for a in targets: orientations[a],angles[a]=bounded_quaternion(self.robot[a]['quaternion'],self.plan['quaternions'][a])
        if self.stage in ('approach','press_approach') and max(angles.values())>.10:
            self.debug['external_action']=dict(rule='orient tool local +X toward contact surface, <=0.20 rad per action',
                angle_remaining_rad=angles,translation='zero; Jev not called',evidence='observed quaternion + measured normal/axis')
            return self._result({a:dict(delta_xyz_m=[0.,0.,0.],quaternion_wxyz=orientations[a],gripper_opening=opening) for a in targets},
                                reason='external orientation alignment',ticks=5)
        # Per-axis tolerance exactly matches the disclosed dead zone. No forced directions to escape holds.
        if all(np.all(np.abs(targets[a]-self.robot[a]['grasp'])<=dz) for a in targets): return None
        if self.jev_calls>=180: return self._result(stop=True,reason='180 Jev call budget reached',ticks=1)
        state=self._state(targets,uncertainty,opening,obs); questions=self._questions(targets)
        self.debug['jev_request']=dict(state=state,questions=questions)
        started=time.monotonic(); self.jev_calls+=1
        try: raw=ask_jev(state,questions)
        finally: self.jev_seconds+=time.monotonic()-started
        self.debug['jev_response']=plain(raw); answers=raw.get('answers') if isinstance(raw,dict) else None
        if not isinstance(answers,dict): return self._result(stop=True,reason='invalid Jev response: missing answers',ticks=1)
        signs={}; commands={}; amplitude_log={}
        for a,p in targets.items():
            choices=[]
            for axis in AXES:
                answer=answers.get(f'{a}_{axis}',{})
                if not isinstance(answer,dict) or answer.get('type')!='choice' or answer.get('choice') not in ('negative','hold','positive'):
                    return self._result(stop=True,reason='invalid or missing Jev axis choice',ticks=1)
                choices.append(answer['choice'])
            errors=p-self.robot[a]['grasp']; amplitude=np.minimum(.025,.70*np.abs(errors)); masked=np.abs(errors)<=dz
            amplitude[masked]=0.; scale=min(1.,self.max_step/max(float(np.linalg.norm(amplitude)),1e-12)); amplitude*=scale
            sign=np.array([{'negative':-1.,'hold':0.,'positive':1.}[c] for c in choices]); delta=amplitude*sign
            signs[a]=dict(zip(AXES,choices)); amplitude_log[a]=dict(amplitudes_m=amplitude,dead_zone_mask=masked,norm_scale=scale,
                rule='min(25mm, 0.70*abs(error)); zero inside disclosed dead zone; common norm cap',sign_flipped=False,hold_zero=True)
            commands[a]=dict(delta_xyz_m=delta,quaternion_wxyz=orientations[a],gripper_opening=opening)
        self.debug['jev_signs']=signs; self.debug['axis_amplitudes']=amplitude_log
        self.history.append(dict(event='translation',stage=self.stage,native_step=self.last_native,signs=signs,
                                 amplitudes=plain(amplitude_log),targets=plain(targets)))
        blocked=self._motion_guard(commands)
        if blocked:
            self.debug['suppressed_commands']=commands; self.debug['external_guard']=blocked
            return self._result(stop=True,reason=blocked,ticks=1)
        self.stall_count=self.stall_count+1 if all(np.linalg.norm(c['delta_xyz_m'])<1e-9 for c in commands.values()) else 0
        if self.stall_count>=4: return self._result(stop=True,reason='four Jev all-hold actions outside convergence zone',ticks=1)
        self.last_motion=dict(stage=self.stage,grasp={a:self.robot[a]['grasp'].copy() for a in targets},
                             target={a:p.copy() for a,p in targets.items()},delta={a:c['delta_xyz_m'].copy() for a,c in commands.items()})
        return self._result(commands,reason='Jev world-axis choices with external nonnegative amplitudes',
                            ticks=2 if self.task=='match_and_pick_from_conveyor' or self.stage=='press_stroke' else 5)

    def _fixed(self,opening,reason,ticks=5):
        arms={a:dict(delta_xyz_m=[0.,0.,0.],quaternion_wxyz=self.robot[a]['quaternion'],gripper_opening=opening) for a in self.plan['arms']}
        self.debug['external_action']=dict(rule=reason,evidence=dict(robot=self.robot,stage=self.stage),translation='zero; Jev not called')
        return self._result(arms,reason=reason,ticks=ticks)

    def _baseline(self):
        row=self._get(self.plan['source'],fresh=True)
        return dict(center=row['center'].copy(),top=row['top'].copy(),low=row['low'].copy(),high=row['high'].copy(),
            keypoints={k:v.copy() for k,v in row['keypoints'].items()},robot={a:self.robot[a]['grasp'].copy() for a in self.plan['arms']},
            native_step=self.last_native)

    def _verify_grasp(self):
        row=self._get(self.plan['source'],fresh=True); base=self.plan['baseline']
        if self.task=='fold_clothes':
            if row['landmark_view']!=self.plan['landmark_view']: raise EvidenceError('cloth landmark view changed')
            evidence={}
            for a in self.plan['arms']:
                name=self.plan['source_names'][a]; measured=row['keypoints'].get(name); before=base['keypoints'].get(name)
                if measured is None or before is None: return False,dict(reason='each held cloth landmark must be visible after lift')
                displacement=measured-before; movement=self.robot[a]['grasp']-base['robot'][a]
                evidence[a]=dict(visible_rise_m=float(displacement[2]),robot_rise_m=float(movement[2]),
                                  displacement_mismatch_m=float(np.linalg.norm(displacement-movement)))
            ok=all(e['visible_rise_m']>.012 and e['robot_rise_m']>.020 and e['displacement_mismatch_m']<.035 for e in evidence.values())
        else:
            a=self.plan['arms'][0]; displacement=row['center']-base['center']; movement=self.robot[a]['grasp']-base['robot'][a]
            mismatch=float(np.linalg.norm(displacement-movement)); ok=displacement[2]>.020 and movement[2]>.020 and mismatch<.028
            evidence=dict(visible_object_displacement_m=displacement,robot_displacement_m=movement,
                          displacement_mismatch_m=mismatch,identity=row['id'],observed=True)
        if ok: self.grasp_evidence.append(dict(native_step=self.last_native,evidence=plain(evidence)))
        else: self.grasp_evidence=[]
        self.grasp_evidence=self.grasp_evidence[-3:]
        verified=len(self.grasp_evidence)>=2 and self.grasp_evidence[-1]['native_step']!=self.grasp_evidence[-2]['native_step']
        return verified,evidence

    def _verify_release(self):
        row=self._get(self.plan['source'],fresh=True)
        if self.task=='fold_clothes':
            if row['landmark_view']!=self.plan['landmark_view']: raise EvidenceError('cloth landmark view changed')
            errors={}
            for a,name in self.plan['source_names'].items():
                if name not in row['keypoints']: return False,dict(reason='released cloth landmark occluded')
                errors[a]=float(np.linalg.norm(row['keypoints'][name]-self.plan['fold_destination'][a]))
            extent=row['high']-row['low']; ratio=float(np.linalg.norm(extent[:2])/max(np.linalg.norm(self.plan['initial_extent'][:2]),1e-6))
            ok=bool(errors) and max(errors.values())<.045 and ratio<.95
            evidence=dict(visible_landmark_destination_errors_m=errors,visible_extent_ratio=ratio,native_fold_success='not evaluated')
        else:
            dest=self._get(self.plan['destination'],fresh=True); xy=float(np.linalg.norm(row['center'][:2]-dest['center'][:2]))
            gap=float(row['low'][2]-dest['top'][2]); limit=max(.012,min(.040,float(np.min(dest['high'][:2]-dest['low'][:2]))*.35))
            ok=xy<limit and -.04<gap<.025
            evidence=dict(horizontal_center_separation_m=xy,visible_bottom_to_destination_top_m=gap,xy_tolerance_m=limit,native_stability='not evaluated')
        drift=float(np.linalg.norm(row['center']-self.release_evidence[-1]['center'])) if self.release_evidence else None
        self.release_evidence.append(dict(center=row['center'].copy(),native_step=self.last_native,ok=bool(ok)))
        self.release_evidence=self.release_evidence[-3:]; evidence['inter_observation_drift_m']=drift
        stable=len(self.release_evidence)>=2 and all(e['ok'] for e in self.release_evidence[-2:]) and drift<.012
        return stable,evidence

    def _after_motion(self):
        if self.last_motion is None: return
        data={a:dict(observed_grasp_delta_m=self.robot[a]['grasp']-before,requested_delta_m=self.last_motion['delta'][a],
                     remaining_to_previous_target_m=float(np.linalg.norm(self.last_motion['target'][a]-self.robot[a]['grasp'])))
              for a,before in self.last_motion['grasp'].items()}
        self.debug['after_action_robot_feedback']=data
        self.history.append(dict(event='after_action_robot_feedback',stage=self.last_motion['stage'],arms=plain(data)))
        self.last_motion=None

    def step(self,observation: dict,ask_jev,perceive) -> dict:
        self.transitions=[]; self.debug={}
        if self.stopped: return self._result(stop=True,reason=self.stop_reason,ticks=1)
        if not isinstance(observation,dict): return self._result(stop=True,reason='observation must be a dictionary',ticks=1)
        try:
            native=int(observation['native_step'])
            if self.last_native is not None and native==self.last_native: return self.last_result
            if self.last_native is not None and native<self.last_native:
                return self._result(stop=True,reason='native_step moved backwards; use a new controller per episode',ticks=1)
            self.last_native=native; self.remaining=int(observation['remaining_steps'])
            if self.remaining<=0: return self._result(stop=True,reason='native step budget exhausted',ticks=1)
            if time.monotonic()-self.started>19*60: return self._result(stop=True,reason='controller wall budget reached',ticks=1)
            instruction=str(observation.get('instruction','')).strip()
            if not instruction: raise EvidenceError('public task instruction missing')
            if self.instruction is not None and instruction!=self.instruction:
                return self._result(stop=True,reason='instruction changed during episode',ticks=1)
            self.instruction=instruction; self._read_robot(observation); self._after_motion()
            self.step_index+=1; self.stage_age+=1
            force=self.recovery_count>0 or self.stage in ('verify_grasp','verify_release','press_verify')
            self.current=self.vision.update(observation,perceive,force=force)
            self.debug['previous_execution']=self._execution_summary(observation.get('previous_execution'))
            if self.stage_age>32: return self._result(stop=True,reason='phase budget exhausted without verified progress',ticks=1)
            if self.stage=='select': self._select()
            if self.stage in ('press_contact','press_stroke','press_verify'):
                row=self.current.get(self.plan['source'])
                if row is not None and row['observed']:
                    self.plan['press_displacements'].append(float(np.dot(self.plan['button_before']-row['center'],self.plan['normal'])))
                    self.plan['press_displacements']=self.plan['press_displacements'][-32:]
            for _ in range(5):
                if self.stage=='close':
                    if self.pending is None:
                        self.plan['baseline']=self._baseline(); self.pending='close'; self.recovery_count=0
                        return self._fixed(0.,'external close after measured contact alignment',ticks=6)
                    self.debug['close_feedback']={a:self.robot[a]['opening'] for a in self.plan['arms']}; self.pending=None
                    self._transition('lift',dict(reason='close executed; grasp unverified',openings=self.debug['close_feedback']))
                if self.stage=='verify_grasp':
                    verified,evidence=self._verify_grasp(); self.debug['grasp_verification']=plain(evidence)
                    if verified:
                        self.plan['grasp_verified']=True
                        if self.task=='fold_clothes': self._transition('transport',evidence); continue
                        a=self.plan['arms'][0]; row=self._get(self.plan['source'],fresh=True)
                        self.plan['carry_offset']=self.robot[a]['grasp']-row['center']
                        if self.plan['destination'] is None:
                            self.completed.append(self.plan['source']); self._transition('observed_pickup_complete',evidence)
                            return self._result(stop=True,reason='visual lift verified twice; native outcome is evaluator-only',ticks=1)
                        self._transition('transport',evidence); continue
                    if self.stage_age>=4: return self._result(stop=True,reason='grasp not verified from after-action visual displacement',ticks=1)
                    self.recovery_count=0; return self._fixed(0.,'hold closed for independent after-lift visual evidence',ticks=3)
                if self.stage=='release':
                    if self.pending is None:
                        self.plan['release_robot']={a:self.robot[a]['grasp'].copy() for a in self.plan['arms']}
                        self.pending='release'; self.recovery_count=0
                        return self._fixed(1.,'external open after measured placement/fold alignment',ticks=6)
                    self.pending=None; self._transition('retreat',dict(reason='release executed; placement unverified'))
                if self.stage=='verify_release':
                    verified,evidence=self._verify_release(); self.debug['release_verification']=plain(evidence)
                    if verified:
                        self.completed.append(self.plan['source'])
                        if self.task.startswith('stack_'):
                            self.stack_members.add(self.plan['source'])
                            category='bowl' if self.task=='stack_bowls' else 'object'
                            remaining=[r for r in self.current.values() if r['observed'] and r['category']==category and r['id'] not in self.stack_members]
                            if remaining:
                                self.plan['stack_base']=self.plan['source']; self._transition('select',evidence); self._select(); continue
                        if self.task=='fold_clothes' and self.plan['fold_mode']=='visible_sleeve_fold':
                            self.fold_index+=1; self._transition('select',evidence); self._select(); continue
                        self._transition('observed_operation_complete',evidence)
                        return self._result(stop=True,reason='visual operation verified; native outcome is evaluator-only',ticks=1)
                    if self.stage_age>=5: return self._result(stop=True,reason='released object/cloth geometry not verified',ticks=1)
                    self.recovery_count=0; return self._fixed(1.,'observe release settling and landmark geometry',ticks=3)
                if self.stage=='press_verify':
                    row=self._get(self.plan['source'],fresh=True)
                    displacement=float(np.dot(self.plan['button_before']-row['center'],self.plan['normal']))
                    self.plan['press_displacements'].append(displacement); peak=max(self.plan['press_displacements'])
                    self.debug['press_evidence']=dict(visible_face_displacement_m=displacement,peak_visible_displacement_m=peak,
                        noise_floor_m=row['uncertainty_m'],robot_stroke_reached=True,native_activation='unknown')
                    if peak>max(.0025,row['uncertainty_m']): self._transition('press_retract',self.debug['press_evidence']); continue
                    if self.stage_age>=3: return self._result(stop=True,reason='bounded press reached but button motion not visually resolved',ticks=1)
                    self.recovery_count=0; return self._fixed(0.,'hold bounded press briefly for visual displacement evidence',ticks=2)
                targets,uncertainty,opening=self._targets(); result=self._movement(targets,uncertainty,opening,observation,ask_jev)
                if result is not None: self.recovery_count=0; return result
                evidence=dict(observed_grasp_points={a:self.robot[a]['grasp'] for a in targets},targets=targets,
                              per_axis_dead_zone_m=self._deadzone(uncertainty),source_visible=self._get(self.plan['source'])['observed'])
                if self.stage=='press_retract':
                    self.completed.append('printed_button_'+self.plan['number']); self.press_index+=1
                    if self.press_index>=len(self.sequence):
                        self._transition('observed_press_sequence_complete',evidence)
                        return self._result(stop=True,reason='specified presses visually verified; native outcome is evaluator-only',ticks=1)
                    self._transition('select',evidence); self._select(); continue
                transitions={'approach':'contact','contact':'close','lift':'verify_grasp','transport':'lower','lower':'release',
                             'retreat':'verify_release','press_approach':'press_contact','press_contact':'press_stroke','press_stroke':'press_verify'}
                if self.stage not in transitions: raise EvidenceError('no transition for '+self.stage)
                if self.stage=='contact': self._get(self.plan['source'],fresh=True)
                self._transition(transitions[self.stage],evidence)
            self.recovery_count=0; return self._result(reason='bounded internal phase transition yield',ticks=1)
        except EvidenceError as exc: return self._recover(str(exc))
        except (KeyError,TypeError,ValueError,np.linalg.LinAlgError) as exc:
            return self._result(stop=True,reason='invalid input/geometry: '+type(exc).__name__+': '+str(exc)[:240],ticks=1)
        except Exception as exc:
            return self._result(stop=True,reason='callback/controller error: '+type(exc).__name__+': '+str(exc)[:240],ticks=1)
