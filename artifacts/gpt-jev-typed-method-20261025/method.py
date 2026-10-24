def main(api):
    task = 'could you put the cream cheese into the bowl'
    log, saved, track = [], {}, {}
    tol, floor_u = 0.0025, 0.0015
    pixel = {'type':'array','items':{'type':'integer','minimum':0,'maximum':767},'minItems':2,'maxItems':2}
    polygon = {'type':['array','null'],'items':pixel,'minItems':3,'maxItems':16}
    outline = {'type':['array','null'],'items':pixel,'minItems':4,'maxItems':4}
    cameras = ['agentview','robot0_eye_in_hand','unknown']
    questions = {}
    for axis in ['x','y','z','rx','ry','rz']:
        questions[axis] = {'type':'choice','instructions':'Control world axis '+axis+'. Read its bound goal_relation, not another axis. Follow increase, decrease, or within_tolerance; do not calculate geometry.', 'criteria':{'negative':'The selected axis relation is decrease.','hold':'The selected axis relation is within_tolerance.','positive':'The selected axis relation is increase.'}}
    questions['gripper'] = {'type':'choice','instructions':'Follow state.processed_features.objective.gripper exactly. A keep objective preserves the existing grip; no exploratory opening.', 'criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep.'}}
    def note(label, data):
        log.append({'event':label,'data':data}); api.note(label+': '+str(data))
    def require(ok, reason):
        if not ok:
            raise RuntimeError(reason)
    def checkpoint(phase):
        saved['phase'] = phase; saved['last_state'] = api.state()
        api.checkpoint('placement_episode', saved)
    def review(question, fields, context=None, reserve=3):
        require(api.state()['budgets']['gpt_remaining'] > reserve, 'Insufficient review reserve')
        r = api.review(question, context=context, fields=fields)
        note('review', {'frame':r['frame_id'],'parameters':r['parameters'],'measurement_errors':r['measurement_errors'],'explanation':r['explanation']})
        require(r['status'] != 'stop', 'Observation reviewer requested stop')
        return r
    def move(target, grip='keep', calls=20, contact=False, reserve=16):
        s = api.state(); b = s['budgets']
        require(b['jev_remaining'] >= calls+reserve and b['native_steps_remaining'] >= 3*(calls+reserve), 'Insufficient control reserve')
        args = dict(target=np.array(target).tolist(), quaternion=saved['q'], gripper=grip, questions=questions, features={'phase':saved.get('phase','observation'),'target_role':'pad_center','uncertainty_m':saved.get('u',floor_u),'held_evidence':saved.get('retention',None)}, tool_point='pad_center', translation_limit=0.012 if contact else 0.02, rotation_limit=0.08, steps=3, position_tolerance=tol, rotation_tolerance=0.045)
        if contact:
            for k in range(calls):
                r = api.control(**args)
                if r['status'] != 'moved':
                    break
        else:
            r = api.drive(max_calls=calls, **args)
        note('motion', {'status':r['status'],'frame':r['frame_id'],'position_error_m':r['position_error_m'],'rotation_error_rad':r['rotation_error_rad'],'lease_calls':r.get('lease_calls',k+1 if contact else 0)})
        saved['last_receipt'] = {'status':r['status'],'frame_id':r['frame_id'],'target':np.array(target).tolist()}; checkpoint(saved.get('phase','motion'))
        require(r['status'] == 'reached', 'Motion stopped without convergence; no repeated stalled contact')
    def registration():
        t = api.track_update(track['handle'])
        note('registration', {k:t.get(k) for k in ['status','frame_id','reference_frame_id','inliers','matches','rms_m','uncertainty_floor_m','reason']})
        require(t['status'] == 'tracked', 'Current item registration unavailable; do not extrapolate held geometry')
        require(t['inliers'] >= 12 and t['inliers']/max(1,t['matches']) >= 0.55 and t['rms_m'] <= 0.003 and t['uncertainty_floor_m'] <= 0.0025, 'Registration quality insufficient')
        p = geo.transform(track['model'], np.array(t['transform_initial_world_to_current_world']))
        return p, api.state(), max(saved['u'],float(t['uncertainty_floor_m']))
    def refresh(attachment=False):
        p, s, u = registration()
        if attachment:
            e = float(geo.attachment_error(track['current'],p,track['state'],s)); note('attachment_error_m',e)
            require(e <= max(2*(saved['u']+tol),3*u+0.002), 'Observed item motion disagrees with actual hand motion')
        track.update({'current':p,'state':s,'sigma':u}); saved['current_box'] = p.tolist(); saved['box_frame'] = s['frame_id']
        checkpoint(saved.get('phase','observed')); return p
    gate_fields = {'external':['present','none_seen','unknown'],'visibility':['observed','partial_unobserved','self_occluded','unobserved'],'action':['advance','view_up','stop']}
    def route(target, label, held=False, contact=False):
        target = np.array(target); segment = 0.08
        for assessment in range(2):
            current = geo.pad_position(api.state()); delta = target-current
            distance = float(np.linalg.norm(delta))
            if distance <= tol:
                return
            require(distance <= 5*segment, 'Local phase exceeds finite progress allowance: '+str({'distance_m':distance,'allowance_m':5*segment,'phase':label}))
            candidate = current+delta*min(1.0,segment/distance)
            r = review('Assess the bounded local phase '+label+' from current_pad to phase_pad_target along a monotone path, first reaching candidate_pad_target. Execution uses at most six pose-feedback segments, each at most 0.08 m, with native translation updates at most 0.02 m (0.012 m for contact). Do not assess later task phases. external=present means an observed external obstacle intersects this proposed motion; none_seen means no such obstacle observed, NOT a clearance certificate; unknown means no usable immediate-obstruction assessment. visibility=observed means the relevant local workspace is visible, partial_unobserved means some is not visible, self_occluded means the robot or item hides part, and unobserved means no usable immediate workspace view. action=advance authorizes this phase only when visible local evidence plus measured robot/item geometry justify bounded progress. Missing space is not proof of clearance, but self-occlusion alone is not an obstacle and does not demand another view. For high approach or open-jaw staging, assess only noncontact progress, not future grasp contact. For final grasp descent, use grasp_geometry, the measured rectangular top and support assumption, and visible table gaps beside the carton; direct visibility of both vertical faces is not mandatory. The aperture proxy is conservative, not calibrated; request a view or stop if the visible evidence contradicts or cannot support the fit. Do not require the entire perimeter during retained motion. action=view_up authorizes ONLY an immediately justified 0.025 m vertical upward observation move that can resolve a concrete missing view. It does not authorize the original path. Otherwise action=stop. Report all exact fields.', gate_fields, {'task':task,'current_pad':current.tolist(),'candidate_pad_target':candidate.tolist(),'phase_pad_target':target.tolist(),'phase_distance_m':distance,'quaternion':saved['q'],'geometry':saved['g'],'current_box':saved.get('current_box'),'grasp_geometry':saved.get('grasp_geometry'),'opening_estimate_m':saved.get('gap_proxy'),'opening_estimate_is_not_calibrated':True,'finger_envelope':api.state()['own_geometry']})['parameters']
            if r['action'] == 'advance':
                require(r['external']=='none_seen' and r['visibility']!='unobserved', 'No usable local motion basis: '+str(r))
                break
            require(r['action']=='view_up' and assessment==0, 'No justified local phase or useful further view: '+str(r))
            move(current+np.array([0,0,0.025]),calls=8)
            if held:
                refresh(True)
            else:
                refresh(False)
        for step in range(6):
            current = geo.pad_position(api.state()); delta = target-current
            distance = float(np.linalg.norm(delta))
            if distance <= tol:
                return
            candidate = current+delta*min(1.0,segment/distance)
            note('local_progress',{'phase':label,'segment':step+1,'remaining_m':distance,'segment_m':min(segment,distance),'visibility':r['visibility'],'external':r['external']})
            move(candidate,calls=20,contact=contact)
            if held:
                refresh(True)
            elif not contact:
                P = refresh(False)
                drift = float(np.max(np.linalg.norm(P-track['model'],axis=1)))
                bound = 3*(saved['u']+tol)
                note('approach_stationarity',{'frame':track['state']['frame_id'],'max_displacement_m':drift,'bound_m':bound})
                require(drift < bound, 'Carton moved during noncontact approach; target requires reacquisition: '+str({'displacement_m':drift,'bound_m':bound}))
        remaining = float(np.linalg.norm(target-geo.pad_position(api.state())))
        note('local_phase_residual',{'phase':label,'remaining_m':remaining,'tolerance_m':tol})
        require(remaining <= tol, 'Finite local progress allowance exhausted: '+str({'phase':label,'remaining_m':remaining,'tolerance_m':tol}))
    final_fields = {'identity':['yes','no','unknown'],'relation':['inside_supported','outside','still_held','unknown'],'stable':['yes','no','unknown']}
    def verify():
        first = review('After release and withdrawal, inspect the requested item and bowl. identity=yes only for the requested cream cheese. relation=inside_supported means the actual item is inside the bowl opening and supported by its interior, not held, balanced on the outer rim, or merely projected over it. Other values are outside, still_held, unknown. stable=yes requires observed rest, no sliding or tipping; otherwise no or unknown. Report all exact fields.', final_fields, {'task':task,'historical_geometry':saved.get('g')},reserve=1)
        for k in range(3):
            move(geo.pad_position(api.state()),'keep',calls=3,contact=True,reserve=0)
        last = review('Compare this fresh post-settling observation with the preceding post-release images. Use exactly identity, relation, stable with the same meanings. Decide actual interior support and absence of visible motion, not intended placement or elapsed time. The extra physical steps are for a temporal stability observation.', final_fields, {'previous':first['parameters'],'task':task},reserve=0)
        p = last['parameters']; success = p['identity']=='yes' and p['relation']=='inside_supported' and p['stable']=='yes'
        saved['verification'] = {'first_frame':first['frame_id'],'last_frame':last['frame_id'],'result':p}; checkpoint('verified' if success else 'verification_incomplete')
        return {'completion_proposed':success,'evidence':{'events':log,'verification':saved['verification'],'limitations':['Completion is a proposal, not native evaluator success.','Visual stability and local obstruction reviews are fallible observations, not collision or support certificates.']}}
    try:
        for entry in api.recall():
            if entry['key'] == 'placement_episode':
                saved.update(api.recall('placement_episode')['value'])
        historical = saved.get('g')
        fields = {'scene':['box_on_table','box_held','inside_bowl','unsupported','unknown'],'references':['unchanged','changed','unknown'],'camera':cameras,'corners':outline,'patch':polygon}
        request = 'Interpret the runtime instruction. scene describes the requested rigid rectangular carton and upright open bowl; box_on_table requires visible flat table support plus visible top and side. box_held requires visible held-item evidence. inside_bowl means already placed. Do not label another object. camera names the view for corners and patch. corners are the four visible top-face corners in perimeter order, not inferred hidden corners. patch is a textured interior polygon on that same carton top in that same current camera. Request named region top, a tightly interior top-face cloud, stride=4. Regions must have explicit camera, box, stride. For a new episode also request table (bare support) and floor (small central bowl-interior bottom) regions, stride=4; point side on the carton vertical side; and r0..r5 at six separated points on the INNER bowl lip around its circumference. references=unchanged only when saved bowl/table references still describe the stationary scene. With saved geometry request only r0..r2 on the current inner lip to validate it, plus top and the current outline/patch. Boundary depth may fail; do not silently substitute background.'
        r = review(request,fields,{'instruction':task,'historical_geometry':historical},reserve=3); par = r['parameters']
        require(par['scene'] not in ['unsupported','unknown'], 'Task or current object state not supported by this method')
        saved['q'] = api.state()['tcp_quaternion_xyzw']
        if par['scene'] == 'inside_bowl':
            return verify()
        require(par['camera'] != 'unknown' and par['corners'] is not None, 'Visible planar outline unavailable')
        require(historical is not None or par['scene']=='box_on_table', 'No measured rigid-box height exists for an already-held item')
        names = ['r'+str(i) for i in range(3 if historical else 6)] + ([] if historical else ['side'])
        regions = ['top'] if historical else ['top','table','floor']
        points, clouds = dict(r['points']), dict(r['regions'])
        partial = {'frame_id':r['frame_id'],'points':points,'regions':{}}
        for name in clouds:
            c = clouds[name]; a = c['world_m']; partial['regions'][name] = {'camera':c['camera'],'frame_id':c['frame_id'],'world_m':a[::max(1,int(len(a)/20))][:24]}
        api.checkpoint('partial_geometry',partial)
        missing = [n for n in names if n not in points]+[n for n in regions if n not in clouds]
        if missing:
            rr = review('Replace only these failed or absent named measurements, with the identities and region rules of the preceding request: '+str(missing),{'available':['yes','unknown']},{'measurement_errors':r['measurement_errors']})
            points.update(rr['points']); clouds.update(rr['regions'])
        require(all(n in points for n in names) and all(n in clouds for n in regions), 'Required depth measurements remain absent: '+str(missing))
        fits = {}
        for name in regions:
            a = np.array(clouds[name]['world_m']); require(len(a)>=6 and bool(np.all(np.isfinite(a))), 'Insufficient finite cloud '+name)
            fits[name] = geo.plane(a)
        top = fits['top']; plane = np.array(top['coefficients']); u = max(floor_u,3*float(top['rms_m'])); saved['u'] = u
        require(plane[2] > 0.98 and top['rms_m'] < 0.0025, 'Carton top is not a sufficiently measured horizontal plane')
        C = np.array([api.plane_point(par['camera'],pixel,plane.tolist())['world_m'] for pixel in par['corners']])
        edge0, edge1 = C[1]-C[0], C[2]-C[1]; lengths = sorted([float(np.linalg.norm(edge0)),float(np.linalg.norm(edge1))])
        require(abs(float(np.dot(edge0,edge1))) < 0.18*lengths[0]*lengths[1] and np.linalg.norm(C[0]+C[2]-C[1]-C[3]) < 4*u, 'Visible top landmarks inconsistent with a rigid rectangular face')
        rim = np.array([points['r'+str(i)]['world_m'] for i in range(3 if historical else 6)])
        if historical:
            g = historical; residual = np.abs(np.linalg.norm(rim[:,:2]-np.array(g['bowl_xy']),axis=1)-g['rim_radius'])
            require(par['references']=='unchanged' and float(np.max(residual)) < 0.008 and float(np.max(np.abs(rim[:,2]-g['rim_z']))) < 0.008, 'Historical target geometry no longer validated')
            require(max(abs(lengths[i]-g['sizes'][i]) for i in range(2)) < 5*u, 'Current item dimensions disagree with saved rigid invariant')
        else:
            table = fits['table']; rp = geo.plane(rim); circle = geo.circle_xy(rim)
            require(table['coefficients'][2] > 0.98 and table['rms_m'] < 0.0025 and rp['coefficients'][2] > 0.97 and rp['rms_m'] < 0.004, 'Support or rim plane inadequate')
            require(circle['max_radial_error_m'] < 0.006 and circle['largest_angular_gap_rad'] < math.pi, 'Inner rim circle inadequately sampled')
            center = np.mean(C,axis=0); tp = np.array(table['coefficients']); table_z = float(-(np.dot(tp[:2],center[:2])+tp[3])/tp[2]); h = float(center[2]-table_z)
            require(table_z-u < points['side']['world_m'][2] < center[2]+u and h > 2*(u+tol), 'Top, side and observed support do not establish usable carton height')
            g = {'bowl_xy':circle['center_xy_m'],'rim_radius':float(circle['radius_m']),'rim_z':float(np.mean(rim[:,2])),'rim_error':float(circle['max_radial_error_m']),'floor_z':float(fits['floor']['center_world_m'][2]),'height':h,'sizes':lengths,'table_plane':tp.tolist(),'measurement_frame':r['frame_id'],'height_basis':'Rigid rectangular carton observed flat on measured table; underside inferred, not visible.'}
        saved['g'] = g; h = g['height']; margin = u+tol
        radius = float(np.max(np.linalg.norm(C[:,:2]-np.mean(C[:,:2],axis=0),axis=1)))
        note('geometry',{'sizes_m':lengths,'height_m':h,'item_half_diagonal_m':radius,'rim_radius_m':g['rim_radius'],'rim_error_m':g['rim_error'],'margin_m':margin})
        require(radius+margin+g['rim_error'] < g['rim_radius'] and g['floor_z'] < g['rim_z']-u, 'Measured aperture does not support an upright low release')
        B = C.copy(); B[:,2] -= h; track['model'] = np.concatenate([C,B]); saved['current_box'] = track['model'].tolist(); checkpoint('geometry_measured')
        patch, camera = par['patch'], par['camera']
        for attempt in range(2):
            try:
                require(patch is not None, 'No initial textured patch')
                t = api.track_init(camera,patch); track['handle'] = t['handle']; note('tracker_initialized',t); break
            except Exception as e:
                note('patch_failure',str(e))
                require(attempt == 0, 'Two different patch selections failed')
                rr = review('Select a better textured interior polygon on the SAME carton top, preferably from the other camera or with more printed texture. camera and patch must refer to this fresh image. Do not include bowl, table, fingers or carton silhouette.',{'camera':cameras,'patch':polygon},{'failed_patch':patch,'camera':camera})
                camera, patch = rr['parameters']['camera'],rr['parameters']['patch']
                require(camera != 'unknown', 'No obtainable textured object view')
        refresh(False)
        s = api.state(); own = s['own_geometry']; R = geo.rotation(s['tcp_quaternion_xyzw'])
        if par['scene'] == 'box_on_table':
            ext = np.array(own['pad_extent_in_tool_m']); gap = abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1])-max(float(ext[0]),float(ext[2])); saved['gap_proxy'] = float(gap)
            short = edge0 if np.linalg.norm(edge0)<np.linalg.norm(edge1) else edge1
            yaw = (math.atan2(short[1],short[0])-math.atan2(R[1,1],R[0,1])+math.pi/2)%math.pi-math.pi/2
            if abs(yaw)>0.15:
                saved['q'] = api.compose(saved['q'],[0,0,float(yaw)])
            R = geo.rotation(saved['q']); width = float(np.max(C@R[:,1])-np.min(C@R[:,1]))
            saved['grasp_geometry'] = {'projected_width_m':width,'conservative_gap_proxy_m':float(gap),'margin_m':margin,'width_with_margins_m':width+2*margin,'aperture_slack_m':float(gap-width-2*margin),'proxy_is_not_a_measured_inner_aperture':True}
            note('grasp_width',saved['grasp_geometry'])
            require(width+2*margin < gap, 'Aperture estimate does not justify this grasp; requires calibrated jaw observation or a different grasp')
        lo, hi = own['finger_low_offset_tool_m'],own['finger_high_offset_tool_m']
        corners = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
        low = float(np.min(((corners-np.array(own['pad_center_in_tool_m']))@R.T)[:,2]))
        if par['scene'] == 'box_on_table':
            checkpoint('approaching'); center = np.mean(C,axis=0); bottom = float(center[2]-h)
            grasp_z = max(bottom+0.5*h,bottom+margin-low); pad_span = float(np.dot(np.abs(R[2,:]),np.array(own['pad_extent_in_tool_m'])))
            overlap = min(float(center[2]),grasp_z+pad_span/2)-max(bottom,grasp_z-pad_span/2)
            require(overlap > 2*u, 'Table clearance and pad contact overlap incompatible: '+str({'low':low,'grasp_z':grasp_z,'overlap':overlap,'height':h}))
            saved['grasp_geometry'].update({'pad_target_z_m':float(grasp_z),'predicted_lowest_finger_z_m':float(grasp_z+low),'inferred_support_z_m':bottom,'predicted_table_clearance_m':float(grasp_z+low-bottom),'predicted_pad_side_overlap_m':float(overlap),'required_overlap_m':2*u,'basis':'Measured top and stationary support; rigid-box underside inference and own finger envelope. These predict clearance and overlap, not contact or retention.'})
            note('grasp_vertical_geometry',saved['grasp_geometry'])
            move(geo.pad_position(api.state()),'open',calls=5,contact=True)
            high = max(float(geo.pad_position(api.state())[2]),float(center[2]+0.06),g['rim_z']+0.06)
            route([float(center[0]),float(center[1]),high],'high noncontact approach')
            route([float(center[0]),float(center[1]),grasp_z+0.035],'open-jaw staging descent')
            P = refresh(False); shift = np.mean(P[:4]-C,axis=0)
            require(np.linalg.norm(shift) < 3*margin, 'Item moved during approach; geometric grasp requires reacquisition')
            target = np.mean(P[:4],axis=0); target[2] = grasp_z+shift[2]
            route(target,'final opposed-side grasp descent',contact=True); refresh(False); checkpoint('closing')
            for k in range(3):
                move(geo.pad_position(api.state()),'close',calls=4,contact=True)
        before, state_before = track['current'].copy(), track['state']; emax = max(2*margin,3*track['sigma']+0.002)
        checkpoint('retention_probe'); probe = max(0.025,4*emax)
        require(probe <= 0.045, 'Retention uncertainty needs an excessive probe')
        move(geo.pad_position(api.state())+np.array([0,0,probe]),calls=10,contact=True)
        P, sa, sig = registration(); error = float(geo.attachment_error(before,P,state_before,sa)); dz = float(geo.pad_position(sa)[2]-geo.pad_position(state_before)[2]); item_dz = float(np.mean(P[:,2]-before[:,2]))
        saved['retention'] = {'hand_rise_m':dz,'item_rise_m':item_dz,'attachment_error_m':error,'threshold_m':emax,'before_frame':state_before['frame_id'],'after_frame':sa['frame_id']}; note('retention',saved['retention'])
        if not (dz>2*emax and item_dz>0.6*dz and error<=emax):
            rr = review('Retention probe failed numerically. location=on_table only if the item is visibly independently supported on its original table, not in the jaws. Other values held, fallen, unknown. This determines only whether opening for recovery is justified.',{'location':['on_table','held','fallen','unknown']},saved['retention'])
            if rr['parameters']['location']=='on_table':
                move(geo.pad_position(api.state()),'open',calls=5,contact=True); move(geo.pad_position(api.state())+np.array([0,0,0.035]),calls=10)
            raise RuntimeError('Retention not established; recovery did not transfer or reopen a held item')
        track.update({'current':P,'state':sa,'sigma':sig}); saved['current_box'] = P.tolist(); checkpoint('carrying')
        pad = geo.pad_position(api.state()); lift = max(0.025,g['rim_z']+0.045-float(np.min(P[4:,2])))
        route(pad+np.array([0,0,lift]),'retained vertical clearance lift',held=True)
        P = track['current']; pad = geo.pad_position(api.state()); delta = np.array(g['bowl_xy'])-np.mean(P[:4,:2],axis=0)
        route(pad+np.array([delta[0],delta[1],0]),'retained transfer toward bowl',held=True)
        P = track['current']; pad = geo.pad_position(api.state()); offset = float(pad[2]-np.min(P[4:,2])); release_z = max(g['rim_z']+margin+offset,g['rim_z']+margin-low)
        target = pad.copy(); target[:2] += np.array(g['bowl_xy'])-np.mean(P[:4,:2],axis=0); target[2] = release_z
        route(target,'low release positioning above inner aperture',held=True,contact=True)
        P = refresh(True); radial = float(np.max(np.linalg.norm(P[:4,:2]-np.array(g['bowl_xy']),axis=1)))
        require(radial+u+g['rim_error'] < g['rim_radius'], 'Observed retained footprint is not inside measured aperture')
        checkpoint('releasing')
        for k in range(3):
            move(geo.pad_position(api.state()),'open',calls=4,contact=True,reserve=10)
        checkpoint('released'); move(geo.pad_position(api.state())+np.array([0,0,0.065]),'open',calls=14,reserve=6)
        return verify()
    except Exception as e:
        note('incomplete',str(e))
        return {'completion_proposed':False,'evidence':{'reason':str(e),'events':log,'historical_geometry':saved.get('g'),'last_phase':saved.get('phase'),'retention':saved.get('retention'),'limitation':'No motion was undone. Last commanded grip is preserved except for explicitly observed supported-item recovery. Checkpoints are historical, not current sensor values.'}}
