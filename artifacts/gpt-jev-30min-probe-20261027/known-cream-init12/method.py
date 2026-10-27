def main(api):
    manifest = {v['key'] for v in api.recall()}
    def load(k, default):
        return api.recall(k)['value'] if k in manifest else default
    C = load('run', {'phase':'approach','calls':0,'reviews':0,'grasps':0,'probes':0})
    G, R, B, V = load('geometry', {}), load('reference', {}), load('probe', {}), load('verification', {})
    logs = load('evidence', [])
    pixel = {'type':'array','items':{'type':'integer','minimum':0,'maximum':767},'minItems':2,'maxItems':2}
    pixels = lambda n: {'type':'array','items':pixel,'maxItems':n}
    cams = ['agentview','robot0_eye_in_hand']
    ref_fields = {'identity':['same','ambiguous'],'camera':cams,'polygon':pixels(16),'definitions':{'type':'array','items':{'type':'string'},'maxItems':3}}
    Q = {}
    for axis in ['x','y','z','rx','ry','rz']:
        Q[axis] = {'type':'choice','instructions':'For world axis '+axis+', use its explicitly bound goal_relation. Select positive for increase, negative for decrease, and hold for within_tolerance. Do not infer object contact from this residual.','criteria':{'negative':'The selected axis relation is decrease.','hold':'The selected axis relation is within_tolerance.','positive':'The selected axis relation is increase.'}}
    Q['gripper'] = {'type':'choice','instructions':'Use the bound objective.gripper exactly. Open releases; close commands closure; keep preserves the current command. Object retention is assessed separately.','criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep.'}}
    def note(kind, data):
        logs.append({'kind':kind,'data':data,'frame_id':api.state()['frame_id']}); logs[:] = logs[-12:]
        api.checkpoint('evidence', logs)
    def save():
        api.checkpoint('run', C)
    def stop(message):
        raise RuntimeError(message)
    def result(ok, reason):
        return {'completion_proposed':bool(ok),'evidence':{'reason':reason,'phase':C['phase'],'checks':logs,'limitations':'Heuristic measurement uncertainty and bounded observed stability, not collision certification or official task success.'}}
    def review(question, fields, context=None, final=False):
        budget = api.state()['budgets']
        if C['reviews'] >= 20 or budget['gpt_remaining'] <= (0 if final else 4): stop('Review reserve reached; current evidence is insufficient.')
        C['reviews'] += 1; save()
        r = api.review(question, context=context, fields=fields)
        if r['measurement_errors']: note('measurement_errors', r['measurement_errors'])
        if r['status'] == 'stop': stop('Observation review requested stop: '+r['explanation'])
        return r
    def points(r, names):
        return [r['points'][n]['world_m'] for n in names if n in r['points']]
    def fitted(r, name):
        if name not in r['regions']: return None
        p = np.asarray(r['regions'][name]['world_m'], dtype=float)
        if len(p) < 6 or not np.all(np.isfinite(p)): return None
        try:
            f = geo.plane(p)
        except (ValueError, RuntimeError) as e:
            note('plane_rejected', str(e)); return None
        spread = np.asarray(f['in_plane_spread_m'])
        if min(spread) <= 3*max(float(f['rms_m']),0.0004) or f['rms_m'] > 0.0025: return None
        return f
    def rays(camera, pix, f):
        out = []
        try:
            for p in pix: out.append(api.plane_point(camera,p,list(f['coefficients']))['world_m'])
        except RuntimeError as e:
            note('ray_measurement_failed',str(e)); return None
        return np.asarray(out)
    def bowl(r):
        p = points(r, ['rim'+str(i) for i in range(6)])
        if len(p) < 4 or 'cavity' not in r['points']: return False
        try:
            f, c = geo.plane(p), geo.circle_xy(p)
        except (ValueError, RuntimeError) as e:
            note('rim_fit_rejected',str(e)); return False
        u = max(0.001,float(f['rms_m']),float(c['max_radial_error_m']))
        z = float(np.mean(np.asarray(p)[:,2])); depth = z-r['points']['cavity']['world_m'][2]
        if f['coefficients'][2] < 0.97 or c['largest_angular_gap_rad'] > math.pi or u > 0.08*c['radius_m'] or depth <= u: return False
        G.update({'bowl_xy':list(c['center_xy_m']),'rim_z':z,'radius':float(c['radius_m']),'bowl_u':u,'cavity_depth':float(depth),'bowl_frame':r['frame_id']})
        api.checkpoint('geometry',G); return True
    def refresh_bowl():
        for attempt in range(2):
            r = review('Identify the same destination vessel. Use the other camera or different unobstructed rim arcs on a retry. Request rim0 through rim5 distributed around the INNER opening lip, and cavity on the visible interior bottom, not the outside wall. identity is same only if unambiguous; upright means the horizontal circular opening model is supported.', {'identity':['same','ambiguous'],'upright':['yes','no','unknown']}, {'roles':G.get('roles'),'previous_rim':{k:G[k] for k in ['bowl_xy','rim_z','radius']},'attempt':attempt})
            if r['parameters']['identity']=='same' and r['parameters']['upright']=='yes' and bowl(r): return
        stop('Cannot refresh the inner opening geometry from obtainable measurements.')
    def setref(r, envelope=None):
        p = r['parameters']
        if p['identity'] != 'same': return False
        marks = points(r,['n0','n1','n2']); definitions = p['definitions']; handle = None
        if len(p['polygon']) >= 3:
            try:
                t = api.track_init(p['camera'],p['polygon']); handle = t['handle']
                provenance = {k:t[k] for k in ['frame_id','camera','method_number','source_sha256']}
            except RuntimeError as e:
                note('patch_initialization_failed',str(e))
        if len(marks)!=3 or len(definitions)!=3: marks,definitions = [],[]
        if handle is None and not marks: return False
        R.clear(); R.update({'handle':handle,'camera':p['camera'],'polygon':p['polygon'],'marks':marks,'definitions':definitions,'frame_id':r['frame_id'],'identity':G.get('roles'),'envelope':None if envelope is None else np.asarray(envelope).tolist(),'shape_u':G.get('eu',0.002)})
        if handle is not None: R['tracker_provenance']=provenance
        api.checkpoint('reference',R); return True
    def newref():
        for attempt in range(2):
            r = review('Select a CURRENT visible rigid textured patch on the intended item, using another surface/camera on retry. This is a new local motion reference; old corner registration is NOT required. identity means same physical item, not old vertex correspondence. Return camera, a 3..16 vertex polygon strictly inside that surface (empty if unusable), and definitions of three persistent physical texture marks. Request n0,n1,n2 at those marks if identifiable. Definitions must describe physical print/texture, not screen directions. Unknown marks may be omitted.',ref_fields,{'roles':G.get('roles'),'attempt':attempt,'phase':C['phase']})
            if setref(r): return
        stop('No identified local patch or corresponding landmark reference is obtainable; preserve the current jaw state.')
    def pose():
        if R.get('handle') is not None:
            try: t = api.track_update(R['handle'])
            except RuntimeError as e: note('tracker_call_failed',str(e)); t={'status':'unknown'}
            if t['status']=='tracked':
                u = max(0.0006,float(t['rms_m'])+float(t['uncertainty_floor_m']))
                ss = sorted(np.asarray(t['inlier_spread_m']).reshape(-1).tolist()); spread = ss[-2] if len(ss)>1 else ss[-1]
                if t['inliers']>=8 and t['inliers']/max(1,t['matches'])>=0.45 and spread>2*u and t['rms_m']<0.004:
                    return {'T':t['transform_initial_world_to_current_world'],'X':t['reference_inlier_world_m'][::max(1,len(t['reference_inlier_world_m'])//8)][:8],'u':u,'spread':spread,'frame':t['frame_id'],'source':'RGB-D patch'}
                note('tracker_quality',{'inliers':t['inliers'],'matches':t['matches'],'rms':t['rms_m'],'u':u,'spread':spread})
        if len(R.get('marks',[]))==3:
            r = review('Recover current corresponding physical landmarks m0,m1,m2 from the saved definitions and reference measurements. The historical projections are NOT detections. identity concerns the same body; correspondence is exact only if each mark has its saved physical meaning. A different same-body surface does not establish correspondence. Use the other camera if useful; omit hidden or ambiguous marks.',{'identity':['same','ambiguous'],'correspondence':['exact','unknown']},{'reference':R,'phase':C['phase']})
            y = points(r,['m0','m1','m2'])
            if r['parameters']['identity']=='same' and r['parameters']['correspondence']=='exact' and len(y)==3:
                x,y = np.asarray(R['marks']),np.asarray(y); a,b=x.mean(0),y.mean(0)
                U,s,W = np.linalg.svd((x-a).T@(y-b)); rot=W.T@U.T
                if np.linalg.det(rot)<0: W[-1,:]*=-1; rot=W.T@U.T
                T=np.eye(4); T[:3,:3]=rot; T[:3,3]=b-rot@a
                err=float(np.max(np.linalg.norm(geo.transform(x,T)-y,axis=1))); spread=float(np.linalg.svd(x-a,compute_uv=False)[1]); u=max(0.0015,err)
                if spread>2*u and err<0.004: return {'T':T.tolist(),'X':x.tolist(),'u':u,'spread':spread,'frame':r['frame_id'],'source':'identified landmark correspondence'}
                note('landmark_fit_rejected',{'error':err,'spread':spread})
        return None
    def needpose():
        w=pose()
        if w is None: newref(); w=pose()
        if w is None: stop('A new reference also failed current observation; no transform has been inferred from hand motion.')
        return w
    def shape(w):
        if R.get('envelope') is None:
            r=review('Recover only the current rectangular top-face envelope, not old vertex indices. Request region face strictly inside the visible planar top face, camera matching that region, and edge containing the two visible endpoints of ONE COMPLETE physical top edge. Empty edge if an endpoint is hidden. model is same_rectangle only if the saved rigid-box dimensions still apply. The interior region determines the inward side; no hidden corner pixels are requested.',{'model':['same_rectangle','contradicted','unknown'],'camera':cams,'edge':pixels(2)},{'roles':G['roles'],'dimensions':G['lengths'],'height':G['height']})
            f=fitted(r,'face'); p=r['parameters']; candidates=[]
            if f is not None and p['model']=='same_rectangle' and len(p['edge'])==2:
                e=rays(p['camera'],p['edge'],f)
                if e is not None:
                    n=np.asarray(f['coefficients'][:3]); d=e[1]-e[0]; length=float(np.linalg.norm(d))
                    if length>3*G['eu']:
                        side=np.cross(n,d/length); signed=float(np.dot(np.asarray(f['center_world_m'])-e.mean(0),side)); uncertainty=max(G['eu'],2*f['rms_m'])
                        signs=[1 if signed>0 else -1] if abs(signed)>uncertainty else [-1,1]
                        for j in range(2):
                            if abs(length-G['lengths'][j])<=3*uncertainty:
                                for sign in signs:
                                    a=np.asarray([e[0],e[1],e[1]+sign*G['lengths'][1-j]*side,e[0]+sign*G['lengths'][1-j]*side]); candidates.extend(a.tolist()); candidates.extend((a-G['height']*n).tolist())
            if not candidates: stop('Local motion is observable, but a current envelope cannot be recovered from a face and identifiable edge; no old corner correspondence is invented.')
            R['envelope']=geo.transform(candidates,np.linalg.inv(np.asarray(w['T']))).tolist(); R['shape_u']=uncertainty; api.checkpoint('reference',R)
        ref=np.asarray(R['envelope']); E=geo.transform(ref,np.asarray(w['T'])); center=np.mean(np.asarray(w['X']),axis=0)
        lever=np.max(np.linalg.norm(ref-center,axis=1)); ux=R['shape_u']+w['u']*(1+lever/w['spread'])
        return E,float(ux),float(ux)
    def acquire():
        fields=dict(ref_fields); fields.update({'task_kind':['rigid_box_into_open_vessel','other','unknown'],'item_name':'string','vessel_name':'string','box_on_table':['yes','no','unknown'],'upright_vessel':['yes','no','unknown'],'corners':pixels(4)})
        for attempt in range(2):
            r=review('Read the runtime instruction and identify the movable item and destination. This method supports a rigid rectangular package placed into an upright open vessel. Return task_kind, item_name and vessel_name. box_on_table means its flat underside is supported on the table and the visible face is the opposite parallel rectangular face, with no feet or hidden raised support. Request regions face and table, each a small interior single-surface RGB-D region, with explicit camera, box and stride=6. Give camera and four genuinely visible top-face corners in perimeter order as corners; empty if incomplete. Give a textured interior polygon in that camera and semantic definitions for optional n0,n1,n2 texture marks; request those points. Request rim0..rim5 around the INNER lip, and cavity on the visible interior bottom. identity is same only for unambiguous intended-item selection. Use a different view/region on retry, not the same failed boundary depth.',fields,{'attempt':attempt})
            p=r['parameters']; f,t=fitted(r,'face'),fitted(r,'table')
            if p['task_kind']!='rigid_box_into_open_vessel': stop('Runtime task is outside this measured rigid-package/open-vessel method.')
            if p['identity']!='same' or p['box_on_table']!='yes' or p['upright_vessel']!='yes' or f is None or t is None or len(p['corners'])!=4: continue
            if f['coefficients'][2]<0.97 or t['coefficients'][2]<0.97: continue
            top=rays(p['camera'],p['corners'],f)
            if top is None: continue
            edges=np.roll(top,-1,axis=0)-top; lengths=np.linalg.norm(edges,axis=1); eu=max(0.001,2*f['rms_m'],2*t['rms_m'])
            rectangle=max(float(np.linalg.norm(edges[0]+edges[2])),float(np.linalg.norm(edges[1]+edges[3])),abs(float(np.dot(edges[0],edges[1])))/max(lengths))
            a,b,c,d=t['coefficients']; bottom=top.copy(); bottom[:,2]=-(a*top[:,0]+b*top[:,1]+d)/c; h=float(np.mean(top[:,2]-bottom[:,2]))
            if min(lengths)<=3*eu or rectangle>3*eu or h<=eu or np.ptp(top[:,2]-bottom[:,2])>3*eu: note('box_model_rejected',{'lengths':lengths.tolist(),'height':h,'rectangle_error':rectangle,'u':eu}); continue
            G.update({'roles':{'item':p['item_name'],'vessel':p['vessel_name']},'table':list(t['coefficients']),'table_u':max(0.0007,2*t['rms_m']),'lengths':lengths[:2].tolist(),'height':h,'eu':eu,'own_open':api.state()['own_geometry'],'initial_frame':r['frame_id']})
            if not bowl(r): continue
            E=np.concatenate([top,bottom]); api.checkpoint('geometry',G)
            if not setref(r,E): newref()
            note('initial_geometry',{'roles':G['roles'],'lengths':G['lengths'],'height':h,'radius':G['radius'],'rim_z':G['rim_z'],'uncertainty_m':eu}); return
        stop('Initial geometric measurements remain inconclusive after distinct region/view requests.')
    def move(target, q, grip='keep', final=False, tol=0.0015):
        target=np.asarray(target); s=api.state()
        if np.linalg.norm(target-np.asarray(geo.pad_position(s)))>0.59: stop('Requested local lease exceeds the bounded reach scope.')
        C['motion_intent']={'target_pad_world_m':target.tolist(),'quaternion_xyzw':list(q),'gripper':grip,'frame_id':s['frame_id']}; save()
        for leg in range(3):
            b=api.state()['budgets']; reserve=0 if final else 25
            calls=int(min(12,b['jev_remaining']-reserve,b['native_steps_remaining']//3-reserve,180-C['calls']))
            if calls<1 or b['wall_seconds_remaining']<30: stop('Motion budget reserve reached.')
            receipt=api.drive(target.tolist(),list(q),grip,Q,features={'phase':C['phase'],'goal':'local pad-center pose only','evidence_frame':s['frame_id']},max_calls=calls,tool_point='pad_center',translation_limit=0.02,rotation_limit=0.10,steps=3,position_tolerance=max(0.0005,min(0.006,tol)),rotation_tolerance=0.035)
            C['calls']+=receipt['lease_calls']; C['ack']={k:receipt[k] for k in ['status','acknowledged_steps','frame_id','position_error_m','rotation_error_rad','choices']}; save()
            if receipt['status']=='reached': return
            if receipt['status']=='stalled': stop('Pose lease stalled; no repeated contact pushing. Inspect the saved intent and acknowledgment.')
            if receipt['status'] not in ['lease_exhausted','moved']: stop('Unexpected controller outcome.')
        stop('Bounded pose lease ended without reaching its geometric target.')
    def jaw(command, phase):
        s=api.state(); C['phase']=phase; C['jaw_intent']=command; save()
        if s['budgets']['jev_remaining']<1 or C['calls']>=180: stop('No jaw-command budget remains.')
        t=api.control(np.asarray(geo.pad_position(s)).tolist(),s['tcp_quaternion_xyzw'],command,Q,features={'phase':phase,'claim':'command delivery is not an object effect'},tool_point='pad_center',steps=3,position_tolerance=0.0015,rotation_tolerance=0.035)
        C['calls']+=1; C['ack']={k:t[k] for k in ['status','acknowledged_steps','frame_id','choices']}; save()
        if t['choices']['gripper']!=command or t['acknowledged_steps']<1: stop('Requested jaw transition was not acknowledged.')
        if t['status']=='stalled': stop('Unexpected stalled jaw transition; preserve and inspect the acknowledged physical state.')
        if t['status'] not in ['reached','moved']: stop('Unexpected jaw controller outcome.')
        C['phase']='released' if command=='open' and phase=='opening' else ('closed' if command=='close' else phase); save()
    def gate(target, purpose, rim=False, final=False):
        fields={'obstruction':['none_observed','external','unknown'],'visibility':['visible','partial','self_occluded','unobserved'],'basis':['visible_geometry','consistent_local_model','none'],'up_view':['justified','not_justified']}
        if rim: fields['vessel_prior']=['consistent','changed','unknown']
        for attempt in range(2):
            r=review('Assess ONLY the proposed local pad-center motion: '+purpose+'. obstruction=external means a visible nonrobot obstacle intersects this action; none_observed does not certify unseen space. visibility distinguishes partial/unobserved space from robot or held-item self-occlusion. basis=consistent_local_model requires visible partial geometry, the supplied envelope, and no contradictory interaction; it is not a swept-volume certificate. up_view=justified only if an open 15 mm vertical observation motion is supported by current local evidence without contact. If vessel_prior is requested, compare the saved stationary inner rim with current partial observations; request p0,p1,p2 at visible inner-lip locations, not old indexed marks. A changed camera is not vessel motion.',fields,{'purpose':purpose,'target_pad_world_m':np.asarray(target).tolist(),'state':api.state(),'geometry':G,'attempt':attempt},final)
            p=r['parameters']
            if p['obstruction']=='external': stop('Observed external obstruction rejects this local action.')
            if rim:
                v=points(r,['p0','p1','p2']); consistent=False
                if v:
                    a=np.asarray(v); errors=np.maximum(abs(np.linalg.norm(a[:,:2]-np.asarray(G['bowl_xy']),axis=1)-G['radius']),abs(a[:,2]-G['rim_z']))
                    consistent=len(v)>=2 and float(max(errors))<=G['bowl_u']+0.003
                if p['vessel_prior']!='consistent' or not consistent: refresh_bowl()
            if p['obstruction']=='none_observed' and p['basis']!='none': return
            if attempt==0 and p['up_view']=='justified':
                s=api.state(); move(np.asarray(geo.pad_position(s))+[0,0,0.015],s['tcp_quaternion_xyzw'],'keep',final)
            else: break
        stop('Exact gap: no supported local motion model or useful justified view change; unobserved space is not clearance.')
    def floor_offset(q):
        o=G['own_open']; corners=np.asarray([[x,y,z] for x in [o['finger_low_offset_tool_m'][0],o['finger_high_offset_tool_m'][0]] for y in [o['finger_low_offset_tool_m'][1],o['finger_high_offset_tool_m'][1]] for z in [o['finger_low_offset_tool_m'][2],o['finger_high_offset_tool_m'][2]]])
        return float(np.min(((corners-np.asarray(o['pad_center_in_tool_m']))@geo.rotation(q).T)[:,2]))
    def grasp(E):
        s=api.state(); A=geo.rotation(s['tcp_quaternion_xyzw']); choices=[]; o=s['own_geometry']; center=np.mean(E,axis=0)
        gap=2*sum(abs(x) for x in s['gripper_qpos_m'])-o['pad_extent_in_tool_m'][1]
        for j in range(2):
            direction=E[j+1]-E[j]; direction[2]=0; direction/=np.linalg.norm(direction)
            yaw=math.atan2(A[0,1]*direction[1]-A[1,1]*direction[0],A[0,1]*direction[0]+A[1,1]*direction[1]); yaw=(yaw+math.pi/2)%math.pi-math.pi/2
            q=api.compose(s['tcp_quaternion_xyzw'],[0,0,yaw]) if abs(yaw)>0.03 else s['tcp_quaternion_xyzw']; rot=geo.rotation(q)
            half=float(np.dot(abs(rot[2]),np.asarray(o['pad_extent_in_tool_m']))/2); low=floor_offset(q); bot=float(min(E[:,2])); top=float(max(E[:,2])); width=float(np.ptp(E@rot[:,1]))
            for fraction in [0.2,0.4]:
                overlap=fraction*min(top-bot,2*half); lo=max(bot+overlap-half,bot+G['table_u']+0.001-low); hi=top-overlap+half
                if hi>=lo:
                    for z in [lo,(lo+hi)/2,hi]: choices.append(((gap-width,min(z-lo,hi-z)),[float(center[0]),float(center[1]),float(z)],q,{'nominal_opening_proxy':gap,'width':width,'contact_interval':[lo,hi],'side_overlap':overlap,'finger_floor':low}))
        if not choices: stop('No measured side-band/support-clearance candidate under this orientation; this is a model limitation, not physical impossibility.')
        best=sorted(choices,key=lambda v:v[0],reverse=True)[0]; note('grasp_candidate',best[3]); return np.asarray(best[1]),best[2]
    def effect(w):
        x=np.asarray(B['X']); before=geo.transform(x,np.asarray(B['T'])); after=geo.transform(x,np.asarray(w['T'])); now=api.state()
        error=float(geo.attachment_error(before,after,B['state'],now)); dz=float(np.mean(after[:,2]-before[:,2])); hand=float(np.asarray(geo.pad_position(now))[2]-np.asarray(geo.pad_position(B['state']))[2]); u=B['u']+w['u']
        note('motion_test',{'object_rise':dz,'hand_rise':hand,'attachment_error':error,'local_uncertainty_sum':u,'source':w['source']})
        return error,dz,hand,u
    def retain():
        for trial in range(3):
            if C['phase']!='lifting' or not B:
                if C['probes']>=3: stop('Prospective retention-test budget exhausted; preserve closure.')
                w=needpose(); s=api.state(); distance=max(0.025,min(0.04,8*w['u']))
                target=np.asarray(geo.pad_position(s))+[0,0,distance]; gate(target,'small upward observation-producing retention test; holding is not a prerequisite')
                w=needpose(); s=api.state(); target=np.asarray(geo.pad_position(s))+[0,0,distance]
                B.clear(); B.update({'T':w['T'],'X':w['X'],'u':w['u'],'state':s,'target':target.tolist()}); api.checkpoint('probe',B)
                C['probes']+=1; C['phase']='lifting'; save()
            move(B['target'],B['state']['tcp_quaternion_xyzw'])
            w=pose()
            if w is None:
                C['phase']='closed'; B.clear(); api.checkpoint('probe',B); save(); newref(); continue
            error,dz,hand,u=effect(w)
            if hand>=max(0.012,4*u) and dz>=0.6*hand and error<=min(0.30*hand,max(0.003,2*u)):
                C['phase']='held'; save(); return True
            if hand>max(0.012,4*u) and abs(dz)<max(0.003,2*u): return False
            if error>max(0.008,3*u): stop('Observed body/hand motion contradiction or slip; retention is not established.')
            C['phase']='closed'; B.clear(); api.checkpoint('probe',B); save()
        stop('Retention remains inconclusive after bounded independent motion tests.')
    def carry(target, q, tol=0.0015):
        w=needpose(); before=api.state(); move(target,q,tol=tol); after=pose()
        if after is None:
            C['phase']='closed'; B.clear(); api.checkpoint('probe',B); save(); newref()
            if not retain(): stop('Retention not recovered during transfer.')
            return
        x=np.asarray(w['X']); error=float(geo.attachment_error(geo.transform(x,np.asarray(w['T'])),geo.transform(x,np.asarray(after['T'])),before,api.state()))
        note('transfer_attachment',{'error':error,'uncertainty':w['u']+after['u']})
        if error>max(0.004,2*(w['u']+after['u'])): stop('Independent transfer observation contradicts the retained attachment.')
    def verify():
        for k in range(3):
            r=review('Assess the ACTUAL released item. relation=inside_supported requires seating within the cavity, not merely a centered footprint, suspension, or bridging the lip. hand=separated requires visible separation. bowl=upright_stable is about the actual vessel. Request point v on the saved physical printed landmark, with correspondence=exact only for that same mark; if unavailable choose a different visible mark and give its physical definition with correspondence=new. orientation=stable means the item orientation did not change since the prior verification image. Unknown must remain unknown.',{'identity':['same','ambiguous'],'relation':['inside_supported','rim_bridged','outside','occluded'],'hand':['separated','touching','occluded'],'bowl':['upright_stable','disturbed','unknown'],'correspondence':['exact','new','unknown'],'definition':'string','orientation':['stable','changed','unknown']},{'roles':G['roles'],'previous':V,'phase':C['phase']},True)
            p=r['parameters']; current=r['points'].get('v'); delta=None
            if current is not None and V.get('point') is not None and p['correspondence']=='exact': delta=float(np.linalg.norm(np.asarray(current['world_m'])-np.asarray(V['point'])))
            good=p['identity']=='same' and p['relation']=='inside_supported' and p['hand']=='separated' and p['bowl']=='upright_stable'
            note('released_observation',{'parameters':p,'landmark_displacement_m':delta,'measurement_frame':r['frame_id']})
            if good and delta is not None and delta<=0.003 and p['orientation']=='stable' and C['phase']=='withdrawn':
                C['phase']='done'; save(); return result(True,'Observed released item seated inside the vessel and stable after withdrawal; proposal only.')
            V.clear(); V.update({'point':None if current is None else current['world_m'],'definition':p['definition'],'frame_id':r['frame_id']}); api.checkpoint('verification',V)
            if C['phase'] in ['released','withdrawing']:
                s=api.state(); target=np.asarray(geo.pad_position(s))+[0,0,0.065]; C['phase']='withdrawing'; save(); gate(target,'open-finger upward withdrawal for separation and a new view',final=True); move(target,s['tcp_quaternion_xyzw'],'open',True); C['phase']='withdrawn'; save()
            elif k<2:
                s=api.state(); move(np.asarray(geo.pad_position(s)),s['tcp_quaternion_xyzw'],'open',True)
        return result(False,'Release occurred, but supported-inside placement and stable separation were not both observed. No blind regrasp after release.')
    def execute():
        if not G: acquire()
        if C['phase']=='opening':
            if api.state()['last_gripper_command']=='open': C['phase']='released'; save()
            else: C['phase']='held'; save()
        if C['phase']=='closing':
            if api.state()['last_gripper_command']=='close': C['phase']='closed'; save()
            else: stop('Unacknowledged closure intent after repair; inspect current alignment before resuming.')
        if C['phase']=='done': C['phase']='withdrawn'; save()
        if C['phase'] in ['released','withdrawing','withdrawn']: return verify()
        for attempt in range(2):
            if C['phase'] in ['held','transit','release_ready']: break
            if C['phase']=='approach':
                if C['grasps']>=2: stop('Grasp-attempt budget exhausted.')
                w=needpose(); E,ux,uz=shape(w); target,q=grasp(E); hover=target+[0,0,0.045]
                gate(hover,'open-finger approach above the identified package; no later transfer-corridor certificate is requested'); move(hover,q,'open')
                gate(target,'descend with open fingers around the package, preserving the measured table and side-band constraints'); move(target,q,'open')
                aligned=False
                for check in range(2):
                    r=review('Check CURRENT local closure alignment, not a global object pose. identity must be the intended package. straddle=yes means opposing OPEN inside pad faces flank the intended side faces, with sufficient visible or locally modeled overlap and no finger/table penetration. Request j0,j1 on visible opposing inner pad faces if possible; missing measurements are not contact evidence. Use another view or interior features on the second query. A nominal aperture computed from joint span is only a proxy, never proof of clearance.',{'identity':['same','ambiguous'],'straddle':['yes','no','unknown']},{'target_pad':target.tolist(),'actual_pad':np.asarray(geo.pad_position(api.state())).tolist(),'own_geometry':api.state()['own_geometry'],'attempt':check})
                    pp=points(r,['j0','j1'])
                    if len(pp)==2: note('visible_jaw_gap',{'m':float(abs(np.dot(np.asarray(pp[1])-np.asarray(pp[0]),geo.rotation(api.state()['tcp_quaternion_xyzw'])[:,1])))})
                    if r['parameters']['identity']=='same' and r['parameters']['straddle']=='yes': aligned=True; break
                    if r['parameters']['straddle']=='no': break
                if not aligned: stop('Local pad/side alignment unresolved or contradicted; closure was not attempted.')
                C['grasps']+=1; save(); jaw('close','closing')
            if retain(): break
            w=pose()
            if w is None: stop('Observed failed lift but current support is not localized; do not reopen.')
            E,ux,uz=shape(w); table=G['table']; support_z=-(table[0]*E[:,0]+table[1]*E[:,1]+table[3])/table[2]
            if C['grasps']>=2 or abs(float(np.min(E[:,2]-support_z)))>max(0.004,uz): stop('No retention; no independently localized supported regrasp remains.')
            r=review('The measured lift did not carry the package. Is the same package currently resting on the original table, separate from the raised pads? supported=yes requires actual visible support/separation, not a predicted failed grasp.',{'supported':['yes','no','unknown']},{'roles':G['roles'],'current_envelope':E.tolist()})
            if r['parameters']['supported']!='yes': stop('Safe supported retry is not evidenced; keep the jaws unchanged.')
            jaw('open','approach'); C['phase']='approach'; save()
        if C['phase']!='held' and C['phase'] not in ['transit','release_ready']: stop('Retention prerequisite was not established.')
        C['phase']='transit'; save(); w=needpose(); E,ux,uz=shape(w); s=api.state(); pad=np.asarray(geo.pad_position(s)); q=s['tcp_quaternion_xyzw']
        lift=max(0,G['rim_z']+0.04+uz-float(min(E[:,2])),G['rim_z']+0.025-(pad[2]+floor_offset(q)))
        if lift>0.001:
            target=pad+[0,0,lift]; gate(target,'raise the observed held envelope above the destination lip',True); carry(target,q)
        w=needpose(); E,ux,uz=shape(w); s=api.state(); target=np.asarray(geo.pad_position(s)); target[:2]+=np.asarray(G['bowl_xy'])-(np.min(E[:,:2],axis=0)+np.max(E[:,:2],axis=0))/2
        gate(target,'bounded overhead transfer of the measured held envelope',True); carry(target,q)
        for correction in range(2):
            w=needpose(); E,ux,uz=shape(w); s=api.state(); pad=np.asarray(geo.pad_position(s)); center=(np.min(E[:,:2],axis=0)+np.max(E[:,:2],axis=0))/2
            radius=float(np.max(np.linalg.norm(E[:,:2]-center,axis=1))); nominal=G['radius']-radius; robust=nominal-G['bowl_u']-ux
            note('entry_geometry',{'nominal_slack':nominal,'heuristic_robust_slack':robust,'xy_uncertainty':ux,'z_uncertainty':uz,'radius':radius})
            if nominal<=0:
                if correction==0: R['envelope']=None; api.checkpoint('reference',R); refresh_bowl(); continue
                stop('The refreshed upright-entry model has no nominal footprint slack; this does not prove all placements impossible.')
            target=pad.copy(); target[:2]+=np.asarray(G['bowl_xy'])-center
            target[2]+=max(G['rim_z']+0.004+uz-float(min(E[:,2])),G['rim_z']+0.004+uz-(pad[2]+floor_offset(q)))
            gate(target,'release approach above the inner lip; if uncertainty consumes nominal slack, one bounded above-rim placement trial with independent outcome verification, not certified clearance',True)
            carry(target,q,max(0.0005,min(0.002,nominal/4)))
            w=needpose(); E,ux,uz=shape(w); pad=np.asarray(geo.pad_position(api.state())); actual=G['radius']-float(np.max(np.linalg.norm(E[:,:2]-np.asarray(G['bowl_xy']),axis=1)))
            high=min(float(min(E[:,2]))-G['rim_z'],pad[2]+floor_offset(q)-G['rim_z']); note('release_actual',{'footprint_slack':actual,'height_clearance':high,'xy_uncertainty':ux,'z_uncertainty':uz,'bounded_trial':actual<=ux+G['bowl_u']})
            if actual>0 and high>max(0.001,G['bowl_u']):
                C['phase']='release_ready'; save(); jaw('open','opening'); return verify()
        stop('Two measured release corrections did not establish a justified above-rim release.')
    try:
        return execute()
    except RuntimeError as e:
        note('incomplete',str(e)); save(); return result(False,str(e))
